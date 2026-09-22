from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

OPTIONS_PATH = Path('/data/options.json')


def _read_options() -> dict:
    if not OPTIONS_PATH.exists():
        return {}
    return json.loads(OPTIONS_PATH.read_text())


def _sign(value: float | None, mode: str) -> float | None:
    if value is None:
        return None
    return value if mode == 'positive' else -value


@dataclass(slots=True)
class Settings:
    api_port: int = 8099
    observation_soc: float = 97.0
    intensive_soc: float = 99.0
    intensive_vmax: float = 3.40
    charge_zero_current_a: float = 0.15
    charge_zero_power_w: float = 15.0
    charge_stop_stable_seconds: int = 30
    cycle_end_below_soc: float = 96.5
    post_charge_observation_minutes: int = 240
    sample_interval_seconds: int = 5
    battery_cell_count: int = 16
    battery_nominal_voltage_v: float = 51.2
    battery_capacity_ah: float = 100.0
    battery_gross_capacity_kwh: float = 5.12
    battery_dod_percent: float = 88.0
    dc_charge_sign: str = 'positive'
    ac_charge_sign: str = 'negative'
    entity_soc: str = 'sensor.marstek_venus_1_battery_soc'
    entity_vmax: str = 'sensor.marstek_venus_1_max_cell_voltage'
    entity_vmin: str = 'sensor.marstek_venus_1_min_cell_voltage'
    entity_dc_power: str = 'sensor.marstek_venus_1_battery_power'
    entity_dc_current: str = 'sensor.marstek_venus_1_battery_current'
    entity_ac_power: str = 'sensor.marstek_venus_1_ac_power'
    entity_ac_current: str = 'sensor.marstek_venus_1_ac_current'
    entity_battery_temperature: str = 'sensor.marstek_venus_1_battery_temperature'
    entity_internal_temperature: str = 'sensor.marstek_venus_1_internal_temperature'
    entity_balancing: str = 'binary_sensor.marstek_venus_1_balancing_mode'
    cell_entities_csv: str = ''
    cell_entities: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> 'Settings':
        raw = _read_options()
        allowed = cls.__dataclass_fields__.keys()
        values = {k: v for k, v in raw.items() if k in allowed and k != 'cell_entities'}
        obj = cls(**values)
        obj.cell_entities = [x.strip() for x in obj.cell_entities_csv.split(',') if x.strip()]
        return obj

    @property
    def entity_map(self) -> dict[str, str]:
        return {
            'soc': self.entity_soc,
            'vmax': self.entity_vmax,
            'vmin': self.entity_vmin,
            'dc_power': self.entity_dc_power,
            'dc_current': self.entity_dc_current,
            'ac_power': self.entity_ac_power,
            'ac_current': self.entity_ac_current,
            'battery_temperature': self.entity_battery_temperature,
            'internal_temperature': self.entity_internal_temperature,
            'balancing': self.entity_balancing,
        }

    @property
    def watched_entities(self) -> set[str]:
        return {v for v in self.entity_map.values() if v} | set(self.cell_entities)

    @property
    def usable_capacity_kwh(self) -> float:
        return self.battery_gross_capacity_kwh * self.battery_dod_percent / 100.0

    @property
    def usable_capacity_ah(self) -> float:
        return self.battery_capacity_ah * self.battery_dod_percent / 100.0

    def normalize_dc_charge(self, value: float | None) -> float | None:
        return _sign(value, self.dc_charge_sign)

    def normalize_ac_charge(self, value: float | None) -> float | None:
        return _sign(value, self.ac_charge_sign)
