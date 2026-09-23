from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
from statistics import mean, median
from typing import Any

from config import Settings
from db import Database


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def as_float(value: Any) -> float | None:
    try:
        if value in (None, '', 'unknown', 'unavailable'):
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    text = str(value).lower()
    if text in ('on', 'true', '1', 'yes'):
        return True
    if text in ('off', 'false', '0', 'no'):
        return False
    return None


def _in_range(value: float | None, low: float, high: float) -> float | None:
    if value is None or value < low or value > high:
        return None
    return value


@dataclass(slots=True)
class LiveState:
    values: dict[str, Any] = field(default_factory=dict)
    cells: dict[int, float] = field(default_factory=dict)

    def snapshot(self, settings: Settings, phase: str, ts: datetime) -> dict[str, Any]:
        plausibility: list[str] = []

        soc_raw = as_float(self.values.get('soc'))
        soc = _in_range(soc_raw, 0.0, 100.0)
        if soc_raw is not None and soc is None:
            plausibility.append(f'soc_out_of_range:{soc_raw}')

        vmax_raw = as_float(self.values.get('vmax'))
        vmin_raw = as_float(self.values.get('vmin'))
        vmax = _in_range(vmax_raw, settings.cell_voltage_min_v, settings.cell_voltage_max_v)
        vmin = _in_range(vmin_raw, settings.cell_voltage_min_v, settings.cell_voltage_max_v)
        if vmax_raw is not None and vmax is None:
            plausibility.append(f'vmax_out_of_range:{vmax_raw}')
        if vmin_raw is not None and vmin is None:
            plausibility.append(f'vmin_out_of_range:{vmin_raw}')

        delta = None
        if vmax is not None and vmin is not None:
            if vmin > vmax:
                plausibility.append(f'vmin_above_vmax:{vmin}>{vmax}')
            else:
                delta = round((vmax - vmin) * 1000.0, 3)

        battery_voltage = as_float(self.values.get('battery_voltage'))
        if battery_voltage is not None and battery_voltage <= 0:
            plausibility.append(f'battery_voltage_invalid:{battery_voltage}')
            battery_voltage = None

        dc_power = as_float(self.values.get('dc_power'))
        direct_dc_current = as_float(self.values.get('dc_current'))
        ac_power = as_float(self.values.get('ac_power'))
        ac_current = as_float(self.values.get('ac_current'))
        battery_temperature = as_float(self.values.get('battery_temperature'))
        internal_temperature = as_float(self.values.get('internal_temperature'))
        balancing = as_bool(self.values.get('balancing'))

        # DC current is optional on some Venus E integrations. If there is no direct
        # current entity, derive it from DC power / pack voltage for analysis and display.
        # Provenance is kept explicitly so later SoH/balancing-current work can distinguish
        # measured current from a calculated estimate.
        if direct_dc_current is not None:
            dc_current = direct_dc_current
            dc_current_source = 'measured'
            normalized_dc_current = settings.normalize_dc_current_charge(direct_dc_current)
        elif dc_power is not None and battery_voltage is not None and battery_voltage > 0:
            dc_current = dc_power / battery_voltage
            dc_current_source = 'calculated_from_power_voltage'
            normalized_power = settings.normalize_dc_power_charge(dc_power)
            normalized_dc_current = (
                normalized_power / battery_voltage if normalized_power is not None else None
            )
        else:
            dc_current = None
            dc_current_source = 'unavailable'
            normalized_dc_current = None

        # Prefer a real battery-temperature sensor when one exists. On the current Venus E
        # data set only internal temperature is available, so keep it as a clearly labelled
        # proxy rather than pretending it is cell temperature.
        if battery_temperature is not None:
            analysis_temperature = battery_temperature
            analysis_temperature_source = 'battery_sensor'
        elif internal_temperature is not None:
            analysis_temperature = internal_temperature
            analysis_temperature_source = 'internal_temperature_proxy'
        else:
            analysis_temperature = None
            analysis_temperature_source = 'unavailable'

        valid_cells: dict[int, float] = {}
        for idx, value in self.cells.items():
            if settings.cell_voltage_min_v <= value <= settings.cell_voltage_max_v:
                valid_cells[idx] = value
            else:
                plausibility.append(f'cell_{idx:02d}_out_of_range:{value}')

        calculated: dict[str, Any] = {
            'count': len(valid_cells),
            'complete': len(valid_cells) == settings.battery_cell_count,
            'vmax': None,
            'vmin': None,
            'delta_mv': None,
            'mean_v': None,
            'median_v': None,
            'highest_cell': None,
            'lowest_cell': None,
        }
        if valid_cells:
            highest_cell = max(valid_cells, key=valid_cells.get)
            lowest_cell = min(valid_cells, key=valid_cells.get)
            calc_vmax = valid_cells[highest_cell]
            calc_vmin = valid_cells[lowest_cell]
            calculated.update({
                'vmax': calc_vmax,
                'vmin': calc_vmin,
                'delta_mv': round((calc_vmax - calc_vmin) * 1000.0, 3),
                'mean_v': round(mean(valid_cells.values()), 5),
                'median_v': round(median(valid_cells.values()), 5),
                'highest_cell': highest_cell,
                'lowest_cell': lowest_cell,
            })

            if calculated['complete'] and battery_voltage is not None:
                sum_cells = sum(valid_cells.values())
                if abs(sum_cells - battery_voltage) > settings.pack_voltage_tolerance_v:
                    plausibility.append(
                        f'pack_voltage_vs_cell_sum_mismatch:{battery_voltage:.3f}V_vs_{sum_cells:.3f}V'
                    )

        if battery_voltage is not None and vmax is not None and vmin is not None:
            lower = settings.battery_cell_count * vmin - settings.pack_voltage_tolerance_v
            upper = settings.battery_cell_count * vmax + settings.pack_voltage_tolerance_v
            if not (lower <= battery_voltage <= upper):
                plausibility.append(
                    f'pack_voltage_outside_minmax_envelope:{battery_voltage:.3f}V_not_in_{lower:.3f}-{upper:.3f}V'
                )

        if battery_temperature is not None and not (-40 <= battery_temperature <= 90):
            plausibility.append(f'battery_temperature_implausible:{battery_temperature}')
        if internal_temperature is not None and not (-40 <= internal_temperature <= 110):
            plausibility.append(f'internal_temperature_implausible:{internal_temperature}')

        return {
            'ts': iso(ts),
            'phase': phase,
            'soc': soc,
            'vmax': vmax,
            'vmin': vmin,
            'delta_mv': delta,
            'battery_voltage_v': battery_voltage,
            'dc_power_w': dc_power,
            'dc_current_a': dc_current,
            'dc_current_source': dc_current_source,
            'ac_power_w': ac_power,
            'ac_current_a': ac_current,
            'battery_temperature_c': battery_temperature,
            'internal_temperature_c': internal_temperature,
            'analysis_temperature_c': analysis_temperature,
            'analysis_temperature_source': analysis_temperature_source,
            'balancing': balancing,
            'cells': dict(valid_cells),
            'cell_calculated': calculated,
            'normalized_dc_charge_power_w': settings.normalize_dc_power_charge(dc_power),
            'normalized_dc_charge_current_a': normalized_dc_current,
            'normalized_ac_charge_power_w': settings.normalize_ac_power_charge(ac_power),
            'normalized_ac_charge_current_a': settings.normalize_ac_current_charge(ac_current),
            'plausibility': plausibility,
        }


