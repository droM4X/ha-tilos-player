
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import ACTIVE_PLAYER_STATES
from .progress import (
    PLAYBACK_PROGRESS_VERSION,
    PROGRESS_POLL_INTERVAL,
    PROGRESS_SAVE_DELAY,
    SEEK_RETRY_COUNT,
    SEEK_RETRY_DELAY,
    SEEK_TOLERANCE,
    SEEK_WAIT_TIMEOUT,
    ProgressBook,
    effective_position,
    is_finished,
    is_resumable,
    should_keep_tracking,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import TilosRuntimeData

_LOGGER = logging.getLogger(__name__)

QUEUED_KEYS_MAX = 200


class ProgressTracker:

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        runtime: TilosRuntimeData,
        key_from_state: Callable[[Any], str | None],
        state_is_ours: Callable[[Any, str], bool],
    ) -> None:
        self._hass = hass
        self._store = Store(
            hass,
            PLAYBACK_PROGRESS_VERSION,
            f"tilos_player_progress_{entry_id}",
            private=True,
        )
        self._runtime = runtime
        self._key_from_state = key_from_state
        self._state_is_ours = state_is_ours
        self.book = ProgressBook()
        self.listeners: set[Callable[[], None]] = set()
        self._active: dict[str, str] = {}
        self._queued: OrderedDict[str, None] = OrderedDict()
        self._poll_unsub: Callable[[], None] | None = None

    async def async_start(self) -> None:
        try:
            payload = await self._store.async_load()
        except (OSError, ValueError) as err:
            _LOGGER.warning("Could not load stored playback progress: %s", err)
            payload = None

        self.book = ProgressBook.from_payload(payload)
        self._poll_unsub = async_track_time_interval(
            self._hass, self._async_poll, timedelta(seconds=PROGRESS_POLL_INTERVAL)
        )

    async def async_stop(self) -> None:
        if self._poll_unsub is not None:
            self._poll_unsub()
            self._poll_unsub = None
        await self._store.async_save(self.book.to_payload())

    async def async_seek_when_ready(
        self, entity_id: str, key: str, position: int
    ) -> None:
        if not await self._await_playing_episode(entity_id, key):
            _LOGGER.warning(
                "Seek to %s s failed on %s: the episode did not start",
                position,
                entity_id,
            )
            return

        for attempt in range(1, SEEK_RETRY_COUNT + 1):
            try:
                await self._hass.services.async_call(
                    "media_player",
                    "media_seek",
                    {"entity_id": entity_id, "seek_position": position},
                    blocking=True,
                )
            except (HomeAssistantError, TimeoutError) as err:
                _LOGGER.warning(
                    "Seek to %s s failed on %s: %s", position, entity_id, err
                )
                await asyncio.sleep(SEEK_RETRY_DELAY)
                continue

            await asyncio.sleep(SEEK_RETRY_DELAY)

            if self._seek_accepted(entity_id, position):
                _LOGGER.debug("Seek to %s s accepted on %s", position, entity_id)
                return

            _LOGGER.warning(
                "Seek to %s s on %s not confirmed (attempt %d/%d)",
                position,
                entity_id,
                attempt,
                SEEK_RETRY_COUNT,
            )

        _LOGGER.warning("Seek to %s s failed on %s", position, entity_id)

    async def _await_playing_episode(self, entity_id: str, key: str) -> bool:
        deadline = time.monotonic() + SEEK_WAIT_TIMEOUT
        while True:
            state = self._hass.states.get(entity_id)
            if (
                state is not None
                and state.state in ACTIVE_PLAYER_STATES
                and (
                    self._key_from_state(state) == key
                    or self._state_is_ours(state, key)
                )
            ):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(1)

    def _seek_accepted(self, entity_id: str, position: int) -> bool:
        state = self._hass.states.get(entity_id)
        if state is None:
            return False
        current = effective_position(
            state.attributes, state.state, datetime.now(timezone.utc)
        )
        return current is not None and abs(current - position) <= SEEK_TOLERANCE

    def start_tracking(self, entity_id: str, key: str) -> None:
        self._active[entity_id] = key
        self.queue_tracking(key)

    def queue_tracking(self, key: str) -> None:
        self._queued[key] = None
        self._queued.move_to_end(key)
        while len(self._queued) > QUEUED_KEYS_MAX:
            self._queued.popitem(last=False)

    def clear(self, key: str) -> None:
        if self.book.clear(key):
            self._notify_listeners()
            self._save()

    def has(self, key: str) -> bool:
        return self.book.has(key)

    def position(self, key: str) -> int:
        return self.book.position(key)

    def show_names(self) -> set[str]:
        return self.book.show_names()

    def has_any(self, keys: Iterable[str]) -> bool:
        return self.book.has_any(keys)

    @callback
    def note_state_change(self, entity_id: str, old_state: Any, new_state: Any) -> None:
        key = self._active.get(entity_id)
        if key is None:
            return

        if new_state is not None and new_state.state in ACTIVE_PLAYER_STATES:
            new_key = self._key_from_state(new_state)
            if new_key is None or new_key == key:
                return

        self._active.pop(entity_id, None)

        if old_state is not None:
            now = datetime.now(timezone.utc)
            position = effective_position(old_state.attributes, old_state.state, now)
            if position is not None:
                self._record(
                    key,
                    position,
                    float(old_state.attributes.get("media_duration") or 0),
                    self._show_name(key),
                    now,
                )
                if self.book.take_dirty():
                    self._save()

    @callback
    def _async_poll(self, now: datetime) -> None:
        for entity_id in list(self._runtime.watched_players):
            self._poll_entity(entity_id, now)

        if self.book.take_dirty():
            self._save()

    def _poll_entity(self, entity_id: str, now: datetime) -> None:
        state = self._hass.states.get(entity_id)
        if state is None:
            self._active.pop(entity_id, None)
            return

        key = None
        if state.state in ACTIVE_PLAYER_STATES:
            key = self._key_from_state(state)

        tracked = self._active.get(entity_id)
        if tracked is None:
            if key is not None and key in self._queued:
                self._active[entity_id] = key
                self._queued.pop(key, None)
                tracked = key
            else:
                return

        if state.state not in ACTIVE_PLAYER_STATES:
            self._active.pop(entity_id, None)
            return

        if key is not None and key != tracked:
            self._active.pop(entity_id, None)
            return

        if key is None and not self._state_is_ours(state, tracked):
            self._active.pop(entity_id, None)
            return

        position = effective_position(state.attributes, state.state, now)
        if position is None:
            return

        duration = state.attributes.get("media_duration") or 0
        recorded = self._record(
            tracked, position, float(duration), self._show_name(tracked), now
        )

        if not should_keep_tracking(recorded, self.book.has(tracked)):
            self._active.pop(entity_id, None)

    def _record(
        self,
        key: str,
        position: float,
        duration: float,
        show_name: str,
        now: datetime,
    ) -> bool:
        if not is_resumable(position, duration) and not is_finished(position, duration):
            return False
        if self.book.record(key, position, duration, show_name, now):
            self._notify_listeners()
        return True

    def _show_name(self, key: str) -> str:
        info = self._runtime.media_index.get(key)
        return info.show_name if info is not None else ""

    @callback
    def _notify_listeners(self) -> None:
        for listener in list(self.listeners):
            listener()

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(self.book.to_payload, PROGRESS_SAVE_DELAY)
