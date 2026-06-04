import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class ApprovalManager:
    def __init__(self, event: EventCallback) -> None:
        self._event = event
        self._pending: dict[str, asyncio.Future[bool]] = {}

    async def request(self, action: str, summary: str, details: dict[str, Any]) -> bool:
        approval_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending[approval_id] = future
        await self._event(
            "agent.approval_required",
            {"id": approval_id, "action": action, "summary": summary, "details": details},
        )
        try:
            return await future
        finally:
            self._pending.pop(approval_id, None)

    async def resolve(self, approval_id: str, approved: bool) -> None:
        future = self._pending.get(approval_id)
        if future is None or future.done():
            raise RuntimeError("Запрос подтверждения больше не активен.")
        future.set_result(approved)
        await self._event("agent.approval_resolved", {"id": approval_id, "approved": approved})

    def cancel_all(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_result(False)
