from typing import Any

from ..agent.types import AssistantTurn, ToolCall
from .base import DeltaCallback, Provider, StepCallback
from .http_stream import StreamingHttp


class GoogleProvider(Provider):
    def __init__(self, endpoint: str, api_key: str, model: str, system_prompt: str) -> None:
        self._base_endpoint = endpoint
        self._endpoint = f"{endpoint}:streamGenerateContent?alt=sse"
        self._api_key = api_key
        self._model = model
        self._system_prompt = system_prompt
        self._http = StreamingHttp()

    async def turn(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], on_delta: DeltaCallback, on_step: StepCallback) -> AssistantTurn:
        if not self._api_key:
            raise RuntimeError("API key is not configured.")
        await on_step("provider", f"Запрос модели {self._model}")
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        body: dict[str, Any] = {"systemInstruction": {"parts": [{"text": self._system_prompt}]}, "contents": self._convert(messages)}
        if tools:
            body["tools"] = [{"functionDeclarations": [self._declaration(item) for item in tools]}]
        result = ""
        calls: list[ToolCall] = []
        async for value in self._http.sse(self._endpoint, headers, body):
            try:
                parts = value["candidates"][0]["content"]["parts"]
            except Exception:
                continue
            for part in parts:
                delta = str(part.get("text", ""))
                if delta:
                    result += delta
                    await on_delta(delta)
                if "functionCall" in part:
                    call = part["functionCall"]
                    calls.append(ToolCall(f"google-{len(calls) + 1}", str(call.get("name", "")), dict(call.get("args", {}))))
        return AssistantTurn(result.strip(), calls)

    def _convert(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for message in messages:
            if message.get("role") == "tool":
                contents.append({"role": "user", "parts": [{"functionResponse": {"name": message.get("name", ""), "response": {"result": message.get("content", "")}}}]})
                continue
            parts: list[dict[str, Any]] = []
            content = str(message.get("content", ""))
            if content:
                parts.append({"text": content})
            for call in message.get("tool_calls", []) or []:
                parts.append({"functionCall": {"name": call.name, "args": call.arguments}})
            contents.append({"role": "model" if message.get("role") == "assistant" else "user", "parts": parts or [{"text": ""}]})
        return contents

    def _declaration(self, item: dict[str, Any]) -> dict[str, Any]:
        function = item["function"]
        return {"name": function["name"], "description": function["description"], "parameters": function["parameters"]}

    async def vision(self, prompt: str, image_data_url: str) -> str:
        if not self._api_key:
            raise RuntimeError("API key is not configured.")
        prefix, encoded = image_data_url.split(",", 1)
        media_type = prefix.split(":", 1)[1].split(";", 1)[0]
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        body = {
            "systemInstruction": {"parts": [{"text": self._system_prompt}]},
            "contents": [{"role": "user", "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": media_type, "data": encoded}},
            ]}],
        }
        value = await self._http.post_json(f"{self._base_endpoint}:generateContent", headers, body)
        try:
            parts = value["candidates"][0]["content"]["parts"]
        except Exception as error:
            raise RuntimeError("Vision-модель не вернула описание экрана.") from error
        return " ".join(str(part.get("text", "")) for part in parts if "text" in part).strip()

    async def abort(self) -> None:
        await self._http.abort()
