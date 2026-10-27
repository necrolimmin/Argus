"""The scanner service: network discovery on the host's network.

Started from the backend image with `uvicorn app.scanner_app:app` and
`network_mode: host`, so multicast probes reach the real network segment.
It holds no data; the backend calls it with the shared service token.
"""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.deps import require_service
from app.services import discovery

app = FastAPI(title="Argus scanner", docs_url=None, openapi_url=None)


class RangeIn(BaseModel):
    ranges: list[str] = Field(min_length=1, max_length=32)


@app.get("/health")
async def health():
    return {"status": "ok", "interfaces": discovery.local_ipv4()}


@app.post("/discover")
async def discover(_: Annotated[None, Depends(require_service)]):
    return [f.as_dict() for f in await discovery.discover()]


@app.post("/range")
async def scan_range(body: RangeIn, _: Annotated[None, Depends(require_service)]):
    try:
        found = await discovery.scan_ranges(body.ranges)
    except (ValueError, OverflowError) as exc:
        raise HTTPException(422, "range_invalid") from exc
    return [f.as_dict() for f in found]
