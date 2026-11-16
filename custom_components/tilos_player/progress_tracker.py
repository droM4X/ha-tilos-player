"""Home Assistant glue for the playback progress book.

The pure model (keys, positions, the resume rules) is in ``progress.py``; this
module adds the storage, the 30 second poll and the listeners that tell the
pickers a progress flag has changed.

It imports nothing from the package at runtime — the archive-key resolver and
the shared runtime data are passed in, so ``__init__.py`` can import this
module without a circular import. Only the types are imported for checking.
"""

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
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import TilosRuntimeData

_LOGGER = logging.getLogger(__name__)

# Keys that are queued through Music Assistant and not playing yet. Bounded,
# the oldest is dropped — they are only a hint for which playback is ours.
QUEUED_KEYS_MAX = 200


class ProgressTracker:
    """The stored positions, and which playback was started from here."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        runtime: TilosRuntimeData,
        key_from_state: Callable[[Any], str | None],
    ) -> None:
        """Build the tracker for one config entry."""
        self._hass = hass
        # Per entry, so two instances don't fight over one file.
        self._store = Store(
            hass,
            PLAYBACK_PROGRESS_VERSION,
            f"tilos_player_progress_{entry_id}",
            private=True,
        )
        self._runtime = runtime
        self._key_from_state = key_from_state
        self.book = ProgressBook()
        # The pickers re-publish their attributes when a progress flag flips.
        self.listeners: set[Callable[[], None]] = set()
        # Playback started from this integration: player entity -> archive key.
        # Both are in-memory only — after a restart we no longer know which
        # player was ours, only the stored positions survive.
        self._active: dict[str, str] = {}
        self._queued: OrderedDict[str, None] = OrderedDict()
        self._poll_unsub: Callable[[], None] | None = None

    async def async_start(self) -> None:
        """Read the stored positions and start the poll.

        Called before the platforms are set up, so the first render of the
        card already sees the stored positions.
        """
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
        """Stop the poll and write the book out immediately."""
        if self._poll_unsub is not None:
            self._poll_unsub()
            self._poll_unsub = None
        await self._store.async_save(self.book.to_payload())

    async def async_seek_when_ready(
        self, entity_id: str, key: str, position: int
    ) -> None:
        """Seek to a stored position once this episode is really playing.

        The player reports the archive file only after the media is loaded,
        and a seek before that would move whatever else is on the player,
        so first wait for an active state that carries our key. Never
        raises: when the seek does not take, the playback goes on from the
        start.
        """
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
                return

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
            if attempt < SEEK_RETRY_COUNT:
                await asyncio.sleep(SEEK_RETRY_DELAY)

        _LOGGER.warning("Seek to %s s failed on %s", position, entity_id)

    async def _await_playing_episode(self, entity_id: str, key: str) -> bool:
        """Wait for the player to be active and to report exactly this key."""
        deadline = time.monotonic() + SEEK_WAIT_TIMEOUT
        while True:
            state = self._hass.states.get(entity_id)
            if (
                state is not None
                and state.state in ACTIVE_PLAYER_STATES
                and self._key_from_state(state) == key
            ):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(1)

    def _seek_accepted(self, entity_id: str, position: int) -> bool:
        """True when the player now reports the position we asked for."""
        state = self._hass.states.get(entity_id)
        if state is None:
            return False
        current = effective_position(
            state.attributes, state.state, datetime.now(timezone.utc)
        )
        return current is not None and abs(current - position) <= SEEK_TOLERANCE

    def start_tracking(self, entity_id: str, key: str) -> None:
        """Remember that the playback started on this player is ours.

        The key is also queued, so a player that reports the archive file
        only after the first poll (Music Assistant while the file loads) is
        re-adopted instead of lost.
        """
        self._active[entity_id] = key
        self.queue_tracking(key)

    def queue_tracking(self, key: str) -> None:
        """Mark a key that is queued and only plays later."""
        self._queued[key] = None
        self._queued.move_to_end(key)
        while len(self._queued) > QUEUED_KEYS_MAX:
            self._queued.popitem(last=False)

    def clear(self, key: str) -> None:
        """Drop a position ("Előről" or a finished episode).

        The entry is gone, so the pickers must see the change right away,
        and the file must not get the entry back from a later write — a
        crash just after "Előről" must not bring the position back.
        """
        if self.book.clear(key):
            self._notify_listeners()
            self._save()

    def has(self, key: str) -> bool:
        """True when this episode has a stored position."""
        return self.book.has(key)

    def position(self, key: str) -> int:
        """Stored position of an episode, 0 when there is none."""
        return self.book.position(key)

    def show_names(self) -> set[str]:
        """The shows that have a stored position."""
        return self.book.show_names()

    def has_any(self, keys: Iterable[str]) -> bool:
        """True when any of these episodes has a stored position."""
        return self.book.has_any(keys)

    @callback
    def note_state_change(self, entity_id: str, old_state: Any, new_state: Any) -> None:
        """Close the tracking when a player we started moved on or stopped.

        The last stored position stays: an interrupted show is still
        resumable. The old state is the freshest position we have — by the
        next poll the player already reports something else.
        """
        key = self._active.get(entity_id)
        if key is None:
            return

        new_key = None
        if new_state is not None and new_state.state in ACTIVE_PLAYER_STATES:
            new_key = self._key_from_state(new_state)
        if new_key == key:
            return

        self._active.pop(entity_id, None)

        if old_state is not None:
            position = old_state.attributes.get("media_position")
            if isinstance(position, (int, float)):
                self._record(
                    key,
                    float(position),
                    float(old_state.attributes.get("media_duration") or 0),
                    self._show_name(key),
                    datetime.now(timezone.utc),
                )
                if self.book.take_dirty():
                    self._save()

    @callback
    def _async_poll(self, now: datetime) -> None:
        """Read the position of every watched player once."""
        for entity_id in list(self._runtime.watched_players):
            self._poll_entity(entity_id, now)

        if self.book.take_dirty():
            self._save()

    def _poll_entity(self, entity_id: str, now: datetime) -> None:
        """Handle one watched player: adopt a queued item, read, or close."""
        state = self._hass.states.get(entity_id)
        if state is None:
            # The entity is gone — nothing left to read on it.
            self._active.pop(entity_id, None)
            return

        key = None
        if state.state in ACTIVE_PLAYER_STATES:
            key = self._key_from_state(state)

        tracked = self._active.get(entity_id)
        if tracked is None:
            if key is not None and key in self._queued:
                # The queued item started playing — from now on it is ours.
                self._active[entity_id] = key
                self._queued.pop(key, None)
                tracked = key
            else:
                return

        if key != tracked:
            # Something else took the player over; the entry stays as it is.
            self._active.pop(entity_id, None)
            return

        position = effective_position(state.attributes, state.state, now)
        if position is None:
            return

        duration = state.attributes.get("media_duration") or 0
        self._record(tracked, position, float(duration), self._show_name(tracked), now)

        if not self.book.has(tracked):
            # Finished (or dropped below the minimum) — nothing left to track.
            self._active.pop(entity_id, None)

    def _record(
        self,
        key: str,
        position: float,
        duration: float,
        show_name: str,
        now: datetime,
    ) -> None:
        """Store one reading; only a change in the resumable keys is announced.

        A reading that is neither resumable nor finished says nothing about
        the episode: a ten-second accidental playback must not delete a
        twenty-minute stored position, so it is not passed to the book.
        """
        if not is_resumable(position, duration) and not is_finished(position, duration):
            return
        if self.book.record(key, position, duration, show_name, now):
            self._notify_listeners()

    def _show_name(self, key: str) -> str:
        """Show name of a key from the metadata index, empty when unknown."""
        info = self._runtime.media_index.get(key)
        return info.show_name if info is not None else ""

    @callback
    def _notify_listeners(self) -> None:
        """Ask the pickers to re-publish their progress flags."""
        for listener in list(self.listeners):
            listener()

    @callback
    def _save(self) -> None:
        """Schedule writing the book out.

        `async_delay_save` is a callback API; the delayed write runs after the
        given delay (and the Store flushes on shutdown too), so several polls
        do not write several files.
        """
        self._store.async_delay_save(self.book.to_payload, PROGRESS_SAVE_DELAY)
