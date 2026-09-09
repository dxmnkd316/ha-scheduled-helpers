"""Config flow for Scheduled Helpers.

Modeled directly on core `min_max`/`template`: a `SchemaConfigFlowHandler`
subclass with a type-selection menu step, one combined form per helper
type (type-specific fields + shared schedule/device/category fields in a
single screen, matching how core `template` merges what SPEC §4 describes
as separate "steps" into one form per type), and an `options_flow` reusing
those same per-type schemas for post-creation editing (`options_flow_reloads
= True` applies edits immediately -- see SPEC §4).
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping
from functools import partial
from typing import Any, cast, override

import voluptuous as vol

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import (
    CONF_STATE_CLASS,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.components.sensor.const import DEVICE_CLASS_UNITS
from homeassistant.const import (
    CONF_DEVICE_CLASS,
    CONF_DEVICE_ID,
    CONF_ENTITY_CATEGORY,
    CONF_NAME,
    CONF_UNIT_OF_MEASUREMENT,
    EntityCategory,
)
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
    SchemaFlowMenuStep,
)

from .const import (
    CONF_AGGREGATION,
    CONF_AVAILABILITY_TEMPLATE,
    CONF_HELPER_TYPE,
    CONF_HOUR,
    CONF_MINUTE,
    CONF_SECOND,
    CONF_SOURCES,
    CONF_STATE_TEMPLATE,
    DEFAULT_HOUR,
    DEFAULT_MINUTE,
    DEFAULT_SECOND,
    DOMAIN,
    AggregationFunction,
    HelperType,
)
from .schedule import validate_schedule_pattern

_HELPER_TYPES = [HelperType.COMBINE, HelperType.TEMPLATE, HelperType.TEMPLATE_BINARY]


def _schedule_fields() -> dict[vol.Marker, Any]:
    """Schedule pattern fields shared by every helper type (SPEC §3).

    Plain ``TextSelector``s only -- format validation (``*``/int/``/n``)
    and the "not all wildcard" cross-field guard both happen in
    ``schedule.validate_schedule_pattern`` via this flow's
    ``validate_user_input``, not here. See schedule.py's module docstring:
    wrapping a per-field validator function into the schema itself (e.g.
    ``vol.All(TextSelector(), <function>)``) breaks the config-flow HTTP
    endpoint's JSON schema serialization on a real running instance.
    """
    return {
        vol.Optional(CONF_HOUR, default=DEFAULT_HOUR): selector.TextSelector(),
        vol.Optional(CONF_MINUTE, default=DEFAULT_MINUTE): selector.TextSelector(),
        vol.Optional(CONF_SECOND, default=DEFAULT_SECOND): selector.TextSelector(),
    }


def _sensor_class_fields() -> dict[vol.Marker, Any]:
    """Unit/device_class/state_class fields for Combine and Template sensors.

    The unit_of_measurement field is a direct port of core template's own
    sensor schema field: a dropdown built from DEVICE_CLASS_UNITS (the same
    registry SPEC §2.1's Combine Sensor unit-conversion code reads), plus
    custom_value=True so any string can still be typed -- this never
    rejects input, it's suggestions only. Built by reading DEVICE_CLASS_UNITS
    fresh from whatever core version is actually installed and imported at
    runtime, not a hardcoded snapshot, so a unit core adds in a future
    release shows up here automatically without a change on our end.
    """
    return {
        vol.Optional(CONF_UNIT_OF_MEASUREMENT): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(
                    {
                        str(unit)
                        for units in DEVICE_CLASS_UNITS.values()
                        for unit in units
                        if unit is not None
                    }
                ),
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key="sensor_unit_of_measurement",
                custom_value=True,
                sort=True,
            )
        ),
        vol.Optional(CONF_DEVICE_CLASS): selector.SelectSelector(
            selector.SelectSelectorConfig(
                # ENUM excluded: it requires an "options" list config we
                # don't support (matches core template's own exclusion).
                options=[
                    cls.value
                    for cls in SensorDeviceClass
                    if cls != SensorDeviceClass.ENUM
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key="sensor_device_class",
                sort=True,
            )
        ),
        vol.Optional(CONF_STATE_CLASS): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[cls.value for cls in SensorStateClass],
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key="sensor_state_class",
                sort=True,
            )
        ),
    }


def _shared_fields(*, include_name: bool) -> dict[vol.Marker, Any]:
    """Fields common to all three helper types (SPEC §4 "shared configuration")."""
    fields: dict[vol.Marker, Any] = {}
    if include_name:
        fields[vol.Required(CONF_NAME)] = selector.TextSelector()
    fields |= _schedule_fields()
    fields[vol.Optional(CONF_DEVICE_ID)] = selector.DeviceSelector()
    fields[vol.Optional(CONF_ENTITY_CATEGORY)] = selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[cat.value for cat in EntityCategory],
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key="entity_category",
        )
    )
    return fields


def _type_fields(helper_type: HelperType) -> dict[vol.Marker, Any]:
    """Fields specific to one helper type (SPEC §2.1/2.2/2.3)."""
    if helper_type is HelperType.COMBINE:
        return {
            vol.Required(CONF_SOURCES): vol.All(
                selector.EntitySelector(selector.EntitySelectorConfig(multiple=True)),
                vol.Length(min=1),
            ),
            vol.Required(CONF_AGGREGATION): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[fn.value for fn in AggregationFunction],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="aggregation",
                )
            ),
            **_sensor_class_fields(),
        }
    if helper_type is HelperType.TEMPLATE:
        return {
            vol.Required(CONF_STATE_TEMPLATE): selector.TemplateSelector(),
            vol.Optional(CONF_AVAILABILITY_TEMPLATE): selector.TemplateSelector(),
            **_sensor_class_fields(),
        }
    # HelperType.TEMPLATE_BINARY
    return {
        vol.Required(CONF_STATE_TEMPLATE): selector.TemplateSelector(),
        vol.Optional(CONF_AVAILABILITY_TEMPLATE): selector.TemplateSelector(),
        vol.Optional(CONF_DEVICE_CLASS): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[cls.value for cls in BinarySensorDeviceClass],
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key="binary_sensor_device_class",
                sort=True,
            )
        ),
    }


def generate_schema(helper_type: HelperType, flow_type: str) -> vol.Schema:
    """Build the combined schema for one helper type's config or options step."""
    fields = _type_fields(helper_type)
    fields |= _shared_fields(include_name=flow_type == "config")
    return vol.Schema(fields)


config_schema = partial(generate_schema, flow_type="config")
options_schema = partial(generate_schema, flow_type="options")


def _make_validator(
    helper_type: HelperType,
) -> Callable[
    [SchemaCommonFlowHandler, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]
]:
    """Build a validate_user_input callback bound to one helper type.

    Applies the schedule cross-field guard (SPEC §3) and stamps the helper
    type onto the stored options so the options flow can route directly to
    the right per-type step, and so __init__.py/sensor.py know which
    concrete entity to construct.
    """

    async def _validate(
        _: SchemaCommonFlowHandler, user_input: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            validate_schedule_pattern(user_input)
        except vol.Invalid as err:
            # SchemaFlowError, not vol.Invalid: this is what
            # SchemaFlowFormStep.validate_user_input actually catches (see
            # schedule.py's module docstring for why this distinction matters).
            raise SchemaFlowError(str(err)) from err
        return {CONF_HELPER_TYPE: helper_type.value} | user_input

    return _validate


async def _choose_options_step(options: dict[str, Any]) -> str:
    """Route the options flow directly to the entry's own helper-type step."""
    return cast(str, options[CONF_HELPER_TYPE])


CONFIG_FLOW: dict[str, SchemaFlowFormStep | SchemaFlowMenuStep] = {
    "user": SchemaFlowMenuStep(_HELPER_TYPES),
    HelperType.COMBINE: SchemaFlowFormStep(
        config_schema(HelperType.COMBINE),
        validate_user_input=_make_validator(HelperType.COMBINE),
    ),
    HelperType.TEMPLATE: SchemaFlowFormStep(
        config_schema(HelperType.TEMPLATE),
        validate_user_input=_make_validator(HelperType.TEMPLATE),
    ),
    HelperType.TEMPLATE_BINARY: SchemaFlowFormStep(
        config_schema(HelperType.TEMPLATE_BINARY),
        validate_user_input=_make_validator(HelperType.TEMPLATE_BINARY),
    ),
}

OPTIONS_FLOW: dict[str, SchemaFlowFormStep] = {
    "init": SchemaFlowFormStep(next_step=_choose_options_step),
    HelperType.COMBINE: SchemaFlowFormStep(
        options_schema(HelperType.COMBINE),
        validate_user_input=_make_validator(HelperType.COMBINE),
    ),
    HelperType.TEMPLATE: SchemaFlowFormStep(
        options_schema(HelperType.TEMPLATE),
        validate_user_input=_make_validator(HelperType.TEMPLATE),
    ),
    HelperType.TEMPLATE_BINARY: SchemaFlowFormStep(
        options_schema(HelperType.TEMPLATE_BINARY),
        validate_user_input=_make_validator(HelperType.TEMPLATE_BINARY),
    ),
}


class ConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle a config or options flow for Scheduled Helpers."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW
    options_flow_reloads = True

    @override
    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title from the user-entered name."""
        return cast(str, options.get(CONF_NAME, ""))
