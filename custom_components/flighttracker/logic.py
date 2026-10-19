"""Pure helper logic (no Home Assistant or network imports).

Ported from the original Flighttracker Arduino sketch by Daniel Zellhuber
(https://gitlab.com/zellhuber/flighttracker, MIT License): bounding box,
distance calculation, nearest-aircraft selection, aircraft type names and
airline name shortening.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import time
import math
from typing import Any

EARTH_RADIUS_KM = 6371.0

# OpenSky state vector indices
# https://openskynetwork.github.io/opensky-api/rest.html
IDX_ICAO24 = 0
IDX_CALLSIGN = 1
IDX_ORIGIN_COUNTRY = 2
IDX_LON = 5
IDX_LAT = 6
IDX_BARO_ALT = 7
IDX_ON_GROUND = 8
IDX_VELOCITY = 9
IDX_TRACK = 10
IDX_VERTICAL_RATE = 11
IDX_GEO_ALT = 13
IDX_SQUAWK = 14


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres (haversine)."""
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bounding_box(lat: float, lon: float, radius_km: float) -> dict[str, float]:
    """Convert centre + radius into the box OpenSky expects."""
    lat_offset = radius_km / 111.0
    lon_offset = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    return {
        "lamin": round(lat - lat_offset, 4),
        "lomin": round(lon - lon_offset, 4),
        "lamax": round(lat + lat_offset, 4),
        "lomax": round(lon + lon_offset, 4),
    }


@dataclass(slots=True)
class Aircraft:
    """One aircraft from an OpenSky state vector."""

    icao24: str
    callsign: str
    latitude: float
    longitude: float
    distance_km: float
    altitude_m: float | None
    speed_kmh: float | None
    track: float | None
    vertical_rate_ms: float | None
    on_ground: bool
    origin_country: str | None
    squawk: str | None


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def parse_states(
    states: list[list[Any]] | None,
    home_lat: float,
    home_lon: float,
    radius_km: float,
    max_altitude_m: float = 0,
) -> list[Aircraft]:
    """Turn OpenSky states into aircraft inside the radius, nearest first.

    Aircraft on the ground or without a position are skipped. The bounding
    box is a rectangle, so the circle is enforced here.
    """
    result: list[Aircraft] = []
    for state in states or []:
        if not isinstance(state, list) or len(state) <= IDX_TRACK:
            continue
        lat = _num(state[IDX_LAT])
        lon = _num(state[IDX_LON])
        if lat is None or lon is None:
            continue
        if state[IDX_ON_GROUND]:
            continue
        dist = distance_km(home_lat, home_lon, lat, lon)
        if dist > radius_km:
            continue
        alt = _num(state[IDX_BARO_ALT])
        if alt is None and len(state) > IDX_GEO_ALT:
            alt = _num(state[IDX_GEO_ALT])
        if max_altitude_m and alt is not None and alt > max_altitude_m:
            continue
        velocity = _num(state[IDX_VELOCITY])
        result.append(
            Aircraft(
                icao24=str(state[IDX_ICAO24] or "").strip().upper(),
                callsign=str(state[IDX_CALLSIGN] or "").strip(),
                latitude=lat,
                longitude=lon,
                distance_km=round(dist, 1),
                altitude_m=round(alt) if alt is not None else None,
                speed_kmh=round(velocity * 3.6) if velocity is not None else None,
                track=_num(state[IDX_TRACK]),
                vertical_rate_ms=(
                    _num(state[IDX_VERTICAL_RATE])
                    if len(state) > IDX_VERTICAL_RATE
                    else None
                ),
                on_ground=False,
                origin_country=state[IDX_ORIGIN_COUNTRY] or None,
                squawk=(state[IDX_SQUAWK] if len(state) > IDX_SQUAWK else None)
                or None,
            )
        )
    result.sort(key=lambda a: a.distance_km)
    return result


@dataclass(slots=True)
class Airport:
    """Origin or destination airport."""

    iata: str | None = None
    icao: str | None = None
    name: str | None = None
    city: str | None = None
    country: str | None = None


@dataclass(slots=True)
class Lookup:
    """What adsbdb knows about an aircraft and its callsign."""

    has_route: bool = False
    airline_name: str | None = None
    airline_icao: str | None = None
    airline_iata: str | None = None
    flight_number: str | None = None  # IATA style, e.g. "LH725"
    origin: Airport = field(default_factory=Airport)
    destination: Airport = field(default_factory=Airport)
    aircraft_type_code: str | None = None  # ICAO, e.g. "A319"
    aircraft_type: str | None = None  # adsbdb, e.g. "A319-112"
    manufacturer: str | None = None
    registration: str | None = None
    operator: str | None = None
    photo_url: str | None = None
    photo_thumbnail_url: str | None = None


