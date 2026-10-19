"""Data update coordinator for Flighttracker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_RADIUS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    AdsbdbClient,
    FlighttrackerAuthError,
    FlighttrackerConnectionError,
    FlighttrackerRateLimitError,
    OpenSkyClient,
)
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_LOGO_URL,
    CONF_MAX_ALTITUDE,
    CONF_QUIET_END,
    CONF_QUIET_HOURS,
    CONF_QUIET_START,
    CONF_ROUTE_REQUIRED,
    CONF_SCAN_INTERVAL,
    DEFAULT_LOGO_URL,
    DEFAULT_MAX_ALTITUDE,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_HOURS,
    DEFAULT_QUIET_START,
    DEFAULT_ROUTE_REQUIRED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_NEW_FLIGHT,
    MAX_LOOKUPS_PER_UPDATE,
)
from .logic import Flight, bounding_box, in_quiet_hours, parse_states, pick_flight

_LOGGER = logging.getLogger(__name__)

type FlighttrackerConfigEntry = ConfigEntry[FlighttrackerCoordinator]


@dataclass(slots=True)
class FlighttrackerData:
    """State after one update."""

    flight: Flight | None
    aircraft_count: int
    quiet: bool
    credits_remaining: int | None


def _parse_time(value: str | None, default: str) -> time:
    return dt_util.parse_time(value or default) or dt_util.parse_time(default)  # type: ignore[return-value]


class FlighttrackerCoordinator(DataUpdateCoordinator[FlighttrackerData]):
    """Poll OpenSky, enrich via adsbdb and pick the flight overhead."""

    config_entry: FlighttrackerConfigEntry

    def __init__(self, hass: HomeAssistant, entry: FlighttrackerConfigEntry) -> None:
        options = entry.options
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        session = async_get_clientsession(hass)
        self.opensky = OpenSkyClient(
            session,
            entry.data.get(CONF_CLIENT_ID),
            entry.data.get(CONF_CLIENT_SECRET),
        )
        self.adsbdb = AdsbdbClient(session)

        self.latitude: float = entry.data[CONF_LATITUDE]
        self.longitude: float = entry.data[CONF_LONGITUDE]
        self.radius_km: float = entry.data[CONF_RADIUS] / 1000
        self.route_required: bool = options.get(
            CONF_ROUTE_REQUIRED, DEFAULT_ROUTE_REQUIRED
        )
        self.max_altitude: float = options.get(CONF_MAX_ALTITUDE, DEFAULT_MAX_ALTITUDE)
        self.quiet_enabled: bool = options.get(CONF_QUIET_HOURS, DEFAULT_QUIET_HOURS)
        self.quiet_start = _parse_time(options.get(CONF_QUIET_START), DEFAULT_QUIET_START)
        self.quiet_end = _parse_time(options.get(CONF_QUIET_END), DEFAULT_QUIET_END)
        self.logo_url_template: str = options.get(CONF_LOGO_URL, DEFAULT_LOGO_URL)
        self._box = bounding_box(self.latitude, self.longitude, self.radius_km)

    def logo_url(self, flight: Flight | None) -> str | None:
        """Airline logo for the flight, if a template is configured."""
        if flight is None or not self.logo_url_template:
            return None
        icao = flight.lookup.airline_icao
        if not icao:
            return None
        return self.logo_url_template.replace("{icao}", icao.upper())

    def _is_quiet(self) -> bool:
        if not self.quiet_enabled:
            return False
        return in_quiet_hours(dt_util.now().time(), self.quiet_start, self.quiet_end)

    async def _async_update_data(self) -> FlighttrackerData:
        previous = self.data.flight if self.data else None

        if self._is_quiet():
            return FlighttrackerData(None, 0, True, self.opensky.credits_remaining)

        try:
            states = await self.opensky.async_get_states(self._box)
        except FlighttrackerAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except FlighttrackerRateLimitError as err:
            raise UpdateFailed(
                retry_after=err.retry_after,
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                translation_placeholders={
                    "minutes": str(round((err.retry_after or 0) / 60))
                },
            ) from err
        except FlighttrackerConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="connection_error",
                translation_placeholders={"error": str(err)},
            ) from err

        aircraft = parse_states(
            states, self.latitude, self.longitude, self.radius_km, self.max_altitude
        )
        flight = await pick_flight(
            aircraft,
            self.adsbdb.async_lookup,
            self.route_required,
            previous,
            MAX_LOOKUPS_PER_UPDATE,
        )

        if flight is not None and (
            previous is None or previous.aircraft.icao24 != flight.aircraft.icao24
        ):
            self.hass.bus.async_fire(
                EVENT_NEW_FLIGHT,
                {
                    "config_entry_id": self.config_entry.entry_id,
                    **flight.as_dict(),
                    "logo": self.logo_url(flight),
                },
            )

        return FlighttrackerData(
            flight, len(aircraft), False, self.opensky.credits_remaining
        )
