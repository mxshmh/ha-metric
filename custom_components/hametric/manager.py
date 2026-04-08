"""Runtime and activation metrics manager for HA-Metric."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_entity_registry_updated_event,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_TRACKED_LIGHTS,
    CONF_UPDATE_INTERVAL_SECONDS,
    CONF_UPDATE_MODE,
    SIGNAL_METRIC_UPDATED,
    SIGNAL_SOURCE_DISCOVERED,
    UPDATE_MODE_CUSTOM,
    UPDATE_MODE_LIVE,
    UPDATE_MODE_NORMAL,
)

SAVE_DELAY_SECONDS = 1.0

KIND_BINARY = "binary"
KIND_MEDIA = "media"
KIND_MEASUREMENT = "measurement"


@dataclass
class MetricSnapshot:
    """Simple metric value holder."""

    value: float


class HAMetricManager:
    """Keep tracked entity metrics in memory and persistent storage."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store = Store(hass, 1, f"hametric_{entry.entry_id}.json")
        self._unsubs: list[Callable[[], None]] = []
        self._tracked_entities: list[str] = []
        self._data: dict[str, dict[str, Any]] = {}
        self._running_entities: set[str] = set()
        self._tick_seconds = 60
        self._last_registry_sync_minute: str | None = None

    @property
    def title(self) -> str:
        name = self.entry.data.get(CONF_NAME, self.entry.title or "HA-Metric")
        if isinstance(name, str) and name == "HAMetric":
            return "HA-Metric"
        return str(name)

    @property
    def tracked_entities(self) -> list[str]:
        return list(self._tracked_entities)

    async def async_setup(self) -> None:
        stored = await self._store.async_load() or {}
        self._data = stored.get("entities", stored.get("lights", {}))

        option_tracked = self.entry.options.get(CONF_TRACKED_LIGHTS)
        if isinstance(option_tracked, list) and option_tracked:
            configured = list(option_tracked)
        else:
            configured = list(self.entry.data.get(CONF_TRACKED_LIGHTS, []))

        update_mode = self.entry.options.get(
            CONF_UPDATE_MODE,
            self.entry.data.get(CONF_UPDATE_MODE, UPDATE_MODE_NORMAL),
        )
        configured_interval = int(
            self.entry.options.get(
                CONF_UPDATE_INTERVAL_SECONDS,
                self.entry.data.get(CONF_UPDATE_INTERVAL_SECONDS, 60),
            )
        )
        if update_mode == UPDATE_MODE_LIVE:
            self._tick_seconds = 1
        elif update_mode == UPDATE_MODE_CUSTOM:
            self._tick_seconds = max(1, configured_interval)
        else:
            self._tick_seconds = 60

        if not configured and self._data:
            configured = list(self._data.keys())

        entity_registry = er.async_get(self.hass)
        supported = [e for e in configured if self._determine_kind(e) is not None]
        existing = [e for e in supported if self._is_trackable_registry_entity(entity_registry, e)]
        self._tracked_entities = existing

        current_options = dict(self.entry.options)
        current_data = dict(self.entry.data)
        options_changed = current_options.get(CONF_TRACKED_LIGHTS, supported) != existing
        data_changed = current_data.get(CONF_TRACKED_LIGHTS, supported) != existing
        if options_changed or data_changed:
            current_options[CONF_TRACKED_LIGHTS] = existing
            current_data[CONF_TRACKED_LIGHTS] = existing
            self.hass.config_entries.async_update_entry(self.entry, data=current_data, options=current_options)

        changed = False
        now_utc = dt_util.utcnow()
        now_local = dt_util.now()
        self._last_registry_sync_minute = now_local.strftime("%Y-%m-%d %H:%M")

        stale = set(self._data) - set(self._tracked_entities)
        if stale:
            changed = True
            for entity_id in stale:
                self._data.pop(entity_id, None)
                self._running_entities.discard(entity_id)

        for entity_id in self._tracked_entities:
            kind = self._determine_kind(entity_id)
            if entity_id not in self._data:
                self._data[entity_id] = self._new_entity_record(kind, now_local)
                changed = True

            if self._data[entity_id].get("kind") != kind:
                self._data[entity_id] = self._new_entity_record(kind, now_local)
                changed = True

            changed |= self._ensure_record_schema(entity_id, now_local)

            if kind == KIND_MEDIA:
                changed |= self._update_known_sources_from_state(entity_id, self.hass.states.get(entity_id))

            is_active = self._is_entity_active(entity_id)
            running = self._is_running(entity_id)
            if running and not is_active:
                self._finalize_running_session(entity_id, now_utc)
                changed = True
            elif not running and is_active:
                self._start_running_session(
                    entity_id,
                    now_utc,
                    self._extract_media_source_key(entity_id, self.hass.states.get(entity_id)) if kind == KIND_MEDIA else None,
                )
                changed = True
            elif running:
                self._running_entities.add(entity_id)

            self._unsubs.append(
                async_track_state_change_event(self.hass, [entity_id], self._async_handle_state_change)
            )
            self._unsubs.append(
                async_track_entity_registry_updated_event(self.hass, entity_id, self._async_handle_registry_update)
            )

        self._unsubs.append(
            async_track_time_interval(self.hass, self._async_handle_tick, timedelta(seconds=self._tick_seconds))
        )

        if changed:
            self._async_schedule_save()

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save({"entities": self._data})

    def entity_name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        if state and (friendly := state.attributes.get("friendly_name")):
            return str(friendly)
        return entity_id.split(".", 1)[-1].replace("_", " ").title()

    def entity_unit(self, entity_id: str) -> str | None:
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        unit = state.attributes.get("unit_of_measurement")
        return str(unit) if isinstance(unit, str) and unit else None

    def entity_device_class(self, entity_id: str) -> str | None:
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        device_class = state.attributes.get("device_class")
        return str(device_class) if isinstance(device_class, str) and device_class else None

    def source_device_info(self, entity_id: str) -> tuple[set[tuple[str, str]], set[tuple[str, str]]] | None:
        """Return registry identifiers/connections of the source entity's device."""
        entity_registry = er.async_get(self.hass)
        reg_entry = entity_registry.entities.get(entity_id)
        if reg_entry is None or reg_entry.device_id is None:
            return None

        device_registry = dr.async_get(self.hass)
        device_entry = device_registry.devices.get(reg_entry.device_id)
        if device_entry is None:
            return None

        identifiers = set(device_entry.identifiers or set())
        connections = set(device_entry.connections or set())
        if not identifiers and not connections:
            return None
        return identifiers, connections

    def get_entity_kind(self, entity_id: str) -> str | None:
        return self._determine_kind(entity_id)

    def get_media_sources(self, entity_id: str) -> list[tuple[str, str]]:
        record = self._data.get(entity_id, {})
        sources = record.get("sources", {})
        if not isinstance(sources, dict):
            return []
        return sorted(sources.items(), key=lambda item: item[1].lower())

    def get_metric(self, entity_id: str, metric_type: str, source_key: str | None = None) -> MetricSnapshot:
        record = self._data.get(entity_id)
        if record is None:
            return MetricSnapshot(value=0)

        now_utc = dt_util.utcnow()

        if metric_type == "activations":
            return MetricSnapshot(value=float(self._read_counter(record.get("activations"))))

        if metric_type == "runtime_source":
            value = float(record.get("source_runtime_seconds", {}).get(source_key or "", 0))
            if self._is_running(entity_id) and record.get("active_source_key") == source_key:
                value += float(self._running_extra_seconds(entity_id, now_utc))
            return MetricSnapshot(value=value)

        if metric_type == "runtime":
            value = float(self._read_counter(record.get("runtime_seconds")))
            if self._is_running(entity_id):
                value += float(self._running_extra_seconds(entity_id, now_utc))
            return MetricSnapshot(value=value)

        if metric_type == "avg_runtime_per_activation":
            activations = int(self._read_counter(record.get("activations")))
            if activations <= 0:
                return MetricSnapshot(value=0.0)
            runtime = float(self._read_counter(record.get("runtime_seconds")))
            if self._is_running(entity_id):
                runtime += float(self._running_extra_seconds(entity_id, now_utc))
            return MetricSnapshot(value=runtime / float(activations))

        measurement = record.get("measurement", {})
        if metric_type == "minimum":
            return MetricSnapshot(value=float(measurement.get("min", 0.0)))
        if metric_type == "maximum":
            return MetricSnapshot(value=float(measurement.get("max", 0.0)))
        if metric_type == "average":
            count = int(measurement.get("count", 0))
            if count <= 0:
                return MetricSnapshot(value=0.0)
            return MetricSnapshot(value=float(measurement.get("sum", 0.0)) / float(count))
        if metric_type == "samples":
            return MetricSnapshot(value=float(int(measurement.get("count", 0))))
        if metric_type == "samples_per_hour":
            self._roll_measurement_hour(measurement, dt_util.now())
            return MetricSnapshot(value=float(int(measurement.get("hour_count", 0))))
        if metric_type == "avg_samples_per_hour":
            count = int(measurement.get("count", 0))
            if count <= 0:
                return MetricSnapshot(value=0.0)
            first_sample_at = self._parse_started_at(measurement.get("first_sample_at"), now_utc)
            elapsed_seconds = max(1, int((now_utc - first_sample_at).total_seconds()))
            elapsed_hours = max(1.0, float(elapsed_seconds) / 3600.0)
            return MetricSnapshot(value=float(count) / elapsed_hours)

        return MetricSnapshot(value=0)

    @callback
    async def _async_handle_state_change(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        if not isinstance(entity_id, str) or entity_id not in self._data:
            return

        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if new_state is None:
            if self._prune_removed_entities():
                self._async_schedule_save()
                async_dispatcher_send(self.hass, SIGNAL_METRIC_UPDATED, None, "all")
            return

        kind = self._determine_kind(entity_id)
        now_utc = dt_util.utcnow()
        now_local = dt_util.now()
        changed = False

        if kind == KIND_MEDIA:
            changed |= self._update_known_sources_from_state(entity_id, new_state)
            old_active = self._is_media_active_state(old_state.state) if old_state is not None else False
            new_active = self._is_media_active_state(new_state.state)
            old_source_key = self._extract_media_source_key(entity_id, old_state)
            new_source_key = self._extract_media_source_key(entity_id, new_state)

            if old_active and new_active and old_source_key != new_source_key:
                self._finalize_running_session(entity_id, now_utc)
                self._start_running_session(entity_id, now_utc, new_source_key)
                changed = True
                async_dispatcher_send(self.hass, SIGNAL_METRIC_UPDATED, entity_id, "all")
            elif old_state is not None and (not old_active) and new_active:
                self._increment_activation(entity_id)
                self._start_running_session(entity_id, now_utc, new_source_key)
                changed = True
                async_dispatcher_send(self.hass, SIGNAL_METRIC_UPDATED, entity_id, "all")
            elif old_active and (not new_active):
                self._finalize_running_session(entity_id, now_utc)
                changed = True
                async_dispatcher_send(self.hass, SIGNAL_METRIC_UPDATED, entity_id, "all")
            elif old_state is None and new_active and (not self._is_running(entity_id)):
                self._start_running_session(entity_id, now_utc, new_source_key)
                changed = True
                async_dispatcher_send(self.hass, SIGNAL_METRIC_UPDATED, entity_id, "runtime")

        elif kind == KIND_BINARY:
            old_is_on = old_state is not None and old_state.state == "on"
            new_is_on = new_state.state == "on"

            if (not old_is_on) and new_is_on:
                if old_state is not None and old_state.state == "off":
                    self._increment_activation(entity_id)
                self._start_running_session(entity_id, now_utc, None)
                changed = True
                async_dispatcher_send(self.hass, SIGNAL_METRIC_UPDATED, entity_id, "all")

            if old_is_on and (not new_is_on):
                self._finalize_running_session(entity_id, now_utc)
                changed = True
                async_dispatcher_send(self.hass, SIGNAL_METRIC_UPDATED, entity_id, "all")

        elif kind == KIND_MEASUREMENT:
            numeric = self._parse_numeric_state(new_state.state)
            if numeric is not None:
                self._update_measurement(entity_id, numeric, now_local)
                changed = True
                async_dispatcher_send(self.hass, SIGNAL_METRIC_UPDATED, entity_id, "all")

        if changed:
            self._async_schedule_save()

    @callback
    async def _async_handle_tick(self, now: datetime) -> None:
        now_local = dt_util.as_local(now)
        minute_key = now_local.strftime("%Y-%m-%d %H:%M")
        if minute_key != self._last_registry_sync_minute:
            self._last_registry_sync_minute = minute_key
            if self._prune_removed_entities():
                self._async_schedule_save()
                async_dispatcher_send(self.hass, SIGNAL_METRIC_UPDATED, None, "all")

        for entity_id in self._running_entities:
            async_dispatcher_send(self.hass, SIGNAL_METRIC_UPDATED, entity_id, "runtime")

        rolled_any = False
        for entity_id in self._tracked_entities:
            record = self._data.get(entity_id)
            if not record or record.get("kind") != KIND_MEASUREMENT:
                continue
            measurement = record.get("measurement", {})
            if self._roll_measurement_hour(measurement, now_local):
                rolled_any = True
                async_dispatcher_send(self.hass, SIGNAL_METRIC_UPDATED, entity_id, "all")

        if rolled_any:
            self._async_schedule_save()

    @callback
    async def _async_handle_registry_update(self, event: Event) -> None:
        """Prune removed/disabled entities immediately after registry updates."""
        action = event.data.get("action")
        if action not in {"remove", "update"}:
            return
        if self._prune_removed_entities():
            self._async_schedule_save()
            async_dispatcher_send(self.hass, SIGNAL_METRIC_UPDATED, None, "all")

    def _new_entity_record(self, kind: str | None, now_local: datetime) -> dict[str, Any]:
        if kind == KIND_MEDIA:
            return {
                "kind": KIND_MEDIA,
                "activations": {"alltime": 0},
                "runtime_seconds": {"alltime": 0},
                "running": False,
                "started_at": None,
                "active_source_key": None,
                "source_runtime_seconds": {},
                "sources": {},
            }

        if kind == KIND_MEASUREMENT:
            return {
                "kind": KIND_MEASUREMENT,
                "measurement": {
                    "count": 0,
                    "sum": 0.0,
                    "min": 0.0,
                    "max": 0.0,
                    "has_value": False,
                    "first_sample_at": None,
                    "hour_key": self._hour_key(now_local),
                    "hour_count": 0,
                },
            }

        return {
            "kind": KIND_BINARY,
            "activations": {"alltime": 0},
            "runtime_seconds": {"alltime": 0},
            "running": False,
            "started_at": None,
        }

    def _ensure_record_schema(self, entity_id: str, now_local: datetime) -> bool:
        record = self._data[entity_id]
        changed = False
        kind = record.get("kind")

        if kind == KIND_MEASUREMENT:
            measurement = record.get("measurement")
            if not isinstance(measurement, dict):
                record["measurement"] = {
                    "count": 0,
                    "sum": 0.0,
                    "min": 0.0,
                    "max": 0.0,
                    "has_value": False,
                    "first_sample_at": None,
                    "hour_key": self._hour_key(now_local),
                    "hour_count": 0,
                }
                changed = True
                measurement = record["measurement"]

            defaults: dict[str, Any] = {
                "count": 0,
                "sum": 0.0,
                "min": 0.0,
                "max": 0.0,
                "has_value": False,
                "first_sample_at": None,
                "hour_key": self._hour_key(now_local),
                "hour_count": 0,
            }
            for key, default in defaults.items():
                if key not in measurement:
                    measurement[key] = default
                    changed = True

            measurement["count"] = int(measurement.get("count", 0))
            measurement["sum"] = float(measurement.get("sum", 0.0))
            measurement["min"] = float(measurement.get("min", 0.0))
            measurement["max"] = float(measurement.get("max", 0.0))
            measurement["hour_count"] = int(measurement.get("hour_count", 0))
            measurement["has_value"] = bool(measurement.get("has_value", False))
            first_sample_at = measurement.get("first_sample_at")
            if first_sample_at is not None and not isinstance(first_sample_at, str):
                measurement["first_sample_at"] = None
                changed = True
            if not isinstance(measurement.get("hour_key"), str):
                measurement["hour_key"] = self._hour_key(now_local)
                changed = True

            for old_key in ("activations", "runtime_seconds", "running", "started_at", "active_source_key", "source_runtime_seconds", "sources", "last_reset"):
                if old_key in record:
                    record.pop(old_key, None)
                    changed = True
            return changed

        for field in ("activations", "runtime_seconds"):
            value = record.get(field)
            if isinstance(value, dict):
                alltime = int(value.get("alltime", 0))
                if set(value.keys()) != {"alltime"}:
                    record[field] = {"alltime": alltime}
                    changed = True
                elif value.get("alltime") != alltime:
                    value["alltime"] = alltime
                    changed = True
            else:
                record[field] = {"alltime": int(value or 0)}
                changed = True

        if "running" not in record:
            record["running"] = False
            changed = True
        if "started_at" not in record:
            record["started_at"] = None
            changed = True

        if kind == KIND_MEDIA:
            if "active_source_key" not in record:
                record["active_source_key"] = None
                changed = True
            if not isinstance(record.get("source_runtime_seconds"), dict):
                record["source_runtime_seconds"] = {}
                changed = True
            if not isinstance(record.get("sources"), dict):
                record["sources"] = {}
                changed = True

        if "last_reset" in record:
            record.pop("last_reset", None)
            changed = True

        return changed

    def _read_counter(self, value: Any) -> int:
        if isinstance(value, dict):
            return int(value.get("alltime", 0))
        return int(value or 0)

    def _increment_activation(self, entity_id: str) -> None:
        record = self._data[entity_id]
        activations = record.setdefault("activations", {"alltime": 0})
        activations["alltime"] = int(activations.get("alltime", 0)) + 1

    def _start_running_session(self, entity_id: str, now_utc: datetime, source_key: str | None) -> None:
        record = self._data[entity_id]
        record["running"] = True
        record["started_at"] = now_utc.isoformat()
        if record.get("kind") == KIND_MEDIA:
            record["active_source_key"] = source_key
        self._running_entities.add(entity_id)

    def _finalize_running_session(self, entity_id: str, now_utc: datetime) -> None:
        if not self._is_running(entity_id):
            return

        record = self._data[entity_id]
        started_at = self._parse_started_at(record.get("started_at"), now_utc)
        elapsed = max(0, int((now_utc - started_at).total_seconds()))

        runtime = record.setdefault("runtime_seconds", {"alltime": 0})
        runtime["alltime"] = int(runtime.get("alltime", 0)) + elapsed

        if record.get("kind") == KIND_MEDIA:
            source_key = record.get("active_source_key")
            if isinstance(source_key, str) and source_key:
                source_runtime = record.setdefault("source_runtime_seconds", {})
                source_runtime[source_key] = int(source_runtime.get(source_key, 0)) + elapsed
            record["active_source_key"] = None

        record["running"] = False
        record["started_at"] = None
        self._running_entities.discard(entity_id)

    def _running_extra_seconds(self, entity_id: str, now_utc: datetime) -> int:
        record = self._data[entity_id]
        started_at = self._parse_started_at(record.get("started_at"), now_utc)
        return max(0, int((now_utc - started_at).total_seconds()))

    def _update_measurement(self, entity_id: str, value: float, now_local: datetime) -> None:
        record = self._data[entity_id]
        measurement = record.setdefault("measurement", {})
        self._roll_measurement_hour(measurement, now_local)

        count = int(measurement.get("count", 0)) + 1
        measurement["count"] = count
        measurement["sum"] = float(measurement.get("sum", 0.0)) + float(value)
        measurement["hour_count"] = int(measurement.get("hour_count", 0)) + 1
        if measurement.get("first_sample_at") is None:
            measurement["first_sample_at"] = dt_util.utcnow().isoformat()

        if not bool(measurement.get("has_value", False)):
            measurement["min"] = float(value)
            measurement["max"] = float(value)
            measurement["has_value"] = True
        else:
            measurement["min"] = min(float(measurement.get("min", value)), float(value))
            measurement["max"] = max(float(measurement.get("max", value)), float(value))

    def _roll_measurement_hour(self, measurement: dict[str, Any], now_local: datetime) -> bool:
        current_key = self._hour_key(now_local)
        existing_key = measurement.get("hour_key")
        if existing_key == current_key:
            return False

        measurement["hour_key"] = current_key
        measurement["hour_count"] = 0
        return True

    def _hour_key(self, now_local: datetime) -> str:
        return now_local.strftime("%Y-%m-%d %H")

    def _parse_started_at(self, started_at: Any, fallback_now_utc: datetime) -> datetime:
        if not isinstance(started_at, str):
            return fallback_now_utc
        parsed = dt_util.parse_datetime(started_at)
        if parsed is None:
            return fallback_now_utc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _parse_numeric_state(self, state_value: Any) -> float | None:
        if not isinstance(state_value, str):
            return None
        text = state_value.strip()
        if not text or text in {"unknown", "unavailable", "none", "None"}:
            return None
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    def _is_measurement_sensor_entity(self, entity_id: str) -> bool:
        if entity_id.startswith(("sensor.ha_metric_", "sensor.hametric_")):
            return False

        state = self.hass.states.get(entity_id)
        if state is None:
            return False

        state_class = state.attributes.get("state_class")
        return isinstance(state_class, str) and state_class == "measurement"

    def _is_entity_active(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        kind = self._determine_kind(entity_id)
        if kind == KIND_MEDIA:
            return self._is_media_active_state(state.state)
        return state.state == "on"

    def _is_media_active_state(self, state: str) -> bool:
        return state not in {"off", "standby", "unknown", "unavailable"}

    def _is_running(self, entity_id: str) -> bool:
        return bool(self._data.get(entity_id, {}).get("running"))

    def _determine_kind(self, entity_id: str) -> str | None:
        if entity_id.startswith("media_player."):
            return KIND_MEDIA
        if entity_id.startswith(("light.", "switch.")):
            return KIND_BINARY
        if entity_id.startswith("binary_sensor.") and self._is_motion_binary_sensor_entity(entity_id):
            return KIND_BINARY
        if entity_id.startswith("sensor."):
            stored_kind = self._data.get(entity_id, {}).get("kind")
            if stored_kind == KIND_MEASUREMENT:
                return KIND_MEASUREMENT
            if self._is_measurement_sensor_entity(entity_id):
                return KIND_MEASUREMENT
        return None

    def _is_motion_binary_sensor_entity(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        device_class = state.attributes.get("device_class")
        if isinstance(device_class, str) and device_class in {"motion", "occupancy", "presence"}:
            return True
        lowered = entity_id.lower()
        return any(token in lowered for token in ("motion", "occupancy", "presence", "bewegung"))

    def _update_known_sources_from_state(self, entity_id: str, state: Any) -> bool:
        if state is None:
            return False

        changed = False
        source_list = state.attributes.get("source_list") or []
        if isinstance(source_list, list):
            for source in source_list:
                if source is None:
                    continue
                _, added = self._ensure_source(entity_id, str(source))
                if added:
                    changed = True

        current_source = self._extract_media_source_label(state)
        if current_source:
            _, added = self._ensure_source(entity_id, current_source)
            if added:
                changed = True
        return changed

    def _extract_media_source_label(self, state: Any) -> str | None:
        if state is None:
            return None
        attrs = state.attributes
        source = attrs.get("source")
        if isinstance(source, str) and source.strip():
            return source.strip()
        app_name = attrs.get("app_name")
        if isinstance(app_name, str) and app_name.strip():
            return app_name.strip()
        return None

    def _extract_media_source_key(self, entity_id: str, state: Any) -> str | None:
        label = self._extract_media_source_label(state)
        if not label:
            return None
        key, _ = self._ensure_source(entity_id, label)
        return key

    def _ensure_source(self, entity_id: str, label: str) -> tuple[str, bool]:
        record = self._data[entity_id]
        sources = record.setdefault("sources", {})
        source_runtime = record.setdefault("source_runtime_seconds", {})

        for key, existing_label in sources.items():
            if existing_label == label:
                source_runtime.setdefault(key, 0)
                return key, False

        base = self._slugify(label)
        key = base
        suffix = 2
        while key in sources:
            key = f"{base}_{suffix}"
            suffix += 1

        sources[key] = label
        source_runtime[key] = int(source_runtime.get(key, 0))
        async_dispatcher_send(self.hass, SIGNAL_SOURCE_DISCOVERED, entity_id, key)
        return key, True

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return slug or "source"

    def _prune_removed_entities(self) -> bool:
        """Drop tracked entities that no longer exist in the entity registry."""
        entity_registry = er.async_get(self.hass)
        existing = [e for e in self._tracked_entities if self._is_trackable_registry_entity(entity_registry, e)]
        if existing == self._tracked_entities:
            return False

        removed = set(self._tracked_entities) - set(existing)
        self._tracked_entities = existing
        for entity_id in removed:
            self._data.pop(entity_id, None)
            self._running_entities.discard(entity_id)

        current_options = dict(self.entry.options)
        current_data = dict(self.entry.data)
        options_changed = current_options.get(CONF_TRACKED_LIGHTS) != existing
        data_changed = current_data.get(CONF_TRACKED_LIGHTS) != existing
        if options_changed or data_changed:
            current_options[CONF_TRACKED_LIGHTS] = existing
            current_data[CONF_TRACKED_LIGHTS] = existing
            self.hass.config_entries.async_update_entry(self.entry, data=current_data, options=current_options)

        return True

    def _is_trackable_registry_entity(self, entity_registry: er.EntityRegistry, entity_id: str) -> bool:
        """Return true if entity still exists and should stay tracked."""
        reg_entry = entity_registry.entities.get(entity_id)
        if reg_entry is None:
            return False
        if reg_entry.disabled_by is not None:
            return False
        return self._determine_kind(entity_id) is not None

    @callback
    def _async_schedule_save(self) -> None:
        self._store.async_delay_save(lambda: {"entities": self._data}, SAVE_DELAY_SECONDS)
