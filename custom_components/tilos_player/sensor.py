"""Sensor storing the favorite Tilos shows.

The archive picker is a flat list of 200+ shows, so the Lovelace card keeps
the shows the user actually listens to at the top of the dropdown. Those
favorites have to survive restarts, hence an entity of their own: the state
is the number of favorites, the IDs live in the `favorites` attribute, and
the `tilos_player.add_favorite` / `remove_favorite` services write to it.
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

from . import TilosRuntimeData
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tilos favorites sensor."""
    runtime: TilosRuntimeData = entry.runtime_data
    async_add_entities([TilosFavoritesSensor(entry, runtime)])


class TilosFavoritesSensor(RestoreEntity, SensorEntity):
    """Favorite shows of the archive picker."""

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
