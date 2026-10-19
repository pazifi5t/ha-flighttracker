"""Binary sensor: is a plane overhead right now?"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FlighttrackerConfigEntry, FlighttrackerCoordinator
from .entity import FlighttrackerEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FlighttrackerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor."""
    async_add_entities([AircraftNearbySensor(entry.runtime_data)])


class AircraftNearbySensor(FlighttrackerEntity, BinarySensorEntity):
    """On while a flight is shown."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator: FlighttrackerCoordinator) -> None:
        super().__init__(coordinator, "aircraft_nearby")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.flight is not None
