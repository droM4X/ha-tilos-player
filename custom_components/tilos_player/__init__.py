"""The Tilos Radio Player integration.

Fetches the show list from the Tilos Rádió API, lets the user pick a show
and an episode via select entities, and plays the episode's mp3 archive URL
on a configured media player entity.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from pathlib import Path

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.resources import (
    ResourceStorageCollection,
)

from .const import (
    ARCHIVE_TITLE_PATTERN,
    CONF_LOOKBACK_DAYS,
    CONF_MEDIA_PLAYER,
    DEFAULT_EPISODE_IMAGE,
    DEFAULT_LOOKBACK_DAYS,
    DOMAIN,
    HTTP_HEADERS,
    IMAGE_CHECK_TIMEOUT,
    METADATA_EVENT,
    METADATA_REWRITE_INTERVAL,
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
class ActiveMedia:
    """Metadata of the episode currently patched onto the media player."""

    entity_id: str
    url: str  # the mp3 URL we started — used as the "is it still us" key
    title: str
    artist: str
    image_url: str | None


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
    # Media metadata guard state
    active_media: ActiveMedia | None = None
    metadata_unsub: Any = None
    last_metadata_write: float = 0.0  # time.monotonic() of the last write


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


async def url_exists(session: aiohttp.ClientSession, url: str) -> bool:
    """Return True if the URL responds with HTTP 200 (HEAD request)."""
    try:
        async with session.head(
            url,
            headers=HTTP_HEADERS,
            allow_redirects=True,
            timeout=aiohttp.ClientTimeout(total=IMAGE_CHECK_TIMEOUT),
        ) as resp:
            return resp.status == 200
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.debug("Image existence check failed for %s: %s", url, err)
        return False


# Compiled once — used to detect "an archive episode is playing" from the
# file-name-style media_title the player reports for metadata-less mp3s.
_ARCHIVE_TITLE_RE = re.compile(ARCHIVE_TITLE_PATTERN)

# Player states in which the metadata is worth (re-)applying.
# When the player is off/idle/unavailable ("nothing playing") we skip.
_ACTIVE_PLAYER_STATES = {"playing", "paused", "buffering"}


def _patch_player_state(
    hass: HomeAssistant,
    runtime: TilosRuntimeData,
    media: ActiveMedia,
    force: bool = False,
) -> None:
    """Write the metadata fields onto the player entity's current state.

    Only touches the state machine when something actually differs, so the
    listener cannot create a state_changed feedback loop. Guard-triggered
    re-writes are additionally rate-limited to one per
    METADATA_REWRITE_INTERVAL seconds (pass force=True to bypass, used for
    the initial patch right after play_media).
    """
    state = hass.states.get(media.entity_id)
    if state is None:
        return

    attrs = dict(state.attributes)
    changed = False
    for key, value in (
        ("media_title", media.title),
        ("media_artist", media.artist),
        ("entity_picture", media.image_url),
    ):
        if attrs.get(key) != value:
            attrs[key] = value
            changed = True
    if not changed:
        return

    now = time.monotonic()
    if not force and now - runtime.last_metadata_write < METADATA_REWRITE_INTERVAL:
        _LOGGER.debug("Metadata patch on %s throttled", media.entity_id)
        return
    runtime.last_metadata_write = now

    hass.states.async_set(media.entity_id, state.state, attrs)
    # Also broadcast our own event so trigger-based template helpers can
    # react deterministically — some helper types miss attribute-only
    # state_changed updates on the media player entity.
    hass.bus.async_fire(
        METADATA_EVENT,
        {
            "entity_id": media.entity_id,
            "media_title": media.title,
            "media_artist": media.artist,
            "entity_picture": media.image_url,
        },
    )
    _LOGGER.debug("Applied media metadata to %s (state=%s)", media.entity_id, state.state)


def _is_archive_media(new_state) -> bool:
    """Return True if the player is playing one of our archive episodes.

    The archive mp3s have no ID3 tags, so while one of them is playing the
    player reports its file name ('tilos-YYYYMMDD-HHMMSS-HHMMSS') as
    media_title. Matching that pattern is the key: it is stable across
    seeks, where media_content_id gets rewritten by the player integration.
    The live stream and other sources have different titles and are skipped,
    as are inactive players (off / idle / unavailable).
    """
    if new_state.state not in _ACTIVE_PLAYER_STATES:
        return False
    title = new_state.attributes.get("media_title")
    return bool(title and _ARCHIVE_TITLE_RE.match(str(title)))


def _start_metadata_guard(hass: HomeAssistant, runtime: TilosRuntimeData) -> None:
    """Register a state_changed listener that re-applies the metadata.

    Player integrations re-render the entity state on updates (position,
    seek, volume, ...) and drop the attributes we patched in. The guard
    re-applies them on every state change while the player keeps playing
    the registered episode URL. Registered only once per config entry;
    the active episode lives in runtime.active_media.
    """
    if runtime.metadata_unsub is not None:
        return

    def handle_state_changed(event: Event) -> None:
        media = runtime.active_media
        if media is None:
            return
        if event.data.get("entity_id") != media.entity_id:
            return
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if not _is_archive_media(new_state):
            _LOGGER.debug(
                "Skipping metadata patch on %s: not an archive title (%r, state=%s)",
                media.entity_id,
                new_state.attributes.get("media_title"),
                new_state.state,
            )
            return
        _patch_player_state(hass, runtime, media)

    runtime.metadata_unsub = hass.bus.async_listen(EVENT_STATE_CHANGED, handle_state_changed)
    _LOGGER.debug("Metadata guard registered for %s", runtime.media_player_entity)


def stop_metadata_guard(runtime: TilosRuntimeData) -> None:
    """Unregister the metadata guard (called on entry unload)."""
    if runtime.metadata_unsub is not None:
        runtime.metadata_unsub()
        runtime.metadata_unsub = None
    runtime.active_media = None


async def apply_media_metadata(
    hass: HomeAssistant,
    runtime: TilosRuntimeData,
    session: aiohttp.ClientSession,
    entity_id: str,
    url: str,
    title: str,
    artist: str,
    image_url: str | None,
    delay: float = 0,
) -> None:
    """Patch a media player entity's state with known playback metadata.

    The archive mp3 files carry no ID3 tags, so the player entity would show
    the raw file name. We overwrite media_title / media_artist with the data
    the user already picked from the selects, and set entity_picture to the
    show's cover image — or the integration's brand logo when that image
    does not exist on the server.

    Also registers a metadata guard so the patch survives entity updates
    (seek, position tick, ...) as long as the player keeps playing this mp3.
    """
    # Suppress guard writes during the startup burst: Music Assistant
    # re-renders the entity many times right after play_media. Stamping
    # last_metadata_write at play start makes every guard patch during the
    # first METADATA_PATCH_DELAY seconds hit the rate limit, so the only
    # write in that window is our initial one below.
    runtime.last_metadata_write = time.monotonic()

    if delay:
        await asyncio.sleep(delay)

    # Resolve the cover image: show-specific image when it exists,
    # otherwise the integration's brand logo.
    if image_url and await url_exists(session, image_url):
        final_image = image_url
    else:
        _LOGGER.debug(
            "Cover %s not available, falling back to brand logo", image_url
        )
        final_image = DEFAULT_EPISODE_IMAGE

    media = ActiveMedia(
        entity_id=entity_id,
        url=url,
        title=title,
        artist=artist,
        image_url=final_image,
    )
    runtime.active_media = media
    _start_metadata_guard(hass, runtime)

    state = hass.states.get(entity_id)
    if state is None:
        _LOGGER.warning("Cannot update metadata: entity %s not found", entity_id)
        return

    _patch_player_state(hass, runtime, media, force=True)
    _LOGGER.info(
        "Updated %s metadata: title=%r artist=%r picture=%s",
        entity_id,
        title,
        artist,
        final_image,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tilos Radio Player from a config entry."""
    await _register_frontend(hass)
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
    stop_metadata_guard(entry.runtime_data)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def get_runtime(hass: HomeAssistant, entry: ConfigEntry) -> TilosRuntimeData:
    """Return the runtime data for an entry."""
    return entry.runtime_data

async def _register_frontend(hass: HomeAssistant) -> None:
    """Register the Tilos Player Lovelace card."""

    frontend_dir = Path(__file__).parent / "www"

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                "/api/tilos_player",
                str(frontend_dir),
                True,
            )
        ]
    )

    # Keep this in sync with manifest.json.
    version = "1.2.1"
    url = f"/api/tilos_player/tilos-player-card.js?v={version}"

    lovelace = hass.data["lovelace"]

    resources = (
        lovelace.resources
        if hasattr(lovelace, "resources")
        else lovelace["resources"]
    )

    # Force loading of storage resources before inspecting them.
    await resources.async_get_info()

    for item in resources.async_items():
        if item.get("url", "").split("?")[0] == \
                "/api/tilos_player/tilos-player-card.js":
            return

    if isinstance(resources, ResourceStorageCollection):
        await resources.async_create_item(
            {
                "res_type": "module",
                "url": url,
            }
        )
    else:
        add_extra_js_url(hass, url)
