"""Select entities for Tilos Radio Player: show picker and episode picker."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import aiohttp
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import Episode, Show, TilosRuntimeData, fetch_episodes
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tilos select entities."""
    runtime: TilosRuntimeData = entry.runtime_data

    episode_select = TilosEpisodeSelect(hass, entry, runtime)
    show_select = TilosShowSelect(hass, entry, runtime, episode_select)

    async_add_entities([show_select, episode_select])


class TilosShowSelect(CoordinatorEntity, SelectEntity):
    """Select entity listing the available Tilos shows."""

    _attr_has_entity_name = True
    _attr_name = "Show"
    _attr_icon = "mdi:radio"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        runtime: TilosRuntimeData,
        episode_select: TilosEpisodeSelect,
    ) -> None:
        """Initialize the show select."""
        super().__init__(runtime.coordinator)
        self._runtime = runtime
        self._episode_select = episode_select
        self._attr_unique_id = f"{entry.entry_id}_show_select"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Tilos Rádió",
            manufacturer="Tilos Rádió",
        )

    @property
    def options(self) -> list[str]:
        """Available shows, sorted alphabetically (from the coordinator)."""
        shows = self._runtime.coordinator.data or []
        return [show.name for show in shows]

    @property
    def current_option(self) -> str | None:
        """Currently selected show name."""
        return self._runtime.selected_show.name if self._runtime.selected_show else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose details of the selected show."""
        show = self._runtime.selected_show
        if not show:
            return {}
        return {"alias": show.alias, "type": show.type, "id": show.id}

    @property
    def available(self) -> bool:
        """Available when the coordinator has show data."""
        return bool(self._runtime.coordinator.data)

    async def async_select_option(self, option: str) -> None:
        """Handle show selection: store it and refresh the episode list."""
        shows = self._runtime.coordinator.data or []
        selected = next((s for s in shows if s.name == option), None)
        if selected is None:
            _LOGGER.warning("Unknown show selected: %s", option)
            return

        self._runtime.selected_show = selected
        self._runtime.episodes = []
        self._runtime.selected_episode = None
        self.async_write_ha_state()

        _LOGGER.info("Show selected: %s (%s)", selected.name, selected.alias)
        await self._episode_select.async_refresh_episodes()


class TilosEpisodeSelect(SelectEntity):
    """Select entity listing episodes of the selected show."""

    _attr_has_entity_name = True
    _attr_name = "Episode"
    _attr_icon = "mdi:playlist-music"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        runtime: TilosRuntimeData,
    ) -> None:
        """Initialize the episode select."""
        self._hass = hass
        self._runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_episode_select"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Tilos Rádió",
            manufacturer="Tilos Rádió",
        )

    @property
    def options(self) -> list[str]:
        """Episode labels (date + title), newest first."""
        return [self._episode_label(ep) for ep in self._runtime.episodes]

    @property
    def current_option(self) -> str | None:
        """Currently selected episode label."""
        if self._runtime.selected_episode is None:
            return None
        return self._episode_label(self._runtime.selected_episode)

    @property
    def available(self) -> bool:
        """Available only when a show is selected."""
        return self._runtime.selected_show is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the resolved mp3 URL and related info."""
        episode = self._runtime.selected_episode
        show = self._runtime.selected_show
        attrs: dict[str, Any] = {
            "show": show.name if show else None,
            "episode_count": len(self._runtime.episodes),
        }
        if episode:
            attrs["mp3_url"] = episode.url
            attrs["title"] = episode.title
            attrs["broadcast"] = self._format_ts(episode.timestamp)
        return attrs

    async def async_select_option(self, option: str) -> None:
        """Handle episode selection: store the matching Episode object."""
        for ep in self._runtime.episodes:
            if self._episode_label(ep) == option:
                self._runtime.selected_episode = ep
                _LOGGER.info("Episode selected: %s -> %s", ep.title, ep.url)
                break
        self.async_write_ha_state()

    async def async_refresh_episodes(self) -> None:
        """Fetch episodes of the selected show (called by the show select)."""
        show = self._runtime.selected_show
        if show is None:
            return

        session = async_get_clientsession(self._hass)

        try:
            episodes = await fetch_episodes(
                session, show.alias, self._runtime.lookback_days
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Failed to fetch episodes for %s: %s", show.alias, err)
            episodes = []
        except Exception as err:  # noqa: BLE001 - keep the UI responsive
            _LOGGER.exception(
                "Unexpected error fetching episodes for %s: %s", show.alias, err
            )
            episodes = []

        self._runtime.episodes = episodes
        self._runtime.selected_episode = None
        self.async_write_ha_state()

    @staticmethod
    def _episode_label(episode: Episode) -> str:
        """Build the option label: broadcast date + title.

        Many Tilos titles already start with their broadcast date
        (e.g. '2026.07.17. - Tracklistával') — in that case keep the
        title as-is to avoid a doubled date.
        """
        title = episode.title
        if re.match(r"^\d{4}\.\d{2}\.\d{2}\.?", title):
            return title
        date_str = TilosEpisodeSelect._format_ts(episode.timestamp)
        return f"{date_str} — {title}"

    @staticmethod
    def _format_ts(ts_ms: int) -> str:
        """Format a ms epoch as a short date string (Europe/Budapest)."""
        if not ts_ms:
            return "????.??.??."
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y.%m.%d.")
