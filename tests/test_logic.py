"""Tests for the pure logic module (stdlib only, no Home Assistant needed).

Run: python -m unittest discover -s tests
"""

from __future__ import annotations

import asyncio
from datetime import time
import importlib.util
from pathlib import Path
import unittest

_PATH = Path(__file__).parents[1] / "custom_components" / "flighttracker" / "logic.py"
_spec = importlib.util.spec_from_file_location("ft_logic", _PATH)
logic = importlib.util.module_from_spec(_spec)
import sys  # noqa: E402

sys.modules["ft_logic"] = logic
_spec.loader.exec_module(logic)

HOME = (52.1508, 9.9511)  # Hildesheim


def state(icao, callsign, lat, lon, alt=10000.0, on_ground=False, vel=230.0):
    """Build an OpenSky state vector (18 fields)."""
    return [
        icao, callsign, "Germany", 0, 0, lon, lat, alt, on_ground, vel,
        90.0, 0.0, None, alt + 50, "1000", False, 0, 0,
    ]


ADSBDB_FULL = {
    "aircraft": {
        "type": "A319-112",
        "icao_type": "A319",
        "manufacturer": "Airbus SAS",
        "registration": "D-AIBD",
        "registered_owner": "Lufthansa",
        "url_photo": "https://example.org/p.jpg",
        "url_photo_thumbnail": "https://example.org/t.jpg",
    },
    "flightroute": {
        "callsign": "DLH4CK",
        "callsign_iata": "LH4CK",
        "airline": {"name": "Deutsche Lufthansa AG", "icao": "DLH", "iata": "LH"},
        "origin": {
            "iata_code": "FCO", "icao_code": "LIRF",
            "name": "Rome–Fiumicino Leonardo da Vinci International Airport",
            "municipality": "Rome", "country_name": "Italy",
        },
        "destination": {
            "iata_code": "MUC", "icao_code": "EDDM", "name": "Munich Airport",
            "municipality": "Munich", "country_name": "Germany",
        },
    },
}


class GeoTests(unittest.TestCase):
    def test_distance(self):
        # Hildesheim -> Hannover, roughly 27 km
        self.assertAlmostEqual(logic.distance_km(*HOME, 52.3759, 9.7320), 29.3, delta=1.5)

    def test_bounding_box_contains_circle(self):
        box = logic.bounding_box(*HOME, 28)
        self.assertLess(box["lamin"], HOME[0] - 0.25)
        self.assertGreater(box["lomax"], HOME[1] + 0.4)
        area = (box["lamax"] - box["lamin"]) * (box["lomax"] - box["lomin"])
        self.assertLess(area, 25)  # 1 OpenSky credit

    def test_max_radius_is_one_credit(self):
        box = logic.bounding_box(60.0, 10.0, 100)
        area = (box["lamax"] - box["lamin"]) * (box["lomax"] - box["lomin"])
        self.assertLess(area, 25)


class ParseStatesTests(unittest.TestCase):
    def test_sorted_filtered(self):
        states = [
            state("3c6444", "DLH4CK  ", 52.30, 9.95),  # ~16.6 km
            state("4ca123", "RYR12AB ", 52.16, 9.96),  # ~1.2 km
            state("abcdef", "GROUND  ", 52.15, 9.95, on_ground=True),
            state("000001", "NOPOS   ", None, None),
            state("000002", "FAR     ", 53.50, 9.95),  # outside radius
            ["short"],
        ]
        result = logic.parse_states(states, *HOME, 28)
        self.assertEqual([a.callsign for a in result], ["RYR12AB", "DLH4CK"])
        first = result[0]
        self.assertEqual(first.icao24, "4CA123")
        self.assertEqual(first.speed_kmh, 828)
        self.assertEqual(first.altitude_m, 10000)

    def test_max_altitude(self):
        states = [state("1", "LOW", 52.16, 9.96, alt=900), state("2", "HIGH", 52.17, 9.96)]
        result = logic.parse_states(states, *HOME, 28, max_altitude_m=3000)
        self.assertEqual([a.callsign for a in result], ["LOW"])

    def test_none_states(self):
        self.assertEqual(logic.parse_states(None, *HOME, 28), [])


