"""Diagnostics for Flighttracker."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant

from .const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from .coordinator import FlighttrackerConfigEntry

TO_REDACT = {CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_LATITUDE, CONF_LONGITUDE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FlighttrackerConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "authenticated": coordinator.opensky.authenticated,
        "last_update_success": coordinator.last_update_success,
        "quiet": data.quiet if data else None,
        "aircraft_count": data.aircraft_count if data else None,
        "credits_remaining": data.credits_remaining if data else None,
        "flight": (
            async_redact_data(data.flight.as_dict(), {"latitude", "longitude"})
            if data and data.flight
            else None
        ),
    }
