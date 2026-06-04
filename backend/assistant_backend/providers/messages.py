import json
from typing import Any

from ..agent.types import AssistantTurn, ToolCall
from .base import DeltaCallback, Provider, StepCallback
from .http_stream import StreamingHttp


class MessagesProvider(Provider):
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
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self._model,
            "system": self._system_prompt,
            "messages": self._convert(messages),
            "max_tokens": 8192,
            "stream": True,
        }
        if tools:
            body["tools"] = [
                {
                    "name": item["function"]["name"],
                    "description": item["function"]["description"],
                    "input_schema": item["function"]["parameters"],
                }
                for item in tools
            ]
        result = ""
        active: dict[int, dict[str, str]] = {}
        async for value in self._http.sse(self._endpoint, headers, body):
            event_type = value.get("type")
            if event_type == "content_block_start":
                block = value.get("content_block", {}) or {}
                if block.get("type") == "tool_use":
                    active[int(value.get("index", 0))] = {"id": str(block.get("id", "")), "name": str(block.get("name", "")), "arguments": json.dumps(block.get("input", {})) if block.get("input") else ""}
            elif event_type == "content_block_delta":
                delta = value.get("delta", {}) or {}
                if delta.get("type") == "text_delta" or "text" in delta:
                    text = str(delta.get("text", ""))
                    result += text
                    if text:
                        await on_delta(text)
                elif delta.get("type") == "input_json_delta":
                    entry = active.setdefault(int(value.get("index", 0)), {"id": "", "name": "", "arguments": ""})
                    entry["arguments"] += str(delta.get("partial_json", ""))
        return AssistantTurn(result.strip(), [self._tool_call(value) for _, value in sorted(active.items())])

    def _convert(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []

        def append(role: str, blocks: list[dict[str, Any]]) -> None:
            if output and output[-1]["role"] == role:
                output[-1]["content"].extend(blocks)
            else:
                output.append({"role": role, "content": blocks})

        for message in messages:
            role = message.get("role")
            if role == "tool":
                append("user", [{"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": message.get("content", "")}])
                continue
            blocks: list[dict[str, Any]] = []
            content = str(message.get("content", ""))
            if content:
                blocks.append({"type": "text", "text": content})
            for call in message.get("tool_calls", []) or []:
                blocks.append({"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments})
            append("assistant" if role == "assistant" else "user", blocks or [{"type": "text", "text": ""}])
        return output

    def _tool_call(self, value: dict[str, str]) -> ToolCall:
        try:
            arguments = json.loads(value["arguments"] or "{}")
        except json.JSONDecodeError:
            arguments = {"_raw": value["arguments"]}
        return ToolCall(value["id"] or value["name"], value["name"], arguments)

    async def vision(self, prompt: str, image_data_url: str) -> str:
        if not self._api_key:
            raise RuntimeError("API key is not configured.")
        prefix, encoded = image_data_url.split(",", 1)
        media_type = prefix.split(":", 1)[1].split(";", 1)[0]
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        body = {
            "model": self._model,
            "system": self._system_prompt,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}},
                {"type": "text", "text": prompt},
            ]}],
        }
        value = await self._http.post_json(self._endpoint, headers, body)
        blocks = value.get("content", [])
        return " ".join(str(item.get("text", "")) for item in blocks if item.get("type") == "text").strip()

    async def abort(self) -> None:
        await self._http.abort()
