from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AnalyzerCoordinator


class AnalyzerEntity(CoordinatorEntity[AnalyzerCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: AnalyzerCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f'{entry.entry_id}_{key}'
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name='Marstek Battery Analyzer',
            manufacturer='Local',
            model='LFP cycle analyzer',
            sw_version=str(coordinator.data.get('version', 'unknown')),
        )
