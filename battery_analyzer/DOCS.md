# Marstek Battery Analyzer

The app listens to Home Assistant state changes over the Supervisor WebSocket proxy.
It starts detailed cycle logging at the configured SOC threshold and stores semantic cycle data in `/data/analyzer.db`.

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
