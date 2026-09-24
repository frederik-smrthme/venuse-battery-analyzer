# Marstek Battery Analyzer

Analyzes the upper LFP charge range, charge-stop relaxation and BMS balancing behavior.

Version 0.1.5 adds clean balancing-end capture and conservative matched-Vmax delta comparison while keeping the analyzer strictly read-only.

If charging or discharging begins while the BMS balancing flag is still active, the analyzer freezes the last valid zero-series-current sample and uses that as the balancing endpoint. Delta comparisons are only considered valid when both samples are at zero series current and Vmax differs by no more than the configured tolerance (default 5 mV).
InfluxDB replay/history adapters are intentionally deferred until the local InfluxDB schema/version is inspected.


## Optional sensors

DC current, AC current and battery temperature are optional. If DC current is unavailable, the analyzer derives it from DC power divided by pack voltage and records the source as calculated. If no battery-temperature sensor exists, internal temperature is used only as an explicitly labelled analysis proxy.
