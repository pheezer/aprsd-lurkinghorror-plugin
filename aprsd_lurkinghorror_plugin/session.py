"""Per-callsign game session storage.

Persists each player's serialized Z-machine state (plus light metadata) across
APRS messages and across daemon restarts, using aprsd's ObjectStoreMixin. State
blobs are base64-encoded so they live comfortably inside the JSON save file.
"""

import base64
import datetime
import logging
import re
import threading
from typing import ClassVar

from aprsd.utils import objectstore

LOG = logging.getLogger("APRSD")


def sanitize_callsign(callsign: str) -> str:
    """Normalize a callsign for use as a stable dict key.

    APRS callsigns may carry an SSID (e.g. ``KFAKE-7``). We uppercase and keep
    only alnum and dash so the same operator always maps to one session.
    """
    return re.sub(r"[^A-Za-z0-9\-]", "", (callsign or "").upper())


def _now_iso() -> str:
    return datetime.datetime.now().isoformat()


def _parse_iso(value) -> datetime.datetime | None:
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


class GameSessionStore(objectstore.ObjectStoreMixin):
    """Singleton mapping sanitized callsign -> session dict.

    Session dict schema::

        {
            "started_at":    ISO-8601 str,
            "last_activity": ISO-8601 str,
            "turns":         int,
            "state_b64":     base64 str of the engine state blob,
        }
    """

    _instance = None
    data: ClassVar[dict] = {}

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.lock = threading.RLock()
            cls._instance.data = {}
        return cls._instance

    def get_state(self, callsign: str) -> bytes | None:
        """Return the player's serialized VM state, or None if no session."""
        key = sanitize_callsign(callsign)
        with self.lock:
            entry = self.data.get(key)
            if not entry:
                return None
            blob_b64 = entry.get("state_b64")
        if not blob_b64:
            return None
        try:
            return base64.b64decode(blob_b64)
        except (ValueError, TypeError) as ex:
            LOG.warning(f"Corrupt saved state for {key}: {ex}; dropping it.")
            self.delete(callsign)
            return None

    def record_turn(self, callsign: str, state_blob: bytes) -> None:
        """Persist the latest VM state for a player and bump metadata."""
        key = sanitize_callsign(callsign)
        now = _now_iso()
        blob_b64 = base64.b64encode(state_blob).decode("ascii")
        with self.lock:
            entry = self.data.get(key)
            if not entry:
                entry = {"started_at": now, "turns": 0}
                self.data[key] = entry
            entry["last_activity"] = now
            entry["turns"] = entry.get("turns", 0) + 1
            entry["state_b64"] = blob_b64
        self.save()

    def set_overflow(self, callsign: str, chunks: list[str]) -> None:
        """Store the not-yet-sent reply chunks for a player (for '# more')."""
        key = sanitize_callsign(callsign)
        with self.lock:
            entry = self.data.get(key)
            if not entry:
                entry = {"started_at": _now_iso(), "turns": 0}
                self.data[key] = entry
            if chunks:
                entry["overflow"] = list(chunks)
            else:
                entry.pop("overflow", None)
        self.save()

    def peek_overflow(self, callsign: str) -> list[str]:
        """Return all buffered reply chunks for a player (without clearing)."""
        key = sanitize_callsign(callsign)
        with self.lock:
            entry = self.data.get(key)
            if not entry:
                return []
            return list(entry.get("overflow") or [])

    def delete(self, callsign: str) -> None:
        """Drop a player's session entirely (used by the restart command)."""
        key = sanitize_callsign(callsign)
        with self.lock:
            self.data.pop(key, None)
        self.save()

    def expire_idle(self, timeout_seconds: int) -> list[str]:
        """Remove sessions idle longer than timeout. Returns expired keys."""
        if timeout_seconds <= 0:
            return []
        cutoff = datetime.datetime.now() - datetime.timedelta(seconds=timeout_seconds)
        expired = []
        with self.lock:
            for key, entry in list(self.data.items()):
                last = _parse_iso(entry.get("last_activity") or entry.get("started_at"))
                # Drop entries with an unreadable timestamp rather than keeping
                # them forever.
                if last is None or last < cutoff:
                    expired.append(key)
                    self.data.pop(key, None)
        if expired:
            self.save()
        return expired
