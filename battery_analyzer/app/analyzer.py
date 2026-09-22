from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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
        return float(value)
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


@dataclass(slots=True)
class LiveState:
    values: dict[str, Any] = field(default_factory=dict)
    cells: dict[int, float] = field(default_factory=dict)

    def snapshot(self, settings: Settings, phase: str, ts: datetime) -> dict[str, Any]:
        vmax = as_float(self.values.get('vmax'))
        vmin = as_float(self.values.get('vmin'))
        delta = None
        if vmax is not None and vmin is not None:
            delta = round((vmax - vmin) * 1000.0, 3)
        dc_power = as_float(self.values.get('dc_power'))
        dc_current = as_float(self.values.get('dc_current'))
        ac_power = as_float(self.values.get('ac_power'))
        ac_current = as_float(self.values.get('ac_current'))
        return {
            'ts': iso(ts),
            'phase': phase,
            'soc': as_float(self.values.get('soc')),
            'vmax': vmax,
            'vmin': vmin,
            'delta_mv': delta,
            'dc_power_w': dc_power,
            'dc_current_a': dc_current,
            'ac_power_w': ac_power,
            'ac_current_a': ac_current,
            'battery_temperature_c': as_float(self.values.get('battery_temperature')),
            'internal_temperature_c': as_float(self.values.get('internal_temperature')),
            'balancing': as_bool(self.values.get('balancing')) is True,
            'cells': dict(self.cells),
            'normalized_dc_charge_power_w': settings.normalize_dc_charge(dc_power),
            'normalized_dc_charge_current_a': settings.normalize_dc_charge(dc_current),
            'normalized_ac_charge_power_w': settings.normalize_ac_charge(ac_power),
            'normalized_ac_charge_current_a': settings.normalize_ac_charge(ac_current),
        }


