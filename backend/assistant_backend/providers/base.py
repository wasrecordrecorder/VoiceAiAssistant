from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from ..agent.types import AssistantTurn

DeltaCallback = Callable[[str], Awaitable[None]]
StepCallback = Callable[[str, str], Awaitable[None]]


class Provider(ABC):
    @abstractmethod
    async def turn(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], on_delta: DeltaCallback, on_step: StepCallback) -> AssistantTurn:
        raise NotImplementedError

    async def answer(self, text: str, history: list[dict[str, str]], on_delta: DeltaCallback, on_step: StepCallback) -> str:
        turn = await self.turn([*history, {"role": "user", "content": text}], [], on_delta, on_step)
        return turn.content.strip()

    async def vision(self, prompt: str, image_data_url: str) -> str:
        raise RuntimeError("Выбранная модель или API-ветка не поддерживает анализ изображения экрана.")

    async def abort(self) -> None:
        return None
