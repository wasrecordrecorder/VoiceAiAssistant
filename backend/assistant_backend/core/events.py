import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._clients: set[Any] = set()
        self._lock = asyncio.Lock()

    async def add(self, websocket: Any) -> None:
        async with self._lock:
            self._clients.add(websocket)

    async def remove(self, websocket: Any) -> int:
        async with self._lock:
            self._clients.discard(websocket)
            return len(self._clients)

    async def emit(self, event: str, payload: dict[str, Any] | None = None) -> None:
        message = json.dumps({"event": event, "payload": payload or {}}, ensure_ascii=False)
        async with self._lock:
            clients = list(self._clients)
        dead = []
        for client in clients:
            try:
                await client.send(message)
            except Exception:
                dead.append(client)
        if dead:
            async with self._lock:
                for client in dead:
                    self._clients.discard(client)
