"""Constants for the Scheduled Helpers integration."""

from __future__ import annotations

from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "scheduled_helpers"


class HelperType(StrEnum):
    """Which of the three helper flavors a config entry represents."""

    COMBINE = "combine"
    TEMPLATE = "template"
    TEMPLATE_BINARY = "template_binary"


# Combine and Template are both sensor-domain entities; only Template Binary
# Sensor lives on the binary_sensor platform. Each config entry represents
# exactly one helper type, so __init__.py forwards to exactly one platform
# per entry -- there's no integration-wide "PLATFORMS" list to forward to
# unconditionally.
HELPER_TYPE_PLATFORM = {
    HelperType.COMBINE: Platform.SENSOR,
    HelperType.TEMPLATE: Platform.SENSOR,
    HelperType.TEMPLATE_BINARY: Platform.BINARY_SENSOR,
}


class AggregationFunction(StrEnum):
    """Aggregation functions available to the Combine Sensor."""

    MIN = "min"
    MAX = "max"
    MEAN = "mean"
    MEDIAN = "median"
    SUM = "sum"
    RANGE = "range"
    LAST = "last"


# Aggregation functions that require at least 2 usable (numeric) sources to
# produce a meaningful result. All other functions only need 1.
#
# This is a deliberate departure from core min_max, which has no such
# minimum (sum of 1 source = that value, range of 1 source = 0; only 0
# usable sources goes unavailable there). Confirmed with the user per SPEC
# §12, which explicitly called this edge case out as one to ask about
# rather than assume: a sum/range of a single value is either a bare
# passthrough or a possibly-misleading 0, so it's treated as not
# meaningful here and made unavailable instead.
AGGREGATIONS_REQUIRING_MULTIPLE_SOURCES = {
    AggregationFunction.SUM,
    AggregationFunction.RANGE,
}

CONF_HELPER_TYPE = "helper_type"

# Combine Sensor config keys
CONF_SOURCES = "sources"
CONF_AGGREGATION = "aggregation"

# Template Sensor / Template Binary Sensor config keys
CONF_STATE_TEMPLATE = "state_template"
CONF_AVAILABILITY_TEMPLATE = "availability_template"

# Shared config keys (schedule pattern, §3)
CONF_HOUR = "hour"
CONF_MINUTE = "minute"
CONF_SECOND = "second"

# Blank, not "*" -- the user never needs to see or type an asterisk; a
# blank hour/second is resolved into the right concrete value by
# schedule.resolve_schedule_pattern depending on what else is set (see that
# module's docstring). Minute keeps a concrete suggested default since a
# schedule needs at least one concrete field.
DEFAULT_HOUR = ""
DEFAULT_MINUTE = "/5"
DEFAULT_SECOND = ""

# Device link (§5), entity category, unit/device/state class all use existing
# homeassistant.const / homeassistant.components.sensor.const keys
# (CONF_DEVICE_ID, CONF_ENTITY_CATEGORY, CONF_UNIT_OF_MEASUREMENT,
# CONF_DEVICE_CLASS, CONF_STATE_CLASS) rather than redeclaring them here.