class Analyzer:
    PHASE_NORMAL = 'NORMAL'
    PHASE_OBSERVATION = 'OBSERVATION'
    PHASE_TOP_CHARGE = 'TOP_CHARGE'
    PHASE_REST = 'REST'
    PHASE_BALANCING = 'BALANCING'
    PHASE_POST_BALANCING = 'POST_BALANCING'
    PHASE_POST_CHARGE = 'POST_CHARGE_OBSERVATION'

    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.live = LiveState()
        self.phase = self.PHASE_NORMAL
        self.current_cycle_id: int | None = None
        self.cycle_started_at: datetime | None = None
        self.top_charge_at: datetime | None = None
        self.charge_stop_at: datetime | None = None
        self.balancing_start_at: datetime | None = None
        self.balancing_end_at: datetime | None = None
        self.zero_candidate_at: datetime | None = None
        self.last_sample_at: datetime | None = None
        self.last_charging_snapshot: dict[str, Any] | None = None
        self.max_vmax: float | None = None
        self.min_vmin: float | None = None
        self.measurement_gaps = False
        self.charge_resumed = False
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
        self.balancing_start_at = parse_dt(row.get('balancing_start_at'))
        self.balancing_end_at = parse_dt(row.get('balancing_end_at'))
        self.max_vmax = row.get('max_vmax')
        self.min_vmin = row.get('min_vmin')
        quality = row.get('quality_json') or {}
        self.measurement_gaps = bool(quality.get('measurement_gaps'))
        self.charge_resumed = bool(quality.get('charge_resumed'))

    def set_initial_states(self, states: list[dict[str, Any]]) -> None:
        by_id = {s.get('entity_id'): s for s in states}
        for key, entity in self.settings.entity_map.items():
            state = by_id.get(entity)
            if state:
                self.live.values[key] = state.get('state')
        for index, entity in enumerate(self.settings.cell_entities, start=1):
            state = by_id.get(entity)
            if state:
                value = as_float(state.get('state'))
                if value is not None:
                    self.live.cells[index] = value

    def handle_state(self, entity_id: str, state: str | None, ts: datetime | None = None) -> None:
        now = ts or utcnow()
        reverse = {v: k for k, v in self.settings.entity_map.items()}
        if entity_id in reverse:
            self.live.values[reverse[entity_id]] = state
        elif entity_id in self.settings.cell_entities:
            idx = self.settings.cell_entities.index(entity_id) + 1
            value = as_float(state)
            if value is not None:
                self.live.cells[idx] = value
        else:
            return
        self.evaluate(now)

    def _is_charging(self, snap: dict[str, Any]) -> bool:
        current = snap.get('normalized_dc_charge_current_a')
        power = snap.get('normalized_dc_charge_power_w')
        if current is not None and current > self.settings.charge_zero_current_a:
            return True
        if power is not None and power > self.settings.charge_zero_power_w:
            return True
        return False

    def _is_charge_zero(self, snap: dict[str, Any]) -> bool:
        current = snap.get('normalized_dc_charge_current_a')
        power = snap.get('normalized_dc_charge_power_w')
        current_ok = current is None or abs(current) <= self.settings.charge_zero_current_a
        power_ok = power is None or abs(power) <= self.settings.charge_zero_power_w
        return current_ok and power_ok and (current is not None or power is not None)

    def _event(self, event_type: str, now: datetime, data: dict[str, Any] | None = None) -> None:
        if self.current_cycle_id is None:
            return
        self.db.add_event(self.current_cycle_id, iso(now), event_type, self.phase, data or {})

    def _start_cycle(self, now: datetime, soc: float | None) -> None:
        self.phase = self.PHASE_OBSERVATION
        self.cycle_started_at = now
        self.top_charge_at = None
        self.charge_stop_at = None
        self.balancing_start_at = None
        self.balancing_end_at = None
        self.zero_candidate_at = None
        self.last_sample_at = None
        self.last_charging_snapshot = None
        self.max_vmax = None
        self.min_vmin = None
        self.measurement_gaps = False
        self.charge_resumed = False
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

    def _mark_charge_stop(self, now: datetime, snap: dict[str, Any]) -> None:
        before = self.last_charging_snapshot or snap
        first_stop = self.charge_stop_at is None
        self.charge_stop_at = now
        if self.current_cycle_id is not None:
            fields = {
                'charge_stop_at': iso(now),
                'soc_charge_stop': snap.get('soc'),
                'vmax_charge_stop': snap.get('vmax'),
                'vmin_charge_stop': snap.get('vmin'),
                'delta_charge_stop_mv': snap.get('delta_mv'),
                'dc_current_before_stop_a': before.get('dc_current_a'),
                'dc_power_before_stop_w': before.get('dc_power_w'),
                'ac_power_before_stop_w': before.get('ac_power_w'),
                'battery_temperature_at_stop_c': snap.get('battery_temperature_c'),
                'internal_temperature_at_stop_c': snap.get('internal_temperature_c'),
            }
            self.db.update_cycle(self.current_cycle_id, **fields)
            self._event('charge_stop', now, {'first_stop': first_stop, 'before': before, 'at_stop': snap})
        self._set_phase(self.PHASE_REST, now, 'stable_zero_charge')

    def _mark_charge_resumed(self, now: datetime, snap: dict[str, Any]) -> None:
        self.charge_resumed = True
        self.zero_candidate_at = None
        self._event('charge_resumed', now, snap)
        self._set_phase(self.PHASE_TOP_CHARGE, now, 'charge_resumed')

    def _mark_balancing_start(self, now: datetime) -> None:
        if self.phase == self.PHASE_BALANCING:
            return
        if self.balancing_start_at is None:
            self.balancing_start_at = now
            if self.current_cycle_id is not None:
                self.db.update_cycle(
                    self.current_cycle_id,
                    balancing_start_at=iso(now),
                    balancing_detected=1,
                )
        self.balancing_end_at = None
        self._event('balancing_start', now, self.live.snapshot(self.settings, self.phase, now))
        self._set_phase(self.PHASE_BALANCING, now, 'balancing_flag_on')

    def _mark_balancing_end(self, now: datetime) -> None:
        self.balancing_end_at = now
        if self.current_cycle_id is not None:
            self.db.update_cycle(self.current_cycle_id, balancing_end_at=iso(now))
        self._event('balancing_end', now, self.live.snapshot(self.settings, self.phase, now))
        self._set_phase(self.PHASE_POST_BALANCING, now, 'balancing_flag_off')

    def _write_sample(self, now: datetime, force: bool = False) -> None:
        if self.current_cycle_id is None:
            return
        if not force and self.last_sample_at is not None:
            if (now - self.last_sample_at).total_seconds() < self.settings.sample_interval_seconds:
                return
        snap = self.live.snapshot(self.settings, self.phase, now)
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
        snap = self.live.snapshot(self.settings, self.phase, now)
        row = self.db.get_cycle(self.current_cycle_id)
        delta_start = row.get('delta_charge_stop_mv') if row else None
        delta_end = snap.get('delta_mv')
        reduction = None
        if delta_start is not None and delta_end is not None:
            reduction = round(delta_start - delta_end, 3)
        quality = {
            'pack_current_zero_at_stop': self.charge_stop_at is not None,
            'balancing_flag_seen': self.balancing_start_at is not None,
            'measurement_gaps': self.measurement_gaps,
            'charge_resumed': self.charge_resumed,
            'individual_cell_data_available': bool(self.live.cells),
            'cell_count_expected': self.settings.battery_cell_count,
            'cell_count_seen': len(self.live.cells),
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
            quality_json=quality,
        )
        self.current_cycle_id = None
        self.phase = self.PHASE_NORMAL
        self.cycle_started_at = None
        self.top_charge_at = None
        self.charge_stop_at = None
        self.balancing_start_at = None
        self.balancing_end_at = None
        self.zero_candidate_at = None
        self.last_sample_at = None
        self.last_charging_snapshot = None
        self.max_vmax = None
        self.min_vmin = None

    def evaluate(self, now: datetime | None = None) -> None:
        now = now or utcnow()
        snap = self.live.snapshot(self.settings, self.phase, now)
        soc = snap.get('soc')
        vmax = snap.get('vmax')
        balancing = snap.get('balancing') is True
        charging = self._is_charging(snap)
        charge_zero = self._is_charge_zero(snap)

        if self.current_cycle_id is None:
            if soc is not None and soc >= self.settings.observation_soc:
                self._start_cycle(now, soc)
                snap = self.live.snapshot(self.settings, self.phase, now)
            else:
                return

        if soc is not None and soc < self.settings.cycle_end_below_soc:
            self._finish_cycle(now, 'soc_below_end_threshold')
            return

        if charging:
            self.last_charging_snapshot = snap
            self.zero_candidate_at = None
            if self.charge_stop_at is not None and self.phase in (
                self.PHASE_REST,
                self.PHASE_POST_CHARGE,
                self.PHASE_POST_BALANCING,
            ):
                self._mark_charge_resumed(now, snap)

        if self.phase == self.PHASE_OBSERVATION:
            if ((soc is not None and soc >= self.settings.intensive_soc) or
                    (vmax is not None and vmax >= self.settings.intensive_vmax)):
                self._mark_top_charge(now)

        if self.phase in (self.PHASE_TOP_CHARGE, self.PHASE_OBSERVATION):
            if charge_zero and self.last_charging_snapshot is not None:
                if self.zero_candidate_at is None:
                    self.zero_candidate_at = now
                elif (now - self.zero_candidate_at).total_seconds() >= self.settings.charge_stop_stable_seconds:
                    self._mark_charge_stop(now, snap)
                    self.zero_candidate_at = None
            else:
                self.zero_candidate_at = None

        if balancing:
            self._mark_balancing_start(now)
        elif self.phase == self.PHASE_BALANCING:
            self._mark_balancing_end(now)
        elif self.phase == self.PHASE_REST and self.charge_stop_at is not None:
            self._set_phase(self.PHASE_POST_CHARGE, now, 'waiting_for_balancing_or_relaxation')

        if self.charge_stop_at is not None and self.phase in (
            self.PHASE_POST_CHARGE,
            self.PHASE_POST_BALANCING,
        ):
            timeout = timedelta(minutes=self.settings.post_charge_observation_minutes)
            if now - self.charge_stop_at >= timeout:
                self._finish_cycle(now, 'post_charge_timeout')
                return

        self._write_sample(now)

    def tick(self) -> None:
        self.evaluate(utcnow())

    def status(self) -> dict[str, Any]:
        now = utcnow()
        snap = self.live.snapshot(self.settings, self.phase, now)
        balancing_duration_s = 0.0
        if self.balancing_start_at is not None:
            end = self.balancing_end_at or now
            balancing_duration_s = max(0.0, (end - self.balancing_start_at).total_seconds())
        current_cycle = self.db.get_cycle(self.current_cycle_id) if self.current_cycle_id else None
        recent = self.db.recent_cycles(1)
        return {
            'version': '0.1.0',
            'schema_version': 1,
            'phase': self.phase,
            'analysis_active': self.current_cycle_id is not None,
            'current_cycle_id': self.current_cycle_id,
            'cycle_started_at': iso(self.cycle_started_at),
            'top_charge_at': iso(self.top_charge_at),
            'charge_stop_at': iso(self.charge_stop_at),
            'balancing_start_at': iso(self.balancing_start_at),
            'balancing_end_at': iso(self.balancing_end_at),
            'balancing_duration_s': round(balancing_duration_s, 1),
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
            'cell_source': 'individual' if self.live.cells else 'min_max',
            'current_cycle': current_cycle,
            'last_cycle': recent[0] if recent else None,
        }
