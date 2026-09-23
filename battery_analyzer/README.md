# Marstek Battery Analyzer

Analyzes the upper LFP charge range, charge-stop relaxation and BMS balancing behavior.

Version 0.1.4 focuses on safe read-only observation, robust charge-stop/balancing event detection and local SQLite cycle storage.
InfluxDB replay/history adapters are intentionally deferred until the local InfluxDB schema/version is inspected.


## Optional sensors

DC current, AC current and battery temperature are optional. If DC current is unavailable, the analyzer derives it from DC power divided by pack voltage and records the source as calculated. If no battery-temperature sensor exists, internal temperature is used only as an explicitly labelled analysis proxy.
