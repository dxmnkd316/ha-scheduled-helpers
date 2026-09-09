# Scheduled Helpers

A Home Assistant custom integration providing UI-configurable helper
entities that behave like the built-in "Combine the state of several
sensors" (`min_max`) and Template helpers, with two differences:

- Updates happen on a configurable cron-style schedule (hour/minute/second,
  each accepting a specific value, a step like `/5`, or left blank) instead
  of reacting to every source state change.
- The entity can be linked to an existing device.

Each helper is an independent entity with it's own update schedule,
source/template, and device link.

## Entity types

- **Combine Sensor** — aggregates one or more source entities' numeric
  state (min, max, mean, median, sum, range, or the most-recently-updated
  source's value) on each scheduled tick. If both a device class and a
  unit of measurement are configured, a source reporting a different but
  convertible unit (e.g. inHg vs psi for a pressure device class) is
  converted before aggregating.
- **Template Sensor** — renders a Jinja2 state template (and optional
  availability template) on each scheduled tick.
- **Template Binary Sensor** — same as the Template Sensor, but it's a
  binary sensor.

All three support an optional device link, entity category, and (for the
sensor types) unit of measurement, device class, and state class.

## Requirements

- Home Assistant Core **2026.7** or newer.

## Installation

This integration isn't published to HACS. Install manually:

1. Copy the `custom_components/scheduled_helpers/` directory from this
   repo into your Home Assistant configuration's `custom_components/`
   directory (create it if it doesn't exist), so you end up with
   `<config>/custom_components/scheduled_helpers/`.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration**, search for
   "Scheduled Helpers", and pick one of the three helper types.

## Availability

If a source is missing/unavailable, a source's state can't be read as a
number, or a template fails to render, the entity is marked unavailable
(logged as a warning) rather than silently keeping a stale value.

## Development

```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
pytest
mypy custom_components/scheduled_helpers --strict
```