def _airport(data: dict[str, Any] | None) -> Airport:
    data = data or {}
    return Airport(
        iata=data.get("iata_code") or None,
        icao=data.get("icao_code") or None,
        name=data.get("name") or None,
        city=data.get("municipality") or None,
        country=data.get("country_name") or None,
    )


def parse_adsbdb(response: dict[str, Any] | None) -> Lookup:
    """Parse the adsbdb `response` object (aircraft and/or flightroute)."""
    lookup = Lookup()
    if not isinstance(response, dict):
        return lookup

    aircraft = response.get("aircraft")
    if isinstance(aircraft, dict):
        lookup.aircraft_type_code = aircraft.get("icao_type") or None
        lookup.aircraft_type = aircraft.get("type") or None
        lookup.manufacturer = aircraft.get("manufacturer") or None
        lookup.registration = aircraft.get("registration") or None
        lookup.operator = aircraft.get("registered_owner") or None
        lookup.photo_url = aircraft.get("url_photo") or None
        lookup.photo_thumbnail_url = aircraft.get("url_photo_thumbnail") or None

    route = response.get("flightroute")
    if isinstance(route, dict):
        lookup.has_route = True
        airline = route.get("airline") or {}
        lookup.airline_name = airline.get("name") or None
        lookup.airline_icao = airline.get("icao") or None
        lookup.airline_iata = airline.get("iata") or None
        lookup.flight_number = route.get("callsign_iata") or None
        lookup.origin = _airport(route.get("origin"))
        lookup.destination = _airport(route.get("destination"))
    return lookup


# ---------------------------------------------------------------------------
# Display helpers from the original sketch
# ---------------------------------------------------------------------------

AIRLINE_NAME_OVERRIDES: dict[str, str] = {
    "Swiss International Air Lines": "Swiss",
    "Easyjet Switzerland": "easyJet CH",
    "British Airways Plc": "British Airways",
    "Deutsche Lufthansa AG": "Lufthansa",
}

AIRCRAFT_TYPES: dict[str, str] = {
    "A19N": "Airbus A319neo",
    "A20N": "Airbus A320neo",
    "A21N": "Airbus A321neo",
    "A319": "Airbus A319",
    "A320": "Airbus A320",
    "A321": "Airbus A321",
    "A332": "Airbus A330-200",
    "A333": "Airbus A330-300",
    "A339": "Airbus A330-900neo",
    "A343": "Airbus A340-300",
    "A359": "Airbus A350-900",
    "A35K": "Airbus A350-1000",
    "A388": "Airbus A380-800",
    "B737": "Boeing 737-700",
    "B738": "Boeing 737-800",
    "B739": "Boeing 737-900",
    "B38M": "Boeing 737 MAX 8",
    "B39M": "Boeing 737 MAX 9",
    "B744": "Boeing 747-400",
    "B748": "Boeing 747-8",
    "B752": "Boeing 757-200",
    "B763": "Boeing 767-300",
    "B772": "Boeing 777-200",
    "B773": "Boeing 777-300",
    "B77L": "Boeing 777-200LR",
    "B77W": "Boeing 777-300ER",
    "B788": "Boeing 787-8",
    "B789": "Boeing 787-9",
    "B78X": "Boeing 787-10",
    "BCS1": "Airbus A220-100",
    "BCS3": "Airbus A220-300",
    "E170": "Embraer E170",
    "E190": "Embraer E190",
    "E195": "Embraer E195",
    "E290": "Embraer E190-E2",
    "E295": "Embraer E195-E2",
    "E75L": "Embraer E175",
    "E75S": "Embraer E175",
    "CRJ9": "Bombardier CRJ900",
    "CRJX": "Bombardier CRJ1000",
    "AT76": "ATR 72-600",
    "DH8D": "Bombardier Dash 8 Q400",
}


def airline_display_name(name: str | None) -> str | None:
    """Shorten overly formal airline names."""
    if not name:
        return None
    return AIRLINE_NAME_OVERRIDES.get(name, name)


