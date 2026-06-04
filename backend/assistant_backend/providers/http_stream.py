import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx


class StreamingHttp:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def abort(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def post_json(self, endpoint: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0))
        try:
            response = await self._client.post(endpoint, headers=headers, json=body)
            if response.status_code >= 400:
                detail = response.text
                raise RuntimeError(f"Provider error {response.status_code}: {detail[:360]}")
            return response.json()
        finally:
            if self._client is not None:
                await self._client.aclose()
                self._client = None

    async def sse(self, endpoint: str, headers: dict[str, str], body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        emitted = False
        for attempt in range(2):
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0))
            try:
                async with self._client.stream("POST", endpoint, headers=headers, json=body) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", errors="replace")
                        if attempt == 0 and response.status_code in {408, 429, 500, 502, 503, 504}:
                            await asyncio.sleep(0.6)
                            continue
                        raise RuntimeError(f"Provider error {response.status_code}: {detail[:360]}")
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            return
                        try:
                            value = json.loads(data)
                        except Exception:
                            continue
                        emitted = True
                        yield value
                    return
            except (httpx.ConnectError, httpx.ReadTimeout) as error:
                if attempt == 0 and not emitted:
                    await asyncio.sleep(0.6)
                    continue
                raise RuntimeError(f"Network request failed: {error}") from error
            finally:
                if self._client is not None:
                    await self._client.aclose()
                    self._client = None

    async def ndjson(self, endpoint: str, headers: dict[str, str], body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        emitted = False
        for attempt in range(2):
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=20.0))
            try:
                async with self._client.stream("POST", endpoint, headers=headers, json=body) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", errors="replace")
                        if attempt == 0 and response.status_code in {408, 429, 500, 502, 503, 504}:
                            await asyncio.sleep(0.6)
                            continue
                        raise RuntimeError(f"Provider error {response.status_code}: {detail[:360]}")
                    async for line in response.aiter_lines():
                        data = line.strip()
                        if not data:
                            continue
                        try:
                            value = json.loads(data)
                        except Exception:
                            continue
                        emitted = True
                        yield value
                        if value.get("done") is True:
                            return
                    return
            except (httpx.ConnectError, httpx.ReadTimeout) as error:
                if attempt == 0 and not emitted:
                    await asyncio.sleep(0.6)
                    continue
                raise RuntimeError(f"Network request failed: {error}") from error
            finally:
                if self._client is not None:
                    await self._client.aclose()
                    self._client = None
