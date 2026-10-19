"""Base entity for Flighttracker."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import FlighttrackerCoordinator


class FlighttrackerEntity(CoordinatorEntity[FlighttrackerCoordinator]):
    """Common device and naming for all Flighttracker entities."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: FlighttrackerCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Flighttracker",
            model="OpenSky + adsbdb",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://opensky-network.org",
        )
