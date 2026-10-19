"""Small async clients for OpenSky Network and adsbdb."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import aiohttp

from .const import ADSBDB_URL, OPENSKY_STATES_URL, OPENSKY_TOKEN_URL
from .logic import Lookup, parse_adsbdb

_LOGGER = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=20)
_CALLSIGN_RE = re.compile(r"[^A-Z0-9]")
_HEX_RE = re.compile(r"[^A-F0-9]")

# adsbdb results are stable, cache them to spare the free service.
CACHE_TTL_FOUND = 6 * 3600
CACHE_TTL_MISSING = 30 * 60
CACHE_MAX_ENTRIES = 500


class FlighttrackerError(Exception):
    """Generic API error."""


class FlighttrackerConnectionError(FlighttrackerError):
    """Service not reachable or returned garbage."""


class FlighttrackerAuthError(FlighttrackerError):
    """OpenSky rejected the client credentials."""


class FlighttrackerRateLimitError(FlighttrackerError):
    """OpenSky daily credits are used up."""

    def __init__(self, retry_after: int | None) -> None:
        super().__init__(f"OpenSky rate limit reached, retry after {retry_after}s")
        self.retry_after = retry_after


class OpenSkyClient:
    """Fetch state vectors from OpenSky, optionally with OAuth2."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        self._session = session
        self._client_id = client_id or None
        self._client_secret = client_secret or None
        self._token: str | None = None
        self._token_expires = 0.0
        self._token_lock = asyncio.Lock()
        self.credits_remaining: int | None = None

    @property
    def authenticated(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def _get_token(self, force: bool = False) -> str | None:
        if not self.authenticated:
            return None
        async with self._token_lock:
            if not force and self._token and time.monotonic() < self._token_expires:
                return self._token
            try:
                async with self._session.post(
                    OPENSKY_TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                    timeout=TIMEOUT,
                ) as resp:
                    if resp.status in (400, 401, 403):
                        raise FlighttrackerAuthError(
                            f"OpenSky token request rejected ({resp.status})"
                        )
                    resp.raise_for_status()
                    payload = await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise FlighttrackerConnectionError(
                    f"OpenSky token request failed: {err}"
                ) from err
            token = payload.get("access_token") if isinstance(payload, dict) else None
            if not token:
                raise FlighttrackerAuthError("OpenSky returned no access token")
            expires_in = int(payload.get("expires_in") or 1800)
            self._token = token
            # renew one minute early
            self._token_expires = time.monotonic() + max(expires_in - 60, 30)
            return token

    async def async_validate(self) -> None:
        """Check credentials (only used by the config flow)."""
        await self._get_token(force=True)

    async def async_get_states(self, box: dict[str, float]) -> list[list[Any]]:
        """Return the raw state vectors inside the bounding box."""
        for attempt in (1, 2):
            headers = {}
            token = await self._get_token(force=attempt == 2)
            if token:
                headers["Authorization"] = f"Bearer {token}"
            try:
                async with self._session.get(
                    OPENSKY_STATES_URL, params=box, headers=headers, timeout=TIMEOUT
                ) as resp:
                    remaining = resp.headers.get("X-Rate-Limit-Remaining")
                    if remaining is not None and remaining.lstrip("-").isdigit():
                        self.credits_remaining = int(remaining)
                    if resp.status == 429:
                        retry = resp.headers.get("X-Rate-Limit-Retry-After-Seconds")
                        self.credits_remaining = 0
                        raise FlighttrackerRateLimitError(
                            int(retry) if retry and retry.isdigit() else None
                        )
                    if resp.status == 401 and token and attempt == 1:
                        continue  # token expired early, fetch a new one
                    if resp.status in (401, 403) and token:
                        raise FlighttrackerAuthError(
                            f"OpenSky rejected the token ({resp.status})"
                        )
                    resp.raise_for_status()
                    payload = await resp.json(content_type=None)
            except FlighttrackerError:
                raise
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise FlighttrackerConnectionError(
                    f"OpenSky request failed: {err}"
                ) from err
            if not isinstance(payload, dict):
                raise FlighttrackerConnectionError("Unexpected OpenSky response")
            return payload.get("states") or []
        raise FlighttrackerAuthError("OpenSky rejected the token")


class AdsbdbClient:
    """Look up aircraft and route data at adsbdb.com (cached)."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._cache: dict[tuple[str, str], tuple[float, Lookup]] = {}

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict | None:
        """GET an adsbdb path. Returns `response` dict, None for 404."""
        try:
            async with self._session.get(
                f"{ADSBDB_URL}/{path}", params=params, timeout=TIMEOUT
            ) as resp:
                if resp.status == 404:
                    return None
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise FlighttrackerConnectionError(f"adsbdb request failed: {err}") from err
        response = payload.get("response") if isinstance(payload, dict) else None
        return response if isinstance(response, dict) else None

    async def async_lookup(self, icao24: str, callsign: str) -> Lookup:
        """Aircraft + route for one aircraft. Errors give an empty lookup."""
        hex_code = _HEX_RE.sub("", (icao24 or "").upper())
        call = _CALLSIGN_RE.sub("", (callsign or "").upper())
        key = (hex_code, call)
        now = time.monotonic()

        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

        try:
            lookup = await self._fetch(hex_code, call)
        except FlighttrackerConnectionError as err:
            _LOGGER.debug("adsbdb lookup for %s/%s failed: %s", hex_code, call, err)
            return Lookup()  # not cached, try again next time

        ttl = CACHE_TTL_FOUND if lookup.has_route else CACHE_TTL_MISSING
        if len(self._cache) >= CACHE_MAX_ENTRIES:
            self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
            if len(self._cache) >= CACHE_MAX_ENTRIES:
                self._cache.clear()
        self._cache[key] = (now + ttl, lookup)
        return lookup

    async def _fetch(self, hex_code: str, call: str) -> Lookup:
        if hex_code and call:
            # One request gives aircraft + route. 404 means the airframe is
            # unknown; the route may still be known, so ask for it alone.
            # (200 without "flightroute" means the callsign is unknown.)
            response = await self._get(f"aircraft/{hex_code}", {"callsign": call})
            if response is not None:
                return parse_adsbdb(response)
            return parse_adsbdb(await self._get(f"callsign/{call}"))
        if call:
            return parse_adsbdb(await self._get(f"callsign/{call}"))
        if hex_code:
            return parse_adsbdb(await self._get(f"aircraft/{hex_code}"))
        return Lookup()
