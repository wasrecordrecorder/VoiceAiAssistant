from collections.abc import Awaitable, Callable
from typing import Any

from ..providers.base import DeltaCallback, Provider, StepCallback
from .tools import ToolRegistry

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class AgentLoop:
    def __init__(self, provider: Provider, tools: ToolRegistry, max_steps: int, event: EventCallback) -> None:
        self._provider = provider
        self._tools = tools
        self._max_steps = max_steps
        self._event = event

    async def run(self, text: str, history: list[dict[str, str]], on_delta: DeltaCallback, on_step: StepCallback) -> str:
        messages: list[dict[str, Any]] = [*history, {"role": "user", "content": text}]
        schemas = self._tools.schemas()
        for step in range(1, self._max_steps + 1):
            await self._event("agent.iteration", {"current": step, "maximum": self._max_steps})
            buffered: list[str] = []

            async def collect(delta: str) -> None:
                buffered.append(delta)

            turn = await self._provider.turn(messages, schemas, collect, on_step)
            content = turn.content or "".join(buffered)
            if not turn.tool_calls:
                if content.strip():
                    await on_delta(content)
                return content.strip()
            assistant_message: dict[str, Any] = {"role": "assistant", "content": content, "tool_calls": turn.tool_calls}
            if turn.reasoning_content:
                assistant_message["reasoning_content"] = turn.reasoning_content
            messages.append(assistant_message)
            for call in turn.tool_calls:
                await self._event("agent.tool_started", {"id": call.id, "name": call.name, "arguments": call.arguments})
                result = await self._tools.execute(call.name, call.arguments)
                messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": result})
                await self._event("agent.tool_finished", {"id": call.id, "name": call.name, "result": result[:1400]})
        raise RuntimeError("Агент достиг лимита шагов без финального ответа.")
