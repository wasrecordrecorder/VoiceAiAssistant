import asyncio
import base64
import json
import os
from collections.abc import Awaitable, Callable
from io import BytesIO

from ..core.settings import Settings
from .policy import ApprovalManager

VisionCallback = Callable[[str, str], Awaitable[str]]


class ScreenTools:
    def __init__(self, settings: Settings, approvals: ApprovalManager, vision: VisionCallback | None) -> None:
        self._settings = settings
        self._approvals = approvals
        self._vision = vision

    @staticmethod
    def schemas() -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "inspect_screen",
                    "description": "Capture the user's full current screen and analyze it with a vision-capable model. Use only when the user asks to look at the screen, identify what is visible, or when visual state is necessary to complete the requested task.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["question"],
                    },
                },
            }
        ]

    async def execute(self, arguments: dict) -> str:
        if self._vision is None:
            return self._result(False, error="Анализ экрана недоступен в текущем режиме.")
        question = str(arguments.get("question", "")).strip() or "Опиши, что видно на экране и что важно для задачи."
        reason = str(arguments.get("reason", "")).strip()
        if not self._settings.screen_capture_without_confirmation:
            accepted = await self._approvals.request(
                "inspect_screen",
                "Разрешить ассистенту посмотреть текущий экран",
                {"question": question, "reason": reason},
            )
            if not accepted:
                return self._result(False, cancelled=True, error="Пользователь отменил просмотр экрана.")
        try:
            data_url, metadata = await asyncio.to_thread(self._capture_screen)
            prompt = f"{question}\nСкриншот получен с координатами исходного экрана: ширина {metadata['screen_width']}, высота {metadata['screen_height']}. Изображение передано в масштабе {metadata['scale']:.4f}. Если для действия нужны координаты мыши, верни координаты в системе исходного экрана, а не уменьшенного изображения."
            description = await self._vision(prompt, data_url)
            return self._result(True, description=description)
        except Exception as error:
            return self._result(False, error=str(error))

    def _capture_screen(self) -> tuple[str, dict]:
        if os.name != "nt":
            raise RuntimeError("Захват экрана реализован для Windows.")
        from mss import mss
        from PIL import Image
        with mss() as capture:
            monitor = capture.monitors[0]
            raw = capture.grab(monitor)
            image = Image.frombytes("RGB", raw.size, raw.rgb)
            screen_width = image.width
            screen_height = image.height
            maximum = 1600
            scale = 1.0
            if image.width > maximum:
                height = int(image.height * maximum / image.width)
                scale = maximum / image.width
                image = image.resize((maximum, height))
            stream = BytesIO()
            image.save(stream, format="JPEG", quality=80, optimize=True)
        encoded = base64.b64encode(stream.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}", {"screen_width": screen_width, "screen_height": screen_height, "scale": scale}

    @staticmethod
    def _result(ok: bool, **payload) -> str:
        return json.dumps({"ok": ok, **payload}, ensure_ascii=False)
