from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path('/data/analyzer.db')


class Database:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=NORMAL')
        self._migrate()

    def _migrate(self) -> None:
        self.conn.executescript(
            '''
            CREATE TABLE IF NOT EXISTS cycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                phase TEXT NOT NULL,
                top_charge_at TEXT,
                charge_stop_at TEXT,
                balancing_start_at TEXT,
                balancing_end_at TEXT,
                balancing_detected INTEGER NOT NULL DEFAULT 0,
                soc_start REAL,
                soc_charge_stop REAL,
                vmax_charge_stop REAL,
                vmin_charge_stop REAL,
                delta_charge_stop_mv REAL,
                vmax_end REAL,
                vmin_end REAL,
                delta_end_mv REAL,
                delta_reduction_mv REAL,
                max_vmax REAL,
                min_vmin REAL,
                dc_current_before_stop_a REAL,
                dc_power_before_stop_w REAL,
                ac_power_before_stop_w REAL,
                battery_temperature_at_stop_c REAL,
                internal_temperature_at_stop_c REAL,
                quality_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_id INTEGER NOT NULL,
                ts TEXT NOT NULL,
                event_type TEXT NOT NULL,
                phase TEXT NOT NULL,
                data_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(cycle_id) REFERENCES cycles(id)
            );
            CREATE INDEX IF NOT EXISTS idx_events_cycle_ts ON events(cycle_id, ts);

            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cycle_id INTEGER NOT NULL,
                ts TEXT NOT NULL,
                phase TEXT NOT NULL,
                soc REAL,
                vmax REAL,
                vmin REAL,
                delta_mv REAL,
                dc_power_w REAL,
                dc_current_a REAL,
                ac_power_w REAL,
                ac_current_a REAL,
                battery_temperature_c REAL,
                internal_temperature_c REAL,
                balancing INTEGER,
                cells_json TEXT,
                FOREIGN KEY(cycle_id) REFERENCES cycles(id)
            );
            CREATE INDEX IF NOT EXISTS idx_samples_cycle_ts ON samples(cycle_id, ts);
            CREATE INDEX IF NOT EXISTS idx_cycles_started_at ON cycles(started_at DESC);
            '''
        )
        self.conn.commit()

    def create_cycle(self, started_at: str, phase: str, soc_start: float | None) -> int:
        cur = self.conn.execute(
            'INSERT INTO cycles(started_at, phase, soc_start) VALUES(?,?,?)',
            (started_at, phase, soc_start),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_cycle(self, cycle_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols = ', '.join(f'{k}=?' for k in fields)
        vals = [json.dumps(v) if k == 'quality_json' and not isinstance(v, str) else v for k, v in fields.items()]
        vals.append(cycle_id)
        self.conn.execute(f'UPDATE cycles SET {cols} WHERE id=?', vals)
        self.conn.commit()

    def add_event(self, cycle_id: int, ts: str, event_type: str, phase: str, data: dict[str, Any] | None = None) -> None:
        self.conn.execute(
            'INSERT INTO events(cycle_id, ts, event_type, phase, data_json) VALUES(?,?,?,?,?)',
            (cycle_id, ts, event_type, phase, json.dumps(data or {})),
        )
        self.conn.commit()

    def add_sample(self, cycle_id: int, sample: dict[str, Any]) -> None:
        self.conn.execute(
            '''
            INSERT INTO samples(
                cycle_id, ts, phase, soc, vmax, vmin, delta_mv,
                dc_power_w, dc_current_a, ac_power_w, ac_current_a,
                battery_temperature_c, internal_temperature_c, balancing, cells_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''',
            (
                cycle_id,
                sample['ts'], sample['phase'], sample.get('soc'), sample.get('vmax'), sample.get('vmin'),
                sample.get('delta_mv'), sample.get('dc_power_w'), sample.get('dc_current_a'),
                sample.get('ac_power_w'), sample.get('ac_current_a'), sample.get('battery_temperature_c'),
                sample.get('internal_temperature_c'), 1 if sample.get('balancing') else 0,
                json.dumps(sample.get('cells') or {}),
            ),
        )
        self.conn.commit()

    def get_cycle(self, cycle_id: int) -> dict[str, Any] | None:
        row = self.conn.execute('SELECT * FROM cycles WHERE id=?', (cycle_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result['quality_json'] = json.loads(result.get('quality_json') or '{}')
        return result

    def get_open_cycle(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM cycles WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result['quality_json'] = json.loads(result.get('quality_json') or '{}')
        return result

    def recent_cycles(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            'SELECT * FROM cycles ORDER BY id DESC LIMIT ?', (limit,)
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item['quality_json'] = json.loads(item.get('quality_json') or '{}')
            out.append(item)
        return out

    def cycle_events(self, cycle_id: int, limit: int = 5000) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            'SELECT * FROM events WHERE cycle_id=? ORDER BY id ASC LIMIT ?', (cycle_id, limit)
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item['data'] = json.loads(item.pop('data_json') or '{}')
            out.append(item)
        return out

    def cycle_samples(self, cycle_id: int, limit: int = 5000) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            'SELECT * FROM samples WHERE cycle_id=? ORDER BY id ASC LIMIT ?', (cycle_id, limit)
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item['cells'] = json.loads(item.pop('cells_json') or '{}')
            out.append(item)
        return out
