import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

import numpy as np

from ..core.settings import Settings

EventCallback = Callable[[str, dict], Awaitable[None]]


class SpeechToText(ABC):
    @abstractmethod
    async def prepare(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def transcribe(self, audio: np.ndarray) -> str:
        raise NotImplementedError

    async def transcribe_partial(self, audio: np.ndarray) -> str:
        return await self.transcribe(audio)


class FasterWhisperStt(SpeechToText):
    def __init__(self, model_name: str, event: EventCallback) -> None:
        self._model_name = model_name
        self._event = event
        self._model = None
        self._loading = asyncio.Lock()
        self._decode_lock = asyncio.Lock()

    async def prepare(self) -> None:
        await self._load()

    async def _load(self) -> None:
        if self._model is not None:
            return
        async with self._loading:
            if self._model is not None:
                return
            model = f"faster-whisper/{self._model_name}"
            await self._event("model.loading", {"component": "stt", "model": model, "detail": "Загружаю модель распознавания"})
            try:
                from faster_whisper import WhisperModel
                self._model = await asyncio.to_thread(WhisperModel, self._model_name, device="cpu", compute_type="int8")
            except Exception as error:
                await self._event("model.error", {"component": "stt", "model": model, "message": str(error)})
                raise RuntimeError(f"Не удалось подготовить Whisper: {error}") from error
            await self._event("model.ready", {"component": "stt", "model": model})

    def _decode(self, audio: np.ndarray) -> str:
        segments, _ = self._model.transcribe(audio, language="ru", beam_size=1, condition_on_previous_text=False, vad_filter=False)
        return " ".join(segment.text.strip() for segment in segments).strip()

    async def transcribe(self, audio: np.ndarray) -> str:
        await self._load()
        async with self._decode_lock:
            return await asyncio.to_thread(self._decode, audio)


class VoskStt(SpeechToText):
    def __init__(self, model_path: str, event: EventCallback) -> None:
        self._path = model_path
        self._event = event
        self._model = None
        self._loading = asyncio.Lock()
        self._decode_lock = asyncio.Lock()

    async def prepare(self) -> None:
        await self._load()

    async def _load(self) -> None:
        if self._model is not None:
            return
        if not self._path:
            raise RuntimeError("Укажите папку модели Vosk в настройках.")
        async with self._loading:
            if self._model is not None:
                return
            await self._event("model.loading", {"component": "stt", "model": "vosk", "detail": "Загружаю локальную модель распознавания"})
            try:
                from vosk import Model
                self._model = await asyncio.to_thread(Model, self._path)
            except Exception as error:
                await self._event("model.error", {"component": "stt", "model": "vosk", "message": str(error)})
                raise RuntimeError(f"Не удалось подготовить Vosk: {error}") from error
            await self._event("model.ready", {"component": "stt", "model": "vosk"})

    def _decode(self, audio: np.ndarray, partial: bool = False) -> str:
        import json
        from vosk import KaldiRecognizer
        recognizer = KaldiRecognizer(self._model, 16000)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        recognizer.AcceptWaveform(pcm)
        result = recognizer.PartialResult() if partial else recognizer.FinalResult()
        key = "partial" if partial else "text"
        return str(json.loads(result).get(key, "")).strip()

    async def transcribe(self, audio: np.ndarray) -> str:
        await self._load()
        async with self._decode_lock:
            return await asyncio.to_thread(self._decode, audio, False)

    async def transcribe_partial(self, audio: np.ndarray) -> str:
        await self._load()
        async with self._decode_lock:
            return await asyncio.to_thread(self._decode, audio, True)


def create_stt(settings: Settings, event: EventCallback) -> SpeechToText:
    if settings.stt_engine == "vosk":
        return VoskStt(settings.vosk_model_path, event)
    return FasterWhisperStt(settings.stt_model, event)
