"""Combine Sensor and Template Sensor platforms for Scheduled Helpers."""

from __future__ import annotations

import statistics
from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import (
    CONF_STATE_CLASS,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.sensor.const import UNIT_CONVERTERS
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_DEVICE_CLASS,
    CONF_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.template import Template, result_as_boolean

from .const import (
    AGGREGATIONS_REQUIRING_MULTIPLE_SOURCES,
    CONF_AGGREGATION,
    CONF_AVAILABILITY_TEMPLATE,
    CONF_HELPER_TYPE,
    CONF_HOUR,
    CONF_MINUTE,
    CONF_SECOND,
    CONF_SOURCES,
    CONF_STATE_TEMPLATE,
    AggregationFunction,
    HelperType,
)
from .entity import ScheduledHelperEntity, ScheduledHelperUnavailable
from .schedule import SchedulePattern, resolve_schedule_pattern

_AGGREGATE_FUNCS: dict[AggregationFunction, Callable[[list[float]], float]] = {
    AggregationFunction.MIN: min,
    AggregationFunction.MAX: max,
    AggregationFunction.MEAN: statistics.mean,
    AggregationFunction.MEDIAN: statistics.median,
    AggregationFunction.SUM: sum,
    AggregationFunction.RANGE: lambda values: max(values) - min(values),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a Combine Sensor or Template Sensor from a config entry."""
    pattern = resolve_schedule_pattern(
        entry.options[CONF_HOUR], entry.options[CONF_MINUTE], entry.options[CONF_SECOND]
    )
    helper_type = HelperType(entry.options[CONF_HELPER_TYPE])
    entity: CombineSensor | TemplateSensor
    if helper_type is HelperType.COMBINE:
        entity = CombineSensor(hass, entry, pattern)
    else:
        entity = TemplateSensor(hass, entry, pattern)
    async_add_entities([entity])


class _ScheduledHelperSensor(ScheduledHelperEntity, SensorEntity):
    """Shared unit/device_class/state_class wiring for both sensor types."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, pattern: SchedulePattern
    ) -> None:
        super().__init__(hass, entry, pattern)
        if (unit := entry.options.get(CONF_UNIT_OF_MEASUREMENT)) is not None:
            self._attr_native_unit_of_measurement = unit
        if (device_class := entry.options.get(CONF_DEVICE_CLASS)) is not None:
            self._attr_device_class = SensorDeviceClass(device_class)
        if (state_class := entry.options.get(CONF_STATE_CLASS)) is not None:
            self._attr_state_class = SensorStateClass(state_class)


class CombineSensor(_ScheduledHelperSensor):
    """Functional clone of core `min_max`, updated on a schedule (SPEC §2.1)."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, pattern: SchedulePattern
    ) -> None:
        super().__init__(hass, entry, pattern)
        self._sources: list[str] = entry.options[CONF_SOURCES]
        self._aggregation = AggregationFunction(entry.options[CONF_AGGREGATION])

    async def _async_compute_state(self) -> None:
        """Aggregate current source states, skipping unusable ones.

        A source is unusable if it's missing, unavailable/unknown, its
        state can't be coerced to float, or (when this sensor's configured
        device class has a known unit family, see below) its own unit
        doesn't belong to that family at all -- all are skipped from the
        aggregation pool rather than failing the whole computation. `sum`
        and `range` need at least 2 usable sources to be meaningful; every
        other function needs at least 1. Falling short of that minimum is
        what actually makes the entity unavailable (not any single bad
        source) -- see SPEC §6 and the aggregation-edge-case decision this
        was built against.

        Unit handling: SPEC §2.1 has this sensor's unit user-configured,
        not auto-derived from sources (unlike core `min_max`), so sources
        aren't required to share a unit the way core's are. But combining
        raw numbers across genuinely different units (two pressure sensors,
        one in inHg and one in psi) would be physically meaningless, not
        just cosmetically wrong -- so when both a device class *and* a unit
        are configured, and that device class has a known convertible unit
        family (``UNIT_CONVERTERS``, the same registry core's own sensor
        entities use for unit conversion), each source's value is converted
        from its own reported unit into the configured unit before
        aggregating. A source with no reported unit is assumed already
        compatible (passed through as-is, matching how a plain
        `input_number` or unitless template sensor commonly has no unit at
        all); a source whose unit isn't part of that family at all (e.g. a
        mass sensor mixed into a pressure combine) can't be meaningfully
        converted, so it's skipped like any other unusable source instead
        of being combined as if it were already in the right unit.
        """
        unit_converter = UNIT_CONVERTERS.get(self.device_class)
        target_unit = self.native_unit_of_measurement
        if (
            unit_converter is None
            or target_unit is None
            or target_unit not in unit_converter.VALID_UNITS
        ):
            unit_converter = None

        usable: list[tuple[State, float]] = []
        for entity_id in self._sources:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            try:
                value = float(state.state)
            except ValueError:
                continue

            if unit_converter is not None:
                source_unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                if source_unit is not None and source_unit != target_unit:
                    if source_unit not in unit_converter.VALID_UNITS:
                        continue
                    value = unit_converter.convert(value, source_unit, target_unit)

            usable.append((state, value))

        minimum_required = (
            2 if self._aggregation in AGGREGATIONS_REQUIRING_MULTIPLE_SOURCES else 1
        )
        if len(usable) < minimum_required:
            raise ScheduledHelperUnavailable(
                f"only {len(usable)} usable source(s) for '{self._aggregation}' "
                f"aggregation (needs at least {minimum_required})"
            )

        if self._aggregation is AggregationFunction.LAST:
            # "Most recently updated" = latest last_changed among usable
            # sources (SPEC §2.1's "last" mode, translated from core
            # min_max's event-driven version to this tick-based model).
            self._attr_native_value = max(usable, key=lambda pair: pair[0].last_changed)[
                1
            ]
            return

        values = [value for _, value in usable]
        self._attr_native_value = _AGGREGATE_FUNCS[self._aggregation](values)


class TemplateSensor(_ScheduledHelperSensor):
    """Functional clone of core `template` sensor, updated on a schedule (SPEC §2.2)."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, pattern: SchedulePattern
    ) -> None:
        super().__init__(hass, entry, pattern)
        self._state_template = Template(entry.options[CONF_STATE_TEMPLATE], hass)
        availability_template_str = entry.options.get(CONF_AVAILABILITY_TEMPLATE)
        self._availability_template = (
            Template(availability_template_str, hass)
            if availability_template_str
            else None
        )

    async def _async_compute_state(self) -> None:
        """Render availability first, then state, per SPEC §2.2."""
        if self._availability_template is not None:
            try:
                availability_result: Any = self._availability_template.async_render(
                    parse_result=False
                )
            except TemplateError as err:
                raise ScheduledHelperUnavailable(
                    f"availability template error: {err}"
                ) from err
            if not result_as_boolean(availability_result):
                raise ScheduledHelperUnavailable("availability template evaluated falsy")

        try:
            # parse_result left at its default (True) here, unlike the
            # availability render above: core's template sensor parses the
            # main state result too (numeric strings -> int/float, "None" ->
            # actual None -> entity shows "unknown"). Forcing parse_result=
            # False here would make a template that legitimately evaluates
            # to no value (e.g. `state_attr()` on a missing attribute)
            # display the literal string "None" instead of going unknown --
            # not a functional clone of core's behavior per SPEC §2.2.
            self._attr_native_value = self._state_template.async_render()
        except TemplateError as err:
            raise ScheduledHelperUnavailable(f"state template error: {err}") from err
