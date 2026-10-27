"""Pushes new face events to connected browsers.

Kept in-process: the backend runs as a single async worker, which is plenty
for a few dozen operators. Moving to several workers would need Redis
pub/sub here.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

from app.models import User

log = logging.getLogger(__name__)


@dataclass(eq=False)
class Client:
    ws: WebSocket
    user: User
    cameras: set[uuid.UUID] = field(default_factory=set)


class EventHub:
    def __init__(self) -> None:
        self.clients: set[Client] = set()

    def add(self, client: Client) -> None:
        self.clients.add(client)

    def remove(self, client: Client) -> None:
        self.clients.discard(client)

    async def publish(self, camera_id: uuid.UUID, payload: dict) -> None:
        targets = [c for c in self.clients if camera_id in c.cameras]
        results = await asyncio.gather(
            *(c.ws.send_json(payload) for c in targets), return_exceptions=True
        )
        for client, result in zip(targets, results):
            if isinstance(result, Exception):
                log.debug("dropping websocket client: %s", result)
                self.remove(client)


hub = EventHub()
