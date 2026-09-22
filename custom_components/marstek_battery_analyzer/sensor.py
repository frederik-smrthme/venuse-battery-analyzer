from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfElectricCurrent, UnitOfElectricPotential, UnitOfPower, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import AnalyzerEntity


@dataclass(frozen=True, kw_only=True)
class AnalyzerSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], object | None]


def live(key: str):
    return lambda data: (data.get('live') or {}).get(key)


def current_cycle(key: str):
    return lambda data: (data.get('current_cycle') or {}).get(key)


def last_cycle(key: str):
    return lambda data: (data.get('last_cycle') or {}).get(key)


SENSORS = (
    AnalyzerSensorDescription(key='analysis_state', name='Analysis state', value_fn=lambda d: d.get('phase')),
    AnalyzerSensorDescription(key='soc', name='SOC', native_unit_of_measurement=PERCENTAGE, value_fn=live('soc')),
    AnalyzerSensorDescription(key='cell_vmax', name='Cell Vmax', device_class=SensorDeviceClass.VOLTAGE, native_unit_of_measurement=UnitOfElectricPotential.VOLT, value_fn=live('vmax')),
    AnalyzerSensorDescription(key='cell_vmin', name='Cell Vmin', device_class=SensorDeviceClass.VOLTAGE, native_unit_of_measurement=UnitOfElectricPotential.VOLT, value_fn=live('vmin')),
    AnalyzerSensorDescription(key='cell_delta', name='Cell delta', native_unit_of_measurement='mV', value_fn=live('delta_mv')),
    AnalyzerSensorDescription(key='dc_power', name='DC battery power', device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT, value_fn=live('dc_power_w')),
    AnalyzerSensorDescription(key='dc_current', name='DC battery current', device_class=SensorDeviceClass.CURRENT, native_unit_of_measurement=UnitOfElectricCurrent.AMPERE, value_fn=live('dc_current_a')),
    AnalyzerSensorDescription(key='ac_power', name='AC power', device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT, value_fn=live('ac_power_w')),
    AnalyzerSensorDescription(key='battery_temperature', name='Battery temperature', device_class=SensorDeviceClass.TEMPERATURE, native_unit_of_measurement=UnitOfTemperature.CELSIUS, value_fn=live('battery_temperature_c')),
    AnalyzerSensorDescription(key='balancing_duration', name='Balancing duration', device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.SECONDS, value_fn=lambda d: d.get('balancing_duration_s')),
    AnalyzerSensorDescription(key='current_cycle_id', name='Current cycle ID', value_fn=lambda d: d.get('current_cycle_id')),
    AnalyzerSensorDescription(key='last_delta_reduction', name='Last cycle delta reduction', native_unit_of_measurement='mV', value_fn=last_cycle('delta_reduction_mv')),
    AnalyzerSensorDescription(key='last_start_delta', name='Last cycle start delta', native_unit_of_measurement='mV', value_fn=last_cycle('delta_charge_stop_mv')),
    AnalyzerSensorDescription(key='last_end_delta', name='Last cycle end delta', native_unit_of_measurement='mV', value_fn=last_cycle('delta_end_mv')),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AnalyzerSensor(coordinator, entry, desc) for desc in SENSORS])


class AnalyzerSensor(AnalyzerEntity, SensorEntity):
    entity_description: AnalyzerSensorDescription

    def __init__(self, coordinator, entry, description: AnalyzerSensorDescription) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)
