"""Shared base entity for Scheduled Helpers.

Handles what's common across Combine Sensor, Template Sensor, and Template
Binary Sensor: schedule listener lifecycle (SPEC §3), device linking (SPEC
§5), and the availability wrapper around each scheduled compute tick (SPEC
§6). Each concrete entity implements ``_async_compute_state``, raising
``ScheduledHelperUnavailable`` for any expected/transient failure (missing
source entity, non-numeric state, template render error) -- anything else
is a genuine bug and is left to propagate rather than being folded into
"just unavailable".
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from datetime import datetime
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE_ID, CONF_ENTITY_CATEGORY, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import Entity

from .schedule import SchedulePattern, async_register_schedule_listener

_LOGGER = logging.getLogger(__name__)


class ScheduledHelperUnavailable(Exception):
    """Raised by a compute step for an expected, transient failure.

    Caught by ``ScheduledHelperEntity``'s tick handler and turned into an
    ``available = False`` state per SPEC §6.
    """


def async_get_linked_device(
    hass: HomeAssistant, device_id: str
) -> dr.AnyDeviceEntry | None:
    """Look up a user-selected device to link, excluding composite devices.

    A "composite" device is a synthetic, read-only stand-in the device
    registry generates on the fly for a pre-2026.8 device that used to be
    merged across multiple config entries and has since been split -- it
    never corresponds to one real device, so it isn't a valid link target.
    ``include_composite_devices`` doesn't exist before ~2026.8, where the
    composite-device concept doesn't exist either, so the plain call is
    equivalent on those older cores.
    """
    device_registry = dr.async_get(hass)
    try:
        return device_registry.async_get(device_id, include_composite_devices=False)
    except TypeError:
        return device_registry.async_get(device_id)


class ScheduledHelperEntity(Entity):
    """Shared base for all three Scheduled Helpers entity types."""

    _attr_should_poll = False

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, pattern: SchedulePattern
    ) -> None:
        """Initialize shared entity state: identity, device link, schedule."""
        self.hass = hass
        self._entry = entry
        self._schedule_pattern = pattern
        self._unsub_schedule: Callable[[], None] | None = None

        self._attr_unique_id = entry.entry_id
        self._attr_name = entry.title

        entity_category = entry.options.get(CONF_ENTITY_CATEGORY)
        self._attr_entity_category = (
            EntityCategory(entity_category) if entity_category else None
        )

        device_id = entry.options.get(CONF_DEVICE_ID)
        if device_id is not None:
            self.device_entry = async_get_linked_device(hass, device_id)

    async def async_added_to_hass(self) -> None:
        """Register this entity's schedule listener."""
        await super().async_added_to_hass()
        self._unsub_schedule = async_register_schedule_listener(
            self.hass, self._schedule_pattern, self._async_handle_scheduled_update
        )

    async def async_will_remove_from_hass(self) -> None:
        """Tear down this entity's schedule listener."""
        if self._unsub_schedule is not None:
            self._unsub_schedule()
            self._unsub_schedule = None
        await super().async_will_remove_from_hass()

    async def _async_handle_scheduled_update(self, now: datetime) -> None:
        """Run one scheduled tick: compute, apply availability, write state."""
        try:
            await self._async_compute_state()
        except ScheduledHelperUnavailable as err:
            _LOGGER.warning("%s is unavailable: %s", self.entity_id, err)
            self._attr_available = False
        else:
            self._attr_available = True
        self.async_write_ha_state()

    @abstractmethod
    async def _async_compute_state(self) -> None:
        """Compute and set this entity's state for one scheduled tick.

        Implementations must raise ``ScheduledHelperUnavailable`` for any
        expected/transient failure (missing source entity, non-numeric
        state, template render error) rather than returning a sentinel or
        swallowing the error -- see SPEC §6.
        """
