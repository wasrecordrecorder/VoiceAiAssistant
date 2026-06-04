import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from websockets.asyncio.server import ServerConnection, serve

from .core.events import EventBus
from .core.settings import SettingsStore
from .runtime import AssistantRuntime


class AssistantServer:
    def __init__(self, host: str, port: int, token: str, data_dir: Path) -> None:
        self._host = host
        self._port = port
        self._token = token
        self._events = EventBus()
        self._settings = SettingsStore(data_dir)
        self._runtime = AssistantRuntime(self._settings, self._events, data_dir)

    async def run(self) -> None:
        async with serve(self._handle, self._host, self._port, max_size=24 * 1024 * 1024, ping_interval=20, ping_timeout=20):
            await asyncio.Future()

    async def _handle(self, websocket: ServerConnection) -> None:
        parsed = urlparse(websocket.request.path)
        token = parse_qs(parsed.query).get("token", [""])[0]
        if parsed.path != "/ws" or token != self._token:
            await websocket.close(code=4003, reason="Unauthorized")
            return
        await self._events.add(websocket)
        try:
            await self._events.emit("backend.ready", {"version": "0.21.0"})
            await self._events.emit("settings.current", self._runtime.settings())
            await self._events.emit("providers.catalog", self._runtime.catalog())
            await self._events.emit("audio.devices", self._runtime.devices())
            await self._events.emit("models.status", self._runtime.model_status())
            await self._events.emit("conversation.current", self._runtime.sessions())
            await self._events.emit("todo.current", self._runtime.todos())
            await self._events.emit("memory.current", self._runtime.memory())
            await self._events.emit("assistant.state", self._runtime.snapshot())
            await self._runtime.activate()
            async for raw in websocket:
                await self._dispatch(raw)
        finally:
            remaining = await self._events.remove(websocket)
            if remaining == 0:
                await self._runtime.interrupt()

    async def _dispatch(self, raw: str) -> None:
        try:
            message = json.loads(raw)
            command = str(message.get("command", ""))
            payload = message.get("payload", {}) or {}
            if command == "assistant.listen":
                await self._runtime.arm_listening()
            elif command == "assistant.pttDown":
                await self._runtime.ptt_down()
            elif command == "assistant.pttUp":
                await self._runtime.ptt_up()
            elif command == "assistant.startPassive":
                await self._runtime.start_listening()
            elif command == "assistant.stopListening":
                await self._runtime.stop_listening()
            elif command == "assistant.interrupt":
                await self._runtime.interrupt()
            elif command == "assistant.send":
                await self._runtime.submit(str(payload.get("text", "")), list(payload.get("attachments", [])), payload.get("web_search"))
            elif command == "assistant.dictate":
                await self._runtime.start_dictation()
            elif command == "agent.approve":
                await self._runtime.approve(str(payload.get("id", "")), True)
            elif command == "agent.reject":
                await self._runtime.approve(str(payload.get("id", "")), False)
            elif command == "settings.get":
                await self._events.emit("settings.current", self._runtime.settings())
            elif command == "settings.save":
                settings = self._settings.update(payload)
                if set(payload) != {"ui_mode"}:
                    await self._runtime.refresh_settings()
                await self._events.emit("settings.current", settings)
                await self._events.emit("providers.catalog", self._runtime.catalog())
                await self._events.emit("audio.devices", self._runtime.devices())
            elif command == "providers.catalog":
                await self._events.emit("providers.catalog", self._runtime.catalog())
            elif command == "audio.devices":
                await self._events.emit("audio.devices", self._runtime.devices())
            elif command == "models.status":
                await self._events.emit("models.status", self._runtime.model_status())
            elif command == "models.preload":
                await self._runtime.preload_models()
            elif command == "tts.test":
                await self._runtime.test_voice(str(payload.get("text", "Привет. Голос ассистента настроен.")))
            elif command == "conversation.new":
                await self._runtime.new_session()
            elif command == "conversation.select":
                await self._runtime.select_session(str(payload.get("id", "")))
            elif command == "conversation.clear":
                await self._runtime.clear_session()
            elif command == "conversation.rename":
                await self._runtime.rename_session(str(payload.get("id", "")), str(payload.get("title", "")))
            elif command == "conversation.archive":
                await self._runtime.archive_session(str(payload.get("id", "")), bool(payload.get("archived", True)))
            elif command == "conversation.delete":
                await self._runtime.delete_session(str(payload.get("id", "")))
            elif command == "todo.list":
                await self._events.emit("todo.current", self._runtime.todos(payload))
            elif command == "todo.create":
                await self._runtime.todo_create(payload)
            elif command == "todo.update":
                await self._runtime.todo_update(payload)
            elif command == "todo.delete":
                await self._runtime.todo_delete(str(payload.get("id", "")))
            elif command == "memory.get":
                await self._events.emit("memory.current", self._runtime.memory())
            elif command == "memory.add":
                await self._runtime.memory_add(payload)
            elif command == "memory.update":
                await self._runtime.memory_update(payload)
            elif command == "memory.delete":
                await self._runtime.memory_delete(str(payload.get("id", "")))
            elif command == "backend.ping":
                await self._events.emit("backend.pong", {})
            else:
                raise RuntimeError("Unknown backend command.")
        except Exception as error:
            await self._events.emit("assistant.error", {"message": str(error)})
