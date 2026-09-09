"""Tests for schedule.py: pattern validation and blank-field resolution.

SPEC §3 requires blank hour/second fields (rather than a literal ``*``) to
resolve into the correct concrete pattern -- see resolve_schedule_pattern's
docstring for why a blank field can't just default to ``*`` independently
(that reproduces the exact "fires every second of the matching minute, then
waits" bug this replaced, confirmed against a live instance).
"""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.scheduled_helpers.const import CONF_HOUR, CONF_MINUTE, CONF_SECOND
from custom_components.scheduled_helpers.schedule import (
    SchedulePattern,
    resolve_schedule_pattern,
    validate_schedule_pattern,
)


def test_resolve_only_minute_set_treats_hour_as_any_and_second_as_zero() -> None:
    """The suggested default (minute=/5, hour/second blank): fire once every
    5 minutes at second 0, not every second of every matching minute.
    """
    assert resolve_schedule_pattern("", "/5", "") == SchedulePattern(
        hour="*", minute="/5", second="0"
    )


def test_resolve_only_hour_set_treats_minute_and_second_as_zero() -> None:
    """hour=3 alone means "once daily at 3:00:00", not "every second of
    every minute during hour 3".
    """
    assert resolve_schedule_pattern("3", "", "") == SchedulePattern(
        hour="3", minute="0", second="0"
    )


def test_resolve_only_second_set_treats_hour_and_minute_as_any() -> None:
    """second=/30 alone means "every 30 seconds, continuously"."""
    assert resolve_schedule_pattern("", "", "/30") == SchedulePattern(
        hour="*", minute="*", second="/30"
    )


def test_resolve_hour_and_second_set_minute_blank_is_any() -> None:
    """A blank field *between* two concrete fields is still "any": hour=3,
    second=5, minute blank -> fires at second 5 of every minute during hour
    3 (a legitimate, if unusual, explicit pattern -- minute wasn't left
    blank by not touching it, the surrounding fields just don't constrain
    it any further).
    """
    assert resolve_schedule_pattern("3", "", "5") == SchedulePattern(
        hour="3", minute="*", second="5"
    )


def test_resolve_explicit_asterisk_behaves_like_blank() -> None:
    """A user-typed "*" is treated identically to a blank field."""
    assert resolve_schedule_pattern("*", "/5", "*") == resolve_schedule_pattern(
        "", "/5", ""
    )


def test_validate_accepts_blank_and_asterisk_fields() -> None:
    validate_schedule_pattern({CONF_HOUR: "", CONF_MINUTE: "/5", CONF_SECOND: "*"})


def test_validate_rejects_all_blank() -> None:
    with pytest.raises(vol.Invalid, match="specific value or step"):
        validate_schedule_pattern(
            {CONF_HOUR: "", CONF_MINUTE: "", CONF_SECOND: ""}
        )


def test_validate_rejects_all_wildcard() -> None:
    with pytest.raises(vol.Invalid, match="specific value or step"):
        validate_schedule_pattern(
            {CONF_HOUR: "*", CONF_MINUTE: "*", CONF_SECOND: "*"}
        )


@pytest.mark.parametrize("bad_value", ["60", "-1", "banana", "/0", "/60"])
def test_validate_rejects_out_of_range_minute(bad_value: str) -> None:
    with pytest.raises(vol.Invalid):
        validate_schedule_pattern(
            {CONF_HOUR: "", CONF_MINUTE: bad_value, CONF_SECOND: ""}
        )
