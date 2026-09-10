# Scheduled Helpers

A Home Assistant custom integration providing UI-configurable helper
entities that behave like the built-in "Combine the state of several
sensors" (`min_max`) and Template helpers, with two differences:

- Updates happen on a configurable cron-style schedule (hour/minute/second,
  each accepting a specific value, a step like `/5`, or left blank) instead
  of reacting to every source state change.
- The entity can be linked to an existing device.

Each helper is an independent entity with its own update schedule,
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

### Via HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dxmnkd316&repository=ha-scheduled-helpers&category=integration)

If this repository isn't yet in the default HACS store, add it as a
[custom repository](https://hacs.xyz/docs/faq/custom_repositories/) instead:
in HACS, open the 3-dot menu → **Custom repositories**, add
`https://github.com/dxmnkd316/ha-scheduled-helpers`, category
**Integration**, then install "Scheduled Helpers" from HACS as normal.

Restart Home Assistant after installing, then go to **Settings → Devices
& Services → Add Integration**, search for "Scheduled Helpers", and pick
one of the three helper types.

### Manual

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
