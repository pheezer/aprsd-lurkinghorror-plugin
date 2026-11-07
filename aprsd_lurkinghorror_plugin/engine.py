"""Headless, per-turn driver around the vendored ravdin/zmachine interpreter.

APRS turns arrive minutes-to-hours apart from many players, so we never keep a
live interpreter process. For each command we build a fresh interpreter from the
story file, restore the player's serialized VM state, run exactly one command,
capture what the game printed, snapshot the new VM state, and stop.

The snapshot format is the interpreter's own undo triple
(dynamic_memory + serialized call stack + program counter), the same bytes used
by ``do_save_undo`` / ``do_restore_undo`` in the vendored interpreter.
"""

import logging

from ._vendor.zmachine.config import ZMachineConfig
from ._vendor.zmachine.event import EventManager
from ._vendor.zmachine.interpreter import ZMachineInterpreter
from ._vendor.zmachine.memory import MemoryMap
from ._vendor.zmachine.output import OutputStreamManager
from ._vendor.zmachine.settings import RuntimeSettings

LOG = logging.getLogger("APRSD")

# ZSCII carriage return terminates a line of input (Z-machine spec 7.1.1).
_ZSCII_CR = 13


class GameEngineError(Exception):
    """Raised when a turn cannot be completed (bad story file, VM crash)."""


class _EndOfTurn(Exception):
    """Internal: raised from the input source when the game asks for the next
    command, to unwind out of ``run_instruction`` and end the turn."""


class _StubResourceData:
    """Minimal IResourceData stand-in. v3 games carry no picture/sound blorb
    resources, so every query is empty."""

    release_number = 0
    picture_count = 0

    def get_scaling_ratio(self, number, window_width, window_height):
        return 1.0

    def is_valid_picture(self, number):
        return False

    def is_adaptive_picture(self, number):
        return False

    def get_picture_data(self, number):
        return None

    def get_sound_data(self, number):
        return b""


class _HeadlessScreen:
    """An IScreen that captures printed text instead of drawing a terminal.

    We deliberately do NOT wrap, paginate, or render a status line: APRS wants
    the raw game text so the plugin can chunk it into 67-char messages. Window,
    cursor, style, color, and graphics operations are all no-ops for a v3 game.
    """

    def __init__(self):
        self._chunks: list[str] = []
        self._resource_data = _StubResourceData()
        self.pause_enabled = False
        self.transcript_output_enabled = False

    def drain(self) -> str:
        text = "".join(self._chunks)
        self._chunks.clear()
        return text

    @property
    def resource_data(self):
        return self._resource_data

    def print(self, text, newline=False):
        if text:
            self._chunks.append(text)
        if newline:
            self._chunks.append("\n")

    # --- everything below is a no-op for headless v3 play ---
    def set_buffer_mode(self, value):
        pass

    def reset_screen(self):
        pass

    def refresh_status_line(self, location, status):
        pass

    def reset_output_line_count(self):
        pass

    def set_window(self, window_id):
        pass

    def split_window(self, lines):
        pass

    def erase_window(self, window_id):
        pass

    def erase_line(self, value):
        pass

    def sound_effect(self, number, effect, volume, repeats, routine):
        pass

    def get_cursor(self):
        return (1, 1)

    def set_cursor(self, y_cursor, x_cursor, window_id=-3):
        pass

    def set_text_style(self, style):
        pass

    def set_color(self, foreground_color, background_color, window_id=-3):
        pass

    def set_font(self, font_id, window_id=-3):
        return 0

    def get_window_width(self, window_id):
        return 0

    def get_font_width(self, window_id):
        return 1

    def print_table(self, table):
        for row in table:
            self.print(row, True)

    def get_window_property(self, window_id, property_number):
        return 0

    def put_window_property(self, window_id, property_number, value):
        pass

    def get_picture_size(self, number):
        return (0, 0)

    def draw_picture(self, number, y=0, x=0):
        pass

    def erase_picture(self, number, y=0, x=0):
        pass

    def set_mouse_window(self, window_id):
        pass

    def set_cursor_enabled(self, value):
        pass

    def set_margins(self, left, right, window_id=-3):
        pass

    def move_window(self, window_id, y, x):
        pass

    def resize_window(self, window_id, y, x):
        pass

    def scroll_window(self, window_id, pixels):
        pass

    def set_window_attributes(self, window_id, flags, operation=0):
        pass


