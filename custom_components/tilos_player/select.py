"""Select entities for Tilos Radio Player: show picker and episode picker."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import (
    Episode,
    Show,
    TilosRuntimeData,
    fetch_episodes,
    fetch_show_info,
    is_saved_episode,
    register_episodes,
    resolve_show_image,
    saved_episode_key,
    saved_show,
    sorted_saved_episodes,
)
from .const import DOMAIN, SAVED_EPISODES_LABEL, SAVED_SHOW_ID

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

    # The 200+ entry show list is ~17 kB, past the recorder's attribute
    # limit. The card reads it from the live state, so keep it out of the
    # database. The show description is HTML and can be several kB too.
    _unrecorded_attributes = frozenset(
        {"shows", "info_definition", "info_description"}
    )

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
        """Available shows, sorted alphabetically (from the coordinator).

        When there is at least one saved episode, a "Mentett epizódok"
        entry comes first; picking it swaps the episode picker to the
        saved list instead of a show's archive window.
        """
        shows = self._runtime.coordinator.data or []
        options = [show.name for show in shows]

        if self._runtime.saved_episodes:
            options.insert(0, SAVED_EPISODES_LABEL)

        return options

    @property
    def current_option(self) -> str | None:
        """Currently selected show name."""
        return self._runtime.selected_show.name if self._runtime.selected_show else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the whole show list plus details of the selected show.

        The card needs the per-show type (to group the dropdown) and the
        per-show ID (to match favorites) — neither fits into the flat
        `options` list.
        """
        shows = self._runtime.coordinator.data or []
        attrs: dict[str, Any] = {
            "shows": [
                {"id": str(show.id), "name": show.name, "type": show.type}
                for show in shows
            ]
        }

        show = self._runtime.selected_show
        if show:
            attrs["alias"] = show.alias
            attrs["type"] = show.type
            attrs["id"] = str(show.id)

        # Show-level info for the card's show info button. Only present
        # once the info fetch for the selected show has completed.
        info = self._runtime.show_info
        if info:
            attrs["info_name"] = info.name
            attrs["info_definition"] = info.definition
            attrs["info_description"] = info.description

        return attrs

    @property
    def available(self) -> bool:
        """Available when the coordinator has show data."""
        return bool(self._runtime.coordinator.data)

    async def async_added_to_hass(self) -> None:
        """Subscribe to saved-episode changes (option list depends on it)."""
        await super().async_added_to_hass()
        self._runtime.saved_episodes_listeners.add(
            self._handle_saved_episodes_changed
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from saved-episode changes."""
        self._runtime.saved_episodes_listeners.discard(
            self._handle_saved_episodes_changed
        )
        await super().async_will_remove_from_hass()

    @callback
    def _handle_saved_episodes_changed(self) -> None:
        """Re-publish the options when an episode is saved or removed.

        While the saved list is open, the removed episode may be the
        selected one — drop it so the entity state stays consistent.
        """
        if (
            self._runtime.selected_show is not None
            and self._runtime.selected_show.id == SAVED_SHOW_ID
        ):
            selected = self._runtime.selected_episode
            if selected is not None and not is_saved_episode(
                self._runtime, selected
            ):
                self._runtime.selected_episode = None

            self._runtime.episodes = sorted_saved_episodes(self._runtime)

        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Handle show selection: store it and refresh the episode list."""

        if option == SAVED_EPISODES_LABEL and self._runtime.saved_episodes:
            await self._select_show(saved_show())
            return

        shows = self._runtime.coordinator.data or []
        selected = next((s for s in shows if s.name == option), None)
        if selected is None:
            _LOGGER.warning("Unknown show selected: %s", option)
            return

        await self._select_show(selected)

    async def _select_show(self, selected: Show) -> None:
        """Store the picked show and rebuild the episode list around it."""
        self._runtime.selected_show = selected
        # Drop the previous show's info immediately: the entity state flips
        # to the new show now, and the card must not show stale info while
        # the new one is being fetched.
        self._runtime.show_info = None
        self._runtime.episodes = []
        self._runtime.selected_episode = None
        self.async_write_ha_state()

        _LOGGER.info("Show selected: %s (%s)", selected.name, selected.alias)
        await self._episode_select.async_refresh_episodes()
        # Re-publish so the freshly fetched show info reaches the card.
        self.async_write_ha_state()


async def _fetch_guarded(coro, fallback, label: str, alias: str):
    """Await a fetch, logging and falling back on any regular error.

    Only `Exception` is caught — a cancellation (CancelledError) still
    propagates, so unloading the entry is not swallowed here.
    """
    try:
        return await coro
    except Exception as err:  # noqa: BLE001 - keep the UI responsive
        _LOGGER.error("Failed to fetch %s for %s: %s", label, alias, err)
        return fallback


class TilosEpisodeSelect(SelectEntity):
    """Select entity listing episodes of the selected show."""

    _attr_has_entity_name = True
    _attr_name = "Episode"
    _attr_icon = "mdi:playlist-music"

    # The HTML description can be several kB and is only needed by the
    # card in the live state — keep it out of the recorder database.
    _unrecorded_attributes = frozenset({"description"})

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        runtime: TilosRuntimeData,
    ) -> None:
        """Initialize the episode select."""
        self._hass = hass
        self._runtime = runtime
        # Pontosan az a felirat, amit a felhasztó
        # kiválasztott. Így a duplikált (számozott)
        # címkék is helyesen mappablek az epizódra.
        self._selected_label: str | None = None
        self._attr_unique_id = f"{entry.entry_id}_episode_select"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Tilos Rádió",
            manufacturer="Tilos Rádió",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to saved-episode changes (they change the list)."""
        await super().async_added_to_hass()
        self._runtime.saved_episodes_listeners.add(
            self._handle_saved_episodes_changed
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from saved-episode changes."""
        self._runtime.saved_episodes_listeners.discard(
            self._handle_saved_episodes_changed
        )
        await super().async_will_remove_from_hass()

    @callback
    def _handle_saved_episodes_changed(self) -> None:
        """Re-publish the options when an episode is saved or removed.

        While the saved list is open it is our own option list, so it has
        to be rebuilt (and a removed selection dropped).
        """
        if (
            self._runtime.selected_show is not None
            and self._runtime.selected_show.id == SAVED_SHOW_ID
        ):
            selected = self._runtime.selected_episode
            if selected is not None and not is_saved_episode(
                self._runtime, selected
            ):
                self._runtime.selected_episode = None
                self._selected_label = None

            self._runtime.episodes = sorted_saved_episodes(self._runtime)

        self.async_write_ha_state()

    @property
    def options(self) -> list[str]:
        """Episode labels (date + title), newest first.

        Labels must be unique, otherwise the selection would be ambiguous
        — the show name can repeat (two saved episodes of the same show,
        same title), so a counter is appended in that rare case.
        """
        labels: list[str] = []
        seen: dict[str, int] = {}

        for episode in self._runtime.episodes:
            label = self._episode_label(episode)

            count = seen.get(label, 0) + 1
            seen[label] = count

            if count > 1:
                label = f"{label} ({count})"

            labels.append(label)

        return labels

    @property
    def current_option(self) -> str | None:
        """Currently selected episode label."""
        if self._runtime.selected_episode is None:
            return None

        options = self.options
        label = self._selected_label

        if label is not None and label in options:
            return label

        return self._episode_label(
            self._runtime.selected_episode
        )

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
        if show is not None and show.id == SAVED_SHOW_ID:
            attrs["saved_list"] = True

        if episode:
            attrs["mp3_url"] = episode.url
            attrs["title"] = episode.title
            attrs["broadcast"] = self._format_ts(episode.timestamp)
            # What the card's "Mentés későbbre" row toggles: the stable
            # key of the episode and whether it is saved already.
            attrs["save_key"] = saved_episode_key(episode)
            attrs["saved"] = is_saved_episode(self._runtime, episode)
            if episode.show_name:
                attrs["episode_show"] = episode.show_name
            if episode.description:
                attrs["description"] = episode.description
        return attrs

    async def async_select_option(self, option: str) -> None:
        """Handle episode selection: store the matching Episode object.

        The option strings come from `options` (which disambiguates
        duplicates), so the match is done by position on that very list.
        """
        options = self.options

        try:
            index = options.index(option)
        except ValueError:
            _LOGGER.warning(
                "Unknown episode selected: %s", option
            )
        else:
            episode = self._runtime.episodes[index]
            self._runtime.selected_episode = episode
            self._selected_label = option
            _LOGGER.info(
                "Episode selected: %s -> %s",
                episode.title,
                episode.url,
            )

        self.async_write_ha_state()

    async def async_refresh_episodes(self) -> None:
        """Fetch episodes and show info of the selected show.

        Called by the show select. Both requests go out together so picking
        a show feels instant; a failure of either one is contained so the
        UI still gets whatever the other returned.

        The "Mentett epizódok" pseudo-show fetches nothing: it just lists
        what was saved earlier.
        """
        show = self._runtime.selected_show
        if show is None:
            return

        if show.id == SAVED_SHOW_ID:
            self._runtime.show_info = None
            self._runtime.episodes = sorted_saved_episodes(self._runtime)
            self._runtime.selected_episode = None
            self._selected_label = None

            _LOGGER.info(
                "Browsing saved episodes: %d entries",
                len(self._runtime.episodes),
            )
            self.async_write_ha_state()
            return

        session = async_get_clientsession(self._hass)

        show_info, episodes = await asyncio.gather(
            _fetch_guarded(
                fetch_show_info(session, show.alias),
                None,
                "show info",
                show.alias,
            ),
            _fetch_guarded(
                fetch_episodes(
                    session, show.alias, self._runtime.lookback_days
                ),
                [],
                "episodes",
                show.alias,
            ),
        )

        self._runtime.show_info = show_info
        self._runtime.episodes = episodes
        self._runtime.selected_episode = None
        self._selected_label = None

        # Remember the metadata of the fetched episodes under their mp3
        # file name, so the player metadata can be resolved later — even
        # for Music Assistant queue playback the card never sees start.
        if episodes:
            image_url = await resolve_show_image(
                session, self._runtime, show.alias
            )
            register_episodes(
                self._runtime, episodes, show.name, image_url
            )

        self.async_write_ha_state()

    @staticmethod
    def _episode_label(episode: Episode) -> str:
        """Build the option label: broadcast date + title (+ show name).

        Many Tilos titles already start with their broadcast date
        (e.g. '2026.07.17. - Tracklistával') — in that case keep the
        title as-is to avoid a doubled date.

        The show name is only appended for saved episodes: those can come
        from any show, so it is the only hint of what they are.
        """
        title = episode.title
        if re.match(r"^\d{4}\.\d{2}\.\d{2}\.?", title):
            label = title
        else:
            date_str = TilosEpisodeSelect._format_ts(episode.timestamp)
            label = f"{date_str} — {title}"

        if episode.show_name:
            label = f"{label} · {episode.show_name}"

        return label

    @staticmethod
    def _format_ts(ts_ms: int) -> str:
        """Format a ms epoch as a short date string (Europe/Budapest)."""
        if not ts_ms:
            return "????.??.??."
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y.%m.%d.")
