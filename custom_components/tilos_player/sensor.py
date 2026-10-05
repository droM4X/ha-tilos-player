"""Sensors for Tilos Radio Player.

Two entities of their own, because the data behind them has to survive
restarts and the picker logic reads it from the entity states:

* `Favorites` — the favorite show IDs (the `add_favorite` /
  `remove_favorite` services write to it), stored in the state itself,
  which is small enough for the recorder.
* `Saved episodes` — the episodes saved for later ("Mentés későbbre").
  These carry the whole episode (title, description, show name, cover,
  mp3 URL), which is far past the recorder's attribute limit even for a
  single one, so they are persisted in a `Store` file instead.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.storage import Store

from . import (
    TilosRuntimeData,
    restore_saved_episodes,
    saved_episode_payload,
    sorted_saved_episodes,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "tilos_player_saved_episodes"
# Írási késleltetés másodpercben: egymás utáni
# mentések/eltávolítások egy fájlírásba
# összekapcsolódnak.
STORAGE_WRITE_DELAY = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tilos sensors."""
    runtime: TilosRuntimeData = entry.runtime_data
    async_add_entities(
        [
            TilosFavoritesSensor(entry, runtime),
            TilosSavedEpisodesSensor(hass, entry, runtime),
        ]
    )


class TilosFavoritesSensor(RestoreEntity, SensorEntity):
    """Favorite shows of the archive picker.

    The picker is a flat list of 200+ shows, so the Lovelace card keeps
    the shows the user actually listens to at the top of the dropdown.
    These favorites have to survive restarts, hence an entity of their own:
    the state is the number of favorites, the IDs live in the `favorites`
    attribute, and the `tilos_player.add_favorite` / `remove_favorite`
    services write to it.
    """

    _attr_has_entity_name = True
    _attr_name = "Favorites"
    _attr_icon = "mdi:star"
    _attr_should_poll = False

    def __init__(
        self,
        entry: ConfigEntry,
        runtime: TilosRuntimeData,
    ) -> None:
        """Initialize the favorites sensor."""
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_favorites"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Tilos Rádió",
            manufacturer="Tilos Rádió",
        )

    @property
    def native_value(self) -> int:
        """Number of favorite shows."""
        return len(self._runtime.favorites)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Favorite show IDs, sorted so the state stays comparable."""
        return {"favorites": sorted(self._runtime.favorites)}

    async def async_added_to_hass(self) -> None:
        """Restore the stored favorites and subscribe to changes."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is not None:
            restored = last_state.attributes.get("favorites") or []
            if isinstance(restored, list):
                self._runtime.favorites.update(str(item) for item in restored)
                _LOGGER.debug(
                    "Restored %d favorite shows", len(self._runtime.favorites)
                )
            else:
                _LOGGER.warning(
                    "Ignoring malformed restored favorites: %.200s", restored
                )

        self._runtime.favorites_listeners.add(self._handle_favorites_changed)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from favorites changes."""
        self._runtime.favorites_listeners.discard(self._handle_favorites_changed)
        await super().async_will_remove_from_hass()

    @callback
    def _handle_favorites_changed(self) -> None:
        """Re-publish the state after a favorite service call."""
        self.async_write_ha_state()


class TilosSavedEpisodesSensor(SensorEntity):
    """Episodes the user saved for later.

    The archive list only reaches back a few months, so an episode can be
    kept and replayed any time. The whole episode is stored with it (the
    description alone is past the recorder's attribute limit), which is
    why this is persisted in a `Store` file and not in the entity state —
    the state only carries the count and the keys.
    """

    _attr_has_entity_name = True
    _attr_name = "Saved episodes"
    _attr_icon = "mdi:bookmark"
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        runtime: TilosRuntimeData,
    ) -> None:
        """Initialize the saved episodes sensor."""
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_saved_episodes"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Tilos Rádió",
            manufacturer="Tilos Rádió",
        )
        # Per entry, so two instances don't fight over one list.
        self._store: Store = Store(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY}_{entry.entry_id}",
            private=True,
        )

    @property
    def native_value(self) -> int:
        """Number of saved episodes."""
        return len(self._runtime.saved_episodes)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Saved episode keys, newest first (just a hint for automations)."""
        return {
            "saved_episodes": [
                saved_episode_payload(episode)["key"]
                for episode in sorted_saved_episodes(self._runtime)
            ]
        }

    async def async_added_to_hass(self) -> None:
        """Load the stored episodes back and subscribe to changes."""
        await super().async_added_to_hass()

        stored = await self._store.async_load()
        if stored:
            restore_saved_episodes(
                self._runtime,
                stored.get("episodes")
                if isinstance(stored, dict)
                else stored,
            )

        self._runtime.saved_episodes_listeners.add(
            self._handle_saved_episodes_changed
        )
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe and make sure the latest state is on its way to disk."""
        self._runtime.saved_episodes_listeners.discard(
            self._handle_saved_episodes_changed
        )
        self._async_save()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_saved_episodes_changed(self) -> None:
        """Re-publish the state and persist the list after a service call."""
        self.async_write_ha_state()
        self._async_save()

    @callback
    def _async_save(self) -> None:
        """Schedule writing the saved episodes out.

        `async_delay_save` a callback API, és a késleltetett írás a
        megadott késleltetés után lefut (a Store a leálláskor is
        kiüríti), így több gyors szolgáltatáshívás nem ír külön fájlt.
        """
        self._store.async_delay_save(
            self._storage_payload,
            STORAGE_WRITE_DELAY,
        )

    def _storage_payload(self) -> dict[str, Any]:
        """The exact data to store (built at write time)."""
        return {
            "episodes": [
                saved_episode_payload(episode)
                for episode in sorted_saved_episodes(self._runtime)
            ]
        }
