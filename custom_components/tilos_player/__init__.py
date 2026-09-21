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
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable
from pathlib import Path
from urllib.parse import unquote, urlparse

import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.loader import async_get_integration
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.resources import (
    ResourceStorageCollection,
)

from .const import (
    ARCHIVE_KEY_PATTERN,
    ATTR_ENQUEUE,
    ATTR_MEDIA,
    ATTR_SHOW_ID,
    ATTR_URL,
    CONF_LOOKBACK_DAYS,
    CONF_MEDIA_PLAYER,
    DEFAULT_EPISODE_IMAGE,
    DEFAULT_LOOKBACK_DAYS,
    DOMAIN,
    ENQUEUE_OPTIONS,
    EPISODE_IMAGE_URL,
    HTTP_HEADERS,
    IMAGE_CHECK_TIMEOUT,
    LIVE_STREAM_URL,
    MEDIA_ARTIST_SUFFIX,
    MEDIA_EPISODE,
    MEDIA_INDEX_MAX_ENTRIES,
    MEDIA_LIVE,
    MEDIA_URL,
    METADATA_EVENT,
    METADATA_PATCH_DELAY,
    METADATA_POLL_INTERVAL,
    METADATA_REWRITE_INTERVAL,
    SERVICE_ADD_FAVORITE,
    SERVICE_PLAY,
    SERVICE_REMOVE_FAVORITE,
    SHOW_INFO_URL,
    SHOW_TYPE_MUSIC,
    SHOWS_UPDATE_INTERVAL,
    SHOWS_URL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["select", "button", "sensor"]


@dataclass
class Episode:
    """A single playable episode."""

    title: str
    url: str
    timestamp: int  # ms epoch of realFrom (fallback plannedFrom)
    m3u_url: str
    # Show description / tracklist as HTML, straight from the API's
    # text.formatted field (falls back to text.content). Every episode
    # has its own, and it may be empty.
    description: str = ""


@dataclass
class Show:
    """A radio show."""

    id: str
    name: str
    alias: str
    type: str
    definition: str = ""


@dataclass
class ShowInfo:
    """Show-level info fetched when the show is picked.

    Comes from /api/show/{alias}/episodes *without* a start/end range,
    which returns the show object instead of the episode list. `definition`
    is a short plain-text summary, `description` is the long HTML blurb.
    """

    name: str
    definition: str
    description: str


@dataclass
class EpisodeInfo:
    """Metadata of one archive episode, keyed by its mp3 file name.

    The archive mp3s carry no ID3 tags, so when one is playing we can only
    recognise it by the 'tilos-YYYYMMDD-HHMMSS-HHMMSS' file name the player
    reports. This record is what we look up (and write onto the player) when
    that happens — for direct playback and for Music Assistant queue items
    alike, because we remembered what was browsed/enqueued.
    """

    key: str  # 'tilos-YYYYMMDD-HHMMSS-HHMMSS'
    title: str
    artist: str
    image_url: str
    url: str


@dataclass
class TilosRuntimeData:
    """Shared state for one config entry."""

    coordinator: DataUpdateCoordinator[list[Show]]
    lookback_days: int
    media_player_entity: str
    # Session state driven by the selects
    selected_show: Show | None = None
    # Show-level description of the selected show (fetched alongside the
    # episode list) — shown by the card's show info button.
    show_info: ShowInfo | None = None
    episodes: list[Episode] = field(default_factory=list)
    selected_episode: Episode | None = None
    # Favorite show IDs — owned by the favorites sensor (which persists them
    # via RestoreEntity) and mutated by the favorite services.
    favorites: set[str] = field(default_factory=set)
    favorites_listeners: set[Callable[[], None]] = field(default_factory=set)
    # Media metadata: local file-name -> metadata index, the media players
    # the user has targeted from the card, and the resolved cover per show.
    media_index: "OrderedDict[str, EpisodeInfo]" = field(
        default_factory=OrderedDict
    )
    watched_players: set[str] = field(default_factory=set)
    show_images: dict[str, str] = field(default_factory=dict)
    metadata_state_unsub: Any = None
    metadata_poll_unsub: Any = None
    # time.monotonic() of the last metadata write, per entity
    last_metadata_write: dict[str, float] = field(default_factory=dict)


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
        if not isinstance(text, dict):
            text = {}
        title = (text.get("title") or "Unknown title").strip()
        # The API serves the same HTML under both keys; `formatted` is the
        # documented one, `content` is kept as a fallback.
        description = text.get("formatted") or text.get("content") or ""
        if not isinstance(description, str):
            description = ""
        episodes.append(
            Episode(
                title=title,
                url=mp3_url_from_m3u(m3u),
                timestamp=item.get("realFrom") or item.get("plannedFrom") or 0,
                m3u_url=m3u,
                description=description.strip(),
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


async def fetch_show_info(
    session: aiohttp.ClientSession, alias: str
) -> ShowInfo | None:
    """Fetch a show's own metadata (definition + description).

    The episodes endpoint with a start/end range returns the episode list;
    without the range it returns the show object itself, which is where the
    show-level definition and description live. Returns None on any
    unexpected payload so the card simply keeps the info button disabled.
    """
    url = SHOW_INFO_URL.format(alias=alias)
    _LOGGER.debug("Fetching show info: %s", url)

    async with session.get(url, headers=HTTP_HEADERS) as resp:
        resp.raise_for_status()
        raw = await resp.json()

    if not isinstance(raw, dict):
        _LOGGER.warning(
            "Unexpected show info payload for '%s' (type %s): %.300s",
            alias,
            type(raw).__name__,
            raw,
        )
        return None

    description = raw.get("description") or ""
    if not isinstance(description, str):
        description = ""

    return ShowInfo(
        name=str(raw.get("name") or "").strip(),
        definition=str(raw.get("definition") or "").strip(),
        description=description.strip(),
    )


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


# Compiled once — matches the archive file name inside media_title or
# media_content_id ('tilos-YYYYMMDD-HHMMSS-HHMMSS', with or without path
# and extension), which is how we recognise one of our episodes.
_ARCHIVE_KEY_RE = re.compile(ARCHIVE_KEY_PATTERN)

# Player states in which the metadata is worth (re-)applying.
# When the player is off/idle/unavailable ("nothing playing") we skip.
_ACTIVE_PLAYER_STATES = {"playing", "paused", "buffering"}


def archive_key(value: Any) -> str | None:
    """Return the 'tilos-...' file name inside `value`, if there is one."""
    if not value:
        return None
    match = _ARCHIVE_KEY_RE.search(str(value))
    return match.group(0) if match else None


def _archive_key_from_state(state) -> str | None:
    """Find the archive file name the player currently reports.

    Music Assistant may expose the original URL in media_content_id, other
    players only the bare file name in media_title — check both.
    """
    for attr in ("media_content_id", "media_title"):
        key = archive_key(state.attributes.get(attr))
        if key is not None:
            return key
    return None


def _remember_media(
    runtime: TilosRuntimeData,
    key: str,
    title: str,
    artist: str,
    image_url: str,
    url: str,
) -> None:
    """Store one media metadata record in the bounded local index."""
    runtime.media_index[key] = EpisodeInfo(
        key=key,
        title=title,
        artist=artist,
        image_url=image_url,
        url=url,
    )
    runtime.media_index.move_to_end(key)

    # Keep the index bounded — drop the least recently registered episodes.
    while len(runtime.media_index) > MEDIA_INDEX_MAX_ENTRIES:
        runtime.media_index.popitem(last=False)


def register_episode(
    runtime: TilosRuntimeData,
    episode: Episode,
    show_name: str,
    image_url: str,
) -> str | None:
    """Remember one episode's metadata under its mp3 file name."""
    key = archive_key(episode.url)
    if key is None:
        return None

    _remember_media(
        runtime,
        key,
        episode.title,
        f"{show_name}{MEDIA_ARTIST_SUFFIX}",
        image_url,
        episode.url,
    )
    return key


def register_episodes(
    runtime: TilosRuntimeData,
    episodes: list[Episode],
    show_name: str,
    image_url: str,
) -> None:
    """Remember a whole episode list (called when a show is fetched)."""
    for episode in episodes:
        register_episode(runtime, episode, show_name, image_url)


async def resolve_show_image(
    session: aiohttp.ClientSession,
    runtime: TilosRuntimeData,
    alias: str,
) -> str:
    """Resolve (and cache) the cover image URL of one show.

    Uses the show-specific image when it exists on the server, otherwise
    the integration's brand logo. Cached per show so the HEAD request runs
    once per show instead of once per episode.
    """
    cached = runtime.show_images.get(alias)
    if cached is not None:
        return cached

    candidate = EPISODE_IMAGE_URL.format(alias=alias)
    if await url_exists(session, candidate):
        image = candidate
    else:
        _LOGGER.debug(
            "Cover %s not available, falling back to brand logo", candidate
        )
        image = DEFAULT_EPISODE_IMAGE

    runtime.show_images[alias] = image
    return image


def _patch_player_metadata(
    hass: HomeAssistant,
    runtime: TilosRuntimeData,
    entity_id: str,
    info: EpisodeInfo,
    force: bool = False,
) -> None:
    """Write the episode metadata onto the player entity's current state.

    Only touches the state machine when something actually differs, so the
    listener cannot create a state_changed feedback loop. Re-writes are
    rate-limited to one per METADATA_REWRITE_INTERVAL seconds per entity
    (pass force=True to bypass, used right after play_media).
    """
    state = hass.states.get(entity_id)
    if state is None:
        return

    attrs = dict(state.attributes)
    changed = False
    for key, value in (
        ("media_title", info.title),
        ("media_artist", info.artist),
        ("entity_picture", info.image_url),
    ):
        if attrs.get(key) != value:
            attrs[key] = value
            changed = True
    if not changed:
        return

    now = time.monotonic()
    last = runtime.last_metadata_write.get(entity_id, 0.0)
    if not force and now - last < METADATA_REWRITE_INTERVAL:
        _LOGGER.debug("Metadata patch on %s throttled", entity_id)
        return
    runtime.last_metadata_write[entity_id] = now

    hass.states.async_set(entity_id, state.state, attrs)
    # Also broadcast our own event so trigger-based template helpers can
    # react deterministically — some helper types miss attribute-only
    # state_changed updates on the media player entity.
    hass.bus.async_fire(
        METADATA_EVENT,
        {
            "entity_id": entity_id,
            "media_title": info.title,
            "media_artist": info.artist,
            "entity_picture": info.image_url,
        },
    )
    _LOGGER.debug(
        "Applied media metadata to %s (state=%s, key=%s)",
        entity_id,
        state.state,
        info.key,
    )


def refresh_player_metadata(
    hass: HomeAssistant,
    runtime: TilosRuntimeData,
    entity_id: str,
    state: Any = None,
    force: bool = False,
) -> None:
    """Re-apply the metadata if the player is playing a known archive file.

    This is the core of the metadata handling: it always looks at what the
    player reports *right now* and resolves it through the local index, so
    queue playback (where the card never sees the track that starts) gets
    the correct title/cover instead of a stale one.
    """
    if state is None:
        state = hass.states.get(entity_id)
    if state is None or state.state not in _ACTIVE_PLAYER_STATES:
        return

    key = _archive_key_from_state(state)
    if key is None:
        return

    info = runtime.media_index.get(key)
    if info is None:
        _LOGGER.debug("No metadata registered for archive file %s", key)
        return

    _patch_player_metadata(hass, runtime, entity_id, info, force=force)


@callback
def _start_metadata_watch(hass: HomeAssistant, runtime: TilosRuntimeData) -> None:
    """Watch the targeted player(s) and keep the metadata patched.

    Two triggers: a state_changed listener for immediate reaction to track
    changes, and a periodic timer as a safety net. Both resolve the media
    the player currently reports, so nothing can go stale.
    """
    if runtime.metadata_state_unsub is not None:
        return

    @callback
    def handle_state_changed(event: Event) -> None:
        entity_id = event.data.get("entity_id")
        if entity_id not in runtime.watched_players:
            return
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        refresh_player_metadata(hass, runtime, entity_id, new_state)

    @callback
    def handle_poll(_now) -> None:
        for entity_id in list(runtime.watched_players):
            refresh_player_metadata(hass, runtime, entity_id)

    runtime.metadata_state_unsub = hass.bus.async_listen(
        EVENT_STATE_CHANGED, handle_state_changed
    )
    runtime.metadata_poll_unsub = async_track_time_interval(
        hass, handle_poll, timedelta(seconds=METADATA_POLL_INTERVAL)
    )
    _LOGGER.debug("Metadata watcher registered")


def stop_metadata_watch(runtime: TilosRuntimeData) -> None:
    """Unregister the metadata watcher (called on entry unload)."""
    if runtime.metadata_state_unsub is not None:
        runtime.metadata_state_unsub()
        runtime.metadata_state_unsub = None
    if runtime.metadata_poll_unsub is not None:
        runtime.metadata_poll_unsub()
        runtime.metadata_poll_unsub = None


async def _patch_after_delay(
    hass: HomeAssistant,
    runtime: TilosRuntimeData,
    entity_id: str,
    delay: float,
) -> None:
    """Re-apply the metadata once the player's startup burst has settled."""
    if delay:
        await asyncio.sleep(delay)
    refresh_player_metadata(hass, runtime, entity_id, force=True)


# Service schema shared by add_favorite / remove_favorite
FAVORITE_SERVICE_SCHEMA = vol.Schema({vol.Required(ATTR_SHOW_ID): cv.string})


def _apply_favorite(
    runtime: TilosRuntimeData, show_id: str, favorite: bool
) -> bool:
    """Add or remove a favorite show ID; True when the set changed."""
    if favorite:
        if show_id in runtime.favorites:
            return False
        runtime.favorites.add(show_id)
    else:
        if show_id not in runtime.favorites:
            return False
        runtime.favorites.discard(show_id)
    return True


def _notify_favorites_changed(runtime: TilosRuntimeData) -> None:
    """Ask the favorites sensor to re-publish its state.

    The sensor owns the entity state, so the service handlers (which only
    mutate the shared set) go through it instead of writing HA state
    themselves.
    """
    for listener in list(runtime.favorites_listeners):
        listener()


@callback
def _async_register_favorite_services(
    hass: HomeAssistant, runtime: TilosRuntimeData
) -> None:
    """Register the favorite services for the loaded entry."""

    async def async_add_favorite(call: ServiceCall) -> None:
        """Add a show to the favorites."""
        show_id = str(call.data[ATTR_SHOW_ID])
        if not _apply_favorite(runtime, show_id, True):
            return
        _LOGGER.info("Favorite show added: %s", show_id)
        _notify_favorites_changed(runtime)

    async def async_remove_favorite(call: ServiceCall) -> None:
        """Remove a show from the favorites."""
        show_id = str(call.data[ATTR_SHOW_ID])
        if not _apply_favorite(runtime, show_id, False):
            return
        _LOGGER.info("Favorite show removed: %s", show_id)
        _notify_favorites_changed(runtime)

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_FAVORITE,
        async_add_favorite,
        schema=FAVORITE_SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_FAVORITE,
        async_remove_favorite,
        schema=FAVORITE_SERVICE_SCHEMA,
    )


@callback
def _async_unregister_favorite_services(hass: HomeAssistant) -> None:
    """Drop the favorite services when the entry is unloaded."""
    for service in (SERVICE_ADD_FAVORITE, SERVICE_REMOVE_FAVORITE):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


async def play_on_player(hass: HomeAssistant, entity_id: str, url: str) -> None:
    """Play a URL directly on a media player (Home Assistant path)."""
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


async def play_on_music_assistant(
    hass: HomeAssistant, entity_id: str, url: str, enqueue: str
) -> None:
    """Queue/play a URL through Music Assistant (queue-aware path)."""
    await hass.services.async_call(
        "music_assistant",
        "play_media",
        {
            "entity_id": entity_id,
            "media_id": url,
            "enqueue": enqueue,
        },
        blocking=False,
    )


async def play_selected_episode(
    hass: HomeAssistant,
    runtime: TilosRuntimeData,
    entity_id: str,
    enqueue: str | None = None,
) -> None:
    """Play (or enqueue) the selected archive episode on `entity_id`.

    The episode is registered in the local index first, so the metadata can
    be resolved later — including when Music Assistant starts a queued item
    on its own, without the card being involved.
    """
    episode = runtime.selected_episode
    show = runtime.selected_show
    if episode is None:
        _LOGGER.warning("Play requested but no episode is selected")
        return
    if show is None:
        _LOGGER.warning("Play requested but no show is selected")
        return

    image_url = await resolve_show_image(
        async_get_clientsession(hass), runtime, show.alias
    )
    register_episode(runtime, episode, show.name, image_url)

    # Watch this player from now on: the metadata watcher resolves whatever
    # archive file it reports (direct playback and queue items alike).
    runtime.watched_players.add(entity_id)
    _start_metadata_watch(hass, runtime)

    if enqueue is None:
        _LOGGER.info(
            "Playing '%s' on %s: %s", episode.title, entity_id, episode.url
        )
        await play_on_player(hass, entity_id, episode.url)
    else:
        _LOGGER.info(
            "Enqueueing '%s' (%s) on %s: %s",
            episode.title,
            enqueue,
            entity_id,
            episode.url,
        )
        await play_on_music_assistant(hass, entity_id, episode.url, enqueue)

    # The archive mp3 has no ID3 tags, so re-apply the metadata once the
    # player's startup burst has settled.
    hass.async_create_task(
        _patch_after_delay(hass, runtime, entity_id, METADATA_PATCH_DELAY)
    )


def _title_from_url(url: str) -> str:
    """Best-effort title for a directly pasted URL (its file name)."""
    path = urlparse(url).path or url
    name = unquote(path.rsplit("/", 1)[-1])
    if name.lower().endswith(".mp3"):
        name = name[: -len(".mp3")]
    return name.strip() or "Ismeretlen"


async def play_direct_url(
    hass: HomeAssistant,
    runtime: TilosRuntimeData,
    entity_id: str,
    url: str,
    enqueue: str | None = None,
) -> None:
    """Play (or enqueue) an mp3 URL pasted into the card's link field.

    Any mp3 URL is accepted, not only Tilos archive links. When the URL is
    one of our archive files its metadata is still registered, so the
    title/cover stay correct while it plays.
    """
    if not url:
        _LOGGER.warning("Play requested but no direct URL was given")
        return

    key = archive_key(url)
    if key is not None:
        _remember_media(
            runtime,
            key,
            _title_from_url(url),
            "Tilos Rádió",
            DEFAULT_EPISODE_IMAGE,
            url,
        )

    # Watch this player from now on, exactly like archive playback.
    runtime.watched_players.add(entity_id)
    _start_metadata_watch(hass, runtime)

    if enqueue is None:
        _LOGGER.info("Playing direct URL on %s: %s", entity_id, url)
        await play_on_player(hass, entity_id, url)
    else:
        _LOGGER.info(
            "Enqueueing direct URL (%s) on %s: %s", enqueue, entity_id, url
        )
        await play_on_music_assistant(hass, entity_id, url, enqueue)

    hass.async_create_task(
        _patch_after_delay(hass, runtime, entity_id, METADATA_PATCH_DELAY)
    )


async def play_live_stream(hass: HomeAssistant, entity_id: str) -> None:
    """Play the live Tilos stream on `entity_id`."""
    _LOGGER.info("Playing live stream on %s: %s", entity_id, LIVE_STREAM_URL)
    await play_on_player(hass, entity_id, LIVE_STREAM_URL)


PLAY_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Optional(ATTR_MEDIA, default=MEDIA_EPISODE): vol.In(
            [MEDIA_EPISODE, MEDIA_LIVE, MEDIA_URL]
        ),
        # Only used when media: url — any mp3 URL, not just Tilos links.
        vol.Optional(ATTR_URL): cv.string,
        # When set, the episode goes through Music Assistant's queue
        # (play / add / next / ...). Without it we play directly.
        vol.Optional(ATTR_ENQUEUE): vol.In(ENQUEUE_OPTIONS),
    }
)


