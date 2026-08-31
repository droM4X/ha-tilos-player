"""Buttons for Tilos Radio Player: play archive, play live, reload shows."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TilosRuntimeData
from .const import DOMAIN, LIVE_STREAM_URL

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tilos button entities."""
    runtime: TilosRuntimeData = entry.runtime_data
    async_add_entities(
        [
            TilosReloadShowsButton(hass, entry, runtime),
            TilosPlayButton(hass, entry, runtime),
            TilosLiveButton(hass, entry, runtime),
        ]
    )


async def play_on_player(hass: HomeAssistant, entity_id: str, url: str) -> None:
    """Call media_player.play_media with the given URL."""
    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": entity_id,
            "media_content_type": "music",
            "media_content_id": url,
        },
        blocking=False,
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


class TilosReloadShowsButton(TilosButtonBase):
    """Button that re-fetches the show list from the API."""

    _attr_name = "Reload shows"
    _attr_icon = "mdi:refresh"
    _suffix = "reload_shows_button"

    @property
    def available(self) -> bool:
        """Available when the last show-list update succeeded."""
        return self._runtime.coordinator.last_update_success

    async def async_press(self) -> None:
        """Request an immediate refresh of the show list."""
        _LOGGER.info("Manual show list refresh requested")
        await self._runtime.coordinator.async_request_refresh()


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
        """Play the selected episode's mp3 on the configured media player."""
        episode = self._runtime.selected_episode
        if episode is None:
            _LOGGER.warning("Play pressed but no episode is selected")
            return

        target = self._runtime.media_player_entity
        _LOGGER.info(
            "Playing '%s' on %s: %s", episode.title, target, episode.url
        )
        await play_on_player(self.hass, target, episode.url)


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
        target = self._runtime.media_player_entity
        _LOGGER.info("Playing live stream on %s: %s", target, LIVE_STREAM_URL)
        await play_on_player(self.hass, target, LIVE_STREAM_URL)
