"""Home Assistant glue for the playback progress book.

The pure model (keys, positions, the resume rules) is in ``progress.py``; this
module adds the storage, the 30 second poll and the listeners that tell the
pickers a progress flag has changed.

It imports nothing from the package at runtime — the archive-key resolver and
the shared runtime data are passed in, so ``__init__.py`` can import this
module without a circular import. Only the types are imported for checking.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import ACTIVE_PLAYER_STATES
from .progress import (
    PLAYBACK_PROGRESS_VERSION,
    PROGRESS_POLL_INTERVAL,
    PROGRESS_SAVE_DELAY,
    ProgressBook,
    effective_position,
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

    def start_tracking(self, entity_id: str, key: str) -> None:
        """Remember that the playback started on this player is ours."""
        self._active[entity_id] = key

    def queue_tracking(self, key: str) -> None:
        """Mark a key that is queued and only plays later."""
        self._queued[key] = None
        self._queued.move_to_end(key)
        while len(self._queued) > QUEUED_KEYS_MAX:
            self._queued.popitem(last=False)

    def clear(self, key: str) -> None:
        """Drop a position ("Előről" or a finished episode).

        The entry is gone, so the pickers must see the change right away.
        """
        if self.book.clear(key):
            self._notify_listeners()

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
                duration = old_state.attributes.get("media_duration") or 0
                self._record(
                    key,
                    float(position),
                    float(duration),
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
        """Store one reading; only a change in the resumable keys is announced."""
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
