"""Tests for CombineSensor and TemplateSensor (SPEC §2.1/§2.2, §6 availability)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_DEVICE_CLASS,
    CONF_NAME,
    CONF_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    UnitOfMass,
    UnitOfPressure,
)

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
from custom_components.scheduled_helpers.entity import ScheduledHelperUnavailable
from custom_components.scheduled_helpers.schedule import SchedulePattern
from custom_components.scheduled_helpers.sensor import CombineSensor, TemplateSensor

_PATTERN = SchedulePattern(hour="*", minute="/5", second="*")


def _entry(**options: object) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_HOUR: "*",
            CONF_MINUTE: "/5",
            CONF_SECOND: "*",
            **options,
        },
    )


def _combine(hass, **options: object) -> CombineSensor:
    entity = CombineSensor(hass, _entry(**options), _PATTERN)
    entity.entity_id = "sensor.combine"
    entity.hass = hass
    return entity


def _template(hass, **options: object) -> TemplateSensor:
    entity = TemplateSensor(hass, _entry(**options), _PATTERN)
    entity.entity_id = "sensor.template"
    entity.hass = hass
    return entity


async def test_combine_mean_skips_unavailable_source(hass) -> None:
    """3 sources, 1 unavailable: mean must divide by 2, not 3."""
    hass.states.async_set("sensor.a", "10")
    hass.states.async_set("sensor.b", "20")
    hass.states.async_set("sensor.c", "unavailable")

    entity = _combine(
        hass,
        **{
            CONF_SOURCES: ["sensor.a", "sensor.b", "sensor.c"],
            CONF_AGGREGATION: AggregationFunction.MEAN,
        },
    )
    await entity._async_compute_state()
    assert entity._attr_native_value == 15  # (10 + 20) / 2, not / 3


async def test_combine_non_numeric_source_skipped(hass) -> None:
    """A source with a non-numeric state is skipped, same as unavailable."""
    hass.states.async_set("sensor.a", "10")
    hass.states.async_set("sensor.b", "garbage")

    entity = _combine(
        hass,
        **{
            CONF_SOURCES: ["sensor.a", "sensor.b"],
            CONF_AGGREGATION: AggregationFunction.MEAN,
        },
    )
    await entity._async_compute_state()
    assert entity._attr_native_value == 10


async def test_combine_sum_needs_two_usable_sources(hass) -> None:
    """sum/range with only 1 usable source must raise (SPEC §6 availability)."""
    hass.states.async_set("sensor.a", "10")
    hass.states.async_set("sensor.b", "unavailable")

    entity = _combine(
        hass,
        **{
            CONF_SOURCES: ["sensor.a", "sensor.b"],
            CONF_AGGREGATION: AggregationFunction.SUM,
        },
    )
    with pytest.raises(ScheduledHelperUnavailable):
        await entity._async_compute_state()


async def test_combine_mean_ok_with_one_usable_source(hass) -> None:
    """mean/min/max/median/last only need 1 usable source (unlike sum/range)."""
    hass.states.async_set("sensor.a", "10")
    hass.states.async_set("sensor.b", "unavailable")

    entity = _combine(
        hass,
        **{
            CONF_SOURCES: ["sensor.a", "sensor.b"],
            CONF_AGGREGATION: AggregationFunction.MEAN,
        },
    )
    await entity._async_compute_state()
    assert entity._attr_native_value == 10


async def test_combine_zero_usable_sources_unavailable(hass) -> None:
    """All sources unavailable: entity must be unavailable regardless of function."""
    hass.states.async_set("sensor.a", "unavailable")
    hass.states.async_set("sensor.b", "unknown")

    entity = _combine(
        hass,
        **{
            CONF_SOURCES: ["sensor.a", "sensor.b"],
            CONF_AGGREGATION: AggregationFunction.MIN,
        },
    )
    with pytest.raises(ScheduledHelperUnavailable):
        await entity._async_compute_state()


async def test_combine_last_picks_most_recently_changed(hass, freezer) -> None:
    """'last' picks the usable source with the latest last_changed timestamp."""
    hass.states.async_set("sensor.a", "10")
    freezer.tick(timedelta(seconds=5))
    hass.states.async_set("sensor.b", "20")

    entity = _combine(
        hass,
        **{
            CONF_SOURCES: ["sensor.a", "sensor.b"],
            CONF_AGGREGATION: AggregationFunction.LAST,
        },
    )
    await entity._async_compute_state()
    assert entity._attr_native_value == 20

    # Now sensor.a changes most recently -- "last" must follow it.
    freezer.tick(timedelta(seconds=5))
    hass.states.async_set("sensor.a", "30")
    await entity._async_compute_state()
    assert entity._attr_native_value == 30


async def test_combine_range_and_sum_math(hass) -> None:
    """Sanity-check range and sum with all sources usable."""
    hass.states.async_set("sensor.a", "10")
    hass.states.async_set("sensor.b", "30")

    range_entity = _combine(
        hass,
        **{
            CONF_SOURCES: ["sensor.a", "sensor.b"],
            CONF_AGGREGATION: AggregationFunction.RANGE,
        },
    )
    await range_entity._async_compute_state()
    assert range_entity._attr_native_value == 20

    sum_entity = _combine(
        hass,
        **{
            CONF_SOURCES: ["sensor.a", "sensor.b"],
            CONF_AGGREGATION: AggregationFunction.SUM,
        },
    )
    await sum_entity._async_compute_state()
    assert sum_entity._attr_native_value == 40


async def test_combine_converts_mismatched_but_compatible_units(hass) -> None:
    """Two pressure sources in different but convertible units get
    converted into the sensor's configured unit before aggregating,
    rather than being combined as raw physically-incompatible numbers.
    """
    from homeassistant.util.unit_conversion import PressureConverter

    hass.states.async_set(
        "sensor.a", "30", {ATTR_UNIT_OF_MEASUREMENT: UnitOfPressure.INHG}
    )
    hass.states.async_set(
        "sensor.b", "20", {ATTR_UNIT_OF_MEASUREMENT: UnitOfPressure.PSI}
    )

    entity = _combine(
        hass,
        **{
            CONF_SOURCES: ["sensor.a", "sensor.b"],
            CONF_AGGREGATION: AggregationFunction.MEAN,
            CONF_DEVICE_CLASS: "pressure",
            CONF_UNIT_OF_MEASUREMENT: UnitOfPressure.PSI,
        },
    )
    await entity._async_compute_state()

    converted_a = PressureConverter.convert(30, UnitOfPressure.INHG, UnitOfPressure.PSI)
    assert entity._attr_native_value == pytest.approx((converted_a + 20) / 2)


async def test_combine_skips_source_with_incompatible_unit_family(hass) -> None:
    """A source whose unit isn't part of the configured device class's unit
    family at all can't be meaningfully converted, so it's skipped like any
    other unusable source rather than combined as if it were compatible.
    """
    hass.states.async_set(
        "sensor.a", "30", {ATTR_UNIT_OF_MEASUREMENT: UnitOfPressure.PSI}
    )
    hass.states.async_set("sensor.b", "5", {ATTR_UNIT_OF_MEASUREMENT: UnitOfMass.KILOGRAMS})

    entity = _combine(
        hass,
        **{
            CONF_SOURCES: ["sensor.a", "sensor.b"],
            CONF_AGGREGATION: AggregationFunction.MEAN,
            CONF_DEVICE_CLASS: "pressure",
            CONF_UNIT_OF_MEASUREMENT: UnitOfPressure.PSI,
        },
    )
    await entity._async_compute_state()
    assert entity._attr_native_value == 30


async def test_combine_source_without_unit_passes_through_unchanged(hass) -> None:
    """A source reporting no unit at all is assumed already compatible
    (e.g. a plain input_number or unitless template sensor), not skipped.
    """
    hass.states.async_set("sensor.a", "30")  # no unit_of_measurement attribute

    entity = _combine(
        hass,
        **{
            CONF_SOURCES: ["sensor.a"],
            CONF_AGGREGATION: AggregationFunction.MEAN,
            CONF_DEVICE_CLASS: "pressure",
            CONF_UNIT_OF_MEASUREMENT: UnitOfPressure.PSI,
        },
    )
    await entity._async_compute_state()
    assert entity._attr_native_value == 30


async def test_combine_no_conversion_without_device_class(hass) -> None:
    """Without a device class configured, sources' units are never
    inspected -- raw numeric combination, same as before this feature
    existed (SPEC §2.1: unit is user-configured, not auto-derived, so unit
    awareness is opt-in via also setting a device class).
    """
    hass.states.async_set(
        "sensor.a", "30", {ATTR_UNIT_OF_MEASUREMENT: UnitOfPressure.INHG}
    )
    hass.states.async_set(
        "sensor.b", "20", {ATTR_UNIT_OF_MEASUREMENT: UnitOfPressure.PSI}
    )

    entity = _combine(
        hass,
        **{
            CONF_SOURCES: ["sensor.a", "sensor.b"],
            CONF_AGGREGATION: AggregationFunction.MEAN,
            CONF_UNIT_OF_MEASUREMENT: UnitOfPressure.PSI,
        },
    )
    await entity._async_compute_state()
    assert entity._attr_native_value == 25  # raw (30 + 20) / 2, no conversion


async def test_template_sensor_renders_state(hass) -> None:
    """Basic state template rendering.

    Rendered with parse_result defaulted to True (matching core's template
    sensor): a numeric-looking result is coerced to int/float, not left as
    the raw string -- see the comment in TemplateSensor._async_compute_state.
    """
    hass.states.async_set("sensor.source", "42")
    entity = _template(hass, **{CONF_STATE_TEMPLATE: "{{ states('sensor.source') }}"})

    await entity._async_compute_state()
    assert entity._attr_native_value == 42


async def test_template_sensor_none_result_is_not_literal_string(hass) -> None:
    """A template legitimately evaluating to "no value" must not display as
    the literal string "None" -- that's the specific bug parse_result=True
    (matching core) avoids. `_attr_native_value` of None is what SensorEntity
    turns into an "unknown" state, not a literal "None" string.
    """
    entity = _template(
        hass, **{CONF_STATE_TEMPLATE: "{{ state_attr('sensor.missing', 'foo') }}"}
    )
    await entity._async_compute_state()
    assert entity._attr_native_value is None


async def test_template_sensor_availability_falsy(hass) -> None:
    """A falsy availability template marks the entity unavailable (SPEC §2.2)."""
    entity = _template(
        hass,
        **{
            CONF_STATE_TEMPLATE: "{{ 1 }}",
            CONF_AVAILABILITY_TEMPLATE: "{{ false }}",
        },
    )
    with pytest.raises(ScheduledHelperUnavailable):
        await entity._async_compute_state()


async def test_template_sensor_render_error(hass) -> None:
    """A template render error marks the entity unavailable, not a crash."""
    entity = _template(hass, **{CONF_STATE_TEMPLATE: "{{ 1 / 0 }}"})
    with pytest.raises(ScheduledHelperUnavailable):
        await entity._async_compute_state()


async def test_schedule_listener_lifecycle_end_to_end(hass, freezer) -> None:
    """Full wiring, via the real async_track_time_change listener.

    Not just calling _async_compute_state() directly: this drives entity
    setup through the actual config entry -> platform forwarding ->
    entity.py's async_added_to_hass path, then fires a real time-changed
    event to prove the registered listener actually ticks, and unloads the
    entry to prove it's actually torn down afterward (SPEC §3).
    """
    # Use a once-a-day pattern (real scheduling delay up to ~24h) rather
    # than a tight one like second="/1" -- otherwise the real asyncio timer
    # can legitimately elapse for real during this test's own setup/
    # teardown overhead (especially when run alongside the rest of the
    # suite), firing the tick before we're ready to observe the
    # "hasn't ticked yet" state and making this test flaky.
    #
    # pytest-homeassistant-custom-component's async_fire_time_changed works
    # by comparing how far *_our frozen clock_* has moved past real
    # wall-clock time (via freezer.tick(), a *relative* advance from
    # whatever real "now" is) against how many real seconds remain on the
    # actual scheduled asyncio timer, manually firing it if we've jumped
    # far enough -- freezer.move_to() to an unrelated fixed calendar date
    # breaks that comparison, so relative ticks are the correct tool here.
    hass.states.async_set("sensor.source", "7")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Combine",
        options={
            CONF_NAME: "Test Combine",
            CONF_HELPER_TYPE: HelperType.COMBINE,
            CONF_SOURCES: ["sensor.source"],
            CONF_AGGREGATION: AggregationFunction.MEAN,
            CONF_HOUR: "3",
            CONF_MINUTE: "0",
            CONF_SECOND: "0",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_id = "sensor.test_combine"
    # No tick has fired yet: state must not reflect the source's value.
    assert hass.states.get(entity_id).state != "7.0"

    freezer.tick(timedelta(hours=25))  # safely past the ~24h worst case
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "7.0"

    # Unload: HA marks the entity's state unavailable (a normal "restored"
    # placeholder, not full removal from hass.states). The real proof the
    # listener was torn down is that a further tick, with a changed source
    # value, must NOT bring it back.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE

    hass.states.async_set("sensor.source", "99")
    freezer.tick(timedelta(hours=25))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_reconfigure_replaces_schedule_listener(hass) -> None:
    """SPEC §3: changing the schedule pattern tears down the old listener
    and registers a new one, rather than leaving the old one running
    alongside it or dropping scheduling altogether.

    This is entity.py's async_will_remove_from_hass/async_added_to_hass
    contract that options_flow_reloads's entry reload relies on for a
    reconfigure (see test_schedule_listener_lifecycle_end_to_end for the
    full add/unload path through a real config entry). Verified here
    directly against async_register_schedule_listener, with distinct mock
    unsub callables for the old and new registration, so a broken teardown
    can't hide behind a still-working new listener.
    """
    entity = _combine(
        hass,
        **{CONF_SOURCES: ["sensor.a"], CONF_AGGREGATION: AggregationFunction.MIN},
    )
    unsub_old = Mock(name="unsub_old")
    unsub_new = Mock(name="unsub_new")

    with patch(
        "custom_components.scheduled_helpers.entity.async_register_schedule_listener",
        side_effect=[unsub_old, unsub_new],
    ) as mock_register:
        await entity.async_added_to_hass()
        assert entity._unsub_schedule is unsub_old
        unsub_old.assert_not_called()

        await entity.async_will_remove_from_hass()
        unsub_old.assert_called_once()
        assert entity._unsub_schedule is None

        new_pattern = SchedulePattern(hour="*", minute="*", second="/30")
        entity._schedule_pattern = new_pattern
        await entity.async_added_to_hass()

        assert entity._unsub_schedule is unsub_new
        assert mock_register.call_count == 2
        assert mock_register.call_args_list[1].args[1] == new_pattern

    unsub_new.assert_not_called()