class Analyzer:
    PHASE_NORMAL = 'NORMAL'
    PHASE_OBSERVATION = 'OBSERVATION'
    PHASE_TOP_CHARGE = 'TOP_CHARGE'
    PHASE_REST = 'REST'
    PHASE_POST_CHARGE = 'POST_CHARGE_OBSERVATION'

    FLOW_CHARGING = 'charging'
    FLOW_ZERO = 'zero'
    FLOW_DISCHARGING = 'discharging'
    FLOW_CONFLICT = 'conflict'
    FLOW_UNKNOWN = 'unknown'
    TRANSIENT_GUARD_SECONDS = 5

    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.live = LiveState()
        self.phase = self.PHASE_NORMAL
        self.current_cycle_id: int | None = None
        self.cycle_started_at: datetime | None = None
        self.top_charge_at: datetime | None = None
        self.charge_stop_at: datetime | None = None
        self.charge_stop_confirmed_at: datetime | None = None
        self.rest_reference_at: datetime | None = None
        self.zero_candidate_at: datetime | None = None
        self.zero_candidate_snapshot: dict[str, Any] | None = None
        self.last_sample_at: datetime | None = None
        self.last_charging_snapshot: dict[str, Any] | None = None
        self.max_vmax: float | None = None
        self.min_vmin: float | None = None
        self.measurement_gaps = False
        self.charge_resumed = False
        self.signal_conflict_seen = False
        self.flow_conflict_candidate_at: datetime | None = None
        self.balancing_nonzero_flow_seen = False
        self.balancing_nonzero_candidate_at: datetime | None = None
        self.balancing_signal_unknown_seen = False
        self.post_stop_nonzero_flow_seen = False
        self.invalid_sample_count = 0
        self.balancing_first_start_at: datetime | None = None
        self.balancing_last_end_at: datetime | None = None
        self.balancing_active_since: datetime | None = None
        self.balancing_duration_completed_s = 0.0
        self.balancing_session_count = 0
        self.ha_connected = False
        self.missing_entities: list[str] = []
        self.missing_optional_entities: list[str] = []
        self.config_warnings = settings.validation_warnings()
        self._restore_open_cycle()

    def _restore_open_cycle(self) -> None:
        row = self.db.get_open_cycle()
        if not row:
            return
        self.current_cycle_id = int(row['id'])
        self.phase = row.get('phase') or self.PHASE_OBSERVATION
        self.cycle_started_at = parse_dt(row.get('started_at'))
        self.top_charge_at = parse_dt(row.get('top_charge_at'))
        self.charge_stop_at = parse_dt(row.get('charge_stop_at'))
        self.charge_stop_confirmed_at = parse_dt(row.get('charge_stop_confirmed_at'))
        self.rest_reference_at = parse_dt(row.get('rest_reference_at'))
        self.balancing_first_start_at = parse_dt(row.get('balancing_start_at'))
        self.balancing_last_end_at = parse_dt(row.get('balancing_end_at'))
        self.balancing_active_since = parse_dt(row.get('balancing_active_since'))
        self.balancing_duration_completed_s = float(row.get('balancing_duration_s') or 0.0)
        self.balancing_session_count = int(row.get('balancing_session_count') or 0)
        quality = row.get('quality_json') or {}
        self.measurement_gaps = bool(quality.get('measurement_gaps'))
        self.charge_resumed = bool(quality.get('charge_resumed'))
        self.signal_conflict_seen = bool(quality.get('signal_conflict_seen'))
        self.balancing_nonzero_flow_seen = bool(quality.get('balancing_nonzero_flow_seen'))
        self.balancing_signal_unknown_seen = bool(quality.get('balancing_signal_unknown_seen'))
        self.post_stop_nonzero_flow_seen = bool(quality.get('post_stop_nonzero_flow_seen'))
        self.invalid_sample_count = int(quality.get('invalid_sample_count') or 0)

        stats = self.db.cycle_sample_stats(self.current_cycle_id)
        self.max_vmax = stats.get('max_vmax')
        self.min_vmin = stats.get('min_vmin')
        self.last_sample_at = parse_dt(stats.get('last_sample_at'))

        # A restart while a cycle is open creates an observation gap by definition.
        self.measurement_gaps = True

    def set_connection_state(self, connected: bool) -> None:
        if self.ha_connected and not connected and self.current_cycle_id is not None:
            self.measurement_gaps = True
        self.ha_connected = connected

    def set_initial_states(self, states: list[dict[str, Any]]) -> None:
        by_id = {s.get('entity_id'): s for s in states}
        for key, entity in self.settings.entity_map.items():
            if not entity:
                continue
            state = by_id.get(entity)
            self.live.values[key] = state.get('state') if state else None

        self.live.cells.clear()
        for index, entity in enumerate(self.settings.cell_entities, start=1):
            state = by_id.get(entity)
            if state:
                value = as_float(state.get('state'))
                if value is not None:
                    self.live.cells[index] = value

        self.missing_entities = sorted(
            entity for entity in self.settings.required_entities if entity not in by_id
        )
        self.missing_optional_entities = sorted(
            entity for entity in self.settings.optional_entities if entity not in by_id
        )

    def handle_state(self, entity_id: str, state: str | None, ts: datetime | None = None) -> None:
        now = ts or utcnow()
        reverse = {v: k for k, v in self.settings.entity_map.items() if v}
        if entity_id in reverse:
            self.live.values[reverse[entity_id]] = state
        elif entity_id in self.settings.cell_entities:
            idx = self.settings.cell_entities.index(entity_id) + 1
            value = as_float(state)
            if value is None:
                self.live.cells.pop(idx, None)
            else:
                self.live.cells[idx] = value
        else:
            return
        self.evaluate(now)

    def _classify_flow(self, snap: dict[str, Any]) -> str:
        current = snap.get('normalized_dc_charge_current_a')
        power = snap.get('normalized_dc_charge_power_w')
        if snap.get('dc_current_source') == 'calculated_from_power_voltage':
            # Calculated current contains no independent flow information; using both current
            # and power would apply two different zero thresholds to the same measurement.
            current = None

        def cls(value: float | None, threshold: float) -> str | None:
            if value is None:
                return None
            if value > threshold:
                return self.FLOW_CHARGING
            if value < -threshold:
                return self.FLOW_DISCHARGING
            return self.FLOW_ZERO

        c = cls(current, self.settings.charge_zero_current_a)
        p = cls(power, self.settings.charge_zero_power_w)
        available = [x for x in (c, p) if x is not None]
        if not available:
            return self.FLOW_UNKNOWN
        if len(available) == 1:
            return available[0]
        if c == p:
            return c or self.FLOW_UNKNOWN
        if {c, p} == {self.FLOW_CHARGING, self.FLOW_ZERO}:
            return self.FLOW_CHARGING
        if {c, p} == {self.FLOW_DISCHARGING, self.FLOW_ZERO}:
            return self.FLOW_DISCHARGING
        return self.FLOW_CONFLICT

    def _event(self, event_type: str, now: datetime, data: dict[str, Any] | None = None) -> None:
        if self.current_cycle_id is None:
            return
        self.db.add_event(self.current_cycle_id, iso(now), event_type, self.phase, data or {})

    def _start_cycle(self, now: datetime, soc: float | None) -> None:
        self.phase = self.PHASE_OBSERVATION
        self.cycle_started_at = now
        self.top_charge_at = None
        self.charge_stop_at = None
        self.charge_stop_confirmed_at = None
        self.rest_reference_at = None
        self.zero_candidate_at = None
        self.zero_candidate_snapshot = None
        self.last_sample_at = None
        self.last_charging_snapshot = None
        self.max_vmax = None
        self.min_vmin = None
        self.measurement_gaps = False
        self.charge_resumed = False
        self.signal_conflict_seen = False
        self.flow_conflict_candidate_at = None
        self.balancing_nonzero_flow_seen = False
        self.balancing_nonzero_candidate_at = None
        self.balancing_signal_unknown_seen = False
        self.post_stop_nonzero_flow_seen = False
        self.invalid_sample_count = 0
        self.balancing_first_start_at = None
        self.balancing_last_end_at = None
        self.balancing_active_since = None
        self.balancing_duration_completed_s = 0.0
        self.balancing_session_count = 0
        self.current_cycle_id = self.db.create_cycle(iso(now), self.phase, soc)
        self._event('cycle_started', now, {'soc': soc})
        self._write_sample(now, force=True)

    def _set_phase(self, phase: str, now: datetime, reason: str | None = None) -> None:
        if phase == self.phase:
            return
        old = self.phase
        self.phase = phase
        if self.current_cycle_id is not None:
            self.db.update_cycle(self.current_cycle_id, phase=phase)
            self._event('phase_changed', now, {'from': old, 'to': phase, 'reason': reason})
        self._write_sample(now, force=True)

    def _mark_top_charge(self, now: datetime) -> None:
        if self.top_charge_at is None:
            self.top_charge_at = now
            if self.current_cycle_id is not None:
                self.db.update_cycle(self.current_cycle_id, top_charge_at=iso(now))
                self._event('top_charge_entered', now, self.live.snapshot(self.settings, self.phase, now))
        self._set_phase(self.PHASE_TOP_CHARGE, now, 'top_charge_threshold')

    def _mark_charge_stop(
        self,
        stop_time: datetime,
        stop_snap: dict[str, Any],
        confirmed_at: datetime,
    ) -> None:
        before = self.last_charging_snapshot or stop_snap
        first_stop = self.charge_stop_at is None
        self.charge_stop_at = stop_time
        self.charge_stop_confirmed_at = confirmed_at
        self.rest_reference_at = None
        if self.current_cycle_id is not None:
            fields = {
                'charge_stop_at': iso(stop_time),
                'charge_stop_confirmed_at': iso(confirmed_at),
                'rest_reference_at': None,
                'soc_charge_stop': stop_snap.get('soc'),
                'vmax_charge_stop': stop_snap.get('vmax'),
                'vmin_charge_stop': stop_snap.get('vmin'),
                'delta_charge_stop_mv': stop_snap.get('delta_mv'),
                'dc_current_before_stop_a': before.get('normalized_dc_charge_current_a'),
                'dc_power_before_stop_w': before.get('normalized_dc_charge_power_w'),
                'ac_power_before_stop_w': before.get('normalized_ac_charge_power_w'),
                'ac_current_before_stop_a': before.get('normalized_ac_charge_current_a'),
                'battery_voltage_at_stop_v': stop_snap.get('battery_voltage_v'),
                'battery_temperature_at_stop_c': stop_snap.get('battery_temperature_c'),
                'internal_temperature_at_stop_c': stop_snap.get('internal_temperature_c'),
                'analysis_temperature_at_stop_c': stop_snap.get('analysis_temperature_c'),
                'analysis_temperature_source': stop_snap.get('analysis_temperature_source'),
                'dc_current_source': before.get('dc_current_source'),
            }
            self.db.update_cycle(self.current_cycle_id, **fields)
            self._event(
                'charge_stop_confirmed',
                confirmed_at,
                {
                    'first_stop': first_stop,
                    'stop_time': iso(stop_time),
                    'confirmed_at': iso(confirmed_at),
                    'before': before,
                    'at_stop': stop_snap,
                },
            )
        self._set_phase(self.PHASE_REST, confirmed_at, 'stable_zero_charge')

    def _mark_charge_resumed(self, now: datetime, snap: dict[str, Any]) -> None:
        self.charge_resumed = True
        self.zero_candidate_at = None
        self.zero_candidate_snapshot = None
        self.rest_reference_at = None
        self._event('charge_resumed', now, snap)
        self._set_phase(self.PHASE_TOP_CHARGE, now, 'charge_resumed')

    def _mark_balancing_start(self, now: datetime) -> None:
        if self.balancing_active_since is not None:
            return
        self.balancing_active_since = now
        self.balancing_session_count += 1
        if self.balancing_first_start_at is None:
            self.balancing_first_start_at = now
        if self.current_cycle_id is not None:
            self.db.update_cycle(
                self.current_cycle_id,
                balancing_start_at=iso(self.balancing_first_start_at),
                balancing_active_since=iso(now),
                balancing_detected=1,
                balancing_session_count=self.balancing_session_count,
            )
        self._event('balancing_start', now, self.live.snapshot(self.settings, self.phase, now))

    def _mark_balancing_end(self, now: datetime) -> None:
        if self.balancing_active_since is None:
            return
        seconds = max(0.0, (now - self.balancing_active_since).total_seconds())
        self.balancing_duration_completed_s += seconds
        self.balancing_active_since = None
        self.balancing_last_end_at = now
        if self.current_cycle_id is not None:
            self.db.update_cycle(
                self.current_cycle_id,
                balancing_end_at=iso(now),
                balancing_active_since=None,
                balancing_duration_s=round(self.balancing_duration_completed_s, 3),
                balancing_session_count=self.balancing_session_count,
            )
        self._event('balancing_end', now, {
            'session_duration_s': round(seconds, 3),
            'total_duration_s': round(self.balancing_duration_completed_s, 3),
            'snapshot': self.live.snapshot(self.settings, self.phase, now),
        })

    def _balancing_duration(self, now: datetime) -> float:
        total = self.balancing_duration_completed_s
        if self.balancing_active_since is not None:
            total += max(0.0, (now - self.balancing_active_since).total_seconds())
        return total

    def _write_sample(self, now: datetime, force: bool = False) -> None:
        if self.current_cycle_id is None:
            return
        if not force and self.last_sample_at is not None:
            if (now - self.last_sample_at).total_seconds() < self.settings.sample_interval_seconds:
                return
        snap = self.live.snapshot(self.settings, self.phase, now)
        if snap.get('plausibility'):
            self.invalid_sample_count += 1
        vmax = snap.get('vmax')
        vmin = snap.get('vmin')
        if vmax is not None:
            self.max_vmax = vmax if self.max_vmax is None else max(self.max_vmax, vmax)
        if vmin is not None:
            self.min_vmin = vmin if self.min_vmin is None else min(self.min_vmin, vmin)
        self.db.add_sample(self.current_cycle_id, snap)
        self.last_sample_at = now

    def _finish_cycle(self, now: datetime, reason: str) -> None:
        if self.current_cycle_id is None:
            self.phase = self.PHASE_NORMAL
            return

        if self.balancing_active_since is not None:
            # We do not invent an OFF event; simply account the observed active time up to cycle end.
            self.balancing_duration_completed_s = self._balancing_duration(now)

        snap = self.live.snapshot(self.settings, self.phase, now)
        row = self.db.get_cycle(self.current_cycle_id)
        delta_start = row.get('delta_charge_stop_mv') if row else None
        delta_end = snap.get('delta_mv')
        raw_delta_change = None
        if delta_start is not None and delta_end is not None:
            raw_delta_change = round(delta_start - delta_end, 3)
        delta_reduction_valid = bool(
            raw_delta_change is not None
            and self.charge_stop_at is not None
            and not self.charge_resumed
            and not self.measurement_gaps
            and not self.post_stop_nonzero_flow_seen
            and not self.signal_conflict_seen
            and reason == 'post_charge_timeout'
        )
        reduction = raw_delta_change if delta_reduction_valid else None

        cell_calc = snap.get('cell_calculated') or {}
        quality = {
            'charge_stop_confirmed': self.charge_stop_at is not None,
            'balancing_flag_seen': self.balancing_first_start_at is not None,
            'balancing_session_count': self.balancing_session_count,
            'measurement_gaps': self.measurement_gaps,
            'charge_resumed': self.charge_resumed,
            'signal_conflict_seen': self.signal_conflict_seen,
            'balancing_nonzero_flow_seen': self.balancing_nonzero_flow_seen,
            'balancing_signal_unknown_seen': self.balancing_signal_unknown_seen,
            'post_stop_nonzero_flow_seen': self.post_stop_nonzero_flow_seen,
            'delta_reduction_valid': delta_reduction_valid,
            'raw_delta_change_mv': raw_delta_change,
            'invalid_sample_count': self.invalid_sample_count,
            'individual_cell_data_available': bool(self.live.cells),
            'individual_cell_data_complete': bool(cell_calc.get('complete')),
            'cell_count_expected': self.settings.battery_cell_count,
            'cell_count_seen': int(cell_calc.get('count') or 0),
            'missing_entities': self.missing_entities,
            'config_warnings': self.config_warnings,
            'end_reason': reason,
        }
        self._event('cycle_end', now, {'reason': reason, 'snapshot': snap, 'quality': quality})
        self._write_sample(now, force=True)
        self.db.update_cycle(
            self.current_cycle_id,
            ended_at=iso(now),
            phase='COMPLETE',
            vmax_end=snap.get('vmax'),
            vmin_end=snap.get('vmin'),
            delta_end_mv=delta_end,
            delta_reduction_mv=reduction,
            max_vmax=self.max_vmax,
            min_vmin=self.min_vmin,
            balancing_duration_s=round(self.balancing_duration_completed_s, 3),
            balancing_session_count=self.balancing_session_count,
            balancing_active_since=None,
            end_reason=reason,
            quality_json=quality,
        )

        self.current_cycle_id = None
        self.phase = self.PHASE_NORMAL
        self.cycle_started_at = None
        self.top_charge_at = None
        self.charge_stop_at = None
        self.charge_stop_confirmed_at = None
        self.rest_reference_at = None
        self.zero_candidate_at = None
        self.zero_candidate_snapshot = None
        self.last_sample_at = None
        self.last_charging_snapshot = None
        self.max_vmax = None
        self.min_vmin = None
        self.balancing_first_start_at = None
        self.balancing_last_end_at = None
        self.balancing_active_since = None
        self.balancing_duration_completed_s = 0.0
        self.balancing_session_count = 0
        self.measurement_gaps = False
        self.charge_resumed = False
        self.signal_conflict_seen = False
        self.flow_conflict_candidate_at = None
        self.balancing_nonzero_flow_seen = False
        self.balancing_nonzero_candidate_at = None
        self.balancing_signal_unknown_seen = False
        self.post_stop_nonzero_flow_seen = False
        self.invalid_sample_count = 0

    def evaluate(self, now: datetime | None = None) -> None:
        now = now or utcnow()
        snap = self.live.snapshot(self.settings, self.phase, now)
        soc = snap.get('soc')
        vmax = snap.get('vmax')
        balancing = snap.get('balancing')
        flow = self._classify_flow(snap)
        charging = flow == self.FLOW_CHARGING
        charge_zero = flow == self.FLOW_ZERO

        if self.current_cycle_id is None:
            qualifies = (
                soc is not None
                and soc >= self.settings.observation_soc
                and (charging or balancing is True)
            )
            if qualifies:
                self._start_cycle(now, soc)
                snap = self.live.snapshot(self.settings, self.phase, now)
            else:
                return

        if self.cycle_started_at is not None:
            if now - self.cycle_started_at >= timedelta(hours=self.settings.max_cycle_hours):
                self._finish_cycle(now, 'max_cycle_timeout')
                return

        # Home Assistant updates current and power entities sequentially. A single update can
        # therefore momentarily make them disagree even though the physical flow is valid.
        # Only persist a conflict quality flag when the disagreement survives a short guard.
        if flow == self.FLOW_CONFLICT:
            if self.flow_conflict_candidate_at is None:
                self.flow_conflict_candidate_at = now
            elif (now - self.flow_conflict_candidate_at).total_seconds() >= self.TRANSIENT_GUARD_SECONDS:
                self.signal_conflict_seen = True
        else:
            self.flow_conflict_candidate_at = None

        if balancing is None:
            self.balancing_signal_unknown_seen = True

        if (
            soc is not None
            and soc < self.settings.cycle_end_below_soc
            and not charging
            and balancing is not True
            and self.balancing_active_since is None
        ):
            self._finish_cycle(now, 'soc_below_end_threshold')
            return

        # The observed Venus E balancing phase is expected to have no series current.
        # Keep the data, but flag any non-zero flow so later current/delta estimates are not trusted.
        if balancing is True and flow in (self.FLOW_CHARGING, self.FLOW_DISCHARGING, self.FLOW_CONFLICT):
            if self.balancing_nonzero_candidate_at is None:
                self.balancing_nonzero_candidate_at = now
            elif (now - self.balancing_nonzero_candidate_at).total_seconds() >= self.TRANSIENT_GUARD_SECONDS:
                self.balancing_nonzero_flow_seen = True
        else:
            self.balancing_nonzero_candidate_at = None

        if self.charge_stop_at is not None and flow in (
            self.FLOW_CHARGING,
            self.FLOW_DISCHARGING,
            self.FLOW_CONFLICT,
        ):
            self.post_stop_nonzero_flow_seen = True

        if charging:
            self.last_charging_snapshot = snap
            self.zero_candidate_at = None
            self.zero_candidate_snapshot = None
            if self.charge_stop_at is not None and self.phase in (
                self.PHASE_REST,
                self.PHASE_POST_CHARGE,
            ):
                self._mark_charge_resumed(now, snap)

        if self.phase == self.PHASE_OBSERVATION:
            if (
                (soc is not None and soc >= self.settings.intensive_soc)
                or (vmax is not None and vmax >= self.settings.intensive_vmax)
            ):
                self._mark_top_charge(now)

        if self.phase in (self.PHASE_TOP_CHARGE, self.PHASE_OBSERVATION):
            if charge_zero and self.last_charging_snapshot is not None:
                if self.zero_candidate_at is None:
                    self.zero_candidate_at = now
                    self.zero_candidate_snapshot = snap
                elif (
                    now - self.zero_candidate_at
                ).total_seconds() >= self.settings.charge_stop_stable_seconds:
                    self._mark_charge_stop(
                        self.zero_candidate_at,
                        self.zero_candidate_snapshot or snap,
                        now,
                    )
                    self.zero_candidate_at = None
                    self.zero_candidate_snapshot = None
            elif not charge_zero:
                self.zero_candidate_at = None
                self.zero_candidate_snapshot = None

        # Balancing is deliberately orthogonal to charge/rest phase.
        if balancing is True:
            self._mark_balancing_start(now)
        elif balancing is False:
            self._mark_balancing_end(now)
        # balancing is None means unknown/unavailable: do not invent an OFF edge.

        # If the analyzer was started in the middle of an already-running balancing session,
        # there may be no preceding charging sample or charge-stop timestamp. End that
        # orphan observation cleanly once an explicit OFF state arrives.
        if (
            self.charge_stop_at is None
            and self.last_charging_snapshot is None
            and self.balancing_first_start_at is not None
            and balancing is False
            and self.balancing_active_since is None
        ):
            self._finish_cycle(now, 'balancing_only_cycle_end')
            return

        if self.charge_stop_at is not None and self.phase == self.PHASE_REST:
            if now - self.charge_stop_at >= timedelta(seconds=self.settings.rest_reference_seconds):
                if self.rest_reference_at is None:
                    self.rest_reference_at = now
                    if self.current_cycle_id is not None:
                        self.db.update_cycle(self.current_cycle_id, rest_reference_at=iso(now))
                    self._event(
                        'rest_reference',
                        now,
                        {
                            'elapsed_s': round((now - self.charge_stop_at).total_seconds(), 1),
                            'snapshot': snap,
                        },
                    )
                self._set_phase(self.PHASE_POST_CHARGE, now, 'rest_reference_elapsed')

        if self.charge_stop_at is not None and self.phase == self.PHASE_POST_CHARGE:
            timeout = timedelta(minutes=self.settings.post_charge_observation_minutes)
            if (
                now - self.charge_stop_at >= timeout
                and balancing is not True
                and self.balancing_active_since is None
            ):
                self._finish_cycle(now, 'post_charge_timeout')
                return

        self._write_sample(now)

    def tick(self) -> None:
        self.evaluate(utcnow())

    def status(self) -> dict[str, Any]:
        now = utcnow()
        snap = self.live.snapshot(self.settings, self.phase, now)
        balancing_duration_s = self._balancing_duration(now)
        current_cycle = self.db.get_cycle(self.current_cycle_id) if self.current_cycle_id else None
        completed = self.db.recent_completed_cycles(1)
        balancing_active = snap.get('balancing') is True
        analysis_state = 'BALANCING' if balancing_active else self.phase
        cell_calc = snap.get('cell_calculated') or {}
        if not self.live.cells:
            cell_source = 'min_max'
        elif cell_calc.get('complete'):
            cell_source = 'individual'
        else:
            cell_source = 'partial_individual'
        return {
            'version': __import__('os').environ.get('APP_VERSION', '0.1.4'),
            'schema_version': 2,
            'phase': self.phase,
            'analysis_state': analysis_state,
            'analysis_active': self.current_cycle_id is not None,
            'ha_connected': self.ha_connected,
            'current_cycle_id': self.current_cycle_id,
            'cycle_started_at': iso(self.cycle_started_at),
            'top_charge_at': iso(self.top_charge_at),
            'charge_stop_at': iso(self.charge_stop_at),
            'charge_stop_confirmed_at': iso(self.charge_stop_confirmed_at),
            'rest_reference_at': iso(self.rest_reference_at),
            'balancing_start_at': iso(self.balancing_first_start_at),
            'balancing_end_at': iso(self.balancing_last_end_at),
            'balancing_duration_s': round(balancing_duration_s, 1),
            'balancing_session_count': self.balancing_session_count,
            'flow_state': self._classify_flow(snap),
            'live': snap,
            'battery': {
                'chemistry': 'LFP',
                'cell_count': self.settings.battery_cell_count,
                'nominal_voltage_v': self.settings.battery_nominal_voltage_v,
                'capacity_ah': self.settings.battery_capacity_ah,
                'gross_capacity_kwh': self.settings.battery_gross_capacity_kwh,
                'dod_percent': self.settings.battery_dod_percent,
                'usable_capacity_kwh': round(self.settings.usable_capacity_kwh, 4),
                'usable_capacity_ah': round(self.settings.usable_capacity_ah, 3),
            },
            'cell_source': cell_source,
            'diagnostics': {
                'missing_entities': self.missing_entities,
                'missing_optional_entities': self.missing_optional_entities,
                'config_warnings': self.config_warnings,
                'measurement_gaps': self.measurement_gaps,
                'signal_conflict_seen': self.signal_conflict_seen,
                'balancing_nonzero_flow_seen': self.balancing_nonzero_flow_seen,
                'balancing_signal_unknown_seen': self.balancing_signal_unknown_seen,
                'post_stop_nonzero_flow_seen': self.post_stop_nonzero_flow_seen,
                'invalid_sample_count': self.invalid_sample_count,
            },
            'current_cycle': current_cycle,
            'last_cycle': completed[0] if completed else None,
        }
