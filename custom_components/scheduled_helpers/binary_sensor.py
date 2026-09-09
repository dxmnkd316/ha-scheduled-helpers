"""Template Binary Sensor platform for Scheduled Helpers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE_CLASS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import TemplateError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.template import Template, result_as_boolean

from .const import (
    CONF_AVAILABILITY_TEMPLATE,
    CONF_HOUR,
    CONF_MINUTE,
    CONF_SECOND,
    CONF_STATE_TEMPLATE,
)
from .entity import ScheduledHelperEntity, ScheduledHelperUnavailable
from .schedule import SchedulePattern, resolve_schedule_pattern


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a Template Binary Sensor from a config entry."""
    pattern = resolve_schedule_pattern(
        entry.options[CONF_HOUR], entry.options[CONF_MINUTE], entry.options[CONF_SECOND]
    )
    async_add_entities([TemplateBinarySensor(hass, entry, pattern)])


class TemplateBinarySensor(ScheduledHelperEntity, BinarySensorEntity):
    """Functional clone of core template binary sensor, on a schedule (SPEC §2.3)."""

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
        if (device_class := entry.options.get(CONF_DEVICE_CLASS)) is not None:
            self._attr_device_class = BinarySensorDeviceClass(device_class)

    async def _async_compute_state(self) -> None:
        """Render availability first, then state, per SPEC §2.2/§2.3.

        The state template's truthy/falsy result maps to on/off using the
        same `result_as_boolean` coercion core's binary template sensor
        uses (`states('...') == 'on'`-style, not raw string truthiness) --
        SPEC §2.3.
        """
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
            state_result: Any = self._state_template.async_render(parse_result=False)
        except TemplateError as err:
            raise ScheduledHelperUnavailable(f"state template error: {err}") from err

        self._attr_is_on = result_as_boolean(state_result)
