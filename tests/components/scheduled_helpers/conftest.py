"""Shared fixtures for Scheduled Helpers tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Make custom_components/scheduled_helpers loadable via the hass fixture."""
