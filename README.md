# HA-Metric

HA-Metric is a Home Assistant custom integration that provides local usage metrics for selected entities.

Status: **Stable** (`1.0.0`)

## What it tracks

- Lights, switches, motion binary sensors:
  - Activations
  - Runtime
  - Average runtime per activation
- Media players:
  - Activations
  - Runtime
  - Average runtime per activation
  - Runtime per discovered source
- Measurement sensors (`state_class: measurement`):
  - Minimum / Maximum / Average
  - Samples / Samples this hour / Average samples per hour

## Configuration options

- Device assignment:
  - Separate HA-Metric device
  - Attach to source device
- Display area:
  - Sensor
  - Diagnostic
- Update mode:
  - Normal (every minute)
  - Live (every second)
  - Custom interval

Update mode controls UI refresh frequency. Runtime accounting remains second-accurate internally.

## Installation (HACS Custom Repository)

1. In HACS, open **Custom repositories**.
2. Add this repository URL.
3. Category: **Integration**.
4. Install **HA-Metric**.
5. Restart Home Assistant.
6. Add integration via **Settings → Devices & Services**.

## Localization

- English and German translations included.
- Friendly names follow Home Assistant language.

## Notes

- Feedback and issue reports are welcome.

## Helper-based periods (daily/weekly/monthly/yearly)

HA-Metric currently exposes all metrics as all-time values.
If you want period-based values, create Home Assistant helper entities on top of HA-Metric sensors.

Recommended approach:
- Use `Utility Meter` helpers for daily, weekly, monthly, and yearly cycles.
- Source each helper from the matching HA-Metric sensor (for example runtime or activations).
- Keep HA-Metric as the single raw source and let helpers handle period resets.

This keeps the integration lightweight while still allowing per-period dashboards and automations.

## License

MIT
