import json
from typing import Any

from ..agent.types import AssistantTurn, ToolCall
from .base import DeltaCallback, Provider, StepCallback
from .http_stream import StreamingHttp


class ChatCompletionsProvider(Provider):
    def __init__(self, endpoint: str, api_key: str, model: str, system_prompt: str, extra_headers: dict[str, str] | None = None, reasoning_effort: str = "medium", reasoning_visible: bool = False) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._system_prompt = system_prompt
        self._headers = extra_headers or {}
        self._http = StreamingHttp()
        self._reasoning_effort = reasoning_effort
        self._reasoning_visible = reasoning_visible

    async def turn(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], on_delta: DeltaCallback, on_step: StepCallback) -> AssistantTurn:
        if not self._api_key:
            raise RuntimeError("API key is not configured.")
        await on_step("provider", f"Запрос модели {self._model}")
        converted = [{"role": "system", "content": self._system_prompt}, *self._convert(messages)]
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json", **self._headers}
        body: dict[str, Any] = {"model": self._model, "messages": converted, "stream": True}
        if self._reasoning_effort != "off":
            body["reasoning"] = {"effort": self._reasoning_effort}
            body["reasoning_effort"] = self._reasoning_effort
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        text = ""
        reasoning = ""
        calls: dict[int, dict[str, str]] = {}
        async for value in self._http.sse(self._endpoint, headers, body):
            try:
                delta = value["choices"][0]["delta"]
            except Exception:
                continue
            reasoning_delta = str(delta.get("reasoning_content") or "")
            if reasoning_delta:
                reasoning += reasoning_delta
            content = str(delta.get("content") or "")
            if content:
                text += content
                await on_delta(content)
            for item in delta.get("tool_calls", []) or []:
                index = int(item.get("index", 0))
                entry = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                entry["id"] += str(item.get("id", ""))
                function = item.get("function", {}) or {}
                entry["name"] += str(function.get("name", ""))
                entry["arguments"] += str(function.get("arguments", ""))
        return AssistantTurn(text.strip(), [self._tool_call(value) for _, value in sorted(calls.items())], reasoning)

    def _convert(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            if role == "tool":
                result.append({"role": "tool", "tool_call_id": message["tool_call_id"], "content": message.get("content", "")})
                continue
            converted: dict[str, Any] = {"role": role, "content": message.get("content", "")}
            calls = message.get("tool_calls", [])
            if calls:
                converted["tool_calls"] = [
                    {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)}}
                    for call in calls
                ]
            reasoning = str(message.get("reasoning_content", ""))
            if role == "assistant" and reasoning:
                converted["reasoning_content"] = reasoning
            result.append(converted)
        return result

    def _tool_call(self, value: dict[str, str]) -> ToolCall:
        try:
            arguments = json.loads(value["arguments"] or "{}")
        except json.JSONDecodeError:
            arguments = {"_raw": value["arguments"]}
        return ToolCall(value["id"] or value["name"], value["name"], arguments)

    async def vision(self, prompt: str, image_data_url: str) -> str:
        if not self._api_key:
            raise RuntimeError("API key is not configured.")
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json", **self._headers}
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ]},
            ],
            "stream": False,
        }
        value = await self._http.post_json(self._endpoint, headers, body)
        try:
            content = value["choices"][0]["message"]["content"]
        except Exception as error:
            raise RuntimeError("Vision-модель не вернула текстовое описание экрана.") from error
        if isinstance(content, list):
            return " ".join(str(item.get("text", "")) for item in content if isinstance(item, dict)).strip()
        return str(content).strip()

    async def abort(self) -> None:
        await self._http.abort()
