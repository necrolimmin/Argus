"""Runs network discovery in-process (development) or in the scanner container.

In Docker the backend sits on an isolated bridge network where multicast
cannot reach the cameras, so discovery goes through the `scanner` service,
which uses the host's network directly.
"""

import httpx

from app.config import get_settings
from app.services import discovery


class ScanUnavailable(Exception):
    pass


async def _remote(path: str, payload: dict) -> list[dict]:
    s = get_settings()
    try:
        async with httpx.AsyncClient(base_url=s.scanner_url, timeout=180) as c:
            r = await c.post(path, json=payload, headers={"X-Service-Token": s.service_token})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as exc:
        raise ScanUnavailable() from exc


async def discover() -> list[dict]:
    if get_settings().scanner_url:
        return await _remote("/discover", {})
    return [f.as_dict() for f in await discovery.discover()]


async def scan_ranges(ranges: list[str]) -> list[dict]:
    if get_settings().scanner_url:
        return await _remote("/range", {"ranges": ranges})
    return [f.as_dict() for f in await discovery.scan_ranges(ranges)]
