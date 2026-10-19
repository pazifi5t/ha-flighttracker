"""Config flow for Flighttracker."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME, CONF_RADIUS
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    LocationSelector,
    LocationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)
from homeassistant.util import dt as dt_util

from .api import (
    FlighttrackerAuthError,
    FlighttrackerConnectionError,
    FlighttrackerRateLimitError,
    OpenSkyClient,
)
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_LOCATION,
    CONF_LOGO_URL,
    CONF_MAX_ALTITUDE,
    CONF_QUIET_END,
    CONF_QUIET_HOURS,
    CONF_QUIET_START,
    CONF_ROUTE_REQUIRED,
    CONF_SCAN_INTERVAL,
    CREDITS_ANONYMOUS,
    CREDITS_AUTHENTICATED,
    DEFAULT_LOGO_URL,
    DEFAULT_MAX_ALTITUDE,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_HOURS,
    DEFAULT_QUIET_START,
    DEFAULT_RADIUS_M,
    DEFAULT_ROUTE_REQUIRED,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_RADIUS_M,
    MIN_SCAN_INTERVAL,
)
from .logic import active_hours_per_day, bounding_box, requests_per_day

_LOGGER = logging.getLogger(__name__)

PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _credentials_schema() -> dict[vol.Marker, Any]:
    return {
        vol.Optional(CONF_CLIENT_ID): TextSelector(),
        vol.Optional(CONF_CLIENT_SECRET): PASSWORD,
    }


def _location_schema(default_lat: float, default_lon: float, radius: float) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_LOCATION,
                default={
                    CONF_LATITUDE: default_lat,
                    CONF_LONGITUDE: default_lon,
                    CONF_RADIUS: radius,
                },
            ): LocationSelector(LocationSelectorConfig(radius=True, icon="mdi:airplane")),
            **_credentials_schema(),
        }
    )


async def _validate(hass, user_input: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    """Check location and credentials. Returns (errors, entry data)."""
    errors: dict[str, str] = {}
    location = user_input[CONF_LOCATION]
    radius = float(location.get(CONF_RADIUS) or DEFAULT_RADIUS_M)
    client_id = (user_input.get(CONF_CLIENT_ID) or "").strip()
    client_secret = (user_input.get(CONF_CLIENT_SECRET) or "").strip()
    data = {
        CONF_LATITUDE: float(location[CONF_LATITUDE]),
        CONF_LONGITUDE: float(location[CONF_LONGITUDE]),
        CONF_RADIUS: radius,
        CONF_CLIENT_ID: client_id,
        CONF_CLIENT_SECRET: client_secret,
    }

    if radius > MAX_RADIUS_M:
        errors[CONF_LOCATION] = "radius_too_large"
        return errors, data
    if bool(client_id) != bool(client_secret):
        errors["base"] = "credentials_incomplete"
        return errors, data

    client = OpenSkyClient(async_get_clientsession(hass), client_id, client_secret)
    try:
        await client.async_get_states(
            bounding_box(data[CONF_LATITUDE], data[CONF_LONGITUDE], radius / 1000)
        )
    except FlighttrackerAuthError:
        errors["base"] = "invalid_auth"
    except FlighttrackerRateLimitError:
        # Credits used up today, but the setup itself is fine.
        _LOGGER.warning("OpenSky credits exhausted, continuing setup anyway")
    except FlighttrackerConnectionError as err:
        _LOGGER.debug("OpenSky not reachable: %s", err)
        errors["base"] = "cannot_connect"
    return errors, data


class FlighttrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup UI."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> FlighttrackerOptionsFlow:
        return FlighttrackerOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, data = await _validate(self.hass, user_input)
            if not errors:
                await self.async_set_unique_id(
                    f"{data[CONF_LATITUDE]:.3f}_{data[CONF_LONGITUDE]:.3f}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME) or "Flighttracker", data=data
                )

        schema = vol.Schema(
            {vol.Required(CONF_NAME, default="Flighttracker"): TextSelector()}
        ).extend(
            _location_schema(
                self.hass.config.latitude, self.hass.config.longitude, DEFAULT_RADIUS_M
            ).schema
        )
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            # An empty secret field keeps the stored secret for the same client.
            if (
                user_input.get(CONF_CLIENT_ID)
                and not user_input.get(CONF_CLIENT_SECRET)
                and user_input[CONF_CLIENT_ID] == entry.data.get(CONF_CLIENT_ID)
            ):
                user_input[CONF_CLIENT_SECRET] = entry.data.get(CONF_CLIENT_SECRET, "")
            errors, data = await _validate(self.hass, user_input)
            unique_id = f"{data[CONF_LATITUDE]:.3f}_{data[CONF_LONGITUDE]:.3f}"
            if not errors and any(
                other.unique_id == unique_id and other.entry_id != entry.entry_id
                for other in self._async_current_entries(include_ignore=False)
            ):
                return self.async_abort(reason="already_configured")
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, unique_id=unique_id, data_updates=data
                )

        schema = _location_schema(
            entry.data[CONF_LATITUDE], entry.data[CONF_LONGITUDE], entry.data[CONF_RADIUS]
        )
        schema = self.add_suggested_values_to_schema(
            schema,
            user_input
            or {
                CONF_CLIENT_ID: entry.data.get(CONF_CLIENT_ID, ""),
            },
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, data = await _validate(
                self.hass,
                {
                    CONF_LOCATION: {
                        CONF_LATITUDE: entry.data[CONF_LATITUDE],
                        CONF_LONGITUDE: entry.data[CONF_LONGITUDE],
                        CONF_RADIUS: entry.data[CONF_RADIUS],
                    },
                    **user_input,
                },
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_CLIENT_ID: data[CONF_CLIENT_ID],
                        CONF_CLIENT_SECRET: data[CONF_CLIENT_SECRET],
                    },
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_credentials_schema()),
                {CONF_CLIENT_ID: entry.data.get(CONF_CLIENT_ID, "")},
            ),
            errors=errors,
        )


class FlighttrackerOptionsFlow(OptionsFlow):
    """Polling interval, quiet hours and display options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        authenticated = bool(self.config_entry.data.get(CONF_CLIENT_ID))
        credits = CREDITS_AUTHENTICATED if authenticated else CREDITS_ANONYMOUS

        if user_input is not None:
            start = dt_util.parse_time(user_input.get(CONF_QUIET_START) or DEFAULT_QUIET_START)
            end = dt_util.parse_time(user_input.get(CONF_QUIET_END) or DEFAULT_QUIET_END)
            per_day = requests_per_day(
                int(user_input[CONF_SCAN_INTERVAL]),
                active_hours_per_day(start, end, user_input[CONF_QUIET_HOURS]),  # type: ignore[arg-type]
            )
            if per_day > credits:
                errors[CONF_SCAN_INTERVAL] = "too_many_requests"
                placeholders = {"requests": str(per_day), "credits": str(credits)}
            else:
                user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
                user_input.setdefault(CONF_LOGO_URL, "")
                return self.async_create_entry(data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_SCAN_INTERVAL): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=3600,
                        step=10,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_ROUTE_REQUIRED): BooleanSelector(),
                vol.Required(CONF_MAX_ALTITUDE): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=15000,
                        step=100,
                        unit_of_measurement="m",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(CONF_QUIET_HOURS): BooleanSelector(),
                vol.Required(CONF_QUIET_START): TimeSelector(),
                vol.Required(CONF_QUIET_END): TimeSelector(),
                vol.Optional(CONF_LOGO_URL): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.URL)
                ),
            }
        )
        current = {
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_ROUTE_REQUIRED: DEFAULT_ROUTE_REQUIRED,
            CONF_MAX_ALTITUDE: DEFAULT_MAX_ALTITUDE,
            CONF_QUIET_HOURS: DEFAULT_QUIET_HOURS,
            CONF_QUIET_START: DEFAULT_QUIET_START,
            CONF_QUIET_END: DEFAULT_QUIET_END,
            CONF_LOGO_URL: DEFAULT_LOGO_URL,
            **self.config_entry.options,
            **(user_input or {}),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, current),
            errors=errors,
            description_placeholders={
                "credits": str(credits),
                "icao": "{icao}",
                "requests": "",
                **placeholders,
            },
        )
