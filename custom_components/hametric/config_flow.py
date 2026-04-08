"""Config flow for HAMetric."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_ASSIGNMENT,
    CONF_ENTITY_CATEGORY_MODE,
    CONF_TRACKED_LIGHTS,
    CONF_UPDATE_INTERVAL_SECONDS,
    CONF_UPDATE_MODE,
    DEVICE_ASSIGNMENT_SEPARATE,
    DEVICE_ASSIGNMENT_SOURCE,
    DOMAIN,
    ENTITY_CATEGORY_DIAGNOSTIC,
    ENTITY_CATEGORY_SENSOR,
    UPDATE_MODE_CUSTOM,
    UPDATE_MODE_LIVE,
    UPDATE_MODE_NORMAL,
)


class HAMetricConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HAMetric."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        self._pending_data: dict = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return HAMetricOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        supported_entities = _build_supported_entities(self.hass)
        default_lights: list[str] = []

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="HA-Metric"): str,
                vol.Required(CONF_TRACKED_LIGHTS, default=default_lights): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["light", "switch", "media_player", "sensor", "binary_sensor"],
                        include_entities=supported_entities,
                        multiple=True,
                    )
                ),
                vol.Required(CONF_DEVICE_ASSIGNMENT, default=DEVICE_ASSIGNMENT_SEPARATE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=DEVICE_ASSIGNMENT_SEPARATE, label="Create separate HA-Metric device"),
                            selector.SelectOptionDict(value=DEVICE_ASSIGNMENT_SOURCE, label="Attach to source device"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_ENTITY_CATEGORY_MODE, default=ENTITY_CATEGORY_SENSOR): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=ENTITY_CATEGORY_SENSOR, label="Show as sensors"),
                            selector.SelectOptionDict(value=ENTITY_CATEGORY_DIAGNOSTIC, label="Show as diagnostics"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_UPDATE_MODE, default=UPDATE_MODE_NORMAL): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=UPDATE_MODE_NORMAL, label="Normal (every minute)"),
                            selector.SelectOptionDict(value=UPDATE_MODE_LIVE, label="Live (every second)"),
                            selector.SelectOptionDict(value=UPDATE_MODE_CUSTOM, label="Custom"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        if user_input is not None:
            errors: dict[str, str] = {}
            selected_entities = sorted(set(user_input[CONF_TRACKED_LIGHTS]))
            if any(not _is_supported_entity(self.hass, entity_id) for entity_id in selected_entities):
                errors["base"] = "unsupported_entities"
                return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

            tracked_entities = selected_entities
            update_mode = user_input[CONF_UPDATE_MODE]
            self._pending_data = {
                CONF_NAME: user_input[CONF_NAME],
                CONF_TRACKED_LIGHTS: tracked_entities,
                CONF_DEVICE_ASSIGNMENT: user_input[CONF_DEVICE_ASSIGNMENT],
                CONF_ENTITY_CATEGORY_MODE: user_input[CONF_ENTITY_CATEGORY_MODE],
                CONF_UPDATE_MODE: update_mode,
            }
            if update_mode == UPDATE_MODE_CUSTOM:
                return await self.async_step_custom()

            interval = 1 if update_mode == UPDATE_MODE_LIVE else 60
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_TRACKED_LIGHTS: tracked_entities,
                    CONF_DEVICE_ASSIGNMENT: user_input[CONF_DEVICE_ASSIGNMENT],
                    CONF_ENTITY_CATEGORY_MODE: user_input[CONF_ENTITY_CATEGORY_MODE],
                    CONF_UPDATE_MODE: update_mode,
                    CONF_UPDATE_INTERVAL_SECONDS: interval,
                },
            )

        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def async_step_custom(self, user_input=None):
        """Collect custom update interval for custom mode."""
        data_schema = vol.Schema(
            {
                vol.Required(CONF_UPDATE_INTERVAL_SECONDS, default=60): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=3600,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                )
            }
        )

        if user_input is not None:
            interval = int(user_input[CONF_UPDATE_INTERVAL_SECONDS])
            return self.async_create_entry(
                title=self._pending_data[CONF_NAME],
                data={
                    CONF_NAME: self._pending_data[CONF_NAME],
                    CONF_TRACKED_LIGHTS: self._pending_data[CONF_TRACKED_LIGHTS],
                    CONF_DEVICE_ASSIGNMENT: self._pending_data[CONF_DEVICE_ASSIGNMENT],
                    CONF_ENTITY_CATEGORY_MODE: self._pending_data[CONF_ENTITY_CATEGORY_MODE],
                    CONF_UPDATE_MODE: self._pending_data[CONF_UPDATE_MODE],
                    CONF_UPDATE_INTERVAL_SECONDS: interval,
                },
            )

        return self.async_show_form(step_id="custom", data_schema=data_schema)


class HAMetricOptionsFlow(config_entries.OptionsFlow):
    """Handle HAMetric options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._pending_data: dict = {}

    async def async_step_init(self, user_input=None):
        """Manage tracked entities after setup."""
        supported_entities = _build_supported_entities(self.hass)
        supported_values = set(supported_entities)
        current_entities = list(
            self._config_entry.options.get(
                CONF_TRACKED_LIGHTS,
                self._config_entry.data.get(CONF_TRACKED_LIGHTS, []),
            )
        )
        current_entities = _filter_existing_supported_entities(self.hass, current_entities)
        current_entities = [entity_id for entity_id in current_entities if entity_id in supported_values]
        current_update_mode = self._config_entry.options.get(
            CONF_UPDATE_MODE,
            self._config_entry.data.get(CONF_UPDATE_MODE, UPDATE_MODE_NORMAL),
        )
        current_device_assignment = self._config_entry.options.get(
            CONF_DEVICE_ASSIGNMENT,
            self._config_entry.data.get(CONF_DEVICE_ASSIGNMENT, DEVICE_ASSIGNMENT_SEPARATE),
        )
        current_entity_category_mode = self._config_entry.options.get(
            CONF_ENTITY_CATEGORY_MODE,
            self._config_entry.data.get(CONF_ENTITY_CATEGORY_MODE, ENTITY_CATEGORY_SENSOR),
        )
        data_schema = vol.Schema(
            {
                vol.Required(CONF_TRACKED_LIGHTS, default=current_entities): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["light", "switch", "media_player", "sensor", "binary_sensor"],
                        include_entities=supported_entities,
                        multiple=True,
                    )
                ),
                vol.Required(CONF_DEVICE_ASSIGNMENT, default=current_device_assignment): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=DEVICE_ASSIGNMENT_SEPARATE, label="Create separate HA-Metric device"),
                            selector.SelectOptionDict(value=DEVICE_ASSIGNMENT_SOURCE, label="Attach to source device"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_ENTITY_CATEGORY_MODE, default=current_entity_category_mode): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=ENTITY_CATEGORY_SENSOR, label="Show as sensors"),
                            selector.SelectOptionDict(value=ENTITY_CATEGORY_DIAGNOSTIC, label="Show as diagnostics"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_UPDATE_MODE, default=current_update_mode): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=UPDATE_MODE_NORMAL, label="Normal (every minute)"),
                            selector.SelectOptionDict(value=UPDATE_MODE_LIVE, label="Live (every second)"),
                            selector.SelectOptionDict(value=UPDATE_MODE_CUSTOM, label="Custom"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        if user_input is not None:
            errors: dict[str, str] = {}
            selected_entities = sorted(set(user_input[CONF_TRACKED_LIGHTS]))
            if any(not _is_supported_entity(self.hass, entity_id) for entity_id in selected_entities):
                errors["base"] = "unsupported_entities"
                return self.async_show_form(step_id="init", data_schema=data_schema, errors=errors)

            tracked_entities = selected_entities
            update_mode = user_input[CONF_UPDATE_MODE]
            self._pending_data = {
                CONF_TRACKED_LIGHTS: tracked_entities,
                CONF_DEVICE_ASSIGNMENT: user_input[CONF_DEVICE_ASSIGNMENT],
                CONF_ENTITY_CATEGORY_MODE: user_input[CONF_ENTITY_CATEGORY_MODE],
                CONF_UPDATE_MODE: update_mode,
            }
            if update_mode == UPDATE_MODE_CUSTOM:
                return await self.async_step_custom()

            interval = 1 if update_mode == UPDATE_MODE_LIVE else 60
            return self.async_create_entry(
                title="",
                data={
                    CONF_TRACKED_LIGHTS: tracked_entities,
                    CONF_DEVICE_ASSIGNMENT: user_input[CONF_DEVICE_ASSIGNMENT],
                    CONF_ENTITY_CATEGORY_MODE: user_input[CONF_ENTITY_CATEGORY_MODE],
                    CONF_UPDATE_MODE: update_mode,
                    CONF_UPDATE_INTERVAL_SECONDS: interval,
                },
            )

        return self.async_show_form(step_id="init", data_schema=data_schema)

    async def async_step_custom(self, user_input=None):
        """Handle custom update interval in options."""
        current_update_interval = int(
            self._config_entry.options.get(
                CONF_UPDATE_INTERVAL_SECONDS,
                self._config_entry.data.get(CONF_UPDATE_INTERVAL_SECONDS, 60),
            )
        )
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_UPDATE_INTERVAL_SECONDS,
                    default=current_update_interval,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=3600,
                        step=1,
                        mode=selector.NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                )
            }
        )

        if user_input is not None:
            interval = int(user_input[CONF_UPDATE_INTERVAL_SECONDS])
            return self.async_create_entry(
                title="",
                data={
                    CONF_TRACKED_LIGHTS: self._pending_data[CONF_TRACKED_LIGHTS],
                    CONF_DEVICE_ASSIGNMENT: self._pending_data[CONF_DEVICE_ASSIGNMENT],
                    CONF_ENTITY_CATEGORY_MODE: self._pending_data[CONF_ENTITY_CATEGORY_MODE],
                    CONF_UPDATE_MODE: self._pending_data[CONF_UPDATE_MODE],
                    CONF_UPDATE_INTERVAL_SECONDS: interval,
                },
            )

        return self.async_show_form(step_id="custom", data_schema=data_schema)