class _HeadlessTerminal:
    """ITerminalAdapter stand-in. The real screen is bypassed, so only geometry
    and a couple of writes are ever consulted. Geometry is reported huge so the
    interpreter never tries to paginate with a MORE prompt."""

    height = 255
    width = 255
    font_size = 0x0101  # one unit per char (height<<8 | width)
    at_wrap_boundary = False

    def refresh(self):
        pass

    def set_scrollable_height(self, top):
        pass

    def write_to_screen(self, text):
        pass

    def get_input_char(self, echo=True):
        return _ZSCII_CR

    def get_input_string(self, prompt, lowercase):
        return ""

    def set_timeout(self, timeout_ms):
        pass

    def get_coordinates(self):
        return (0, 0)

    def move_cursor(self, y_pos, x_pos):
        pass

    def move_cursor_to_line_start(self):
        pass

    def cache_current_line(self):
        pass

    def uncache_current_line(self):
        pass

    def erase_screen(self, background_color=2):
        pass

    def erase_window(self, left, top, width, height, background_color=2):
        pass

    def clear_to_eol(self):
        pass

    def apply_style_attributes(self, attributes):
        pass

    def apply_color_settings(self, background_color, foreground_color):
        pass

    def beep(self):
        pass

    def shutdown(self):
        pass


class _HeadlessInput:
    """IInputSource that feeds a single queued command, then ends the turn.

    The interpreter's ``do_read`` calls ``read_input`` each time the game wants
    a line. We serve the queued command on the first read of a turn, and on the
    next read we raise ``_EndOfTurn`` -- that read is the game asking for the
    NEXT command, which marks the end of this turn.
    """

    def __init__(self):
        self._command: str | None = None
        self._served = False

    def load(self, command: str | None):
        self._command = command
        self._served = False

    def select_keyboard_stream(self):
        pass

    def select_playback_stream(self, commands):
        pass

    def read_input(
        self,
        timeout_ms,
        text_buffer,
        interrupt_routine_caller,
        interrupt_routine_addr,
        echo,
    ):
        if self._served or self._command is None:
            # The game has consumed our command and is prompting again: stop.
            raise _EndOfTurn
        self._served = True
        command = self._command
        pos = 0
        while pos < len(text_buffer) and text_buffer[pos] != 0:
            pos += 1
        for ch in command:
            if pos >= len(text_buffer) - 1:
                break
            text_buffer[pos] = ord(ch)
            pos += 1
        text_buffer[pos] = _ZSCII_CR


