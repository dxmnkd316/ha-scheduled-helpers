"""Cron-style schedule pattern validation and listener registration.

Modeled on the core Time Pattern trigger
(``homeassistant.components.homeassistant.triggers.time_pattern``), with one
deliberate departure: this integration's hour/minute/second fields are
blank by default and accept blank, rather than showing the user a literal
``*``. A field's raw, possibly-blank value (exactly what the user typed, or
didn't) is what's validated and stored in the config entry; a *separate*
resolution step (``resolve_schedule_pattern``, called only when building the
actual listener pattern in sensor.py/binary_sensor.py's ``async_setup_entry``)
turns that into the concrete ``*``/int/``/n`` triple ``async_track_time_change``
needs. Keeping the raw form separate from the resolved form matters for two
reasons:

1. Reconfigure must show back exactly what the user left blank, not a
   resolved value that happened to fill in behind the scenes.
2. Resolution isn't a per-field default -- a blank field's meaning depends on
   which *other* fields are set. Naively defaulting every blank field to
   ``*`` (which is what "blank behaves like assumed default" would mean if
   applied field-by-field) reproduces the exact bug this replaced: a blank
   *second* with a concrete minute (e.g. this integration's own suggested
   ``minute: /5`` default) means "every 5 minutes", but passing
   ``second="*"`` to ``async_track_time_change`` means "every second of
   that matching minute" -- confirmed against the installed core:
   ``homeassistant.helpers.event.async_track_time_change`` resolves a ``*``
   field via ``dt_util.parse_time_expression(field, 0, 59)``, which for
   ``"*"`` returns *every* value 0-59, not "don't care, inherit the
   nearest set field's cadence". That produced exactly the "rapid-fire
   updates, then wait for the next cycle" symptom reported against a live
   instance. ``resolve_schedule_pattern`` fixes this by reading
   hour->minute->second as coarse-to-fine: the finest explicitly-set field
   is the intended cadence; anything coarser than it that's blank means
   "any" (``*``); anything finer than it that's blank means "at zero"
   (``0``), not "any".

Per-field format validation (``*``, an in-range int, or ``/n``) mirrors the
core Time Pattern trigger's ``TimePattern`` validator; reimplemented here
rather than imported since reaching into another integration's platform
module isn't a stable cross-component dependency. All validation -- per-field
format *and* the cross-field "at least one concrete field" guard -- runs from
the config/options flow's ``validate_user_input`` callback (config_flow.py's
``_make_validator``), never as a per-field ``vol.All(Selector(),
<validator>)`` marker in the schema itself: the schema is serialized to JSON
for the frontend to render the form (via ``voluptuous_serialize.convert`` on
a live 2026.7.3 instance, or ``probatio.to_field_list`` on the 2026.9.1
this repo's tests run against -- HA swapped the underlying library between
those versions), and neither serializer recognizes an arbitrary Python
callable, only specific voluptuous primitives and ``Selector`` objects.
Embedding one there passed every local test (which drives the flow manager
directly in Python, never touching JSON serialization) but crashed the real
config-flow HTTP endpoint on a live instance with ``ValueError: Unable to
convert schema: <function ...>``.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change

from .const import CONF_HOUR, CONF_MINUTE, CONF_SECOND

_FIELD_MAXIMUMS = {CONF_HOUR: 23, CONF_MINUTE: 59, CONF_SECOND: 59}
_FIELD_ORDER = (CONF_HOUR, CONF_MINUTE, CONF_SECOND)

# Blank and "*" are equivalent "not constrained by the user" markers at the
# raw-field level -- accepting an explicitly-typed "*" too costs nothing and
# means a user who types it out of habit isn't rejected.
_UNSET = ("", "*")


@dataclass(frozen=True, slots=True)
class SchedulePattern:
    """A resolved, concrete hour/minute/second cron-style pattern.

    Always fully resolved (every field is ``*``, a literal int, or ``/n``
    -- never blank): only ``resolve_schedule_pattern`` constructs one.
    """

    hour: str
    minute: str
    second: str


def _validate_time_pattern_field(field: str, value: Any) -> None:
    """Check one hour/minute/second field's format.

    Accepts blank, ``*``, a literal int in ``0..maximum``, or a step value
    ``/n`` with ``n`` in ``1..maximum`` (maximum is 23 for hour, 59 for
    minute/second). Raises ``vol.Invalid`` on a bad value; doesn't return or
    normalize anything -- the field's raw string is what's stored, and
    ``resolve_schedule_pattern`` (not this function) is what turns it into
    what ``async_track_time_change`` expects.
    """
    if value in _UNSET:
        return
    maximum = _FIELD_MAXIMUMS[field]
    if isinstance(value, str) and value.startswith("/"):
        try:
            step = int(value[1:])
        except ValueError as err:
            raise vol.Invalid(f"{field}: invalid time pattern value") from err
        if not 1 <= step <= maximum:
            raise vol.Invalid(f"{field}: step must be between 1 and {maximum}")
        return
    try:
        literal = int(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid(f"{field}: invalid time pattern value") from err
    if not 0 <= literal <= maximum:
        raise vol.Invalid(f"{field}: must be between 0 and {maximum}")


def validate_schedule_pattern(value: dict[str, Any]) -> dict[str, Any]:
    """Voluptuous validator: per-field format, then reject an all-blank/
    all-wildcard hour/minute/second pattern.

    See module docstring -- this is what actually enforces both the format
    of each field and SPEC §3's "not all wildcard" guard (now "at least one
    field must be concrete", blank having replaced ``*`` as the user-facing
    default), since neither can live in the schema itself without breaking
    the config-flow HTTP endpoint's JSON serialization.
    """
    for field in _FIELD_ORDER:
        if field in value:
            _validate_time_pattern_field(field, value[field])

    if all(value.get(field, "") in _UNSET for field in _FIELD_ORDER):
        raise vol.Invalid(
            "At least one of hour, minute, or second must be set to a "
            "specific value or step"
        )
    return value


def resolve_schedule_pattern(hour: str, minute: str, second: str) -> SchedulePattern:
    """Turn raw (possibly blank) hour/minute/second fields into the concrete
    pattern ``async_track_time_change`` needs.

    See module docstring for why this can't just default each blank field to
    ``*`` independently. Reads hour->minute->second as coarse-to-fine: the
    finest field that's actually set (not blank/``*``) is the intended
    cadence. Every blank/``*`` field coarser than it resolves to ``*``
    ("any"); every blank/``*`` field finer than it resolves to ``"0"`` ("at
    zero"), not "any". If nothing is set at all, everything resolves to
    ``*`` -- ``validate_schedule_pattern`` is what actually prevents that
    combination from reaching here.
    """
    fields = (hour, minute, second)
    concrete_indices = [i for i, f in enumerate(fields) if f not in _UNSET]
    finest = max(concrete_indices, default=-1)

    resolved: list[str] = []
    for i, f in enumerate(fields):
        if f not in _UNSET:
            resolved.append(f)
        elif finest == -1 or i < finest:
            resolved.append("*")
        else:
            resolved.append("0")

    return SchedulePattern(hour=resolved[0], minute=resolved[1], second=resolved[2])


def async_register_schedule_listener(
    hass: HomeAssistant,
    pattern: SchedulePattern,
    action: Callable[[datetime], Coroutine[Any, Any, None] | None],
) -> Callable[[], None]:
    """Register a time-pattern listener and return its unregister callback.

    ``async_track_time_change`` wraps ``action`` in its own ``HassJob``
    internally (detecting sync/async automatically) — do not pre-wrap it
    here.
    """
    return async_track_time_change(
        hass,
        action,
        hour=pattern.hour,
        minute=pattern.minute,
        second=pattern.second,
    )
