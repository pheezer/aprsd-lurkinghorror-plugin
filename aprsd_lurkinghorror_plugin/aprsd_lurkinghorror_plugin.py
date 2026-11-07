import logging
import os
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from aprsd import packets, plugin, threads
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


def chunk_for_aprs(text: str, max_msgs: int, width: int = APRS_MAX_LEN):
    """Flatten game output and split it into <=width word-boundary chunks.

    Returns a single str when it fits in one message (parity with other
    plugins), else a list[str]. Caps at max_msgs, marking truncation.
    """
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return "Ok."

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

    if len(chunks) <= max_msgs:
        return chunks[0] if len(chunks) == 1 else chunks

    kept = chunks[:max_msgs]
    marker = " (more)"
    tail = kept[-1]
    if len(tail) + len(marker) > width:
        tail = tail[: width - len(marker)].rstrip()
    kept[-1] = tail + marker
    return kept


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
        self.enabled = True

    def create_threads(self):
        if self.enabled and CONF.lurking_horror.session_idle_timeout > 0:
            return GameIdleThread()
        return []

    def help(self) -> str:
        p = self.prefix
        return (
            f"Play Lurking Horror: '{p} <cmd>' e.g. '{p} go north'. "
            f"'{p}' alone resumes, '{p} restart' starts over."
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
            if low == "restart":
                store.delete(callsign)
                command = ""  # fall through to a fresh game intro

            state = store.get_state(callsign)
            # A bare prefix resumes: show the current room if a game exists,
            # otherwise start a new one (empty command -> intro only).
            if command == "" and state is not None:
                command = "look"

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

        return chunk_for_aprs(text, CONF.lurking_horror.max_reply_messages)
