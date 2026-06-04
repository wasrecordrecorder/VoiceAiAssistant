import asyncio
import html
import ipaddress
import json
import os
import socket
from html.parser import HTMLParser
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from .policy import ApprovalManager

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocked = 0
        self._parts: list[str] = []
        self.title = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "svg", "noscript", "template"}:
            self._blocked += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "svg", "noscript", "template"} and self._blocked:
            self._blocked -= 1

    def handle_data(self, data: str) -> None:
        if self._blocked:
            return
        value = " ".join(data.split())
        if value:
            self._parts.append(value)

    def text(self) -> str:
        return "\n".join(self._parts)


class WebTools:
    def __init__(self, approvals: ApprovalManager, allow_commands: bool, event: EventCallback | None = None) -> None:
        self._approvals = approvals
        self._allow_commands = allow_commands
        self._event = event

    @staticmethod
    def schemas() -> list[dict]:
        return [
            WebTools._schema(
                "web_search",
                "Search the public internet for up-to-date information. Use it when the answer depends on current facts, websites, products, services or news.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                        "time_limit": {"type": "string", "enum": ["day", "week", "month", "year", "any"]},
                    },
                    "required": ["query"],
                },
            ),
            WebTools._schema(
                "web_news_search",
                "Search recent public news pages on the internet.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                        "time_limit": {"type": "string", "enum": ["day", "week", "month", "any"]},
                    },
                    "required": ["query"],
                },
            ),
            WebTools._schema(
                "music_search",
                "Find actual music tracks or official audio for an artist or song. Use this for requests to play music, a song or an artist; do not use generic video search for music playback.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["query"],
                },
            ),
            WebTools._schema(
                "play_music",
                "Find a real music track for the request, open it on YouTube and attempt to start playback automatically. Use this when the user asks to turn on or play music. Requires confirmation unless command actions were allowed.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["query"],
                },
            ),
            WebTools._schema(
                "music_control",
                "Control the track playing inside the assistant media dock. Use after play_music for pause, resume, stop, mute, volume changes or expanding the embedded player.",
                {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["play", "pause", "stop", "mute", "volume_up", "volume_down", "expand", "collapse"]}
                    },
                    "required": ["action"],
                },
            ),
            WebTools._schema(
                "web_video_search",
                "Search general videos on the internet, including YouTube. Use this for videos, reviews, streams or gameplay, but not for requests to play music.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["query"],
                },
            ),
            WebTools._schema(
                "web_read_page",
                "Read extracted visible text from a public web page by URL. Local and private-network URLs are blocked.",
                {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            ),
            WebTools._schema(
                "open_url",
                "Open an HTTP or HTTPS URL in the user's default browser. Use after selecting a requested page, YouTube video or music result. Requires confirmation unless command actions were allowed.",
                {
                    "type": "object",
                    "properties": {"url": {"type": "string"}, "reason": {"type": "string"}},
                    "required": ["url"],
                },
            ),
        ]

    async def execute(self, name: str, arguments: dict) -> str:
        try:
            if name == "web_search":
                return await self._search(arguments, "text")
            if name == "web_news_search":
                return await self._search(arguments, "news")
            if name == "music_search":
                return await self._music(arguments)
            if name == "play_music":
                return await self._play_music(arguments)
            if name == "music_control":
                return await self._music_control(arguments)
            if name == "web_video_search":
                return await self._videos(arguments)
            if name == "web_read_page":
                return await self._read_page(arguments)
            if name == "open_url":
                return await self._open_url(arguments)
            raise RuntimeError(f"Неизвестный веб-инструмент: {name}")
        except Exception as error:
            return self._result(False, error=str(error))

    async def _search(self, arguments: dict, kind: str) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise RuntimeError("Поисковый запрос не указан.")
        limit = min(10, max(1, int(arguments.get("max_results", 5))))
        period = {"day": "d", "week": "w", "month": "m", "year": "y"}.get(str(arguments.get("time_limit", "any")))
        def execute() -> list[dict]:
            from ddgs import DDGS
            search = DDGS(timeout=12)
            if kind == "news":
                return list(search.news(query=query, region="ru-ru", safesearch="moderate", timelimit=period, max_results=limit))
            return list(search.text(query=query, region="ru-ru", safesearch="moderate", timelimit=period, max_results=limit))
        items = await asyncio.to_thread(execute)
        normalized = []
        for item in items[:limit]:
            normalized.append({
                "title": str(item.get("title", ""))[:280],
                "url": str(item.get("href") or item.get("url") or "")[:2048],
                "snippet": str(item.get("body", ""))[:900],
                "date": str(item.get("date", ""))[:80],
                "source": str(item.get("source", ""))[:120],
            })
        return self._result(True, query=query, results=normalized)

    async def _videos(self, arguments: dict) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise RuntimeError("Запрос видео не указан.")
        limit = min(10, max(1, int(arguments.get("max_results", 5))))
        def execute() -> list[dict]:
            from ddgs import DDGS
            return list(DDGS(timeout=12).videos(query=query, region="ru-ru", safesearch="moderate", max_results=limit))
        items = await asyncio.to_thread(execute)
        normalized = []
        for item in items[:limit]:
            normalized.append({
                "title": str(item.get("title", ""))[:280],
                "url": str(item.get("content") or item.get("url") or "")[:2048],
                "description": str(item.get("description", ""))[:700],
                "duration": str(item.get("duration", ""))[:40],
                "publisher": str(item.get("publisher", ""))[:120],
            })
        return self._result(True, query=query, results=normalized)

    async def _music(self, arguments: dict) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise RuntimeError("Запрос музыки не указан.")
        limit = min(10, max(1, int(arguments.get("max_results", 6))))
        search_query = f"{query} official audio песня трек музыка"
        def execute() -> list[dict]:
            from ddgs import DDGS
            return list(DDGS(timeout=12).videos(query=search_query, region="ru-ru", safesearch="moderate", max_results=min(20, limit * 3)))
        items = await asyncio.to_thread(execute)
        positive = {
            "official audio": 8,
            "official music": 8,
            "official video": 5,
            "topic": 6,
            "audio": 5,
            "lyrics": 4,
            "lyric": 4,
            "песня": 4,
            "трек": 4,
            "клип": 3,
            "music": 3,
        }
        negative = {
            "играет": -15,
            "gameplay": -15,
            "летсплей": -15,
            "stream": -12,
            "стрим": -12,
            "реакция": -10,
            "reaction": -10,
            "обзор": -8,
            "shorts": -7,
            "minecraft": -14,
            "майнкрафт": -14,
        }
        ranked = []
        for item in items:
            title = str(item.get("title", ""))[:280]
            description = str(item.get("description", ""))[:700]
            publisher = str(item.get("publisher", ""))[:120]
            content = f"{title} {description} {publisher}".lower()
            score = sum(value for term, value in positive.items() if term in content)
            score += sum(value for term, value in negative.items() if term in content)
            ranked.append({
                "title": title,
                "url": str(item.get("content") or item.get("url") or "")[:2048],
                "description": description,
                "duration": str(item.get("duration", ""))[:40],
                "publisher": publisher,
                "music_score": score,
            })
        ranked.sort(key=lambda item: item["music_score"], reverse=True)
        candidates = [item for item in ranked if item["music_score"] >= 0][:limit]
        if not candidates:
            candidates = ranked[:limit]
        return self._result(True, query=query, intent="music_track", results=candidates)

    async def _play_music(self, arguments: dict) -> str:
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise RuntimeError("Запрос музыки не указан.")
        music = json.loads(await self._music({"query": query, "max_results": 5}))
        results = music.get("results", [])
        if not results:
            return self._result(False, error="Подходящий трек не найден.")
        selected = results[0]
        url = self._youtube_autoplay_url(str(selected.get("url", "")))
        reason = str(arguments.get("reason", "")).strip() or f"Включить трек: {selected.get('title', query)}"
        if not self._allow_commands:
            accepted = await self._approvals.request(
                "play_music",
                f"Открыть и включить музыку: {selected.get('title', query)}",
                {"url": url, "query": query, "reason": reason},
            )
            if not accepted:
                return self._result(False, cancelled=True, error="Пользователь отменил запуск музыки.")
        video_id = self._youtube_video_id(url)
        if video_id and self._event is not None:
            await self._event("media.play", {"video_id": video_id, "title": str(selected.get("title", query)), "source_url": url})
            return self._result(True, player="embedded", video_id=video_id, title=selected.get("title", ""), autoplay_attempted=True, hint="Трек отправлен во встроенный плеер ассистента. Для управления используй music_control.")
        if os.name != "nt":
            raise RuntimeError("Встроенный плеер недоступен, а внешний запуск музыки реализован только для Windows.")
        await asyncio.to_thread(os.startfile, url)
        return self._result(True, player="browser_fallback", opened=url, title=selected.get("title", ""), autoplay_attempted=True)

    async def _music_control(self, arguments: dict) -> str:
        action = str(arguments.get("action", "")).strip().lower()
        allowed = {"play", "pause", "stop", "mute", "volume_up", "volume_down", "expand", "collapse"}
        if action not in allowed:
            raise RuntimeError("Неизвестная команда встроенного плеера.")
        if self._event is None:
            raise RuntimeError("Встроенный плеер недоступен.")
        await self._event("media.control", {"action": action})
        return self._result(True, player="embedded", action=action)

    @staticmethod
    def _youtube_video_id(url: str) -> str:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if "youtu.be" in host:
            return parsed.path.strip("/").split("/")[0][:20]
        if "youtube.com" in host:
            if parsed.path == "/watch":
                return str(parse_qs(parsed.query).get("v", [""])[0])[:20]
            if parsed.path.startswith("/shorts/") or parsed.path.startswith("/embed/"):
                return parsed.path.rstrip("/").split("/")[-1][:20]
        return ""

    @staticmethod
    def _youtube_autoplay_url(url: str) -> str:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if "youtu" not in host:
            return url
        query = parsed.query or ""
        separator = "&" if query else "?"
        if "youtube.com/watch" in url and "v=" in query:
            if "autoplay=" not in query:
                query = f"{query}&autoplay=1" if query else "autoplay=1"
            if "app=desktop" not in query:
                query = f"{query}&app=desktop"
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{query}"
        if "autoplay=" in query:
            return url
        return f"{url}{separator}autoplay=1"

    async def _read_page(self, arguments: dict) -> str:
        url = str(arguments.get("url", "")).strip()
        await self._ensure_public_url(url)
        import httpx
        current = url
        response = None
        async with httpx.AsyncClient(timeout=12, headers={"User-Agent": "WebViewDA/0.7"}, follow_redirects=False) as client:
            for _ in range(4):
                response = await client.get(current)
                if response.status_code in {301, 302, 303, 307, 308}:
                    target = response.headers.get("location", "")
                    current = urljoin(current, target)
                    await self._ensure_public_url(current)
                    continue
                break
        if response is None:
            raise RuntimeError("Страница недоступна.")
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type and "text/plain" not in content_type:
            raise RuntimeError("Можно читать только HTML или текстовые веб-страницы.")
        raw = response.text[:1000000]
        if "html" in content_type:
            parser = TextExtractor()
            parser.feed(raw)
            content = parser.text()
        else:
            content = raw
        content = "\n".join(line for line in (item.strip() for item in content.splitlines()) if line)
        return self._result(True, url=current, content=html.unescape(content[:14000]))

    async def _open_url(self, arguments: dict) -> str:
        url = str(arguments.get("url", "")).strip()
        parsed = self._parse_web_url(url)
        reason = str(arguments.get("reason", "")).strip()
        if not self._allow_commands:
            accepted = await self._approvals.request("open_url", f"Открыть ссылку в браузере: {parsed.netloc}", {"url": url, "reason": reason})
            if not accepted:
                return self._result(False, cancelled=True, error="Пользователь отменил открытие ссылки.")
        if os.name != "nt":
            raise RuntimeError("Открытие браузера реализовано для Windows.")
        await asyncio.to_thread(os.startfile, url)
        return self._result(True, opened=url)

    async def _ensure_public_url(self, url: str) -> None:
        parsed = self._parse_web_url(url)
        host = parsed.hostname or ""
        if host.lower() in {"localhost", "localhost.localdomain"}:
            raise RuntimeError("Локальные URL нельзя читать через веб-инструмент.")
        def resolve() -> list[str]:
            return [value[4][0] for value in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)]
        addresses = await asyncio.to_thread(resolve)
        for value in addresses:
            address = ipaddress.ip_address(value)
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast:
                raise RuntimeError("Private-network URL нельзя читать через веб-инструмент.")

    @staticmethod
    def _parse_web_url(url: str):
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise RuntimeError("Разрешены только HTTP/HTTPS ссылки.")
        return parsed

    @staticmethod
    def _schema(name: str, description: str, parameters: dict) -> dict:
        return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}

    @staticmethod
    def _result(ok: bool, **payload) -> str:
        return json.dumps({"ok": ok, **payload}, ensure_ascii=False)
