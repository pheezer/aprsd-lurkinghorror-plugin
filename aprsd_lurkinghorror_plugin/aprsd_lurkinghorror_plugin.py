import logging
import os
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from aprsd import packets, plugin, threads
from aprsd.threads import tx
from aprsd.utils import trace
from oslo_config import cfg

import aprsd_lurkinghorror_plugin
from aprsd_lurkinghorror_plugin import conf  # noqa
from aprsd_lurkinghorror_plugin.engine import GameEngineError, ZMachineEngine
from aprsd_lurkinghorror_plugin.session import GameSessionStore

CONF = cfg.CONF
LOG = logging.getLogger("APRSD")

# APRS payloads are hard-truncated to 67 chars by aprsd before transmit.
APRS_MAX_LEN = 67

# One lock per callsign so a single player's rapid-fire messages serialize on
# their own state, while different players still run concurrently.
_callsign_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


DEFAULT_MORE_MARKER = " (more)"


def wrap_chunks(text: str, width: int = APRS_MAX_LEN) -> list[str]:
    """Flatten whitespace and split text into <=width word-boundary chunks.

    No cap and no marker -- this returns ALL chunks, losslessly.
    """
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return []
    chunks: list[str] = []
    current = ""
    for word in text.split(" "):
        # Hard-wrap a single word longer than the line width.
        while len(word) > width:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(word[:width])
            word = word[width:]
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current = f"{current} {word}"
        else:
            chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks


def take_batch(
    chunks: list[str],
    max_msgs: int,
    width: int = APRS_MAX_LEN,
    marker: str = DEFAULT_MORE_MARKER,
):
    """Take up to max_msgs chunks to send now; return (to_send, remaining).

    to_send is a bare str for a single chunk (parity with other plugins), else
    a list[str]. When chunks are left over, the last sent chunk ends with
    `marker` and -- crucially -- any text displaced to make room for the marker
    is pushed back onto `remaining` rather than lost, so `# more` can retrieve
    the full text.
    """
    if not chunks:
        return "Ok.", []
    if len(chunks) <= max_msgs:
        return (chunks[0] if len(chunks) == 1 else list(chunks)), []

    batch = list(chunks[:max_msgs])
    remaining = list(chunks[max_msgs:])
    last = batch[-1]
    if len(last) + len(marker) > width:
        limit = width - len(marker)
        # Trim at a word boundary when possible; hard-cut a single long word.
        cut = last.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        kept, dropped = last[:cut].rstrip(), last[cut:].strip()
        batch[-1] = kept + marker
        if dropped:
            remaining = [dropped, *remaining]
    else:
        batch[-1] = last + marker
    return batch, remaining


def chunk_for_aprs(text: str, max_msgs: int, width: int = APRS_MAX_LEN):
    """Convenience: wrap text and return just the first batch to send.

    Kept for callers/tests that don't need the overflow remainder.
    """
    return take_batch(wrap_chunks(text, width), max_msgs, width)[0]


