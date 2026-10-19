"""Sensors for Flighttracker."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfLength, UnitOfSpeed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FlighttrackerConfigEntry, FlighttrackerCoordinator, FlighttrackerData
from .entity import FlighttrackerEntity
from .logic import Flight

PARALLEL_UPDATES = 0

STATUS_FLIGHT = "flight"
STATUS_CLEAR = "clear"
STATUS_QUIET = "quiet"


def _status(data: FlighttrackerData) -> str:
    if data.quiet:
        return STATUS_QUIET
    return STATUS_FLIGHT if data.flight else STATUS_CLEAR


def _flight(fn: Callable[[Flight], Any]) -> Callable[[FlighttrackerData], Any]:
    """Apply `fn` to the current flight, None if there is none."""
    return lambda data: fn(data.flight) if data.flight else None


@dataclass(frozen=True, kw_only=True)
class FlighttrackerSensorDescription(SensorEntityDescription):
    """Describes a Flighttracker sensor."""

    value_fn: Callable[[FlighttrackerData], Any]
    attrs_fn: Callable[[FlighttrackerData], dict[str, Any]] | None = None


def _airport_attrs(which: str) -> Callable[[FlighttrackerData], dict[str, Any]]:
    def attrs(data: FlighttrackerData) -> dict[str, Any]:
        if not data.flight:
            return {}
        airport = getattr(data.flight.lookup, which)
        return {
            "iata": airport.iata,
            "icao": airport.icao,
            "city": airport.city,
            "country": airport.country,
        }

    return attrs


SENSORS: tuple[FlighttrackerSensorDescription, ...] = (
    FlighttrackerSensorDescription(
        key="status",
        device_class=SensorDeviceClass.ENUM,
        options=[STATUS_FLIGHT, STATUS_CLEAR, STATUS_QUIET],
        value_fn=_status,
    ),
    FlighttrackerSensorDescription(
        key="airline",
        value_fn=_flight(lambda f: f.airline),
        attrs_fn=lambda d: (
            {"icao": d.flight.lookup.airline_icao, "iata": d.flight.lookup.airline_iata}
            if d.flight
            else {}
        ),
    ),
    FlighttrackerSensorDescription(
        key="route",
        value_fn=_flight(lambda f: f.route),
    ),
    FlighttrackerSensorDescription(
        key="origin",
        value_fn=_flight(lambda f: f.lookup.origin.name),
        attrs_fn=_airport_attrs("origin"),
    ),
    FlighttrackerSensorDescription(
        key="destination",
        value_fn=_flight(lambda f: f.lookup.destination.name),
        attrs_fn=_airport_attrs("destination"),
    ),
    FlighttrackerSensorDescription(
        key="aircraft_type",
        value_fn=_flight(lambda f: f.aircraft_type),
        attrs_fn=lambda d: (
            {
                "icao_type": d.flight.lookup.aircraft_type_code,
                "registration": d.flight.lookup.registration,
            }
            if d.flight
            else {}
        ),
    ),
    FlighttrackerSensorDescription(
        key="altitude",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.METERS,
        suggested_display_precision=0,
        value_fn=_flight(lambda f: f.aircraft.altitude_m),
    ),
    FlighttrackerSensorDescription(
        key="speed",
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        suggested_display_precision=0,
        value_fn=_flight(lambda f: f.aircraft.speed_kmh),
    ),
    FlighttrackerSensorDescription(
        key="distance",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        suggested_display_precision=1,
        value_fn=_flight(lambda f: f.aircraft.distance_km),
    ),
    FlighttrackerSensorDescription(
        key="aircraft_count",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: None if d.quiet else d.aircraft_count,
    ),
    FlighttrackerSensorDescription(
        key="api_credits",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.credits_remaining,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FlighttrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [FlightSensor(coordinator)]
        + [FlighttrackerSensor(coordinator, desc) for desc in SENSORS]
    )


class FlighttrackerSensor(FlighttrackerEntity, SensorEntity):
    """Single value from the current flight."""

    entity_description: FlighttrackerSensorDescription

    def __init__(
        self,
        coordinator: FlighttrackerCoordinator,
        description: FlighttrackerSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)


class FlightSensor(FlighttrackerEntity, SensorEntity):
    """Main sensor: flight number with all details as attributes.

    Has latitude/longitude attributes, so the map card can show the plane,
    and the airline logo as entity picture.
    """

    _unrecorded_attributes = frozenset(
        {
            "photo",
            "photo_thumbnail",
            "logo",
            "latitude",
            "longitude",
            "heading",
            "vertical_rate_ms",
            "altitude_m",
            "speed_kmh",
            "distance_km",
        }
    )

    def __init__(self, coordinator: FlighttrackerCoordinator) -> None:
        super().__init__(coordinator, "flight")

    @property
    def native_value(self) -> str | None:
        flight = self.coordinator.data.flight
        return flight.flight_number if flight else None

    @property
    def entity_picture(self) -> str | None:
        return self.coordinator.logo_url(self.coordinator.data.flight)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if not data.flight:
            return {"quiet": data.quiet}
        return {
            **data.flight.as_dict(),
            "logo": self.coordinator.logo_url(data.flight),
            "quiet": data.quiet,
        }
