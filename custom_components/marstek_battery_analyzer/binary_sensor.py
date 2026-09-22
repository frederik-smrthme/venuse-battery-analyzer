from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import AnalyzerEntity


DESCRIPTIONS = (
    BinarySensorEntityDescription(key='analysis_active', name='Analysis active'),
    BinarySensorEntityDescription(key='balancing_active', name='Balancing active'),
    BinarySensorEntityDescription(
        key='ha_connected',
        name='Home Assistant connection',
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key='analysis_data_gap',
        name='Analysis data gap',
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key='flow_signal_conflict',
        name='DC flow signal conflict',
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key='balancing_nonzero_flow',
        name='Balancing with non-zero series flow',
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key='balancing_signal_unknown',
        name='Balancing signal unknown during cycle',
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key='last_delta_reduction_valid',
        name='Last delta reduction valid',
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AnalyzerBinarySensor(coordinator, entry, desc) for desc in DESCRIPTIONS])


class AnalyzerBinarySensor(AnalyzerEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry, description: BinarySensorEntityDescription) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def is_on(self):
        data = self.coordinator.data
        diagnostics = data.get('diagnostics') or {}
        last_quality = ((data.get('last_cycle') or {}).get('quality_json') or {})
        key = self.entity_description.key
        if key == 'analysis_active':
            return bool(data.get('analysis_active'))
        if key == 'balancing_active':
            return (data.get('live') or {}).get('balancing') is True
        if key == 'ha_connected':
            return bool(data.get('ha_connected'))
        if key == 'analysis_data_gap':
            return bool(diagnostics.get('measurement_gaps'))
        if key == 'flow_signal_conflict':
            return bool(diagnostics.get('signal_conflict_seen'))
        if key == 'balancing_nonzero_flow':
            return bool(diagnostics.get('balancing_nonzero_flow_seen'))
        if key == 'balancing_signal_unknown':
            return bool(diagnostics.get('balancing_signal_unknown_seen'))
        if key == 'last_delta_reduction_valid':
            value = last_quality.get('delta_reduction_valid')
            return None if value is None else bool(value)
        return None
