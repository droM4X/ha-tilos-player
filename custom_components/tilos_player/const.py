"""Constants for the Tilos Radio Player integration."""

DOMAIN = "tilos_player"

# API endpoints
API_BASE = "https://tilos.hu/api"
SHOWS_URL = f"{API_BASE}/show"
EPISODES_URL = f"{API_BASE}/show/{{alias}}/episodes?start={{start}}&end={{end}}"

# Request timeout in seconds
REQUEST_TIMEOUT = 30

# HEAD-request timeout for the episode cover image existence check
IMAGE_CHECK_TIMEOUT = 10

# Some Tilos endpoints reject default Python user agents
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) HomeAssistant-TilosPlayer/1.0",
}

# Options
CONF_MEDIA_PLAYER = "media_player_entity"
CONF_LOOKBACK_DAYS = "lookback_days"
DEFAULT_LOOKBACK_DAYS = 120  # 4 months, matching the original bash fetcher (10512000 s)
MIN_LOOKBACK_DAYS = 1
MAX_LOOKBACK_DAYS = 365

# Show types from the API (we only expose these)
SHOW_TYPE_MUSIC = "MUSIC"
SHOW_TYPE_SPEECH = "SPEECH"

# Live stream (Icecast)
LIVE_STREAM_URL = "https://stream.tilos.hu/tilos"

# Metadata overrides for archive playback — the archive mp3 files carry no
# ID3 tags, so the player shows the raw file name. We overwrite the known
# fields with the data picked from the selects.
MEDIA_ARTIST_SUFFIX = " // Tilos Rádió"
EPISODE_IMAGE_URL = "https://tilos.hu/upload/episode-new/{alias}.jpg"
# Fallback cover: the integration's own brand logo, served by HA itself
DEFAULT_EPISODE_IMAGE = "/api/brands/integration/tilos_player/logo.png"

# The archive mp3 files are named 'tilos-YYYYMMDD-HHMMSS-HHMMSS'; because
# they carry no ID3 tags, players report this file name as media_title.
# We use the pattern to detect that an archive episode (not the live
# stream or another source) is currently playing — this survives seeks,
# where media_content_id may get rewritten by the player integration.
ARCHIVE_TITLE_PATTERN = r"^tilos-\d{8}-\d{6}-\d{6}$"
# Seconds to wait after play_media before patching the player state.
# Music Assistant emits a burst of state updates when playback starts, so
# we don't fight it: let the burst settle, then patch once.
METADATA_PATCH_DELAY = 5
# Minimum seconds between guard-triggered metadata re-writes — the player
# can emit state updates (seek, position ticks) faster than we want to
# write back. The initial patch after play is not throttled.
METADATA_REWRITE_INTERVAL = 5
# Custom event fired whenever we (re)write player metadata. Lets
# trigger-based template helpers update deterministically instead of
# relying on attribute tracking of the media player entity.
METADATA_EVENT = "tilos_player_media_metadata"

# Shows list refresh interval
SHOWS_UPDATE_INTERVAL = 12  # hours

# Favorites — the show IDs are stored by the favorites sensor (which
# persists them via RestoreEntity) and toggled through these services.
SERVICE_ADD_FAVORITE = "add_favorite"
SERVICE_REMOVE_FAVORITE = "remove_favorite"
ATTR_SHOW_ID = "show_id"
