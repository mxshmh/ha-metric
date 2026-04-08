# HA-Metric (Beta)

HA-Metric is a Home Assistant custom integration that provides local usage metrics for selected entities.

Status: **Beta** (`0.1.0-beta.1`)

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
  - Samples / Samples per hour / Average samples per hour

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

- This is a beta release.
- Please report edge cases before a stable `1.0.0` release.

## License

MIT
