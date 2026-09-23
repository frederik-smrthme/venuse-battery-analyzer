# Changelog

## 0.1.4

- Make DC current, AC current and battery-temperature entities optional.
- Derive DC current from DC power / pack voltage when no measured current sensor is available.
- Record current provenance (`measured` vs `calculated_from_power_voltage`).
- Use internal temperature only as an explicitly labelled analysis-temperature proxy when no battery temperature sensor exists.
- Persist current/temperature provenance with cycle samples and charge-stop metadata.
- Do not treat calculated DC current as an independent flow signal for charge-stop classification.
- Show cell Vmax/Vmin with 3 decimal places and improve display precision of key values.
- Separate missing required entities from missing optional entities.


## 0.1.3

- Replaced the obsolete Home Assistant `watchdog` app setting with a native Docker `HEALTHCHECK` against `/health`.
- Removed redundant `startup` and `boot` settings that only repeated Home Assistant defaults.
- Sorted integration manifest keys as required by Hassfest.
- Updated GitHub Actions to current Node 24 based checkout/setup actions and pinned Ubuntu 24.04 runners.
- Tightened configurable LFP plausibility bounds to 2.0–3.8 V for cell voltage limits.
- No battery-control behavior added; the analyzer remains read-only.

## 0.1.2

- Corrected Home Assistant manifest type to `service` and enforced a single config entry.
- Added Home Assistant app watchdog using the existing `/health` endpoint.
- Marked the app as experimental while the first live installations are being validated.
- Set the default LFP cell plausibility floor to 2.0 V while retaining configurability.
- Debounced transient DC signal conflicts caused by sequential Home Assistant entity updates.
- Debounced transient non-zero-flow observations at balancing start to avoid false quality flags.
- Updated package/version metadata consistently to 0.1.2.

## 0.1.1

- Hardened charge-stop detection and timestamping.
- Balancing is now tracked independently from charge/rest phase.
- Correct cumulative duration for multiple balancing sessions.
- Preserve tri-state balancing input (`on` / `off` / unavailable).
- Added battery-voltage acquisition and storage.
- Separate sign normalization for AC/DC current and power.
- Added LFP plausibility checks and pack-voltage consistency checks.
- Prevent false idle cycles at high SOC, including high-Vmax idle conditions.
- Distinguish current cycle from last completed cycle.
- Added restart/disconnect measurement-gap tracking.
- Added forward SQLite schema migrations.
- Added HACS-required manifest metadata and inline brand assets.
- Flagged non-zero series current during balancing/post-charge analysis.
- Close balancing-only observations cleanly when the analyzer starts mid-balancing.
- Reject non-finite sensor values (`NaN` / `Inf`).
- Store normalized AC current before charge stop in cycle summaries.
- Delta reduction is only published when the post-charge window is uncontaminated.
- Added unit tests and GitHub validation workflow.

## 0.1.0

- Initial Home Assistant app.
- Live WebSocket state listener.
- LFP top-charge state machine.
- SQLite cycle and sample persistence.
- REST API for the Home Assistant custom integration.
- Future-proof schema for individual cell voltages.
