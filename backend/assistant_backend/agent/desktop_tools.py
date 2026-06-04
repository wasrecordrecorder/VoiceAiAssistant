import asyncio
import ctypes
import json
import os
import time
from ctypes import wintypes

from .policy import ApprovalManager


class DesktopInteractionTools:
    def __init__(self, approvals: ApprovalManager, allow_commands: bool) -> None:
        self._approvals = approvals
        self._allow_commands = allow_commands

    @staticmethod
    def schemas() -> list[dict]:
        schema = DesktopInteractionTools._schema
        return [
            schema(
                "screen_metrics",
                "Get virtual desktop bounds and current mouse cursor position before using coordinate interaction.",
                {"type": "object", "properties": {}},
            ),
            schema(
                "window_list",
                "List visible top-level Windows application windows and their screen bounds. Use to find a target application before activating or interacting with it.",
                {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 80}}},
            ),
            schema(
                "window_activate",
                "Bring an application window returned by window_list to the foreground. Requires confirmation unless command actions were allowed.",
                {"type": "object", "properties": {"hwnd": {"type": "integer"}, "title": {"type": "string"}}, "required": ["hwnd"]},
            ),
            schema(
                "mouse_move",
                "Move the pointer to absolute screen coordinates. Use inspect_screen or screen_metrics first. Requires confirmation unless command actions were allowed.",
                {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]},
            ),
            schema(
                "mouse_click",
                "Click an absolute screen position with left, right or middle mouse button. Can single-click or double-click. Requires confirmation unless command actions were allowed.",
                {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "enum": ["left", "right", "middle"]}, "count": {"type": "integer", "minimum": 1, "maximum": 2}}, "required": ["x", "y"]},
            ),
            schema(
                "mouse_drag",
                "Drag from one absolute screen position to another. Requires confirmation unless command actions were allowed.",
                {"type": "object", "properties": {"from_x": {"type": "integer"}, "from_y": {"type": "integer"}, "to_x": {"type": "integer"}, "to_y": {"type": "integer"}, "button": {"type": "string", "enum": ["left", "right"]}}, "required": ["from_x", "from_y", "to_x", "to_y"]},
            ),
            schema(
                "mouse_scroll",
                "Scroll at an absolute screen position. Positive clicks scroll up and negative clicks scroll down. Requires confirmation unless command actions were allowed.",
                {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}, "clicks": {"type": "integer", "minimum": -20, "maximum": 20}}, "required": ["x", "y", "clicks"]},
            ),
        ]

    async def execute(self, name: str, arguments: dict) -> str:
        try:
            if name == "screen_metrics":
                return await asyncio.to_thread(self._screen_metrics)
            if name == "window_list":
                return await asyncio.to_thread(self._window_list, str(arguments.get("query", "")), int(arguments.get("limit", 30)))
            if name == "window_activate":
                return await self._window_activate(arguments)
            if name == "mouse_move":
                return await self._mouse_move(arguments)
            if name == "mouse_click":
                return await self._mouse_click(arguments)
            if name == "mouse_drag":
                return await self._mouse_drag(arguments)
            if name == "mouse_scroll":
                return await self._mouse_scroll(arguments)
            raise RuntimeError(f"Неизвестный desktop tool: {name}")
        except Exception as error:
            return self._result(False, error=str(error))

    async def _allow(self, action: str, summary: str, details: dict) -> bool:
        if self._allow_commands:
            return True
        return await self._approvals.request(action, summary, details)

    async def _window_activate(self, arguments: dict) -> str:
        hwnd = int(arguments.get("hwnd", 0))
        if hwnd <= 0:
            raise RuntimeError("Не передан корректный hwnd.")
        if not await self._allow("window_activate", f"Переключиться на окно {arguments.get('title', hwnd)}", {"hwnd": hwnd, "title": arguments.get("title", "")}):
            return self._result(False, cancelled=True)
        await asyncio.to_thread(self._activate_window, hwnd)
        return self._result(True, hwnd=hwnd)

    async def _mouse_move(self, arguments: dict) -> str:
        x, y = int(arguments["x"]), int(arguments["y"])
        if not await self._allow("mouse_move", f"Переместить указатель в точку {x}, {y}", {"x": x, "y": y}):
            return self._result(False, cancelled=True)
        await asyncio.to_thread(self._set_cursor, x, y)
        return self._result(True, x=x, y=y)

    async def _mouse_click(self, arguments: dict) -> str:
        x, y = int(arguments["x"]), int(arguments["y"])
        button = str(arguments.get("button", "left")).lower()
        count = max(1, min(2, int(arguments.get("count", 1))))
        if not await self._allow("mouse_click", f"{'Двойной ' if count == 2 else ''}клик {button} в точке {x}, {y}", {"x": x, "y": y, "button": button, "count": count}):
            return self._result(False, cancelled=True)
        await asyncio.to_thread(self._click, x, y, button, count)
        return self._result(True, x=x, y=y, button=button, count=count)

    async def _mouse_drag(self, arguments: dict) -> str:
        values = {key: int(arguments[key]) for key in ("from_x", "from_y", "to_x", "to_y")}
        button = str(arguments.get("button", "left")).lower()
        if not await self._allow("mouse_drag", f"Перетащить указатель из {values['from_x']}, {values['from_y']} в {values['to_x']}, {values['to_y']}", {**values, "button": button}):
            return self._result(False, cancelled=True)
        await asyncio.to_thread(self._drag, values, button)
        return self._result(True, **values, button=button)

    async def _mouse_scroll(self, arguments: dict) -> str:
        x, y, clicks = int(arguments["x"]), int(arguments["y"]), int(arguments["clicks"])
        if clicks == 0:
            return self._result(True, x=x, y=y, clicks=0)
        if not await self._allow("mouse_scroll", f"Прокрутить в точке {x}, {y}: {clicks}", {"x": x, "y": y, "clicks": clicks}):
            return self._result(False, cancelled=True)
        await asyncio.to_thread(self._scroll, x, y, clicks)
        return self._result(True, x=x, y=y, clicks=clicks)

    def _screen_metrics(self) -> str:
        self._require_windows()
        user32 = ctypes.windll.user32
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        return self._result(
            True,
            left=user32.GetSystemMetrics(76),
            top=user32.GetSystemMetrics(77),
            width=user32.GetSystemMetrics(78),
            height=user32.GetSystemMetrics(79),
            cursor={"x": point.x, "y": point.y},
        )

    def _window_list(self, query: str, limit: int) -> str:
        self._require_windows()
        user32 = ctypes.windll.user32
        target = query.casefold().strip()
        items = []

        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def collect(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            value = title.value.strip()
            if not value or target and target not in value.casefold():
                return True
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            items.append({"hwnd": int(hwnd), "title": value, "bounds": {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom}})
            return len(items) < max(1, min(80, limit))

        user32.EnumWindows(callback_type(collect), 0)
        return self._result(True, windows=items)

    def _activate_window(self, hwnd: int) -> None:
        self._require_windows()
        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            raise RuntimeError("Окно больше не существует.")
        user32.ShowWindow(hwnd, 9)
        if not user32.SetForegroundWindow(hwnd):
            raise RuntimeError("Windows не разрешила переключить фокус на окно.")

    def _set_cursor(self, x: int, y: int) -> None:
        self._require_windows()
        if not ctypes.windll.user32.SetCursorPos(x, y):
            raise RuntimeError("Windows не смогла переместить указатель.")

    def _click(self, x: int, y: int, button: str, count: int) -> None:
        self._set_cursor(x, y)
        down, up = self._button_flags(button)
        for _ in range(count):
            self._mouse_event(down)
            self._mouse_event(up)
            if count > 1:
                time.sleep(0.06)

    def _drag(self, values: dict, button: str) -> None:
        self._set_cursor(values["from_x"], values["from_y"])
        down, up = self._button_flags(button)
        self._mouse_event(down)
        steps = 18
        for index in range(1, steps + 1):
            ratio = index / steps
            x = round(values["from_x"] + (values["to_x"] - values["from_x"]) * ratio)
            y = round(values["from_y"] + (values["to_y"] - values["from_y"]) * ratio)
            self._set_cursor(x, y)
            time.sleep(0.01)
        self._mouse_event(up)

    def _scroll(self, x: int, y: int, clicks: int) -> None:
        self._set_cursor(x, y)
        self._mouse_event(0x0800, clicks * 120)

    @staticmethod
    def _button_flags(button: str) -> tuple[int, int]:
        values = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}
        if button not in values:
            raise RuntimeError("Неизвестная кнопка мыши.")
        return values[button]

    @staticmethod
    def _mouse_event(flags: int, data: int = 0) -> None:
        ctypes.windll.user32.mouse_event(flags, 0, 0, data, 0)

    @staticmethod
    def _require_windows() -> None:
        if os.name != "nt":
            raise RuntimeError("Desktop interaction реализован для Windows.")

    @staticmethod
    def _schema(name: str, description: str, parameters: dict) -> dict:
        return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}

    @staticmethod
    def _result(ok: bool, **payload) -> str:
        return json.dumps({"ok": ok, **payload}, ensure_ascii=False)
