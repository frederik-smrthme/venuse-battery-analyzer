# Marstek Battery Analyzer

Analyzes the upper LFP charge range, charge-stop relaxation and BMS balancing behavior.

Version 0.1.3 focuses on safe read-only observation, robust charge-stop/balancing event detection and local SQLite cycle storage.
InfluxDB replay/history adapters are intentionally deferred until the local InfluxDB schema/version is inspected.