def _is_supported_entity(hass, entity_id: str) -> bool:
    """Return true if entity can be tracked by HA-Metric."""
    if entity_id.startswith(("light.", "switch.", "media_player.")):
        return True

    if entity_id.startswith("binary_sensor."):
        state = hass.states.get(entity_id)
        if state is None:
            return False
        device_class = state.attributes.get("device_class")
        if isinstance(device_class, str) and device_class in {"motion", "occupancy", "presence"}:
            return True
        lowered = entity_id.lower()
        return any(token in lowered for token in ("motion", "occupancy", "presence", "bewegung"))

    if not entity_id.startswith("sensor."):
        return False

    if entity_id.startswith(("sensor.ha_metric_", "sensor.hametric_")):
        return False

    state = hass.states.get(entity_id)
    if state is None:
        return False

    state_class = state.attributes.get("state_class")
    return isinstance(state_class, str) and state_class == "measurement"


def _filter_existing_supported_entities(hass, entity_ids: list[str]) -> list[str]:
    """Return only existing, enabled, supported entities."""
    entity_registry = er.async_get(hass)
    filtered: list[str] = []
    for entity_id in entity_ids:
        reg_entry = entity_registry.entities.get(entity_id)
        if reg_entry is None:
            continue
        if reg_entry.disabled_by is not None:
            continue
        if _is_supported_entity(hass, entity_id):
            filtered.append(entity_id)
    return filtered


def _build_supported_entities(hass) -> list[str]:
    """Build entity list from currently supported entities only."""
    entity_registry = er.async_get(hass)
    supported: list[str] = []
    for entity_id, reg_entry in entity_registry.entities.items():
        if reg_entry.disabled_by is not None:
            continue
        if not _is_supported_entity(hass, entity_id):
            continue
        supported.append(entity_id)

    supported.sort()
    return supported
