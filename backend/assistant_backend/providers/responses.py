import json
from typing import Any

from ..agent.types import AssistantTurn, ToolCall
from .base import DeltaCallback, Provider, StepCallback
from .http_stream import StreamingHttp


class ResponsesProvider(Provider):
    def __init__(self, endpoint: str, api_key: str, model: str, system_prompt: str) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._model = model
        self._system_prompt = system_prompt
        self._http = StreamingHttp()

    async def turn(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], on_delta: DeltaCallback, on_step: StepCallback) -> AssistantTurn:
        if not self._api_key:
            raise RuntimeError("API key is not configured.")
        await on_step("provider", f"Запрос модели {self._model}")
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        body: dict[str, Any] = {"model": self._model, "instructions": self._system_prompt, "input": self._convert(messages), "stream": True}
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "name": item["function"]["name"],
                    "description": item["function"]["description"],
                    "parameters": item["function"]["parameters"],
                    "strict": False,
                }
                for item in tools
            ]
        result = ""
        calls: dict[str, dict[str, str]] = {}
        async for value in self._http.sse(self._endpoint, headers, body):
            event_type = value.get("type")
            if event_type == "response.output_text.delta":
                delta = str(value.get("delta", ""))
                result += delta
                if delta:
                    await on_delta(delta)
            elif event_type == "response.output_item.added":
                item = value.get("item", {}) or {}
                if item.get("type") == "function_call":
                    key = str(item.get("id", item.get("call_id", "")))
                    calls[key] = {"id": str(item.get("call_id", key)), "name": str(item.get("name", "")), "arguments": str(item.get("arguments", ""))}
            elif event_type == "response.function_call_arguments.delta":
                key = str(value.get("item_id", value.get("call_id", "")))
                entry = calls.setdefault(key, {"id": str(value.get("call_id", key)), "name": "", "arguments": ""})
                entry["arguments"] += str(value.get("delta", ""))
            elif event_type == "response.output_item.done":
                item = value.get("item", {}) or {}
                if item.get("type") == "function_call":
                    key = str(item.get("id", item.get("call_id", "")))
                    calls[key] = {"id": str(item.get("call_id", key)), "name": str(item.get("name", "")), "arguments": str(item.get("arguments", calls.get(key, {}).get("arguments", "")))}
        return AssistantTurn(result.strip(), [self._tool_call(value) for value in calls.values()])

    def _convert(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for message in messages:
            if message.get("role") == "tool":
                items.append({"type": "function_call_output", "call_id": message["tool_call_id"], "output": message.get("content", "")})
                continue
            content = str(message.get("content", ""))
            if content:
                items.append({"role": message.get("role", "user"), "content": content})
            for call in message.get("tool_calls", []) or []:
                items.append({"type": "function_call", "call_id": call.id, "name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)})
        return items

    def _tool_call(self, value: dict[str, str]) -> ToolCall:
        try:
            arguments = json.loads(value["arguments"] or "{}")
        except json.JSONDecodeError:
            arguments = {"_raw": value["arguments"]}
        return ToolCall(value["id"] or value["name"], value["name"], arguments)

    async def vision(self, prompt: str, image_data_url: str) -> str:
        if not self._api_key:
            raise RuntimeError("API key is not configured.")
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        body = {
            "model": self._model,
            "instructions": self._system_prompt,
            "input": [{"role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": image_data_url},
            ]}],
        }
        value = await self._http.post_json(self._endpoint, headers, body)
        if value.get("output_text"):
            return str(value["output_text"]).strip()
        output = []
        for item in value.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    output.append(str(content.get("text", "")))
        return " ".join(output).strip()

    async def abort(self) -> None:
        await self._http.abort()
