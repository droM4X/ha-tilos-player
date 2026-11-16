"""The pure playback-progress model and the card header text.

This module is deliberately Home Assistant free: it may only import from the
standard library and must not import from the package, so the model can be
tested without HA. The HA glue (Store, the 30 second poll, the listeners) is in
``progress_tracker.py``.

Entries are keyed by the archive file name (``tilos-YYYYMMDD-HHMMSS-HHMMSS``),
the same key the metadata watcher resolves, so saved positions survive restarts
and work for saved episodes too.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

PLAYBACK_PROGRESS_VERSION = 1

PROGRESS_POLL_INTERVAL = 30  # the requested half-minute check
PROGRESS_RESUME_MIN = 30  # a position shorter than this is not resumable
PROGRESS_FINISH_MARGIN = 30  # this close to the end the episode is finished
PROGRESS_MAX_ENTRIES = 300  # upper bound, the oldest entry is evicted
PROGRESS_SAVE_DELAY = 1  # Store.async_delay_save delay

SEEK_WAIT_TIMEOUT = 20  # seconds to wait for the player to start
SEEK_RETRY_COUNT = 5
SEEK_RETRY_DELAY = 3
SEEK_TOLERANCE = 10  # seconds within which a seek is accepted

# Tilos episode titles often already start with the broadcast date
# ("2026.07.17. - Tracklistával"); the header must not repeat it.
LEADING_DATE_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}\.?\s*(?:[-–—]\s*)?")

HEADER_SEPARATOR = " – "


def format_date(timestamp_ms: int) -> str:
    """Format a ms epoch as the date string the episode picker uses (UTC)."""
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime(
        "%Y.%m.%d."
    )


def format_now_playing(show_name: str, title: str, timestamp_ms: int) -> str:
    """Build the header line: "Show – Title (YYYY.MM.DD.)".

    A title that already starts with the broadcast date loses it, so the date
    is not shown twice; if the title is only a date it is kept as it is. A
    missing show name or date is simply left out (direct link playback).
    """
    title = (title or "").strip()
    match = LEADING_DATE_RE.match(title)
    if match:
        remainder = title[match.end() :].strip()
        if remainder:
            title = remainder

    parts = [part for part in ((show_name or "").strip(), title) if part]
    text = HEADER_SEPARATOR.join(parts)
    if timestamp_ms and text:
        text = f"{text} ({format_date(timestamp_ms)})"
    return text


def _as_utc(value: datetime) -> datetime:
    """Read a datetime as UTC — state timestamps are not always aware."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def effective_position(
    attributes: Mapping[str, Any], player_state: str, now: datetime
) -> float | None:
    """Current playback position, corrected for the delay of the poll.

    Home Assistant only refreshes ``media_position`` when it writes the state,
    so a value read 30 seconds later is stale: while playing we add the seconds
    elapsed since ``media_position_updated_at``. While paused nothing moves, so
    nothing is extrapolated (a pause would otherwise push the resume point
    forward). Without a usable position we return None — storing 0 would move
    the resume point to the start.
    """
    position = attributes.get("media_position")
    if not isinstance(position, (int, float)):
        return None
    position = float(position)

    if player_state == "playing":
        updated_at = attributes.get("media_position_updated_at")
        if isinstance(updated_at, datetime):
            position += (_as_utc(now) - _as_utc(updated_at)).total_seconds()

    return max(0.0, position)


def is_finished(position: float, duration: float) -> bool:
    """True when the episode has played to within the finish margin."""
    if not duration:
        # A stream never reports a duration; its entry stays resumable.
        return False
    return position >= duration - PROGRESS_FINISH_MARGIN


def is_resumable(position: float, duration: float) -> bool:
    """True when a position is worth resuming from."""
    if position < PROGRESS_RESUME_MIN:
        return False
    return not is_finished(position, duration)


def should_keep_tracking(recorded: bool, stored: bool) -> bool:
    """Keep tracking unless the reading was stored and the entry is gone (finished).

    A reading that never reached the book says nothing about the episode, so
    the first poll of a fresh playback — always below the resume minimum — must
    not close the tracking; only a reading the book accepted and that no longer
    has an entry means the episode is finished.
    """
    return not recorded or stored


