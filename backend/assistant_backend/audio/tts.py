import asyncio
import re
import threading
import traceback
from collections.abc import Awaitable, Callable

import numpy as np
import sounddevice as sd

from ..core.settings import Settings
from .devices import resolve_device
from .speech_text import normalize_for_speech

EventCallback = Callable[[str, dict], Awaitable[None]]


class SpeechOutput:
    sample_rate = 48000
    block_size = 1536

    def __init__(self, settings: Settings, on_event: EventCallback) -> None:
        self._settings = settings
        self._on_event = on_event
        self._engine = settings.tts_engine
        self._voice = settings.tts_voice
        self._model = None
        self._device = None
        self._stop = threading.Event()
        self._queue: asyncio.Queue[str | None] | None = None
        self._audio_queue: asyncio.Queue[np.ndarray | None] | None = None
        self._prefetch_ms = max(0, min(1000, int(settings.tts_prefetch_ms)))
        self._batch_chars = max(80, min(1000, int(settings.tts_batch_chars)))
        self._worker: asyncio.Task | None = None
        self._loading = asyncio.Lock()

    @property
    def model_name(self) -> str:
        if self._engine == "edge":
            return f"microsoft-neural/{self._voice}"
        return "silero/v5_5_ru"

    async def begin(self) -> None:
        await self.stop()
        self._stop.clear()
        self._queue = asyncio.Queue()
        self._audio_queue = asyncio.Queue(maxsize=2048)
        self._worker = asyncio.create_task(self._run_stream())

    async def add(self, text: str) -> None:
        spoken = normalize_for_speech(text)
        if self._queue is not None and spoken:
            await self._queue.put(spoken)

    async def finish(self) -> None:
        if self._queue is not None:
            await self._queue.put(None)
        if self._worker is not None:
            await self._worker
        self._worker = None
        self._queue = None
        self._audio_queue = None

    async def stop(self) -> None:
        self._stop.set()
        sd.stop()
        if self._worker and not self._worker.done():
            self._worker.cancel()
            try:
                await self._worker
            except BaseException:
                pass
        self._worker = None
        self._queue = None
        self._audio_queue = None

    async def prepare(self) -> None:
        await self._load()

    async def speak(self, text: str) -> None:
        if not self._settings.tts_enabled or not text.strip():
            return
        await self.begin()
        for chunk in self.split_chunks(text):
            await self.add(chunk)
        await self.finish()

    @staticmethod
    def split_chunks(text: str) -> list[str]:
        chunks, tail = SpeechOutput.consume_chunks(text, True)
        if tail.strip():
            chunks.append(tail.strip())
        return chunks

    @staticmethod
    def consume_chunks(text: str, final: bool = False) -> tuple[list[str], str]:
        remaining = text
        chunks: list[str] = []
        while True:
            boundaries: list[int] = []
            for match in re.finditer(r"[.!?;:\n]", remaining):
                if match.end() >= 10 and (match.end() == len(remaining) or remaining[match.end()].isspace()):
                    boundaries.append(match.end())
            for match in re.finditer(r",", remaining):
                if match.end() >= 15 and (match.end() == len(remaining) or remaining[match.end()].isspace()):
                    boundaries.append(match.end())
            cut = min(boundaries) if boundaries else -1
            if cut < 0 and len(remaining) >= 42:
                cut = remaining.rfind(" ", 20, 42)
                if cut < 0:
                    cut = 38
            if cut < 0:
                break
            chunk = remaining[:cut].strip()
            if chunk:
                chunks.append(chunk)
            remaining = remaining[cut:].lstrip()
        if final and remaining.strip():
            chunks.append(remaining.strip())
            remaining = ""
        return chunks, remaining

    async def _load(self) -> None:
        if self._engine == "edge":
            await self._load_edge()
        else:
            await self._load_silero()

    async def _load_edge(self) -> None:
        if self._model == "edge":
            return
        async with self._loading:
            if self._model == "edge":
                return
            await self._on_event("model.loading", {"component": "tts", "model": self.model_name, "detail": "Проверяю Microsoft Neural voice"})
            try:
                import edge_tts
                if not edge_tts:
                    raise RuntimeError("edge-tts недоступен")
            except Exception as error:
                traceback.print_exc()
                message = f"Не удалось подготовить Microsoft Neural TTS: {error}. Диагностика записана в backend.log."
                await self._on_event("model.error", {"component": "tts", "model": self.model_name, "message": message})
                raise RuntimeError(message) from error
            self._model = "edge"
            await self._on_event("model.ready", {"component": "tts", "model": self.model_name, "voice": self._voice})

    async def _load_silero(self) -> None:
        if self._model is not None:
            return
        async with self._loading:
            if self._model is not None:
                return
            await self._on_event("model.loading", {"component": "tts", "model": self.model_name, "detail": "Загружаю локальную русскую озвучку"})
            try:
                await asyncio.to_thread(self._load_silero_sync)
            except Exception as error:
                traceback.print_exc()
                message = f"Не удалось загрузить Silero TTS: {error}. Диагностика записана в backend.log."
                await self._on_event("model.error", {"component": "tts", "model": self.model_name, "message": message})
                raise RuntimeError(message) from error
            await self._on_event("model.ready", {"component": "tts", "model": self.model_name, "voice": self._voice})

    def _load_silero_sync(self) -> None:
        import torch
        torch.set_num_threads(max(1, min(4, int(torch.get_num_threads()))))
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-models",
            model="silero_tts",
            language="ru",
            speaker="v5_5_ru",
            trust_repo=True,
            force_reload=False,
            verbose=False,
        )
        self._model.to(self._device)
        available = list(getattr(self._model, "speakers", []) or [])
        if available and self._voice not in available:
            self._voice = "xenia" if "xenia" in available else available[0]

    async def _synthesize_silero(self, text: str) -> np.ndarray:
        return await asyncio.to_thread(self._synth_silero, text)

    def _synth_silero(self, text: str) -> np.ndarray:
        import torch
        with torch.inference_mode():
            audio = self._model.apply_tts(
                text=text,
                speaker=self._voice,
                sample_rate=self.sample_rate,
                put_accent=True,
                put_yo=True,
            )
        value = audio.detach().cpu().numpy().astype(np.float32)
        speed = max(0.7, min(1.35, float(self._settings.tts_speed)))
        if speed != 1.0 and value.size > 1:
            source = np.arange(value.size, dtype=np.float32)
            target = np.arange(0, value.size - 1, speed, dtype=np.float32)
            value = np.interp(target, source, value).astype(np.float32)
        return value

    async def _open_output(self) -> sd.OutputStream:
        requested = resolve_device(self._settings.output_device)
        try:
            return await asyncio.to_thread(self._open_output_sync, requested)
        except Exception as error:
            if requested is None:
                raise RuntimeError(f"Не удалось открыть устройство вывода: {error}") from error
            await self._on_event("audio.output.fallback", {"message": "Выбранные динамики недоступны, использую системные."})
            return await asyncio.to_thread(self._open_output_sync, None)

    def _open_output_sync(self, device: int | str | None) -> sd.OutputStream:
        stream = sd.OutputStream(samplerate=self.sample_rate, channels=1, dtype="float32", device=device, blocksize=self.block_size)
        stream.start()
        return stream

    async def _run_stream(self) -> None:
        await self._on_event("assistant.speaking", {})
        producer: asyncio.Task | None = None
        player: asyncio.Task | None = None
        try:
            await self._load()
            producer = asyncio.create_task(self._produce_audio())
            player = asyncio.create_task(self._play_audio_queue())
            await producer
            await player
        except asyncio.CancelledError:
            if producer:
                producer.cancel()
            if player:
                player.cancel()
            await asyncio.gather(*(task for task in (producer, player) if task), return_exceptions=True)
            raise
        except Exception as error:
            if producer:
                producer.cancel()
            if player:
                player.cancel()
            await asyncio.gather(*(task for task in (producer, player) if task), return_exceptions=True)
            traceback.print_exc()
            await self._on_event("voice.error", {"message": f"{error}. Диагностика записана в backend.log.", "component": "tts"})
            raise
        finally:
            await self._on_event("audio.level", {"value": 0.0, "channel": "output"})
            await self._on_event("audio.output.finished", {})

    async def _produce_audio(self) -> None:
        if self._engine == "edge":
            await self._produce_edge_audio()
        else:
            await self._produce_silero_audio()
        if self._audio_queue is not None:
            await self._audio_queue.put(None)

    async def _next_text(self) -> str | None:
        if self._queue is None:
            return None
        value = await self._queue.get()
        if value is None or self._stop.is_set():
            return None
        return value

    async def _collect_text_batch(self) -> tuple[str | None, bool]:
        first = await self._next_text()
        if first is None:
            return None, True
        parts = [first]
        ended = False
        deadline = asyncio.get_running_loop().time() + self._prefetch_ms / 1000.0
        while len(" ".join(parts)) < self._batch_chars and not ended and self._queue is not None:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                value = await asyncio.wait_for(self._queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            if value is None:
                ended = True
                break
            parts.append(value)
        return " ".join(parts), ended

    async def _produce_edge_audio(self) -> None:
        ended = False
        while not self._stop.is_set() and not ended:
            text, ended = await self._collect_text_batch()
            if not text:
                break
            await self._stream_edge_to_buffer(text)

    async def _stream_edge_to_buffer(self, text: str) -> None:
        import av
        import edge_tts
        rate = int(round((max(0.7, min(1.35, float(self._settings.tts_speed))) - 1.0) * 100.0))
        communication = edge_tts.Communicate(text=text, voice=self._voice, rate=f"{rate:+d}%")
        decoder = av.CodecContext.create("mp3", "r")
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=self.sample_rate)
        generated = False
        async for packet in communication.stream():
            if self._stop.is_set():
                return
            if packet["type"] != "audio":
                continue
            for encoded in decoder.parse(packet["data"]):
                for frame in decoder.decode(encoded):
                    generated = await self._buffer_frame(frame, resampler) or generated
        for encoded in decoder.parse(b""):
            for frame in decoder.decode(encoded):
                generated = await self._buffer_frame(frame, resampler) or generated
        for frame in decoder.decode(None):
            generated = await self._buffer_frame(frame, resampler) or generated
        tail = resampler.resample(None)
        for item in (tail if isinstance(tail, list) else [tail] if tail is not None else []):
            generated = await self._buffer_samples(item.to_ndarray().astype(np.float32).reshape(-1)) or generated
        if not generated:
            raise RuntimeError("Microsoft Neural TTS не вернул аудио.")

    async def _buffer_frame(self, frame, resampler) -> bool:
        converted = resampler.resample(frame)
        if converted is None:
            return False
        values = converted if isinstance(converted, list) else [converted]
        buffered = False
        for item in values:
            buffered = await self._buffer_samples(item.to_ndarray().astype(np.float32).reshape(-1)) or buffered
        return buffered

    async def _buffer_samples(self, audio: np.ndarray) -> bool:
        if self._audio_queue is None or audio.size == 0:
            return False
        for offset in range(0, len(audio), self.block_size):
            if self._stop.is_set():
                return False
            await self._audio_queue.put(audio[offset:offset + self.block_size])
        return True

    async def _produce_silero_audio(self) -> None:
        ended = False
        while not self._stop.is_set() and not ended:
            text, ended = await self._collect_text_batch()
            if not text:
                break
            audio = await self._synthesize_silero(text)
            await self._buffer_samples(audio)

    async def _play_audio_queue(self) -> None:
        if self._audio_queue is None:
            return
        stream: sd.OutputStream | None = None
        played = False
        try:
            while not self._stop.is_set():
                audio = await self._audio_queue.get()
                if audio is None:
                    break
                if stream is None:
                    stream = await self._open_output()
                played = await self._write_samples(audio, stream) or played
        finally:
            if stream is not None:
                await asyncio.to_thread(stream.stop)
                await asyncio.to_thread(stream.close)
        if not played and not self._stop.is_set():
            raise RuntimeError("TTS не вернул аудио для воспроизведения.")

    async def _write_samples(self, audio: np.ndarray, stream: sd.OutputStream) -> bool:
        if audio.size == 0:
            return False
        level = float(min(1.0, np.sqrt(np.mean(audio * audio) + 1e-8) * 4.4))
        await asyncio.to_thread(stream.write, audio.reshape(-1, 1))
        await self._on_event("audio.level", {"value": level, "channel": "output"})
        return True