class ZMachineEngine:
    """Plays one command per call against a Z-machine story file."""

    def __init__(self, story_file: str):
        self.story_file = story_file
        # Validate the story file up front so a bad path disables the plugin.
        self._config = ZMachineConfig.from_game_file(story_file)

    def run_turn(
        self, state_blob: bytes | None, command: str | None
    ) -> tuple[str, bytes]:
        """Run one command and return (printed_text, new_state_blob).

        state_blob is None for a brand-new game (command is then typically
        None/empty and we capture the intro + opening room).
        """
        interp, screen, source = self._assemble()
        if state_blob is not None:
            self._restore(interp, state_blob)
        source.load(command)

        # Snapshot the PC at the start of each instruction. When the turn-ending
        # read unwinds, read_instruction_ptr holds the address of that read op,
        # so the restored VM re-executes the read and asks for input again.
        read_instruction_ptr = interp.pc

        try:
            while not interp.quit:
                read_instruction_ptr = interp.pc
                interp.run_instruction()
        except _EndOfTurn:
            pc_for_snapshot = read_instruction_ptr
        except Exception as ex:
            # A VM-level fault (bad opcode, out-of-range memory) means the game
            # or its saved state is broken; surface it as a clean engine error.
            raise GameEngineError(f"interpreter fault: {ex}") from ex
        else:
            # The game ended (quit) without asking for more input.
            pc_for_snapshot = interp.pc

        text = screen.drain()
        new_blob = self._snapshot(interp, pc_for_snapshot)
        return text, new_blob

    def _assemble(self):
        """Wire up an interpreter with headless I/O. Mirrors the vendored
        ZMachineBuilder, minus the curses/graphics terminal path."""
        config = self._config
        event_manager = EventManager()
        memory_map = MemoryMap(config, graphics_enabled=False)
        runtime_settings = RuntimeSettings(memory_map)
        terminal = _HeadlessTerminal()
        screen = _HeadlessScreen()
        source = _HeadlessInput()
        output_manager = OutputStreamManager(
            screen, memory_map, terminal, config, runtime_settings, event_manager
        )
        quetzal = _UnusedQuetzal()
        interp = ZMachineInterpreter(
            memory_map,
            config,
            runtime_settings,
            screen,
            source,
            output_manager,
            quetzal,
            event_manager,
        )
        return interp, screen, source

    def _snapshot(self, interp: ZMachineInterpreter, pc: int) -> bytes:
        """Serialize VM state as the undo triple: dynamic memory, call stack,
        and PC. Mirrors ZMachineInterpreter.do_save_undo."""
        static_base = interp.config.static_memory_base_addr
        dynamic_memory = bytes(interp.memory_map[:static_base])
        call_stack_bytes = interp.call_stack.serialize()
        return _pack(dynamic_memory, call_stack_bytes, pc)

    def _restore(self, interp: ZMachineInterpreter, blob: bytes):
        """Load a snapshot. Mirrors ZMachineInterpreter.do_restore_undo."""
        try:
            dynamic_memory, call_stack_bytes, pc = _unpack(blob)
        except Exception as ex:
            raise GameEngineError(f"corrupt save state: {ex}") from ex
        # Dynamic memory is exactly the bytes below static base for this story;
        # a mismatch means the blob is corrupt or from a different game.
        static_base = interp.config.static_memory_base_addr
        if len(dynamic_memory) != static_base:
            raise GameEngineError(
                "corrupt save state: dynamic memory size "
                f"{len(dynamic_memory)} != expected {static_base}"
            )
        try:
            interp.memory_map.reset_dynamic_memory(dynamic_memory)
            interp.call_stack.deserialize(call_stack_bytes)
        except Exception as ex:
            raise GameEngineError(f"corrupt save state: {ex}") from ex
        interp.pc = pc


class _UnusedQuetzal:
    """The engine snapshots state itself; the interpreter's Quetzal dependency
    is only invoked by the in-game save/restore opcodes, which cannot fire in a
    scripted single-turn run."""

    def do_save(self, pc, call_stack):
        return False

    def do_restore(self, call_stack):
        return (0, False)


def _pack(dynamic_memory: bytes, call_stack_bytes: bytes, pc: int) -> bytes:
    out = bytearray()
    out.extend(len(dynamic_memory).to_bytes(4, "big"))
    out.extend(dynamic_memory)
    out.extend(len(call_stack_bytes).to_bytes(4, "big"))
    out.extend(call_stack_bytes)
    out.extend(pc.to_bytes(3, "big"))
    return bytes(out)


def _unpack(blob: bytes) -> tuple[bytes, bytes, int]:
    ptr = 0
    dyn_len = int.from_bytes(blob[ptr : ptr + 4], "big")
    ptr += 4
    dynamic_memory = blob[ptr : ptr + dyn_len]
    ptr += dyn_len
    cs_len = int.from_bytes(blob[ptr : ptr + 4], "big")
    ptr += 4
    call_stack_bytes = blob[ptr : ptr + cs_len]
    ptr += cs_len
    pc = int.from_bytes(blob[ptr : ptr + 3], "big")
    return dynamic_memory, call_stack_bytes, pc
