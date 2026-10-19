"""Constants for the Flighttracker integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "flighttracker"

# Config entry data
CONF_CLIENT_ID: Final = "client_id"
CONF_CLIENT_SECRET: Final = "client_secret"
CONF_LOCATION: Final = "location"

# Options
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_QUIET_HOURS: Final = "quiet_hours"
CONF_QUIET_START: Final = "quiet_start"
CONF_QUIET_END: Final = "quiet_end"
CONF_ROUTE_REQUIRED: Final = "route_required"
CONF_MAX_ALTITUDE: Final = "max_altitude"
CONF_LOGO_URL: Final = "logo_url"

DEFAULT_RADIUS_M: Final = 28_000  # ~15 NM, same as the original sketch
MAX_RADIUS_M: Final = 100_000  # keeps the bounding box below 25 sq° (1 credit)
DEFAULT_SCAN_INTERVAL: Final = 180  # seconds, like the original sketch
MIN_SCAN_INTERVAL: Final = 30
DEFAULT_QUIET_HOURS: Final = True
DEFAULT_QUIET_START: Final = "23:00:00"
DEFAULT_QUIET_END: Final = "07:00:00"
DEFAULT_ROUTE_REQUIRED: Final = True
DEFAULT_MAX_ALTITUDE: Final = 0  # 0 = no limit
DEFAULT_LOGO_URL: Final = (
    "https://raw.githubusercontent.com/Jxck-S/airline-logos/main/flightaware_logos/{icao}.png"
)

# OpenSky daily API credits (one /states/all call with a small box costs 1)
CREDITS_ANONYMOUS: Final = 400
CREDITS_AUTHENTICATED: Final = 4000

OPENSKY_STATES_URL: Final = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN_URL: Final = (
    "https://auth.opensky-network.org/auth/realms/opensky-network"
    "/protocol/openid-connect/token"
)
ADSBDB_URL: Final = "https://api.adsbdb.com/v0"

# How many of the nearest aircraft are looked up at adsbdb per update
# when only flights with a known route should be shown.
MAX_LOOKUPS_PER_UPDATE: Final = 5

EVENT_NEW_FLIGHT: Final = f"{DOMAIN}_new_flight"

ATTRIBUTION: Final = "Data: OpenSky Network, adsbdb.com"
