import json
from typing import Any

from ..agent.types import AssistantTurn, ToolCall
from .base import DeltaCallback, Provider, StepCallback
from .http_stream import StreamingHttp


class OllamaProvider(Provider):
    def __init__(self, base_url: str, model: str, system_prompt: str) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/api/chat"
        self._model = model.strip() or "llama3.2"
        self._system_prompt = system_prompt
        self._http = StreamingHttp()

    async def turn(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], on_delta: DeltaCallback, on_step: StepCallback) -> AssistantTurn:
        await on_step("provider", f"Ollama {self._model}")
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "system", "content": self._system_prompt}, *self._convert(messages)],
            "stream": True,
        }
        if tools:
            body["tools"] = tools
        text = ""
        calls: list[ToolCall] = []
        async for value in self._http.ndjson(self._endpoint, {"Content-Type": "application/json"}, body):
            message = value.get("message") or {}
            content = str(message.get("content") or "")
            if content:
                text += content
                await on_delta(content)
            for item in message.get("tool_calls", []) or []:
                call = self._tool_call(item)
                if call.name:
                    calls.append(call)
        return AssistantTurn(text.strip(), calls, "")

    def _convert(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role", "user"))
            if role == "tool":
                result.append({"role": "tool", "content": message.get("content", "")})
                continue
            converted: dict[str, Any] = {"role": role, "content": message.get("content", "")}
            calls = message.get("tool_calls", [])
            if calls:
                converted["tool_calls"] = [
                    {"function": {"name": call.name, "arguments": call.arguments}}
                    for call in calls
                ]
            result.append(converted)
        return result

    def _tool_call(self, value: dict[str, Any]) -> ToolCall:
        function = value.get("function", {}) or {}
        name = str(function.get("name", ""))
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"_raw": arguments}
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}
        return ToolCall(name, name, arguments)

    async def vision(self, prompt: str, image_data_url: str) -> str:
        header, _, payload = image_data_url.partition(",")
        if not payload:
            raise RuntimeError("Некорректное изображение для Ollama vision.")
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": prompt, "images": [payload]},
            ],
            "stream": False,
        }
        value = await self._http.post_json(self._endpoint, {"Content-Type": "application/json"}, body)
        try:
            return str(value["message"]["content"]).strip()
        except Exception as error:
            raise RuntimeError("Ollama vision-модель не вернула текстовое описание.") from error

    async def abort(self) -> None:
        await self._http.abort()
