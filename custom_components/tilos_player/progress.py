
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

PLAYBACK_PROGRESS_VERSION = 1

PROGRESS_POLL_INTERVAL = 30
PROGRESS_RESUME_MIN = 30
PROGRESS_FINISH_MARGIN = 30
PROGRESS_MAX_ENTRIES = 300
PROGRESS_SAVE_DELAY = 1

SEEK_WAIT_TIMEOUT = 20
SEEK_RETRY_COUNT = 5
SEEK_RETRY_DELAY = 3
SEEK_TOLERANCE = 10

LEADING_DATE_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}\.?\s*(?:[-–—]\s*)?")

HEADER_SEPARATOR = " – "


def format_date(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime(
        "%Y.%m.%d."
    )


def format_now_playing(show_name: str, title: str, timestamp_ms: int) -> str:
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
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def effective_position(
    attributes: Mapping[str, Any], player_state: str, now: datetime
) -> float | None:
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
    if not duration:
        return False
    return position >= duration - PROGRESS_FINISH_MARGIN


def is_resumable(position: float, duration: float) -> bool:
    if position < PROGRESS_RESUME_MIN:
        return False
    return not is_finished(position, duration)


def should_keep_tracking(recorded: bool, stored: bool) -> bool:
    return not recorded or stored


@dataclass
class ProgressEntry:

    key: str
    position: int
    duration: int
    show_name: str
    updated: str


class ProgressBook:

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
        return {entry.show_name for entry in self._entries.values() if entry.show_name}

    def has_any(self, keys: Iterable[str]) -> bool:
        return any(self.has(key) for key in keys)

    def take_dirty(self) -> bool:
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
        while len(self._entries) > self._max_entries:
            oldest = min(self._entries.values(), key=lambda entry: entry.updated)
            self._entries.pop(oldest.key, None)
            self._dirty = True


def _now_iso(now: datetime | None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()
