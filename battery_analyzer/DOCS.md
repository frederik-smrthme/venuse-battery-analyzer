# Marstek Battery Analyzer

The app listens to Home Assistant state changes over the Supervisor WebSocket proxy.
It starts a cycle only when the upper SOC range is reached **and** active charging or balancing is present. A high cell voltage alone never starts a new cycle, preventing an already-full idle battery from creating a long false session. Semantic cycle data is stored in `/data/analyzer.db`.

## Battery defaults

- Chemistry: LFP
- Cells: 16 series
- Gross energy: 5.12 kWh
- Nominal pack voltage: 51.2 V
- Nominal capacity: 100 Ah
- DoD: 88 percent
- Nominal usable energy: 4.5056 kWh

## API

The app exposes a read-only JSON API on port 8099 by default:

- `/health`
- `/api/v1/status`
- `/api/v1/cycles`
- `/api/v1/cycles/{id}`

## Notes

The app does not alter charging or battery control settings. It is observation-only.


## Important v0.1.3 behavior

- Charge-stop time is the start of the stable-zero window; confirmation occurs after the configured stability interval.
- Balancing is an independent signal and may span multiple ON/OFF sessions in one cycle.
- An unavailable balancing entity is treated as unknown, never as an OFF transition.
- DC current and power direction conflicts are flagged in cycle quality data.
- Cell-voltage plausibility defaults to 2.0-3.8 V; values below 3.0 V are valid LFP measurements.
- The API remains read-only.
