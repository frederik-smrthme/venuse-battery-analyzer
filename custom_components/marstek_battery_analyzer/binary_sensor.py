from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import AnalyzerEntity


DESCRIPTIONS = (
    BinarySensorEntityDescription(key='analysis_active', name='Analysis active'),
    BinarySensorEntityDescription(key='balancing_detected', name='Balancing active'),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AnalyzerBinarySensor(coordinator, entry, desc) for desc in DESCRIPTIONS])


class AnalyzerBinarySensor(AnalyzerEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry, description: BinarySensorEntityDescription) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def is_on(self):
        data = self.coordinator.data
        if self.entity_description.key == 'analysis_active':
            return bool(data.get('analysis_active'))
        if self.entity_description.key == 'balancing_detected':
            return (data.get('live') or {}).get('balancing') is True
        return False
