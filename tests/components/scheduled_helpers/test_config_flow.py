"""Tests for the Scheduled Helpers config flow (setup + reconfigure/options)."""

from __future__ import annotations

from typing import Any

import pytest
from probatio import to_field_list

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import config_validation as cv

from custom_components.scheduled_helpers.config_flow import generate_schema
from custom_components.scheduled_helpers.const import (
    CONF_AGGREGATION,
    CONF_AVAILABILITY_TEMPLATE,
    CONF_HELPER_TYPE,
    CONF_HOUR,
    CONF_MINUTE,
    CONF_SECOND,
    CONF_SOURCES,
    CONF_STATE_TEMPLATE,
    DOMAIN,
    AggregationFunction,
    HelperType,
)


@pytest.mark.parametrize("helper_type", list(HelperType))
@pytest.mark.parametrize("flow_type", ["config", "options"])
def test_schema_is_json_serializable(helper_type: HelperType, flow_type: str) -> None:
    """Every generated schema must survive the same JSON serialization the
    real config-flow HTTP endpoint applies before sending a form to the
    frontend (``homeassistant.helpers.data_entry_flow`` calls
    ``to_field_list``/``voluptuous_serialize.convert`` depending on core
    version, both fed our schema plus ``cv.custom_serializer``).

    This is exactly the check that was missing when a per-field schedule
    validator got embedded as a raw function inside a schema marker
    (``vol.All(TextSelector(), <function>)``): every other test in this
    file drives the flow manager directly in Python and never touches this
    serialization step, so that bug shipped invisibly until it hit a real
    running instance and crashed the config-flow API with `ValueError:
    Unable to convert schema: <function ...>`. A bare Python
    callable anywhere in the schema fails this the same way regardless of
    which serializer library the installed core uses.
    """
    schema = generate_schema(helper_type, flow_type)
    to_field_list(schema, custom_serializer=cv.custom_serializer)


