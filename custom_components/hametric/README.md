# HA-Metric

HA-Metric is a custom Home Assistant integration that creates local runtime and usage metrics for selected entities.

It is designed to be:
- precise for runtime tracking (independent from long-term statistics retention),
- lightweight,
- easy to configure from the UI.

## Features

### Binary-style entities (light, switch, motion binary_sensor)
For each tracked entity, HA-Metric provides:
- `Activations`
- `Runtime`
- `Average runtime per activation`

### Media players
For each tracked media player, HA-Metric provides:
- `Activations`
- `Runtime`
- `Average runtime per activation`
- `Runtime Source <source>` (per discovered source/app/input)

### Measurement sensors (`state_class: measurement`)
For each tracked measurement sensor, HA-Metric provides:
- `Minimum`
- `Maximum`
- `Average`
- `Samples`
- `Samples this hour`
- `Average samples per hour`

## Supported entity types

- `light`
- `switch`
- `media_player`
- `binary_sensor` (motion/occupancy/presence)
- `sensor` with `state_class = measurement`

## Configuration

Add the integration in Home Assistant UI and select entities to track.

### Options

- **Device assignment**
  - Create separate HA-Metric devices
  - Attach metrics to source devices

- **Display area**
  - Show as normal sensors
  - Show as diagnostic entities

- **Update mode**
  - `Normal` (every minute)
  - `Live` (every second)
  - `Custom` (user-defined seconds)

> Update mode changes sensor refresh frequency in the UI.
> Internal runtime accounting remains second-accurate.

## Persistence and accuracy

- Metrics are stored in Home Assistant storage.
- Runtime counters are based on state transitions and elapsed time, not recorder history.
- Final runtime is committed when an entity turns off.

## Localization

- English and German translations are included.
- Friendly names are localized by Home Assistant language.

## Notes

- HA-Metric excludes its own generated sensors from re-selection.
- Motion binary sensors are detected by device class (`motion`, `occupancy`, `presence`) with a compatibility fallback by entity name tokens.

## Helper-based periods (daily/weekly/monthly/yearly)

HA-Metric currently exposes all metrics as all-time values.
If period-based values are required, create Home Assistant helpers on top of HA-Metric sensors.

Recommended:
- Create `Utility Meter` helpers for daily, weekly, monthly, and yearly cycles.
- Use HA-Metric entities (runtime/activations) as the source entities.
- Keep HA-Metric as raw all-time data and let helpers handle period windows.

## Development status

Early release. Feedback and edge-case reports are welcome.

## License

MIT