class GameIdleThread(threads.APRSDThread):
    """Periodically expire idle player sessions."""

    def __init__(self):
        super().__init__("LurkingHorrorIdle")
        timeout = CONF.lurking_horror.session_idle_timeout
        # Check ~10 times per timeout window, bounded to a sane range.
        self.period = max(60, min(timeout // 10 or 60, 3600))

    def loop(self) -> bool:
        store = GameSessionStore()
        expired = store.expire_idle(CONF.lurking_horror.session_idle_timeout)
        if expired:
            LOG.info(f"Expired idle Lurking Horror sessions: {expired}")
        # Pace the loop. aprsd's APRSDThread base has no portable sleep helper
        # across versions (newer has wait(), 4.x does not), so sleep in short
        # slices and bail early when asked to stop.
        slept = 0
        while slept < self.period and not self._should_quit():
            time.sleep(1)
            slept += 1
        return True

    def _cleanup(self):
        GameSessionStore().save()


class GameBeaconThread(threads.APRSDThread):
    """Periodically beacon the service position with a themed comment/symbol.

    aprsd's built-in beacon hardcodes its comment, so we send our own so the
    game shows up on aprs.fi labeled as Lurking Horror.
    """

    def __init__(self):
        super().__init__("LurkingHorrorBeacon")
        self.period = max(60, CONF.lurking_horror.beacon_interval)
        # Send one shortly after startup rather than waiting a full interval.
        self._first = True

    def loop(self) -> bool:
        if self._first:
            self._first = False
        else:
            slept = 0
            while slept < self.period and not self._should_quit():
                time.sleep(1)
                slept += 1
            if self._should_quit():
                return False
        self._send_beacon()
        return True

    def _send_beacon(self):
        try:
            pkt = packets.BeaconPacket(
                from_call=CONF.callsign,
                to_call="APRS",
                latitude=float(CONF.lurking_horror.beacon_latitude),
                longitude=float(CONF.lurking_horror.beacon_longitude),
                comment=CONF.lurking_horror.beacon_comment,
                symbol=CONF.lurking_horror.beacon_symbol,
                symbol_table=CONF.lurking_horror.beacon_symbol_table,
            )
            pkt.retry_count = 1
            tx.send(pkt)
            LOG.info(f"Sent Lurking Horror beacon: {CONF.lurking_horror.beacon_comment}")
        except Exception as ex:  # noqa: BLE001 - a beacon failure must never kill the thread/daemon
            LOG.error(f"LurkingHorror beacon failed: {ex}")


class LurkingHorrorPlugin(plugin.APRSDRegexCommandPluginBase):
    """Play Infocom's Lurking Horror (or any Z-machine game) over APRS."""

    version = aprsd_lurkinghorror_plugin.__version__
    command_regex = r"^#"  # replaced in setup() from the configured prefix
    command_name = "lurking horror"
    short_description = "Play a Z-machine text adventure over APRS"

    enabled = False
    prefix = "#"
    engine: ZMachineEngine | None = None

    def setup(self):
        self.prefix = (CONF.lurking_horror.command_prefix or "#").strip()
        # Build a regex that matches ONLY our prefix so we never collide with
        # other command plugins (time '^[tT]', weather '^[wW]', etc.). An alnum
        # prefix needs a word boundary; a punctuation prefix does not.
        if self.prefix.isalnum():
            self.command_regex = rf"^{re.escape(self.prefix)}(\s|$)"
        else:
            self.command_regex = rf"^{re.escape(self.prefix)}"

        story = CONF.lurking_horror.story_file
        if not story or not os.path.isfile(story):
            LOG.error(
                f"LurkingHorrorPlugin: story_file missing/invalid ({story!r}); "
                "disabling plugin."
            )
            self.enabled = False
            return
        try:
            self.engine = ZMachineEngine(story)
        except Exception as ex:  # noqa: BLE001 - any load failure must only disable the plugin, never crash daemon startup
            LOG.error(f"LurkingHorrorPlugin: failed to load story {story!r}: {ex}")
            self.enabled = False
            return

        # Restore per-callsign saved games from disk so players resume where
        # they left off across daemon/pod restarts. ObjectStoreMixin only reads
        # the file when load() is called -- nothing else does it for us.
        try:
            store = GameSessionStore()
            store.load()
            LOG.info(
                f"LurkingHorrorPlugin: loaded {len(store)} saved game session(s)."
            )
        except Exception as ex:  # noqa: BLE001 - a bad save file must not crash startup
            LOG.error(f"LurkingHorrorPlugin: failed to load saved sessions: {ex}")

        self.enabled = True

    def create_threads(self):
        if not self.enabled:
            return []
        created = []
        if CONF.lurking_horror.session_idle_timeout > 0:
            created.append(GameIdleThread())
        if (
            CONF.lurking_horror.beacon_enabled
            and CONF.lurking_horror.beacon_latitude is not None
            and CONF.lurking_horror.beacon_longitude is not None
        ):
            created.append(GameBeaconThread())
        elif CONF.lurking_horror.beacon_enabled:
            LOG.warning(
                "LurkingHorror beacon_enabled but beacon_latitude/longitude "
                "not set; beacon disabled."
            )
        return created

    def help(self) -> str:
        p = self.prefix
        return (
            f"Play Lurking Horror: '{p} <cmd>' e.g. '{p} go north'. "
            f"'{p}' resumes, '{p} more' continues long text, "
            f"'{p} restart' starts over."
        )

    def _run_turn(self, state_blob, command):
        """Run one turn under a wall-clock guard so a pathological game can't
        wedge the plugin forever."""
        timeout = CONF.lurking_horror.turn_timeout
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.engine.run_turn, state_blob, command)
            return future.result(timeout=timeout)

    @trace.trace
    def process(self, packet: packets.core.Packet):
        callsign = packet.from_call
        raw = (packet.message_text or "").strip()
        # Strip the prefix to recover the actual game command.
        command = raw[len(self.prefix) :].strip()
        low = command.lower()

        if low in ("help", "?"):
            return self.help()

        store = GameSessionStore()
        lock = _callsign_locks[callsign]
        with lock:
            # '# more' / '# m': send the next batch of previously-truncated text
            # instead of running a game turn.
            if low in ("more", "m"):
                buffered = store.peek_overflow(callsign)
                if not buffered:
                    return "Nothing more to show."
                return self._emit(callsign, buffered, store)

            if low == "restart":
                store.delete(callsign)
                command = ""  # fall through to a fresh game intro

            state = store.get_state(callsign)
            # A bare prefix resumes: show the current room if a game exists,
            # otherwise start a new one (empty command -> intro only).
            if command == "" and state is not None:
                command = "look"

            # A new game turn supersedes any pending overflow from a prior one.
            store.set_overflow(callsign, [])

            try:
                text, new_state = self._run_turn(state, command)
            except FutureTimeout:
                LOG.error(f"LurkingHorror turn timed out for {callsign}")
                return "The horror is slow to respond... (timed out)"
            except GameEngineError as ex:
                LOG.error(f"LurkingHorror engine error for {callsign}: {ex}")
                return f"Game error: {ex}"
            except Exception as ex:
                LOG.exception(f"LurkingHorror unexpected error for {callsign}")
                return f"Game error: {ex}"

            store.record_turn(callsign, new_state)
            return self._emit(callsign, wrap_chunks(text), store)

    def _emit(self, callsign, all_chunks, store):
        """Send up to max_reply_messages chunks now; buffer the rest for
        '# more'. If anything is buffered, the last sent line ends with
        '(more)'."""
        max_msgs = CONF.lurking_horror.max_reply_messages
        to_send, remaining = take_batch(all_chunks, max_msgs)
        store.set_overflow(callsign, remaining)
        return to_send
