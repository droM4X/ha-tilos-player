"""Buttons for Tilos Radio Player: play archive, play live."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TilosRuntimeData, play_live_stream, play_selected_episode
from .const import DOMAIN, LIVE_STREAM_URL


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tilos button entities."""
    runtime: TilosRuntimeData = entry.runtime_data
    async_add_entities(
        [
            TilosPlayButton(hass, entry, runtime),
            TilosLiveButton(hass, entry, runtime),
        ]
    )


class TilosButtonBase(ButtonEntity):
    """Shared bits for all Tilos buttons."""

    _attr_has_entity_name = True
    _suffix = ""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        runtime: TilosRuntimeData,
    ) -> None:
        """Initialize common button attributes."""
        self._hass = hass
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_{self._suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Tilos Rádió",
            manufacturer="Tilos Rádió",
        )


class TilosPlayButton(TilosButtonBase):
    """Button that plays the selected episode on the configured media player."""

    _attr_name = "Play"
    _attr_icon = "mdi:play"
    _suffix = "play_button"

    @property
    def available(self) -> bool:
        """Available only when an episode is selected."""
        return self._runtime.selected_episode is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose what would be played and where."""
        episode = self._runtime.selected_episode
        return {
            "media_player": self._runtime.media_player_entity,
            "mp3_url": episode.url if episode else None,
        }

    async def async_press(self) -> None:
        """Play the selected episode on the configured media player."""
        await play_selected_episode(
            self.hass, self._runtime, self._runtime.media_player_entity
        )


class TilosLiveButton(TilosButtonBase):
    """Button that plays the live Tilos stream on the configured media player."""

    _attr_name = "Live"
    _attr_icon = "mdi:radio"
    _suffix = "live_button"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the stream URL and target player."""
        return {
            "media_player": self._runtime.media_player_entity,
            "stream_url": LIVE_STREAM_URL,
        }

    async def async_press(self) -> None:
        """Play the live stream on the configured media player."""
        await play_live_stream(
            self.hass, self._runtime.media_player_entity
        )
