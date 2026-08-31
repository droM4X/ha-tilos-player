"""Constants for the Tilos Radio Player integration."""

DOMAIN = "tilos_player"

# API endpoints
API_BASE = "https://tilos.hu/api"
SHOWS_URL = f"{API_BASE}/show"
EPISODES_URL = f"{API_BASE}/show/{{alias}}/episodes?start={{start}}&end={{end}}"

# Request timeout in seconds
REQUEST_TIMEOUT = 30

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

# Shows list refresh interval
SHOWS_UPDATE_INTERVAL = 12  # hours
