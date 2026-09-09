"""Tests for TemplateBinarySensor (SPEC §2.3, §6 availability)."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.scheduled_helpers.binary_sensor import TemplateBinarySensor
from custom_components.scheduled_helpers.const import (
    CONF_AVAILABILITY_TEMPLATE,
    CONF_HOUR,
    CONF_MINUTE,
    CONF_SECOND,
    CONF_STATE_TEMPLATE,
    DOMAIN,
)
from custom_components.scheduled_helpers.entity import ScheduledHelperUnavailable
from custom_components.scheduled_helpers.schedule import SchedulePattern

_PATTERN = SchedulePattern(hour="*", minute="/5", second="*")


def _entity(hass, **options: object) -> TemplateBinarySensor:
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_HOUR: "*",
            CONF_MINUTE: "/5",
            CONF_SECOND: "*",
            **options,
        },
    )
    entity = TemplateBinarySensor(hass, entry, _PATTERN)
    entity.entity_id = "binary_sensor.template"
    entity.hass = hass
    return entity


@pytest.mark.parametrize(
    ("rendered", "expected_is_on"),
    [
        ("on", True),
        ("true", True),
        ("1", True),
        ("off", False),
        ("false", False),
        ("0", False),
    ],
)
async def test_state_template_boolean_coercion(
    hass, rendered: str, expected_is_on: bool
) -> None:
    """SPEC §2.3: on/off coercion matches core's `states('...') == 'on'`-style
    mapping, not raw Python truthiness of arbitrary strings.
    """
    entity = _entity(hass, **{CONF_STATE_TEMPLATE: f"{{{{ '{rendered}' }}}}"})
    await entity._async_compute_state()
    assert entity._attr_is_on is expected_is_on


async def test_arbitrary_non_keyword_string_is_falsy(hass) -> None:
    """A rendered string that isn't a recognized on/off keyword is falsy,
    not truthy -- proving this isn't raw Python truthiness (a non-empty
    string like "banana" is truthy in Python, but not a recognized on/off
    keyword).
    """
    entity = _entity(hass, **{CONF_STATE_TEMPLATE: "{{ 'banana' }}"})
    await entity._async_compute_state()
    assert entity._attr_is_on is False


async def test_availability_falsy_marks_unavailable(hass) -> None:
    """A falsy availability template marks the entity unavailable."""
    entity = _entity(
        hass,
        **{
            CONF_STATE_TEMPLATE: "{{ 'on' }}",
            CONF_AVAILABILITY_TEMPLATE: "{{ false }}",
        },
    )
    with pytest.raises(ScheduledHelperUnavailable):
        await entity._async_compute_state()


async def test_render_error_marks_unavailable(hass) -> None:
    """A template render error marks the entity unavailable, not a crash."""
    entity = _entity(hass, **{CONF_STATE_TEMPLATE: "{{ 1 / 0 }}"})
    with pytest.raises(ScheduledHelperUnavailable):
        await entity._async_compute_state()
