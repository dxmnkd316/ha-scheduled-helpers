"""The Scheduled Helpers integration.

Each config entry represents exactly one helper (Combine, Template, or
Template Binary Sensor) and forwards to exactly one platform based on its
stored helper type -- see ``const.HELPER_TYPE_PLATFORM``.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_HELPER_TYPE, HELPER_TYPE_PLATFORM, HelperType


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Scheduled Helpers from a config entry."""
    helper_type = HelperType(entry.options[CONF_HELPER_TYPE])
    await hass.config_entries.async_forward_entry_setups(
        entry, (HELPER_TYPE_PLATFORM[helper_type],)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    helper_type = HelperType(entry.options[CONF_HELPER_TYPE])
    return await hass.config_entries.async_unload_platforms(
        entry, (HELPER_TYPE_PLATFORM[helper_type],)
    )
