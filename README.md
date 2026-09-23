# Marstek Battery Analyzer

A local Home Assistant analyzer for **Marstek Venus E / LFP batteries**. The project observes the upper charging range, charge stop, relaxation and BMS balancing behavior and exposes the analysis as native Home Assistant entities.

> **Development status:** v0.1.4 – observation only. The analyzer does **not** write to battery control entities and does not change charging behavior.

## What it is for

The analyzer is intended to build a reliable long-term picture of battery behavior around the top of charge, including:

- cell voltage spread (`Vmax - Vmin`)
- top-charge behavior from about 97% SoC upward
- charge-stop detection
- relaxation after charging
- BMS balancing flag detection
- balancing duration and delta reduction
- AC/DC charging conditions before charge stop
- comparison of cycles with and without active balancing
- future estimation of balancing current
- future capacity / SoH analysis

The current Marstek data source provides only minimum and maximum cell voltage. The internal data model is deliberately prepared for **all 16 individual cell voltages** when these become available later.

## Architecture

```text
Marstek / OmniBattery entities
            |
            v
      Home Assistant
       |          |
       |          +----> existing InfluxDB
       |                 raw / long-term time series
       |
       +----> Marstek Battery Analyzer App
                   |
                   +---- event-driven state machine
                   +---- cycle / balancing analysis
                   +---- SQLite semantic cycle storage
                   +---- local read-only REST API
                              |
                              v
                 Home Assistant custom integration
                              |
                              v
                    native HA entities
```

No MQTT and no external server are required.

## Battery defaults

The default profile reflects the current target system:

| Parameter | Default |
|---|---:|
| Chemistry | LFP |
| Cells | 16s |
| Nominal pack voltage | 51.2 V |
| Nominal capacity | 100 Ah |
| Gross energy | 5.12 kWh |
| DoD | 88% |
| Reserve | 12% |
| Nominal usable range | 88 Ah / 4.5056 kWh |

These values are configuration data, not hard-coded assumptions inside the analysis logic.

## Current analysis states

The analyzer follows the battery through a small state machine:

```text
NORMAL
  -> OBSERVATION        SoC >= 97% while charging (or balancing already active)
  -> TOP_CHARGE         SoC >= 99% or configured high-cell threshold
  -> CHARGE_STOP / REST DC power stably near zero (plus current when directly measured)
  -> POST_CHARGE_REST   post-charge observation window
  -> CYCLE_END

BALANCING is tracked independently as an ON/OFF signal and may overlap REST or POST_CHARGE_REST.
```

Cycles without a balancing flag are intentionally retained because they provide a useful reference for natural LFP relaxation.


## v0.1.4 validation and plausibility safeguards

Before the first live test the analyzer was hardened with the following checks:

- charge stop is timestamped at the **start of the stable-zero window**, not 30 s late at confirmation time
- balancing is tracked independently from the charge/rest phase and can contain multiple ON/OFF sessions
- `unknown` / `unavailable` balancing state is not treated as `OFF`
- a high-SoC battery sitting idle — even with a high Vmax — does not create a false observation cycle
- DC current is optional; when absent it is derived from DC power / pack voltage and tagged as calculated
- directly measured DC current and DC power are cross-checked; contradictory flow directions are flagged instead of silently interpreted
- non-zero series current during balancing or after charge stop is flagged so delta-based estimates are not treated as clean measurements
- a cycle-level delta reduction is only published when the post-charge observation stayed uncontaminated by subsequent current flow
- LFP cell values below 3.0 V remain valid; the configured upper plausibility limit defaults to 3.8 V
- pack voltage is checked against the possible envelope from Vmin/Vmax and, later, against the sum of all individual cells
- battery voltage is stored explicitly for later capacity / SoH work
- internal temperature may be used as an explicitly labelled analysis-temperature proxy when no battery-temperature sensor exists
- current and temperature provenance are stored so future SoH/balancing-current estimates can distinguish measured values from proxies
- current-cycle and last-completed-cycle data are kept separate
- open cycles survive analyzer restarts and are marked with a measurement-gap flag
- Home Assistant WebSocket disconnects are recorded as measurement gaps
- SQLite schema upgrades are forward-migrated from v0.1.0

The repository also contains unit tests and GitHub validation workflows for the analyzer logic, HACS metadata and Home Assistant app configuration.