@dataclass
class ProgressEntry:
    """One stored position for one archive episode key."""

    key: str
    position: int
    duration: int
    show_name: str
    updated: str


class ProgressBook:
    """The stored positions, keyed by archive episode key."""

    def __init__(self, max_entries: int = PROGRESS_MAX_ENTRIES) -> None:
        self._entries: dict[str, ProgressEntry] = {}
        self._max_entries = max_entries
        self._dirty = False

    def record(
        self,
        key: str,
        position: float,
        duration: float,
        show_name: str,
        now: datetime | None = None,
    ) -> bool:
        """Store a position; True when the set of resumable keys changed.

        The bool is what drives the entity listeners — writing their state on
        every poll would be pointless — while ``take_dirty()`` decides whether
        the file is written, because the position moves without the key set
        changing. A position below the minimum or at the end is not stored.
        """
        if not key:
            return False

        position = int(round(position))
        duration = int(round(duration))
        if not is_resumable(position, duration):
            return self.clear(key)

        entry = self._entries.get(key)
        if entry is None:
            self._entries[key] = ProgressEntry(
                key=key,
                position=position,
                duration=duration,
                show_name=show_name,
                updated=_now_iso(now),
            )
            self._dirty = True
            self._evict()
            return True

        # An entry registered from the media index has a show name; a later
        # poll that cannot resolve the key (e.g. after a restart, while the
        # episode keeps playing) must not blank it out.
        show_name = show_name or entry.show_name

        if (entry.position, entry.duration, entry.show_name) == (
            position,
            duration,
            show_name,
        ):
            return False

        entry.position = position
        entry.duration = duration
        entry.show_name = show_name
        entry.updated = _now_iso(now)
        self._dirty = True
        return False

    def clear(self, key: str) -> bool:
        """Drop an entry ("Előről", or a finished episode); True on removal."""
        if self._entries.pop(key, None) is None:
            return False
        self._dirty = True
        return True

    def get(self, key: str) -> ProgressEntry | None:
        return self._entries.get(key)

    def has(self, key: str) -> bool:
        return key in self._entries

    def position(self, key: str) -> int:
        entry = self._entries.get(key)
        return entry.position if entry else 0

    def show_names(self) -> set[str]:
        """The shows that have a stored position."""
        return {entry.show_name for entry in self._entries.values() if entry.show_name}

    def has_any(self, keys: Iterable[str]) -> bool:
        return any(self.has(key) for key in keys)

    def take_dirty(self) -> bool:
        """Report whether the contents changed since the last check, and reset."""
        dirty = self._dirty
        self._dirty = False
        return dirty

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": PLAYBACK_PROGRESS_VERSION,
            "entries": {
                key: {
                    "position": entry.position,
                    "duration": entry.duration,
                    "show_name": entry.show_name,
                    "updated": entry.updated,
                }
                for key, entry in self._entries.items()
            },
        }

    @classmethod
    def from_payload(cls, payload: Any) -> ProgressBook:
        """Read a stored payload; anything that does not fit is skipped.

        The version is not checked on read, so a file written by a newer
        version still loads instead of failing the integration setup.
        """
        book = cls()
        raw_entries = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(raw_entries, dict):
            return book

        for key, raw in raw_entries.items():
            if not isinstance(key, str) or not isinstance(raw, dict):
                continue
            position = raw.get("position")
            if not isinstance(position, (int, float)):
                continue
            duration = raw.get("duration")
            duration = (
                int(round(duration)) if isinstance(duration, (int, float)) else 0
            )
            # A legacy or hand-edited file can hold a position that is not
            # worth resuming; keeping it would offer a "Folytatás" that seeks
            # to the start.
            if not is_resumable(int(round(position)), duration):
                continue
            book._entries[key] = ProgressEntry(
                key=key,
                position=int(round(position)),
                duration=duration,
                show_name=str(raw.get("show_name", "")),
                updated=str(raw.get("updated", "")),
            )

        book._evict()
        return book

    def _evict(self) -> None:
        """Drop the oldest entries past the limit so the file cannot grow."""
        while len(self._entries) > self._max_entries:
            oldest = min(self._entries.values(), key=lambda entry: entry.updated)
            self._entries.pop(oldest.key, None)
            self._dirty = True


def _now_iso(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()