class AdsbdbTests(unittest.TestCase):
    def test_full(self):
        lk = logic.parse_adsbdb(ADSBDB_FULL)
        self.assertTrue(lk.has_route)
        self.assertEqual(lk.flight_number, "LH4CK")
        self.assertEqual(lk.origin.iata, "FCO")
        self.assertEqual(lk.destination.city, "Munich")
        self.assertEqual(lk.aircraft_type_code, "A319")
        self.assertEqual(logic.airline_display_name(lk.airline_name), "Lufthansa")
        self.assertEqual(logic.aircraft_display_name(lk), "Airbus A319")

    def test_aircraft_only(self):
        lk = logic.parse_adsbdb({"aircraft": ADSBDB_FULL["aircraft"]})
        self.assertFalse(lk.has_route)
        self.assertEqual(lk.registration, "D-AIBD")

    def test_unknown_type_uses_adsbdb_name(self):
        lk = logic.Lookup(aircraft_type_code="A21X", aircraft_type="A321-271NX",
                          manufacturer="Airbus SAS")
        self.assertEqual(logic.aircraft_display_name(lk), "Airbus A321-271NX")

    def test_garbage(self):
        self.assertFalse(logic.parse_adsbdb("unknown callsign").has_route)


class FlightTests(unittest.TestCase):
    def test_as_dict(self):
        ac = logic.parse_states([state("3c6444", "DLH4CK", 52.16, 9.96)], *HOME, 28)[0]
        flight = logic.Flight(ac, logic.parse_adsbdb(ADSBDB_FULL))
        d = flight.as_dict()
        self.assertEqual(d["flight_number"], "LH4CK")
        self.assertEqual(d["route"], "FCO → MUC")
        self.assertEqual(d["airline"], "Lufthansa")
        self.assertEqual(d["latitude"], 52.16)

    def test_fallback_flight_number(self):
        ac = logic.parse_states([state("3c6444", "DLH4CK", 52.16, 9.96)], *HOME, 28)[0]
        flight = logic.Flight(ac, logic.Lookup())
        self.assertEqual(flight.flight_number, "DLH4CK")
        self.assertIsNone(flight.route)


class PickFlightTests(unittest.TestCase):
    def setUp(self):
        self.aircraft = logic.parse_states(
            [
                state("000001", "PRIVATE", 52.155, 9.955),
                state("3c6444", "DLH4CK", 52.20, 9.95),
                state("4ca123", "RYR12AB", 52.25, 9.95),
            ],
            *HOME, 28,
        )
        self.calls = []

    async def lookup(self, icao, callsign):
        self.calls.append(callsign)
        if callsign == "DLH4CK":
            return logic.parse_adsbdb(ADSBDB_FULL)
        return logic.Lookup()

    def pick(self, aircraft, route_required=True, previous=None, max_lookups=5):
        return asyncio.run(
            logic.pick_flight(aircraft, self.lookup, route_required, previous, max_lookups)
        )

    def test_skips_aircraft_without_route(self):
        flight = self.pick(self.aircraft)
        self.assertEqual(flight.aircraft.callsign, "DLH4CK")
        self.assertEqual(self.calls, ["PRIVATE", "DLH4CK"])

    def test_nearest_without_route_requirement(self):
        flight = self.pick(self.aircraft, route_required=False)
        self.assertEqual(flight.aircraft.callsign, "PRIVATE")

    def test_lookup_limit(self):
        self.assertIsNone(self.pick(self.aircraft, max_lookups=1))

    def test_keeps_previous_when_no_route(self):
        previous = self.pick(self.aircraft)
        others = [a for a in self.aircraft if a.callsign != "DLH4CK"]
        moved = logic.parse_states([state("3c6444", "", 52.30, 9.95)], *HOME, 28)
        flight = self.pick(others + moved, previous=previous)
        self.assertEqual(flight.aircraft.icao24, "3C6444")
        self.assertEqual(flight.flight_number, "LH4CK")
        self.assertGreater(flight.aircraft.distance_km, 15)

    def test_empty(self):
        self.assertIsNone(self.pick([]))


class TimeTests(unittest.TestCase):
    def test_quiet_over_midnight(self):
        s, e = time(23), time(7)
        self.assertTrue(logic.in_quiet_hours(time(23, 30), s, e))
        self.assertTrue(logic.in_quiet_hours(time(3), s, e))
        self.assertFalse(logic.in_quiet_hours(time(7), s, e))
        self.assertFalse(logic.in_quiet_hours(time(12), s, e))

    def test_quiet_same_day(self):
        self.assertTrue(logic.in_quiet_hours(time(13), time(12), time(14)))
        self.assertFalse(logic.in_quiet_hours(time(13), time(12), time(12)))

    def test_budget_like_original(self):
        hours = logic.active_hours_per_day(time(23), time(7), True)
        self.assertEqual(hours, 16)
        self.assertEqual(logic.requests_per_day(180, hours), 320)  # sketch comment
        self.assertEqual(logic.requests_per_day(180, 24), 480)


if __name__ == "__main__":
    unittest.main()