async def _start_flow(hass: HomeAssistant, menu_choice: str) -> dict[str, Any]:
    """Init the config flow and pick a helper type from the menu."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "user"

    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": menu_choice}
    )


async def test_create_combine_sensor(hass: HomeAssistant) -> None:
    """Combine Sensor: full config flow creates an entry with expected options."""
    step = await _start_flow(hass, HelperType.COMBINE)
    assert step["type"] is FlowResultType.FORM
    assert step["step_id"] == HelperType.COMBINE

    result = await hass.config_entries.flow.async_configure(
        step["flow_id"],
        {
            CONF_NAME: "Test Combine",
            CONF_SOURCES: ["sensor.a", "sensor.b"],
            CONF_AGGREGATION: AggregationFunction.MEAN,
            CONF_MINUTE: "/5",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Combine"
    options = result["result"].options
    assert options[CONF_HELPER_TYPE] == HelperType.COMBINE
    assert options[CONF_SOURCES] == ["sensor.a", "sensor.b"]
    assert options[CONF_AGGREGATION] == AggregationFunction.MEAN
    assert options[CONF_HOUR] == ""
    assert options[CONF_MINUTE] == "/5"
    assert options[CONF_SECOND] == ""


async def test_create_template_sensor(hass: HomeAssistant) -> None:
    """Template Sensor: full config flow creates an entry with expected options."""
    step = await _start_flow(hass, HelperType.TEMPLATE)
    result = await hass.config_entries.flow.async_configure(
        step["flow_id"],
        {
            CONF_NAME: "Test Template",
            CONF_STATE_TEMPLATE: "{{ states('sensor.a') }}",
            CONF_MINUTE: "/5",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = result["result"].options
    assert options[CONF_HELPER_TYPE] == HelperType.TEMPLATE
    assert options[CONF_STATE_TEMPLATE] == "{{ states('sensor.a') }}"
    assert CONF_AVAILABILITY_TEMPLATE not in options


async def test_create_template_binary_sensor(hass: HomeAssistant) -> None:
    """Template Binary Sensor: full config flow creates an entry."""
    step = await _start_flow(hass, HelperType.TEMPLATE_BINARY)
    result = await hass.config_entries.flow.async_configure(
        step["flow_id"],
        {
            CONF_NAME: "Test Binary",
            CONF_STATE_TEMPLATE: "{{ states('binary_sensor.a') == 'on' }}",
            CONF_MINUTE: "/5",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = result["result"].options
    assert options[CONF_HELPER_TYPE] == HelperType.TEMPLATE_BINARY


async def test_all_wildcard_schedule_rejected(hass: HomeAssistant) -> None:
    """SPEC §3: an hour=*, minute=*, second=* pattern must be rejected."""
    step = await _start_flow(hass, HelperType.TEMPLATE)
    result = await hass.config_entries.flow.async_configure(
        step["flow_id"],
        {
            CONF_NAME: "Test Template",
            CONF_STATE_TEMPLATE: "{{ 1 }}",
            CONF_HOUR: "*",
            CONF_MINUTE: "*",
            CONF_SECOND: "*",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {
        "base": "At least one of hour, minute, or second must be set to a "
        "specific value or step"
    }


async def test_all_blank_schedule_rejected(hass: HomeAssistant) -> None:
    """Blank is the new user-facing "unset" value (SPEC §3 replacing `*`):
    all three blank must be rejected exactly like all three wildcarded.
    """
    step = await _start_flow(hass, HelperType.TEMPLATE)
    result = await hass.config_entries.flow.async_configure(
        step["flow_id"],
        {
            CONF_NAME: "Test Template",
            CONF_STATE_TEMPLATE: "{{ 1 }}",
            CONF_HOUR: "",
            CONF_MINUTE: "",
            CONF_SECOND: "",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {
        "base": "At least one of hour, minute, or second must be set to a "
        "specific value or step"
    }


async def test_empty_sources_rejected(hass: HomeAssistant) -> None:
    """Combine Sensor must have at least one source entity.

    This is a per-field schema validator (`vol.Length(min=1)`), so it's
    enforced by the FlowManager's own schema pre-check -- calling the flow
    manager directly (as this test does, bypassing the HTTP view that
    normally turns `InvalidData` into a JSON error response) surfaces it as
    a raised exception rather than a FlowResult with `errors`.
    """
    step = await _start_flow(hass, HelperType.COMBINE)
    with pytest.raises(InvalidData, match="sources"):
        await hass.config_entries.flow.async_configure(
            step["flow_id"],
            {
                CONF_NAME: "Test Combine",
                CONF_SOURCES: [],
                CONF_AGGREGATION: AggregationFunction.MEAN,
            },
        )


async def test_options_flow_edits_existing_entry(hass: HomeAssistant) -> None:
    """Options flow (SPEC §4 reconfigure-equivalent): routes to the right
    per-type step, pre-fills current values, and applies edits.
    """
    step = await _start_flow(hass, HelperType.COMBINE)
    create_result = await hass.config_entries.flow.async_configure(
        step["flow_id"],
        {
            CONF_NAME: "Test Combine",
            CONF_SOURCES: ["sensor.a"],
            CONF_AGGREGATION: AggregationFunction.MIN,
            CONF_MINUTE: "/5",
        },
    )
    entry = create_result["result"]

    options_result = await hass.config_entries.options.async_init(entry.entry_id)
    # "init" step is a transparent pass-through straight to the "combine" step.
    assert options_result["type"] is FlowResultType.FORM
    assert options_result["step_id"] == HelperType.COMBINE
    # Existing values are pre-filled as suggested_value on each schema marker.
    suggested = {
        key: key.description.get("suggested_value")
        for key in options_result["data_schema"].schema
        if key.description
    }
    assert suggested[CONF_SOURCES] == ["sensor.a"]
    assert suggested[CONF_AGGREGATION] == AggregationFunction.MIN

    edit_result = await hass.config_entries.options.async_configure(
        options_result["flow_id"],
        {
            CONF_SOURCES: ["sensor.a", "sensor.c"],
            CONF_AGGREGATION: AggregationFunction.MAX,
            CONF_MINUTE: "/10",
        },
    )
    assert edit_result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SOURCES] == ["sensor.a", "sensor.c"]
    assert entry.options[CONF_AGGREGATION] == AggregationFunction.MAX
    assert entry.options[CONF_MINUTE] == "/10"
    # helper_type persists across the edit; name persists even though it's
    # not part of the options-flow schema.
    assert entry.options[CONF_HELPER_TYPE] == HelperType.COMBINE
    assert entry.title == "Test Combine"


async def test_options_flow_edits_template_sensor(hass: HomeAssistant) -> None:
    """Options flow routing/pre-fill/apply also holds for Template Sensor,
    not just Combine -- the per-type step schemas are generated by the same
    code path, but each is wired up separately in OPTIONS_FLOW, so a typo
    in one type's entry wouldn't be caught by testing only Combine.
    """
    step = await _start_flow(hass, HelperType.TEMPLATE)
    create_result = await hass.config_entries.flow.async_configure(
        step["flow_id"],
        {
            CONF_NAME: "Test Template",
            CONF_STATE_TEMPLATE: "{{ states('sensor.a') }}",
            CONF_MINUTE: "/5",
        },
    )
    entry = create_result["result"]

    options_result = await hass.config_entries.options.async_init(entry.entry_id)
    assert options_result["type"] is FlowResultType.FORM
    assert options_result["step_id"] == HelperType.TEMPLATE

    edit_result = await hass.config_entries.options.async_configure(
        options_result["flow_id"],
        {
            CONF_STATE_TEMPLATE: "{{ states('sensor.b') }}",
            CONF_AVAILABILITY_TEMPLATE: "{{ true }}",
            CONF_MINUTE: "/10",
        },
    )
    assert edit_result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_STATE_TEMPLATE] == "{{ states('sensor.b') }}"
    assert entry.options[CONF_AVAILABILITY_TEMPLATE] == "{{ true }}"
    assert entry.options[CONF_MINUTE] == "/10"
    assert entry.options[CONF_HELPER_TYPE] == HelperType.TEMPLATE


async def test_options_flow_edits_template_binary_sensor(hass: HomeAssistant) -> None:
    """Options flow routing/pre-fill/apply also holds for Template Binary
    Sensor, not just Combine -- see test_options_flow_edits_template_sensor.
    """
    step = await _start_flow(hass, HelperType.TEMPLATE_BINARY)
    create_result = await hass.config_entries.flow.async_configure(
        step["flow_id"],
        {
            CONF_NAME: "Test Binary",
            CONF_STATE_TEMPLATE: "{{ states('binary_sensor.a') == 'on' }}",
            CONF_MINUTE: "/5",
        },
    )
    entry = create_result["result"]

    options_result = await hass.config_entries.options.async_init(entry.entry_id)
    assert options_result["type"] is FlowResultType.FORM
    assert options_result["step_id"] == HelperType.TEMPLATE_BINARY

    edit_result = await hass.config_entries.options.async_configure(
        options_result["flow_id"],
        {
            CONF_STATE_TEMPLATE: "{{ states('binary_sensor.b') == 'on' }}",
            CONF_MINUTE: "/10",
        },
    )
    assert edit_result["type"] is FlowResultType.CREATE_ENTRY
    assert (
        entry.options[CONF_STATE_TEMPLATE] == "{{ states('binary_sensor.b') == 'on' }}"
    )
    assert entry.options[CONF_MINUTE] == "/10"
    assert entry.options[CONF_HELPER_TYPE] == HelperType.TEMPLATE_BINARY
