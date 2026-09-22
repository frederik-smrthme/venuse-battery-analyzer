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
    observation_soc: float = 97.0
    intensive_soc: float = 99.0
    intensive_vmax: float = 3.45
    charge_zero_current_a: float = 0.15
    charge_zero_power_w: float = 15.0
    charge_stop_stable_seconds: int = 30
    rest_reference_seconds: int = 60
    cycle_end_below_soc: float = 96.5
    post_charge_observation_minutes: int = 240
    max_cycle_hours: int = 24
    sample_interval_seconds: int = 5
    cell_voltage_min_v: float = 1.5
    cell_voltage_max_v: float = 3.8
    pack_voltage_tolerance_v: float = 0.75
    battery_cell_count: int = 16
    battery_nominal_voltage_v: float = 51.2
    battery_capacity_ah: float = 100.0
    battery_gross_capacity_kwh: float = 5.12
    battery_dod_percent: float = 88.0
    dc_power_charge_sign: str = 'positive'
    dc_current_charge_sign: str = 'positive'
    ac_power_charge_sign: str = 'negative'
    ac_current_charge_sign: str = 'negative'
    entity_soc: str = 'sensor.marstek_venus_1_battery_soc'
    entity_vmax: str = 'sensor.marstek_venus_1_max_cell_voltage'
    entity_vmin: str = 'sensor.marstek_venus_1_min_cell_voltage'
    entity_battery_voltage: str = 'sensor.marstek_venus_1_battery_voltage'
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

        # Compatibility with the initial v0.1.0 option names.
        if 'dc_charge_sign' in raw:
            raw.setdefault('dc_power_charge_sign', raw['dc_charge_sign'])
            raw.setdefault('dc_current_charge_sign', raw['dc_charge_sign'])
        if 'ac_charge_sign' in raw:
            raw.setdefault('ac_power_charge_sign', raw['ac_charge_sign'])
            raw.setdefault('ac_current_charge_sign', raw['ac_charge_sign'])

        allowed = cls.__dataclass_fields__.keys()
        values = {k: v for k, v in raw.items() if k in allowed and k != 'cell_entities'}
        obj = cls(**values)
        obj.cell_entities = [x.strip() for x in obj.cell_entities_csv.split(',') if x.strip()]
        return obj

    @property
    def api_port(self) -> int:
        # Internal container port is fixed. The Supervisor may map it to a different host port.
        return 8099

    @property
    def entity_map(self) -> dict[str, str]:
        return {
            'soc': self.entity_soc,
            'vmax': self.entity_vmax,
            'vmin': self.entity_vmin,
            'battery_voltage': self.entity_battery_voltage,
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

    def normalize_dc_power_charge(self, value: float | None) -> float | None:
        return _sign(value, self.dc_power_charge_sign)

    def normalize_dc_current_charge(self, value: float | None) -> float | None:
        return _sign(value, self.dc_current_charge_sign)

    def normalize_ac_power_charge(self, value: float | None) -> float | None:
        return _sign(value, self.ac_power_charge_sign)

    def normalize_ac_current_charge(self, value: float | None) -> float | None:
        return _sign(value, self.ac_current_charge_sign)

    def validation_warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.observation_soc >= self.intensive_soc:
            warnings.append('observation_soc should be lower than intensive_soc')
        if self.cycle_end_below_soc >= self.observation_soc:
            warnings.append('cycle_end_below_soc should be lower than observation_soc')
        if self.cell_voltage_min_v >= self.cell_voltage_max_v:
            warnings.append('cell_voltage_min_v must be lower than cell_voltage_max_v')
        expected_nominal = self.battery_cell_count * 3.2
        if expected_nominal > 0:
            mismatch = abs(self.battery_nominal_voltage_v - expected_nominal) / expected_nominal
            if mismatch > 0.03:
                warnings.append(
                    f'nominal pack voltage {self.battery_nominal_voltage_v:.2f} V is not consistent '
                    f'with {self.battery_cell_count} LFP cells (~{expected_nominal:.2f} V)'
                )
        expected_kwh = self.battery_nominal_voltage_v * self.battery_capacity_ah / 1000.0
        if expected_kwh > 0:
            mismatch = abs(self.battery_gross_capacity_kwh - expected_kwh) / expected_kwh
            if mismatch > 0.03:
                warnings.append(
                    f'gross capacity {self.battery_gross_capacity_kwh:.3f} kWh is not consistent '
                    f'with {self.battery_nominal_voltage_v:.2f} V x {self.battery_capacity_ah:.1f} Ah '
                    f'(~{expected_kwh:.3f} kWh)'
                )
        if self.cell_entities and len(self.cell_entities) != self.battery_cell_count:
            warnings.append(
                f'{len(self.cell_entities)} individual cell entities configured, '
                f'but battery_cell_count is {self.battery_cell_count}'
            )
        return warnings