## Data storage

The project keeps the responsibilities separate:

- **Home Assistant Recorder / MariaDB**: untouched; remains Home Assistant's own recorder database.
- **InfluxDB**: existing long-term raw time-series storage.
- **Analyzer SQLite**: only semantic analyzer data such as detected cycles, phases, samples and calculated results.
- **RAM**: current state and short working buffers only.

SQLite therefore does not replace or duplicate Home Assistant's MariaDB recorder.

## Installation from GitHub

This repository can be used both as a Home Assistant App repository and as the source for the custom integration.

### 1. Install the analyzer app

In Home Assistant OS:

1. Open **Settings -> Apps**.
2. Open the repository management menu.
3. Add this repository URL:

```text
https://github.com/frederik-smrthme/venuse-battery-analyzer
```
4. Install **Marstek Battery Analyzer**.
5. Open the app configuration and map the entity IDs to your installation.
6. Start the app and check its log.

The analyzer exposes a local, read-only REST API on port **8099** by default.

### 2. Install the Home Assistant integration

#### With HACS

1. Add this repository to HACS as a custom repository of type **Integration**:

```text
https://github.com/frederik-smrthme/venuse-battery-analyzer
```
2. Install **Marstek Battery Analyzer**.
3. Restart Home Assistant.
4. Open **Settings -> Devices & services -> Add integration**.
5. Select **Marstek Battery Analyzer**.
6. Enter the analyzer API URL if auto/default access does not resolve, for example:

```text
http://<HOME_ASSISTANT_IP>:8099
```

#### Without HACS

Copy:

```text
custom_components/marstek_battery_analyzer
```

to:

```text
/config/custom_components/marstek_battery_analyzer
```

and restart Home Assistant.

## Updates

Using GitHub makes updates straightforward:

- new analyzer app versions can be published through the same Home Assistant repository
- integration updates can be delivered through HACS
- configuration and persistent analyzer data remain local on Home Assistant

No battery measurements, credentials or private installation data need to be stored in the GitHub repository.

## Entity mapping

The analyzer is designed around normalized internal signals. Actual Marstek/OmniBattery entity IDs are configured locally.

Typical inputs include:

- battery SoC
- maximum cell voltage
- minimum cell voltage
- balancing active flag
- DC battery voltage
- DC battery current
- DC battery power
- AC power
- AC current, if available
- battery / internal temperature

The sign convention of source sensors is normalized separately for DC power, DC current, AC power and AC current so later algorithms do not depend on source-specific sign conventions.

## Future 16-cell support

The internal model is not limited to `Vmin` and `Vmax`.

When individual cell voltages become available, the analyzer can be extended with:

```text
cell_01 ... cell_16
```

and calculate, among other things:

- actual highest / lowest cell number
- per-cell voltage history
- mean and median cell voltage
- standard deviation
- per-cell voltage slope
- switching of the highest cell during balancing
- comparison of the balanced cell against the median behavior of the other cells

The currently reported Marstek `Vmin` and `Vmax` can then remain as independent BMS reference values.

## Planned analysis extensions

Not yet implemented in v0.1.4:

- InfluxDB history and replay adapter
- robust slope calculation / regression over time windows
- automatic comparison of similar charge cycles
- statistical separation of relaxation and active balancing effects
- approximate balancing-current estimation with confidence/quality indicators
- individual-cell analysis
- usable capacity estimation
- SoH estimation using the 5.12 kWh gross / 100 Ah nominal reference and the configured 88% DoD operating window

## Resource philosophy

The analyzer is intentionally event-driven and lightweight for a Raspberry Pi 4 installation:

- no constant high-frequency polling
- no permanent full-database scans
- intensive observation only in relevant top-charge windows
- targeted historical queries when required
- small local SQLite database for semantic results only

## Safety

Version 0.1.4 is strictly **read-only / observation-only**. It does not control charging, discharging, force mode, power limits or BMS settings.

## Repository structure

```text
battery_analyzer/                         Home Assistant analyzer app
custom_components/marstek_battery_analyzer/  Native HA integration
repository.yaml                           Home Assistant repository metadata
hacs.json                                 HACS metadata
README.md                                 This file
```

## License

See [LICENSE](LICENSE).
