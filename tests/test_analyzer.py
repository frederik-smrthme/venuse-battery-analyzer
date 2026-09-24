from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'battery_analyzer' / 'app'))

from analyzer import Analyzer, LiveState  # noqa: E402
from config import Settings  # noqa: E402
from db import Database  # noqa: E402


BASE = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


class AnalyzerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / 'test.db')
        self.settings = Settings(
            sample_interval_seconds=5,
            post_charge_observation_minutes=240,
            rest_reference_seconds=60,
        )
        self.analyzer = Analyzer(self.settings, self.db)
        self.analyzer.set_connection_state(True)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def set_values(self, **kwargs):
        mapping = {
            'soc': 'soc',
            'vmax': 'vmax',
            'vmin': 'vmin',
            'battery_voltage': 'battery_voltage',
            'dc_power': 'dc_power',
            'dc_current': 'dc_current',
            'ac_power': 'ac_power',
            'ac_current': 'ac_current',
            'battery_temperature': 'battery_temperature',
            'internal_temperature': 'internal_temperature',
            'balancing': 'balancing',
        }
        for key, value in kwargs.items():
            self.analyzer.live.values[mapping[key]] = str(value) if not isinstance(value, str) else value

    def begin_charge(self, t=BASE):
        self.set_values(
            soc=97.2,
            vmax=3.44,
            vmin=3.39,
            battery_voltage=54.1,
            dc_power=120,
            dc_current=2.2,
            ac_power=-165,
            ac_current=-0.75,
            battery_temperature=24.0,
            internal_temperature=31.0,
            balancing='off',
        )
        self.analyzer.evaluate(t)
        self.assertIsNotNone(self.analyzer.current_cycle_id)

    def test_idle_at_high_soc_does_not_start_cycle(self):
        self.set_values(
            soc=100,
            vmax=3.55,
            vmin=3.39,
            dc_power=0,
            dc_current=0,
            balancing='off',
        )
        self.analyzer.evaluate(BASE)
        self.assertIsNone(self.analyzer.current_cycle_id)

    def test_charge_stop_is_backdated_to_zero_candidate(self):
        self.begin_charge()
        self.set_values(soc=99.5, vmax=3.52)
        self.analyzer.evaluate(BASE + timedelta(seconds=60))

        zero_at = BASE + timedelta(seconds=120)
        self.set_values(dc_power=0, dc_current=0)
        self.analyzer.evaluate(zero_at)
        self.analyzer.evaluate(zero_at + timedelta(seconds=30))

        self.assertEqual(self.analyzer.charge_stop_at, zero_at)
        row = self.db.get_cycle(self.analyzer.current_cycle_id)
        self.assertEqual(row['charge_stop_at'], zero_at.isoformat())
        self.assertEqual(row['charge_stop_confirmed_at'], (zero_at + timedelta(seconds=30)).isoformat())
        self.assertAlmostEqual(row['dc_power_before_stop_w'], 120.0)
        self.assertAlmostEqual(row['ac_power_before_stop_w'], 165.0)
        self.assertAlmostEqual(row['ac_current_before_stop_a'], 0.75)

    def test_balancing_duration_accumulates_multiple_sessions(self):
        self.begin_charge()
        self.analyzer._mark_balancing_start(BASE + timedelta(seconds=10))
        snap = self.analyzer.live.snapshot(self.settings, self.analyzer.phase, BASE + timedelta(seconds=20))
        self.analyzer._mark_balancing_end(BASE + timedelta(seconds=20), snap, Analyzer.FLOW_CHARGING)
        self.analyzer._mark_balancing_start(BASE + timedelta(seconds=30))
        snap = self.analyzer.live.snapshot(self.settings, self.analyzer.phase, BASE + timedelta(seconds=50))
        self.analyzer._mark_balancing_end(BASE + timedelta(seconds=50), snap, Analyzer.FLOW_CHARGING)
        self.assertAlmostEqual(self.analyzer._balancing_duration(BASE + timedelta(seconds=60)), 30.0)
        row = self.db.get_cycle(self.analyzer.current_cycle_id)
        self.assertAlmostEqual(row['balancing_duration_s'], 30.0)
        self.assertEqual(row['balancing_session_count'], 2)

    def test_unavailable_balancing_does_not_create_false_off_edge(self):
        self.begin_charge()
        self.set_values(balancing='on')
        self.analyzer.evaluate(BASE + timedelta(seconds=10))
        started = self.analyzer.balancing_active_since
        self.assertIsNotNone(started)

        self.set_values(balancing='unavailable')
        self.analyzer.evaluate(BASE + timedelta(seconds=20))
        self.assertEqual(self.analyzer.balancing_active_since, started)

    def test_nonfinite_sensor_values_are_rejected(self):
        state = LiveState(values={'vmin': 'nan', 'vmax': 'inf', 'soc': '99'})
        snap = state.snapshot(self.settings, Analyzer.PHASE_NORMAL, BASE)
        self.assertIsNone(snap['vmin'])
        self.assertIsNone(snap['vmax'])
        self.assertIsNone(snap['delta_mv'])

    def test_lfp_voltage_plausibility_allows_below_three_volts_and_caps_at_3_8(self):
        state = LiveState(values={'vmin': '2.80', 'vmax': '3.80', 'soc': '50'})
        snap = state.snapshot(self.settings, Analyzer.PHASE_NORMAL, BASE)
        self.assertEqual(snap['vmin'], 2.8)
        self.assertEqual(snap['vmax'], 3.8)
        self.assertEqual(snap['delta_mv'], 1000.0)

        state.values['vmax'] = '3.81'
        snap = state.snapshot(self.settings, Analyzer.PHASE_NORMAL, BASE)
        self.assertIsNone(snap['vmax'])
        self.assertTrue(any(item.startswith('vmax_out_of_range') for item in snap['plausibility']))


    def test_dc_current_is_calculated_when_direct_sensor_missing(self):
        state = LiveState(values={
            'battery_voltage': '53.0',
            'dc_power': '727',
            'soc': '25',
            'vmax': '3.316',
            'vmin': '3.313',
        })
        snap = state.snapshot(self.settings, Analyzer.PHASE_NORMAL, BASE)
        self.assertAlmostEqual(snap['dc_current_a'], 727 / 53.0, places=6)
        self.assertAlmostEqual(snap['normalized_dc_charge_current_a'], 727 / 53.0, places=6)
        self.assertEqual(snap['dc_current_source'], 'calculated_from_power_voltage')

    def test_calculated_dc_current_does_not_apply_a_second_flow_threshold(self):
        state = LiveState(values={
            'battery_voltage': '53.0',
            'dc_power': '10',
            'soc': '99',
            'vmax': '3.50',
            'vmin': '3.40',
        })
        snap = state.snapshot(self.settings, Analyzer.PHASE_NORMAL, BASE)
        # 10 W / 53 V is about 0.19 A, above the current threshold, but it is derived
        # from the same power sample. Flow classification must therefore use power only.
        self.assertEqual(snap['dc_current_source'], 'calculated_from_power_voltage')
        self.assertEqual(self.analyzer._classify_flow(snap), Analyzer.FLOW_ZERO)

    def test_direct_dc_current_is_preferred_when_available(self):
        state = LiveState(values={
            'battery_voltage': '53.0',
            'dc_power': '727',
            'dc_current': '13.5',
        })
        snap = state.snapshot(self.settings, Analyzer.PHASE_NORMAL, BASE)
        self.assertEqual(snap['dc_current_source'], 'measured')
        self.assertAlmostEqual(snap['dc_current_a'], 13.5)

    def test_internal_temperature_is_used_as_labelled_analysis_proxy(self):
        state = LiveState(values={'internal_temperature': '31.8'})
        snap = state.snapshot(self.settings, Analyzer.PHASE_NORMAL, BASE)
        self.assertAlmostEqual(snap['analysis_temperature_c'], 31.8)
        self.assertEqual(snap['analysis_temperature_source'], 'internal_temperature_proxy')
        self.assertIsNone(snap['battery_temperature_c'])

    def test_battery_temperature_is_preferred_over_internal_proxy(self):
        state = LiveState(values={'battery_temperature': '24.2', 'internal_temperature': '31.8'})
        snap = state.snapshot(self.settings, Analyzer.PHASE_NORMAL, BASE)
        self.assertAlmostEqual(snap['analysis_temperature_c'], 24.2)
        self.assertEqual(snap['analysis_temperature_source'], 'battery_sensor')

    def test_missing_optional_entities_are_not_reported_as_required(self):
        required_states = [
            {'entity_id': entity, 'state': '0'}
            for entity in self.settings.required_entities
        ]
        # Simulate a legacy installation that still has non-existent optional IDs configured.
        self.settings.entity_dc_current = 'sensor.missing_dc_current'
        self.settings.entity_ac_current = 'sensor.missing_ac_current'
        self.settings.entity_battery_temperature = 'sensor.missing_battery_temperature'
        self.analyzer.set_initial_states(required_states)
        self.assertEqual(self.analyzer.missing_entities, [])
        self.assertEqual(len(self.analyzer.missing_optional_entities), 3)

    def test_last_cycle_means_last_completed_cycle(self):
        self.begin_charge()
        first_id = self.analyzer.current_cycle_id
        self.analyzer._finish_cycle(BASE + timedelta(minutes=1), 'test')
        self.assertEqual(self.analyzer.status()['last_cycle']['id'], first_id)

        self.begin_charge(BASE + timedelta(minutes=2))
        self.assertNotEqual(self.analyzer.current_cycle_id, first_id)
        self.assertEqual(self.analyzer.status()['last_cycle']['id'], first_id)

    def test_dc_signal_conflict_is_not_interpreted_as_charging_or_zero(self):
        self.set_values(
            soc=99,
            vmax=3.50,
            vmin=3.40,
            dc_power=100,
            dc_current=-2,
            balancing='off',
        )
        snap = self.analyzer.live.snapshot(self.settings, Analyzer.PHASE_NORMAL, BASE)
        self.assertEqual(self.analyzer._classify_flow(snap), Analyzer.FLOW_CONFLICT)

    def test_post_charge_without_balancing_does_not_publish_balancing_delta_reduction(self):
        self.settings.post_charge_observation_minutes = 2
        self.begin_charge()
        self.set_values(soc=99.5, vmax=3.52, vmin=3.40)
        self.analyzer.evaluate(BASE + timedelta(seconds=10))

        stop_at = BASE + timedelta(seconds=20)
        self.set_values(dc_power=0, dc_current=0, vmax=3.50, vmin=3.40)
        self.analyzer.evaluate(stop_at)
        self.analyzer.evaluate(stop_at + timedelta(seconds=30))
        self.analyzer.evaluate(stop_at + timedelta(seconds=60))

        self.set_values(vmax=3.48, vmin=3.40)
        self.analyzer.evaluate(stop_at + timedelta(seconds=120))
        last = self.analyzer.status()['last_cycle']
        self.assertIsNotNone(last)
        self.assertIsNone(last['delta_reduction_mv'])
        self.assertFalse(last['quality_json']['delta_reduction_valid'])

    def test_balancing_end_uses_last_clean_rest_sample_before_discharge(self):
        self.settings.post_charge_observation_minutes = 10
        self.begin_charge()
        self.set_values(soc=100, vmax=3.59, vmin=3.399)
        self.analyzer.evaluate(BASE + timedelta(seconds=10))

        stop_at = BASE + timedelta(seconds=20)
        self.set_values(dc_power=0, dc_current=0, balancing='off', vmax=3.56, vmin=3.40)
        self.analyzer.evaluate(stop_at)
        self.analyzer.evaluate(stop_at + timedelta(seconds=30))

        # Balancing starts at rest. The last clean point before discharge is 126 mV.
        self.set_values(balancing='on', vmax=3.526, vmin=3.400)
        self.analyzer.evaluate(stop_at + timedelta(seconds=60))
        self.analyzer.evaluate(stop_at + timedelta(seconds=120))

        # Discharge starts while the BMS flag still says balancing. Voltage delta collapses,
        # but this point must not be used as the balancing end value.
        self.set_values(dc_power=-300, dc_current=-5.5, vmax=3.442, vmin=3.400)
        self.analyzer.evaluate(stop_at + timedelta(seconds=125))
        self.set_values(balancing='off')
        self.analyzer.evaluate(stop_at + timedelta(seconds=130))

        row = self.db.get_cycle(self.analyzer.current_cycle_id)
        self.assertAlmostEqual(row['balancing_clean_end_delta_mv'], 126.0)
        self.assertAlmostEqual(row['balancing_clean_end_vmax'], 3.526)
        self.assertEqual(row['balancing_end_reason'], 'interrupted_by_discharge')

    def test_matched_vmax_comparison_uses_only_zero_flow_points(self):
        self.settings.post_charge_observation_minutes = 5
        self.settings.matched_vmax_tolerance_mv = 5.0
        self.settings.matched_min_elapsed_seconds = 60
        self.begin_charge()
        self.set_values(soc=100, vmax=3.55, vmin=3.40)
        self.analyzer.evaluate(BASE + timedelta(seconds=10))

        stop_at = BASE + timedelta(seconds=20)
        self.set_values(dc_power=0, dc_current=0, balancing='off', vmax=3.505, vmin=3.400)
        self.analyzer.evaluate(stop_at)
        self.analyzer.evaluate(stop_at + timedelta(seconds=30))

        # Clean reference at 3.505 V / 105 mV.
        self.set_values(balancing='on')
        self.analyzer.evaluate(stop_at + timedelta(seconds=60))

        # A much smaller delta under discharge must be ignored despite similar Vmax.
        self.set_values(dc_power=-200, dc_current=-3.7, vmax=3.503, vmin=3.450)
        self.analyzer.evaluate(stop_at + timedelta(seconds=90))

        # Return to rest with nearly the same Vmax and a genuine 80 mV delta.
        self.set_values(dc_power=0, dc_current=0, vmax=3.502, vmin=3.422)
        self.analyzer.evaluate(stop_at + timedelta(seconds=130))
        self.set_values(balancing='off')
        self.analyzer.evaluate(stop_at + timedelta(seconds=140))

        # End the cycle manually so matched metrics are finalized.
        self.analyzer._finish_cycle(stop_at + timedelta(seconds=150), 'test_end')
        last = self.analyzer.status()['last_cycle']
        self.assertTrue(last['quality_json']['delta_reduction_valid'])
        self.assertAlmostEqual(last['matched_vmax_diff_mv'], 3.0)
        self.assertAlmostEqual(last['matched_delta_reduction_mv'], 25.0)
        self.assertAlmostEqual(last['delta_reduction_mv'], 25.0)

    def test_recent_v014_cycle_is_backfilled_with_clean_balancing_end(self):
        self.settings.post_charge_observation_minutes = 10
        self.begin_charge()
        self.set_values(soc=100, vmax=3.59, vmin=3.399)
        self.analyzer.evaluate(BASE + timedelta(seconds=10))

        stop_at = BASE + timedelta(seconds=20)
        self.set_values(dc_power=0, dc_current=0, balancing='off', vmax=3.56, vmin=3.40)
        self.analyzer.evaluate(stop_at)
        self.analyzer.evaluate(stop_at + timedelta(seconds=30))
        self.set_values(balancing='on', vmax=3.526, vmin=3.400)
        self.analyzer.evaluate(stop_at + timedelta(seconds=60))
        self.analyzer.evaluate(stop_at + timedelta(seconds=120))
        self.set_values(dc_power=-300, dc_current=-5.5, vmax=3.442, vmin=3.400)
        self.analyzer.evaluate(stop_at + timedelta(seconds=125))
        self.set_values(balancing='off')
        self.analyzer.evaluate(stop_at + timedelta(seconds=130))
        self.analyzer._finish_cycle(stop_at + timedelta(seconds=140), 'test_end')
        cycle_id = self.analyzer.status()['last_cycle']['id']

        # Mimic a v0.1.4 database: samples exist, but clean-end metadata and stored
        # flow_state were not available yet.
        self.db.conn.execute(
            '''
            UPDATE cycles
            SET balancing_clean_end_at=NULL,
                balancing_clean_end_vmax=NULL,
                balancing_clean_end_vmin=NULL,
                balancing_clean_end_delta_mv=NULL,
                balancing_end_reason=NULL
            WHERE id=?
            ''',
            (cycle_id,),
        )
        self.db.conn.execute('UPDATE samples SET flow_state=NULL WHERE cycle_id=?', (cycle_id,))
        self.db.conn.commit()

        Analyzer(self.settings, self.db)
        row = self.db.get_cycle(cycle_id)
        self.assertAlmostEqual(row['balancing_clean_end_delta_mv'], 126.0)
        self.assertAlmostEqual(row['balancing_clean_end_vmax'], 3.526)
        self.assertEqual(row['balancing_end_reason'], 'interrupted_by_discharge')

    def test_post_stop_current_invalidates_delta_reduction(self):
        self.settings.post_charge_observation_minutes = 2
        self.begin_charge()
        self.set_values(soc=99.5, vmax=3.52, vmin=3.40)
        self.analyzer.evaluate(BASE + timedelta(seconds=10))

        stop_at = BASE + timedelta(seconds=20)
        self.set_values(dc_power=0, dc_current=0, vmax=3.50, vmin=3.40)
        self.analyzer.evaluate(stop_at)
        self.analyzer.evaluate(stop_at + timedelta(seconds=30))

        self.set_values(dc_power=-100, dc_current=-2)
        self.analyzer.evaluate(stop_at + timedelta(seconds=70))
        self.set_values(dc_power=0, dc_current=0, vmax=3.48, vmin=3.40)
        self.analyzer.evaluate(stop_at + timedelta(seconds=120))

        last = self.analyzer.status()['last_cycle']
        self.assertIsNone(last['delta_reduction_mv'])
        self.assertTrue(last['quality_json']['post_stop_nonzero_flow_seen'])
        self.assertFalse(last['quality_json']['delta_reduction_valid'])

    def test_balancing_unavailable_does_not_timeout_known_active_session(self):
        self.settings.post_charge_observation_minutes = 2
        self.begin_charge()
        self.set_values(soc=99.5, vmax=3.52, vmin=3.40)
        self.analyzer.evaluate(BASE + timedelta(seconds=10))

        stop_at = BASE + timedelta(seconds=20)
        self.set_values(dc_power=0, dc_current=0, balancing='off')
        self.analyzer.evaluate(stop_at)
        self.analyzer.evaluate(stop_at + timedelta(seconds=30))
        self.analyzer.evaluate(stop_at + timedelta(seconds=60))

        self.set_values(balancing='on')
        self.analyzer.evaluate(stop_at + timedelta(seconds=70))
        self.set_values(balancing='unavailable')
        self.analyzer.evaluate(stop_at + timedelta(seconds=130))
        self.assertIsNotNone(self.analyzer.current_cycle_id)
        self.assertTrue(self.analyzer.balancing_signal_unknown_seen)

        self.set_values(balancing='off')
        self.analyzer.evaluate(stop_at + timedelta(seconds=140))
        self.assertIsNone(self.analyzer.current_cycle_id)

    def test_balancing_only_cycle_ends_when_flag_turns_off(self):
        self.set_values(
            soc=100,
            vmax=3.55,
            vmin=3.42,
            battery_voltage=55.0,
            dc_power=0,
            dc_current=0,
            balancing='on',
        )
        self.analyzer.evaluate(BASE)
        cycle_id = self.analyzer.current_cycle_id
        self.assertIsNotNone(cycle_id)
        self.set_values(balancing='off')
        self.analyzer.evaluate(BASE + timedelta(minutes=10))
        self.assertIsNone(self.analyzer.current_cycle_id)
        last = self.analyzer.status()['last_cycle']
        self.assertEqual(last['id'], cycle_id)
        self.assertEqual(last['end_reason'], 'balancing_only_cycle_end')

    def test_transient_dc_signal_conflict_is_not_persisted_as_quality_failure(self):
        self.begin_charge()
        self.set_values(dc_power=100, dc_current=-2)
        self.analyzer.evaluate(BASE + timedelta(seconds=10))
        self.assertFalse(self.analyzer.signal_conflict_seen)

        self.set_values(dc_current=2)
        self.analyzer.evaluate(BASE + timedelta(seconds=12))
        self.assertFalse(self.analyzer.signal_conflict_seen)

    def test_stable_dc_signal_conflict_is_flagged(self):
        self.begin_charge()
        self.set_values(dc_power=100, dc_current=-2)
        self.analyzer.evaluate(BASE + timedelta(seconds=10))
        self.analyzer.evaluate(BASE + timedelta(seconds=15))
        self.assertTrue(self.analyzer.signal_conflict_seen)

    def test_transient_balancing_nonzero_flow_is_not_flagged(self):
        self.begin_charge()
        self.set_values(balancing='on')
        self.analyzer.evaluate(BASE + timedelta(seconds=10))
        self.assertFalse(self.analyzer.balancing_nonzero_flow_seen)

        self.set_values(dc_power=0, dc_current=0)
        self.analyzer.evaluate(BASE + timedelta(seconds=12))
        self.assertFalse(self.analyzer.balancing_nonzero_flow_seen)

    def test_balancing_with_stable_series_current_is_flagged(self):
        self.begin_charge()
        self.set_values(balancing='on')
        self.analyzer.evaluate(BASE + timedelta(seconds=10))
        self.analyzer.evaluate(BASE + timedelta(seconds=15))
        self.assertTrue(self.analyzer.balancing_nonzero_flow_seen)

    def test_v010_database_is_forward_migrated(self):
        import sqlite3

        legacy_path = Path(self.tmp.name) / 'legacy.db'
        conn = sqlite3.connect(legacy_path)
        conn.executescript(
            """
            CREATE TABLE cycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, ended_at TEXT,
                phase TEXT NOT NULL, top_charge_at TEXT, charge_stop_at TEXT,
                balancing_start_at TEXT, balancing_end_at TEXT, balancing_detected INTEGER NOT NULL DEFAULT 0,
                soc_start REAL, soc_charge_stop REAL, vmax_charge_stop REAL, vmin_charge_stop REAL,
                delta_charge_stop_mv REAL, vmax_end REAL, vmin_end REAL, delta_end_mv REAL,
                delta_reduction_mv REAL, max_vmax REAL, min_vmin REAL, dc_current_before_stop_a REAL,
                dc_power_before_stop_w REAL, ac_power_before_stop_w REAL, battery_temperature_at_stop_c REAL,
                internal_temperature_at_stop_c REAL, quality_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, cycle_id INTEGER NOT NULL, ts TEXT NOT NULL,
                event_type TEXT NOT NULL, phase TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT, cycle_id INTEGER NOT NULL, ts TEXT NOT NULL,
                phase TEXT NOT NULL, soc REAL, vmax REAL, vmin REAL, delta_mv REAL, dc_power_w REAL,
                dc_current_a REAL, ac_power_w REAL, ac_current_a REAL, battery_temperature_c REAL,
                internal_temperature_c REAL, balancing INTEGER, cells_json TEXT
            );
            """
        )
        conn.close()

        migrated = Database(legacy_path)
        try:
            cycle_cols = migrated._columns('cycles')
            sample_cols = migrated._columns('samples')
            self.assertIn('charge_stop_confirmed_at', cycle_cols)
            self.assertIn('ac_current_before_stop_a', cycle_cols)
            self.assertIn('analysis_temperature_at_stop_c', cycle_cols)
            self.assertIn('analysis_temperature_source', cycle_cols)
            self.assertIn('dc_current_source', cycle_cols)
            self.assertIn('battery_voltage_v', sample_cols)
            self.assertIn('plausibility_json', sample_cols)
            self.assertIn('dc_current_source', sample_cols)
            self.assertIn('analysis_temperature_c', sample_cols)
            self.assertIn('analysis_temperature_source', sample_cols)
        finally:
            migrated.close()


if __name__ == '__main__':
    unittest.main()
