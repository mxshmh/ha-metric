"""Sensor platform for HA-Metric."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_METRIC_UPDATED, SIGNAL_SOURCE_DISCOVERED
from .const import CONF_DEVICE_ASSIGNMENT, DEVICE_ASSIGNMENT_SOURCE
from .const import CONF_ENTITY_CATEGORY_MODE, ENTITY_CATEGORY_DIAGNOSTIC
from .manager import HAMetricManager, KIND_BINARY, KIND_MEDIA, KIND_MEASUREMENT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HA-Metric sensors from a config entry."""
    manager: HAMetricManager = hass.data[DOMAIN][entry.entry_id]
    device_assignment = entry.options.get(
        CONF_DEVICE_ASSIGNMENT,
        entry.data.get(CONF_DEVICE_ASSIGNMENT, "separate"),
    )
    entity_category_mode = entry.options.get(
        CONF_ENTITY_CATEGORY_MODE,
        entry.data.get(CONF_ENTITY_CATEGORY_MODE, "sensor"),
    )

    entities: list[HAMetricMetricSensor] = []
    expected_unique_ids: set[str] = set()
    expected_device_keys: set[str] = set()
    known_source_sensors: set[tuple[str, str]] = set()

    for entity_id in manager.tracked_entities:
        kind = manager.get_entity_kind(entity_id)
        entity_slug = entity_id.replace(".", "_")
        expected_device_keys.add(f"{entry.entry_id}_{entity_slug}")

        if kind == KIND_MEDIA:
            s1 = HAMetricMetricSensor(entry.entry_id, manager, entity_id, "activations", device_assignment=device_assignment, entity_category_mode=entity_category_mode)
            s2 = HAMetricMetricSensor(entry.entry_id, manager, entity_id, "runtime", device_assignment=device_assignment, entity_category_mode=entity_category_mode)
            s3 = HAMetricMetricSensor(entry.entry_id, manager, entity_id, "avg_runtime_per_activation", device_assignment=device_assignment, entity_category_mode=entity_category_mode)
            entities.extend([s1, s2, s3])
            expected_unique_ids.update([s1.unique_id, s2.unique_id, s3.unique_id])

            for source_key, _ in manager.get_media_sources(entity_id):
                src_sensor = HAMetricMetricSensor(
                    entry.entry_id,
                    manager,
                    entity_id,
                    "runtime_source",
                    source_key=source_key,
                    device_assignment=device_assignment,
                    entity_category_mode=entity_category_mode,
                )
                entities.append(src_sensor)
                expected_unique_ids.add(src_sensor.unique_id)
                known_source_sensors.add((entity_id, source_key))
            continue

        if kind == KIND_BINARY:
            s1 = HAMetricMetricSensor(entry.entry_id, manager, entity_id, "activations", device_assignment=device_assignment, entity_category_mode=entity_category_mode)
            s2 = HAMetricMetricSensor(entry.entry_id, manager, entity_id, "runtime", device_assignment=device_assignment, entity_category_mode=entity_category_mode)
            s3 = HAMetricMetricSensor(entry.entry_id, manager, entity_id, "avg_runtime_per_activation", device_assignment=device_assignment, entity_category_mode=entity_category_mode)
            entities.extend([s1, s2, s3])
            expected_unique_ids.update([s1.unique_id, s2.unique_id, s3.unique_id])
            continue

        if kind == KIND_MEASUREMENT:
            for metric in (
                "minimum",
                "maximum",
                "average",
                "samples",
                "samples_per_hour",
                "avg_samples_per_hour",
            ):
                sensor = HAMetricMetricSensor(
                    entry.entry_id,
                    manager,
                    entity_id,
                    metric,
                    device_assignment=device_assignment,
                    entity_category_mode=entity_category_mode,
                )
                entities.append(sensor)
                expected_unique_ids.add(sensor.unique_id)

    entity_registry = er.async_get(hass)
    for reg_entry in list(entity_registry.entities.values()):
        if reg_entry.config_entry_id != entry.entry_id:
            continue
        if reg_entry.domain != "sensor":
            continue
        if reg_entry.unique_id and reg_entry.unique_id.startswith(f"{entry.entry_id}_") and reg_entry.unique_id not in expected_unique_ids:
            entity_registry.async_remove(reg_entry.entity_id)

    device_registry = dr.async_get(hass)
    for device in list(device_registry.devices.values()):
        if entry.entry_id not in device.config_entries:
            continue
        identifiers = device.identifiers or set()
        if device_assignment == DEVICE_ASSIGNMENT_SOURCE:
            if any(domain == DOMAIN and key.startswith(f"{entry.entry_id}_") for domain, key in identifiers):
                device_registry.async_remove_device(device.id)
            continue
        for domain, key in identifiers:
            if domain != DOMAIN:
                continue
            if not key.startswith(f"{entry.entry_id}_"):
                continue
            if key in expected_device_keys:
                continue
            device_registry.async_remove_device(device.id)
            break

    if entities:
        async_add_entities(entities)

    @callback
    def _handle_source_discovered(entity_id: str, source_key: str) -> None:
        if (entity_id, source_key) in known_source_sensors:
            return
        known_source_sensors.add((entity_id, source_key))
        source_sensor = HAMetricMetricSensor(
            entry.entry_id,
            manager,
            entity_id,
            "runtime_source",
            source_key=source_key,
            device_assignment=device_assignment,
            entity_category_mode=entity_category_mode,
        )
        async_add_entities([source_sensor])

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_SOURCE_DISCOVERED,
            _handle_source_discovered,
        )
    )