@callback
def _async_register_play_service(
    hass: HomeAssistant, runtime: TilosRuntimeData
) -> None:
    """Register the play service for the loaded entry."""

    async def async_play(call: ServiceCall) -> None:
        """Play the selection on the media player passed in the call."""
        entity_id = call.data[ATTR_ENTITY_ID]
        media = call.data.get(ATTR_MEDIA, MEDIA_EPISODE)
        enqueue = call.data.get(ATTR_ENQUEUE)
        if media == MEDIA_LIVE:
            await play_live_stream(hass, entity_id)
            return
        if media == MEDIA_URL:
            url = (call.data.get(ATTR_URL) or "").strip()
            if not url:
                _LOGGER.warning(
                    "Play service called with media=url but no url"
                )
                return
            await play_direct_url(hass, runtime, entity_id, url, enqueue)
            return
        await play_selected_episode(hass, runtime, entity_id, enqueue)

    hass.services.async_register(
        DOMAIN, SERVICE_PLAY, async_play, schema=PLAY_SERVICE_SCHEMA
    )


@callback
def _async_unregister_play_service(hass: HomeAssistant) -> None:
    """Drop the play service when the entry is unloaded."""
    if hass.services.has_service(DOMAIN, SERVICE_PLAY):
        hass.services.async_remove(DOMAIN, SERVICE_PLAY)


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

    # Watch the integration-configured player from the start, so playback
    # that did not go through the card (e.g. started from the Music
    # Assistant app) also gets the metadata once the file is in the index.
    runtime.watched_players.add(runtime.media_player_entity)
    _start_metadata_watch(hass, runtime)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_favorite_services(hass, runtime)
    _async_register_play_service(hass, runtime)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    stop_metadata_watch(entry.runtime_data)
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        _async_unregister_favorite_services(hass)
        _async_unregister_play_service(hass)
    return unloaded


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

    integration = await async_get_integration(
        hass,
        DOMAIN,
    )

    version = integration.version
    url = (
        f"/api/tilos_player/"
        f"tilos-player-card.js?v={version}"
    )

    lovelace = hass.data["lovelace"]

    resources = (
        lovelace.resources
        if hasattr(lovelace, "resources")
        else lovelace["resources"]
    )

    # Force loading of storage resources before inspecting them.
    await resources.async_get_info()

    resource_path = (
        "/api/tilos_player/tilos-player-card.js"
    )

    for item in resources.async_items():
        current_url = item.get("url", "")

        if current_url.split("?")[0] != resource_path:
            continue

        # Már regisztrálva van, de ellenőrizzük a verziót.
        if current_url != url:
            if isinstance(
                resources,
                ResourceStorageCollection,
            ):
                await resources.async_update_item(
                    item["id"],
                    {
                        "url": url,
                    },
                )
            else:
                add_extra_js_url(hass, url)

        return

    # Még nincs regisztrálva.
    if isinstance(
        resources,
        ResourceStorageCollection,
    ):
        await resources.async_create_item(
            {
                "res_type": "module",
                "url": url,
            }
        )
    else:
        add_extra_js_url(hass, url)