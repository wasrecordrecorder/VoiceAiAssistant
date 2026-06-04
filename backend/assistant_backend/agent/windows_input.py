import asyncio
import ctypes
import json
import os
from ctypes import wintypes

from .policy import ApprovalManager


class KeyboardTools:
    _keys = {
        "backspace": 0x08,
        "tab": 0x09,
        "enter": 0x0D,
        "shift": 0x10,
        "ctrl": 0x11,
        "alt": 0x12,
        "pause": 0x13,
        "capslock": 0x14,
        "escape": 0x1B,
        "space": 0x20,
        "pageup": 0x21,
        "pagedown": 0x22,
        "end": 0x23,
        "home": 0x24,
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
        "printscreen": 0x2C,
        "insert": 0x2D,
        "delete": 0x2E,
        "win": 0x5B,
        "volume_mute": 0xAD,
        "volume_down": 0xAE,
        "volume_up": 0xAF,
        "media_next": 0xB0,
        "media_previous": 0xB1,
        "media_stop": 0xB2,
        "media_play_pause": 0xB3,
    }
    _media = {"play_pause": "media_play_pause", "next": "media_next", "previous": "media_previous", "stop": "media_stop", "volume_up": "volume_up", "volume_down": "volume_down", "mute": "volume_mute"}

    def __init__(self, approvals: ApprovalManager, allow_commands: bool) -> None:
        self._approvals = approvals
        self._allow_commands = allow_commands

    @staticmethod
    def schemas() -> list[dict]:
        return [
            KeyboardTools._schema(
                "send_hotkey",
                "Press a keyboard shortcut in the currently focused application, for example ctrl+l, ctrl+c, alt+tab or enter. Requires confirmation unless command actions were allowed.",
                {
                    "type": "object",
                    "properties": {"keys": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 6}},
                    "required": ["keys"],
                },
            ),
            KeyboardTools._schema(
                "type_text",
                "Type Unicode text into the currently focused application. Requires confirmation unless command actions were allowed. Do not use for passwords or secrets.",
                {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            ),
            KeyboardTools._schema(
                "media_control",
                "Send a system media key such as play_pause, next, previous, stop, volume_up, volume_down or mute. Requires confirmation unless command actions were allowed.",
                {
                    "type": "object",
                    "properties": {"action": {"type": "string", "enum": ["play_pause", "next", "previous", "stop", "volume_up", "volume_down", "mute"]}},
                    "required": ["action"],
                },
            ),
            KeyboardTools._schema(
                "browser_action",
                "Perform a common browser or YouTube action in the focused browser tab, such as fullscreen, play_pause, focus_address, refresh, new_tab or close_tab. Requires confirmation unless command actions were allowed.",
                {
                    "type": "object",
                    "properties": {"action": {"type": "string", "enum": ["play_pause", "fullscreen", "theater", "mute", "focus_address", "refresh", "new_tab", "close_tab", "find"]}},
                    "required": ["action"],
                },
            ),
        ]

    async def execute(self, name: str, arguments: dict) -> str:
        try:
            if name == "send_hotkey":
                return await self._hotkey(arguments)
            if name == "type_text":
                return await self._type_text(arguments)
            if name == "media_control":
                return await self._media_control(arguments)
            if name == "browser_action":
                return await self._browser_action(arguments)
            raise RuntimeError(f"Неизвестный инструмент ввода: {name}")
        except Exception as error:
            return self._result(False, error=str(error))

    async def _hotkey(self, arguments: dict) -> str:
        keys = [str(item).strip().lower() for item in arguments.get("keys", []) if str(item).strip()]
        if not keys:
            raise RuntimeError("Клавиши не указаны.")
        if not self._allow_commands:
            accepted = await self._approvals.request("send_hotkey", f"Нажать клавиши: {' + '.join(keys)}", {"keys": keys})
            if not accepted:
                return self._result(False, cancelled=True, error="Пользователь отменил нажатие клавиш.")
        await asyncio.to_thread(self._send_keys, keys)
        return self._result(True, keys=keys)

    async def _type_text(self, arguments: dict) -> str:
        text = str(arguments.get("text", ""))
        if not text:
            raise RuntimeError("Текст для ввода пуст.")
        preview = text[:100] + ("…" if len(text) > 100 else "")
        if not self._allow_commands:
            accepted = await self._approvals.request("type_text", f"Ввести текст в активное окно: {preview}", {"length": len(text), "preview": preview})
            if not accepted:
                return self._result(False, cancelled=True, error="Пользователь отменил ввод текста.")
        await asyncio.to_thread(self._send_unicode, text)
        return self._result(True, typed_characters=len(text))


    async def _browser_action(self, arguments: dict) -> str:
        action = str(arguments.get("action", "")).strip().lower()
        mapping = {
            "play_pause": ["k"],
            "fullscreen": ["f"],
            "theater": ["t"],
            "mute": ["m"],
            "focus_address": ["ctrl", "l"],
            "refresh": ["ctrl", "r"],
            "new_tab": ["ctrl", "t"],
            "close_tab": ["ctrl", "w"],
            "find": ["ctrl", "f"],
        }
        keys = mapping.get(action)
        if keys is None:
            raise RuntimeError("Неизвестное browser-действие.")
        if not self._allow_commands:
            accepted = await self._approvals.request("browser_action", f"Выполнить действие браузера: {action}", {"action": action, "keys": keys})
            if not accepted:
                return self._result(False, cancelled=True, error="Пользователь отменил действие браузера.")
        await asyncio.to_thread(self._send_keys, keys)
        return self._result(True, action=action, keys=keys)

    async def _media_control(self, arguments: dict) -> str:
        action = str(arguments.get("action", "")).strip().lower()
        key = self._media.get(action)
        if key is None:
            raise RuntimeError("Неизвестная media-команда.")
        if not self._allow_commands:
            accepted = await self._approvals.request("media_control", f"Выполнить media-команду: {action}", {"action": action})
            if not accepted:
                return self._result(False, cancelled=True, error="Пользователь отменил media-команду.")
        await asyncio.to_thread(self._send_keys, [key])
        return self._result(True, action=action)

    def _send_keys(self, keys: list[str]) -> None:
        self._require_windows()
        values = [self._vk(item) for item in keys]
        events = [self._key_event(value, False) for value in values] + [self._key_event(value, True) for value in reversed(values)]
        self._send(events)

    def _send_unicode(self, text: str) -> None:
        self._require_windows()
        events = []
        encoded = text.encode("utf-16-le")
        for offset in range(0, len(encoded), 2):
            value = int.from_bytes(encoded[offset:offset + 2], "little")
            events.append(self._key_event(value, False, True))
            events.append(self._key_event(value, True, True))
        self._send(events)

    def _vk(self, key: str) -> int:
        if len(key) == 1 and key.isalnum():
            return ord(key.upper())
        if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
            return 0x70 + int(key[1:]) - 1
        if key not in self._keys:
            raise RuntimeError(f"Неизвестная клавиша: {key}")
        return self._keys[key]

    def _key_event(self, value: int, released: bool, unicode: bool = False):
        flags = (0x0004 if unicode else 0) | (0x0002 if released else 0)
        return INPUT(1, INPUTUNION(ki=KEYBDINPUT(0 if unicode else value, value if unicode else 0, flags, 0, 0)))

    def _send(self, events: list) -> None:
        array = (INPUT * len(events))(*events)
        sent = ctypes.windll.user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
        if sent != len(events):
            raise RuntimeError("Windows не приняла часть событий клавиатуры.")

    @staticmethod
    def _require_windows() -> None:
        if os.name != "nt":
            raise RuntimeError("Управление клавиатурой реализовано для Windows.")

    @staticmethod
    def _schema(name: str, description: str, parameters: dict) -> dict:
        return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}

    @staticmethod
    def _result(ok: bool, **payload) -> str:
        return json.dumps({"ok": ok, **payload}, ensure_ascii=False)


ULONG_PTR = wintypes.WPARAM


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]
