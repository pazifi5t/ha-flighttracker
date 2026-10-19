# Flighttracker for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)

Shows which airliner is flying overhead right now: airline with logo, flight number, route, aircraft type, speed, altitude and distance, as Home Assistant sensors.

> **Based on [Flighttracker](https://gitlab.com/zellhuber/flighttracker) by Daniel Zellhuber**, a small e-paper display (M5Stack PaperColor) built as a gift for his dad, who loves watching planes over the Alps. This integration ports its logic (nearest-aircraft selection, route lookup, quiet hours, request budget, aircraft type and airline names) from the ESP32 to Home Assistant. Original code under the MIT License. Thank you, Daniel!

## Features

- Nearest airborne aircraft within a radius you pick on a map (default 28 km ≈ 15 NM, like the original)
- Route, airline, flight number and aircraft type from [adsbdb](https://www.adsbdb.com), cached to spare the free service
- By default only flights with a known route are shown, so private planes don't push the airliner away (can be switched off)
- Quiet hours (default 23:00–07:00) with no API requests at all
- The options form checks your settings against the OpenSky daily quota
- Airline logo as entity picture, aircraft photo as attribute
- Latitude/longitude attributes, so the plane shows up on the map card
- Event `flighttracker_new_flight` for automations (notifications, a wall panel, an ESPHome display …)
- UI setup, reconfiguration, reauthentication, diagnostics; English and German

## Installation

### HACS (recommended)

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/pazifi5t/ha-flighttracker`, category *Integration*.
2. Install **Flighttracker** and restart Home Assistant.
3. *Settings → Devices & services → Add integration → Flighttracker*.

### Manual

Copy `custom_components/flighttracker` into your `config/custom_components/` folder and restart.

## Setup

| Field | |
|---|---|
| Location and radius | Defaults to your home. Max. 100 km, so every request costs one OpenSky credit. |
| OpenSky client ID / secret | Optional. Anonymous: 400 requests/day. With a free [OpenSky account](https://opensky-network.org) 4000/day. Since March 2026 OpenSky only accepts OAuth2 API clients (no username/password): create one on your account page. |

### Options

| Option | Default | |
|---|---|---|
| Update interval | 180 s | One OpenSky request per update. |
| Only flights with a known route | on | Up to 5 nearest aircraft are looked up per update. |
| Maximum altitude | 0 (off) | e.g. 3000 m to only see approaches. |
| Quiet hours | on, 23:00–07:00 | No requests during this time. |
| Airline logo URL | [Jxck-S/airline-logos](https://github.com/Jxck-S/airline-logos) | `{icao}` is replaced by the airline ICAO code. Empty = no logos. |

Anonymous with quiet hours: 16 h × 20 requests = 320/day, below the 400 limit. Without quiet hours you need at least 216 s.

## Entities

| Entity | State | Notes |
|---|---|---|
| `sensor.…_flight` | Flight number (e.g. `LH4CK`) | All details as attributes, logo as picture, position for the map |
| `sensor.…_status` | `flight` / `clear` / `quiet` | Handy for conditional cards |
| `binary_sensor.…_aircraft_nearby` | on/off | |
| `sensor.…_airline` | e.g. `Lufthansa` | |
| `sensor.…_route` | e.g. `FCO → MUC` | |
| `sensor.…_origin`, `…_destination` | Airport name | IATA/ICAO/city/country as attributes |
| `sensor.…_aircraft_type` | e.g. `Airbus A320neo` | |
| `sensor.…_altitude`, `…_speed`, `…_distance` | m, km/h, km | Convertible units |
| `sensor.…_aircraft_in_area` | Number of aircraft | |
| `sensor.…_opensky_credits_remaining` | Remaining credits | Diagnostic |

Entity IDs follow your HA language at setup time (e.g. `sensor.flighttracker_flug` in German).

### Event `flighttracker_new_flight`

Fired when a different aircraft becomes the one shown. The data contains all attributes of the flight sensor plus `logo` and `config_entry_id`. See [`examples/automation-notify.yaml`](examples/automation-notify.yaml).

## Dashboard

[`examples/dashboard-card.yaml`](examples/dashboard-card.yaml) contains a markdown card modelled on the original e-paper layout, and a map card. Works nicely on a wall tablet.

## Data sources

- [OpenSky Network](https://opensky-network.org): live positions, free for non-commercial use. Please respect their terms of use.
- [adsbdb](https://www.adsbdb.com): airline, route and aircraft. Free and community run, so lookups are cached for 6 hours.
- Airline logos are trademarks of their respective owners and are not part of this repository.

Route data comes from callsign databases and can be wrong for charter or delayed flights.

## Development

```bash
python -m unittest discover -s tests -v
```

The pure logic in `logic.py` has no Home Assistant dependency and is covered by these tests.

## Credits & License

- Original idea, logic and aircraft/airline tables: [zellhuber/flighttracker](https://gitlab.com/zellhuber/flighttracker) by Daniel Zellhuber (MIT).
- Home Assistant integration: pazifi5t (MIT), see [LICENSE](LICENSE).