class HAMetricMetricSensor(SensorEntity):
    """HA-Metric metric sensor."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        entry_id: str,
        manager: HAMetricManager,
        entity_id: str,
        metric_type: str,
        source_key: str | None = None,
        device_assignment: str = "separate",
        entity_category_mode: str = "sensor",
    ) -> None:
        self._entry_id = entry_id
        self._manager = manager
        self._entity_id = entity_id
        self._metric_type = metric_type
        self._source_key = source_key
        self._device_assignment = device_assignment
        self._entity_category_mode = entity_category_mode
        self._is_measurement_stat_metric = metric_type in ("minimum", "maximum", "average")

        if self._entity_category_mode == ENTITY_CATEGORY_DIAGNOSTIC:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        else:
            self._attr_entity_category = None

        entity_slug = entity_id.replace(".", "_")

        if metric_type == "activations":
            self._attr_translation_key = "activations"
            self._attr_icon = "mdi:counter"
            self._attr_native_unit_of_measurement = "x"
            self._attr_unique_id = f"{entry_id}_{entity_slug}_activations"

        elif metric_type in ("runtime", "runtime_source"):
            self._attr_translation_placeholders = {}
            if metric_type == "runtime_source" and source_key is not None:
                source_label = dict(manager.get_media_sources(entity_id)).get(source_key, source_key)
                self._attr_translation_key = "runtime_source"
                self._attr_translation_placeholders = {"source": source_label}
            else:
                self._attr_translation_key = "runtime"
            self._attr_icon = "mdi:timer-outline"
            self._attr_native_unit_of_measurement = "h"
            self._attr_device_class = SensorDeviceClass.DURATION
            self._attr_suggested_display_precision = 5
            if metric_type == "runtime_source" and source_key is not None:
                self._attr_unique_id = f"{entry_id}_{entity_slug}_runtime_source_{source_key}"
            else:
                self._attr_unique_id = f"{entry_id}_{entity_slug}_runtime"

        elif metric_type == "avg_runtime_per_activation":
            self._attr_translation_key = "avg_runtime_per_activation"
            self._attr_icon = "mdi:chart-timeline-variant"
            self._attr_native_unit_of_measurement = "h"
            self._attr_device_class = SensorDeviceClass.DURATION
            self._attr_suggested_display_precision = 3
            self._attr_unique_id = f"{entry_id}_{entity_slug}_avg_runtime_per_activation"

        elif metric_type == "minimum":
            self._attr_translation_key = "minimum"
            self._attr_icon = "mdi:arrow-down-bold-outline"
            self._attr_unique_id = f"{entry_id}_{entity_slug}_minimum"
            self._attr_native_unit_of_measurement = manager.entity_unit(entity_id)
            device_class = manager.entity_device_class(entity_id)
            if device_class:
                self._attr_device_class = device_class
            self._attr_suggested_display_precision = 2

        elif metric_type == "maximum":
            self._attr_translation_key = "maximum"
            self._attr_icon = "mdi:arrow-up-bold-outline"
            self._attr_unique_id = f"{entry_id}_{entity_slug}_maximum"
            self._attr_native_unit_of_measurement = manager.entity_unit(entity_id)
            device_class = manager.entity_device_class(entity_id)
            if device_class:
                self._attr_device_class = device_class
            self._attr_suggested_display_precision = 2

        elif metric_type == "average":
            self._attr_translation_key = "average"
            self._attr_icon = "mdi:chart-line"
            self._attr_unique_id = f"{entry_id}_{entity_slug}_average"
            self._attr_native_unit_of_measurement = manager.entity_unit(entity_id)
            device_class = manager.entity_device_class(entity_id)
            if device_class:
                self._attr_device_class = device_class
            self._attr_suggested_display_precision = 2

        elif metric_type == "samples":
            self._attr_translation_key = "samples"
            self._attr_icon = "mdi:counter"
            self._attr_native_unit_of_measurement = "x"
            self._attr_unique_id = f"{entry_id}_{entity_slug}_samples"

        elif metric_type == "samples_per_hour":
            self._attr_translation_key = "samples_per_hour"
            self._attr_icon = "mdi:speedometer"
            self._attr_native_unit_of_measurement = "x/h"
            self._attr_unique_id = f"{entry_id}_{entity_slug}_samples_per_hour"

        elif metric_type == "avg_samples_per_hour":
            self._attr_translation_key = "avg_samples_per_hour"
            self._attr_icon = "mdi:chart-bell-curve"
            self._attr_native_unit_of_measurement = "x/h"
            self._attr_suggested_display_precision = 2
            self._attr_unique_id = f"{entry_id}_{entity_slug}_avg_samples_per_hour"

        entity_name = manager.entity_name(entity_id)
        if device_assignment == DEVICE_ASSIGNMENT_SOURCE:
            source_info = manager.source_device_info(entity_id)
        else:
            source_info = None

        if source_info is not None:
            identifiers, connections = source_info
            kwargs = {}
            if identifiers:
                kwargs["identifiers"] = identifiers
            if connections:
                kwargs["connections"] = connections
            self._attr_device_info = DeviceInfo(**kwargs)
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{entry_id}_{entity_slug}")},
                name=f"{manager.title} {entity_name}",
                manufacturer="HA-Metric",
                model="Entity Metrics",
            )

    @property
    def native_value(self) -> int | float:
        snapshot = self._manager.get_metric(
            self._entity_id,
            self._metric_type,
            self._source_key,
        )
        if self._metric_type in ("activations", "samples", "samples_per_hour"):
            return int(snapshot.value)
        if self._metric_type in ("runtime", "runtime_source", "avg_runtime_per_activation"):
            return snapshot.value / 3600
        return snapshot.value

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._is_measurement_stat_metric:
            self._refresh_measurement_meta()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_METRIC_UPDATED,
                self._handle_metric_update,
            )
        )

    @callback
    def _handle_metric_update(self, changed_entity: str | None, kind: str) -> None:
        if changed_entity is not None and changed_entity != self._entity_id:
            return

        if self._metric_type in ("runtime", "runtime_source", "avg_runtime_per_activation"):
            if kind in ("runtime", "all"):
                self.async_write_ha_state()
            return

        if kind == "all":
            if self._is_measurement_stat_metric:
                self._refresh_measurement_meta()
            self.async_write_ha_state()

    def _refresh_measurement_meta(self) -> None:
        """Keep unit/device class aligned with the source sensor."""
        unit = self._manager.entity_unit(self._entity_id)
        self._attr_native_unit_of_measurement = unit
        device_class = self._manager.entity_device_class(self._entity_id)
        if device_class:
            self._attr_device_class = device_class
        else:
            self._attr_device_class = None
