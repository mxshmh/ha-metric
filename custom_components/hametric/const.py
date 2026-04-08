"""Constants for HAMetric."""

from __future__ import annotations

DOMAIN = "hametric"

CONF_TRACKED_LIGHTS = "tracked_lights"
CONF_UPDATE_MODE = "update_mode"
CONF_UPDATE_INTERVAL_SECONDS = "update_interval_seconds"
CONF_DEVICE_ASSIGNMENT = "device_assignment"
CONF_ENTITY_CATEGORY_MODE = "entity_category_mode"

SIGNAL_METRIC_UPDATED = f"{DOMAIN}_metric_updated"
SIGNAL_SOURCE_DISCOVERED = f"{DOMAIN}_source_discovered"

UPDATE_MODE_LIVE = "live"
UPDATE_MODE_NORMAL = "normal"
UPDATE_MODE_CUSTOM = "custom"

DEVICE_ASSIGNMENT_SEPARATE = "separate"
DEVICE_ASSIGNMENT_SOURCE = "source"

ENTITY_CATEGORY_SENSOR = "sensor"
ENTITY_CATEGORY_DIAGNOSTIC = "diagnostic"
