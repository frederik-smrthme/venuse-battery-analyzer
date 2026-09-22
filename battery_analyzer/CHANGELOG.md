# Changelog

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