def aircraft_display_name(lookup: Lookup) -> str | None:
    """Readable aircraft type, e.g. "Airbus A320neo"."""
    code = lookup.aircraft_type_code
    if code and code in AIRCRAFT_TYPES:
        return AIRCRAFT_TYPES[code]
    if lookup.aircraft_type:
        if lookup.manufacturer and lookup.manufacturer.split()[0].lower() not in (
            lookup.aircraft_type.lower()
        ):
            return f"{lookup.manufacturer.split()[0].title()} {lookup.aircraft_type}"
        return lookup.aircraft_type
    return code


def in_quiet_hours(now: time, start: time, end: time) -> bool:
    """True if `now` lies in [start, end), also across midnight."""
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def active_hours_per_day(start: time, end: time, enabled: bool) -> float:
    """Hours per day in which the API is polled."""
    if not enabled or start == end:
        return 24.0
    s = start.hour + start.minute / 60
    e = end.hour + end.minute / 60
    quiet = (e - s) % 24
    return 24.0 - quiet


def requests_per_day(interval_s: int, active_hours: float) -> int:
    """OpenSky calls per day for an interval."""
    return math.ceil(active_hours * 3600 / max(interval_s, 1))


@dataclass(slots=True)
class Flight:
    """The flight shown by the integration (aircraft + lookup)."""

    aircraft: Aircraft
    lookup: Lookup

    @property
    def flight_number(self) -> str:
        return self.lookup.flight_number or self.aircraft.callsign or self.aircraft.icao24

    @property
    def airline(self) -> str | None:
        return airline_display_name(self.lookup.airline_name)

    @property
    def route(self) -> str | None:
        if not self.lookup.has_route:
            return None
        origin = self.lookup.origin.iata or self.lookup.origin.icao or "???"
        dest = self.lookup.destination.iata or self.lookup.destination.icao or "???"
        return f"{origin} → {dest}"

    @property
    def aircraft_type(self) -> str | None:
        return aircraft_display_name(self.lookup)

    def as_dict(self) -> dict[str, Any]:
        """Flat attribute dict for the main sensor and the event."""
        lk = self.lookup
        ac = self.aircraft
        return {
            "flight_number": self.flight_number,
            "callsign": ac.callsign or None,
            "icao24": ac.icao24,
            "airline": self.airline,
            "airline_icao": lk.airline_icao,
            "airline_iata": lk.airline_iata,
            "route": self.route,
            "origin_iata": lk.origin.iata,
            "origin_icao": lk.origin.icao,
            "origin_name": lk.origin.name,
            "origin_city": lk.origin.city,
            "origin_country": lk.origin.country,
            "destination_iata": lk.destination.iata,
            "destination_icao": lk.destination.icao,
            "destination_name": lk.destination.name,
            "destination_city": lk.destination.city,
            "destination_country": lk.destination.country,
            "aircraft_type": self.aircraft_type,
            "aircraft_type_code": lk.aircraft_type_code,
            "registration": lk.registration,
            "operator": lk.operator,
            "altitude_m": ac.altitude_m,
            "speed_kmh": ac.speed_kmh,
            "heading": ac.track,
            "vertical_rate_ms": ac.vertical_rate_ms,
            "distance_km": ac.distance_km,
            "latitude": ac.latitude,
            "longitude": ac.longitude,
            "squawk": ac.squawk,
            "photo": lk.photo_url,
            "photo_thumbnail": lk.photo_thumbnail_url,
        }


async def pick_flight(
    aircraft: list[Aircraft],
    lookup: Callable[[str, str], Awaitable[Lookup]],
    route_required: bool,
    previous: Flight | None,
    max_lookups: int,
) -> Flight | None:
    """Choose the flight to show, like the original sketch does.

    - Nearest airborne aircraft wins.
    - With `route_required`, aircraft without a known route are skipped
      (up to `max_lookups` lookups). If none of them has a route but the
      previously shown aircraft is still around, it stays (with fresh
      position data) instead of flickering to "no flight".
    """
    if not aircraft:
        return None

    if not route_required:
        nearest = aircraft[0]
        return Flight(nearest, await lookup(nearest.icao24, nearest.callsign))

    for candidate in aircraft[:max_lookups]:
        if not candidate.callsign:
            continue
        result = await lookup(candidate.icao24, candidate.callsign)
        if result.has_route:
            return Flight(candidate, result)

    if previous is not None:
        for candidate in aircraft:
            if candidate.icao24 == previous.aircraft.icao24:
                return Flight(candidate, previous.lookup)
    return None


def to_dict(obj: Any) -> dict[str, Any]:
    """Dataclass to dict (for diagnostics)."""
    return asdict(obj)
