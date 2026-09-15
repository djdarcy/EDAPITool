"""
Configuration constants for Elite Dangerous CAPI access.
"""

# CAPI Server URLs
CAPI_SERVER_LIVE = "https://companion.orerve.net"
CAPI_SERVER_LEGACY = "https://legacy-companion.orerve.net"
CAPI_SERVER_BETA = "https://pts-companion.orerve.net"

# CAPI Endpoints
CAPI_PATH_PROFILE = "/profile"
CAPI_PATH_MARKET = "/market"
CAPI_PATH_SHIPYARD = "/shipyard"
CAPI_PATH_FLEETCARRIER = "/fleetcarrier"
CAPI_PATH_JOURNAL = "/journal"
CAPI_PATH_COMMUNITYGOALS = "/communitygoals"

# Frontier Auth URLs
AUTH_SERVER = "https://auth.frontierstore.net"
AUTH_PATH_AUTH = "/auth"
AUTH_PATH_TOKEN = "/token"
AUTH_PATH_DECODE = "/decode"

# Default timeouts (seconds)
DEFAULT_TIMEOUT = 10
FLEETCARRIER_TIMEOUT = 60

# Rate limiting
MIN_QUERY_INTERVAL = 60  # seconds between queries
FLEETCARRIER_COOLDOWN = 900  # 15 minutes between FC queries

# OAuth2 scopes required
OAUTH_SCOPES = ["capi", "auth"]

# Token file location (in user's home directory)
TOKEN_FILE = ".ed_capi_tokens.json"
