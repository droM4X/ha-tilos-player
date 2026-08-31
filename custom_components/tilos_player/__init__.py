"""The Tilos Radio Player integration.

Fetches the show list from the Tilos Rádió API, lets the user pick a show
and an episode via select entities, and plays the episode's mp3 archive URL
on a configured media player entity.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_LOOKBACK_DAYS,
    CONF_MEDIA_PLAYER,
    DEFAULT_LOOKBACK_DAYS,
    DOMAIN,
    HTTP_HEADERS,
    SHOW_TYPE_MUSIC,
    SHOWS_UPDATE_INTERVAL,
    SHOWS_URL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["select", "button"]


@dataclass
class Episode:
    """A single playable episode."""

    title: str
    url: str
    timestamp: int  # ms epoch of realFrom (fallback plannedFrom)
    m3u_url: str


@dataclass
class Show:
    """A radio show."""

    id: str
    name: str
    alias: str
    type: str
    definition: str = ""


@dataclass
class TilosRuntimeData:
    """Shared state for one config entry."""

    coordinator: DataUpdateCoordinator[list[Show]]
    lookback_days: int
    media_player_entity: str
    # Session state driven by the selects
    selected_show: Show | None = None
    episodes: list[Episode] = field(default_factory=list)
    selected_episode: Episode | None = None


async def fetch_shows(session: aiohttp.ClientSession) -> list[Show]:
    """Fetch and parse the show list from the Tilos API."""
    async with session.get(SHOWS_URL, headers=HTTP_HEADERS) as resp:
        resp.raise_for_status()
        raw = await resp.json()

    if not isinstance(raw, list):
        _LOGGER.warning(
            "Unexpected shows payload (type %s): %.300s",
            type(raw).__name__,
            raw,
        )
        return []

    shows = [
        Show(
            id=item["id"],
            name=item["name"].strip(),
            alias=item["alias"],
            type=item.get("type") or "",
            definition=item.get("definition") or "",
        )
        for item in raw
        if isinstance(item, dict)
        and item.get("type") in ("MUSIC", "SPEECH")
        and item.get("alias")
    ]
    # MUSIC shows first (A-Z), then SPEECH shows (A-Z) — same grouping
    # as the original bash fetcher (music_count + speech_count output)
    shows.sort(key=lambda s: (s.type != SHOW_TYPE_MUSIC, s.name.casefold()))
    _LOGGER.info("Fetched %d shows from Tilos API", len(shows))
    return shows


async def fetch_episodes(
    session: aiohttp.ClientSession, alias: str, lookback_days: int
) -> list[Episode]:
    """Fetch episodes of one show and build direct mp3 URLs."""
    now_ms = int(time.time()) * 1000  # second precision, ends in 000 like the bash fetcher
    # lookback may arrive as float (NumberSelector stores 120.0) — coerce to int
    start = now_ms - int(lookback_days) * 24 * 3600 * 1000
    url = (
        f"https://tilos.hu/api/show/{alias}/episodes"
        f"?start={start}&end={now_ms}"
    )
    _LOGGER.debug("Fetching episodes: %s", url)

    async with session.get(url, headers=HTTP_HEADERS) as resp:
        resp.raise_for_status()
        raw = await resp.json()

    if not isinstance(raw, list):
        # WAF / rate-limit / API error payloads can be dicts or strings;
        # log what actually came back instead of crashing on it
        _LOGGER.warning(
            "Unexpected episodes payload for show '%s' (type %s): %.300s",
            alias,
            type(raw).__name__,
            raw,
        )
        return []

    episodes: list[Episode] = []
    for item in raw:
        if not isinstance(item, dict):
            _LOGGER.debug("Skipping non-dict episode entry: %.100s", item)
            continue
        m3u = item.get("m3uUrl")
        if not m3u:
            continue
        text = item.get("text")
        title = text.get("title") if isinstance(text, dict) else None
        title = (title or "Unknown title").strip()
        episodes.append(
            Episode(
                title=title,
                url=mp3_url_from_m3u(m3u),
                timestamp=item.get("realFrom") or item.get("plannedFrom") or 0,
                m3u_url=m3u,
            )
        )
    episodes.sort(key=lambda e: e.timestamp, reverse=True)
    _LOGGER.info("Fetched %d episodes for show '%s'", len(episodes), alias)
    return episodes


def mp3_url_from_m3u(m3u_url: str) -> str:
    """Apply the Tilos archive URL rule: /mp3/ -> /cache/ and .m3u -> .mp3."""
    url = m3u_url.replace("/mp3/", "/cache/", 1)
    if url.endswith(".m3u"):
        url = url[: -len(".m3u")] + ".mp3"
    return url


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tilos Radio Player from a config entry."""
    session = async_get_clientsession(hass)

    async def async_update_shows() -> list[Show]:
        return await fetch_shows(session)

    coordinator: DataUpdateCoordinator[list[Show]] = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_shows",
        update_method=async_update_shows,
        update_interval=timedelta(hours=SHOWS_UPDATE_INTERVAL),
    )
    await coordinator.async_config_entry_first_refresh()

    runtime = TilosRuntimeData(
        coordinator=coordinator,
        lookback_days=entry.data.get(CONF_LOOKBACK_DAYS, DEFAULT_LOOKBACK_DAYS),
        media_player_entity=entry.data[CONF_MEDIA_PLAYER],
    )
    entry.runtime_data = runtime

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def get_runtime(hass: HomeAssistant, entry: ConfigEntry) -> TilosRuntimeData:
    """Return the runtime data for an entry."""
    return entry.runtime_data
