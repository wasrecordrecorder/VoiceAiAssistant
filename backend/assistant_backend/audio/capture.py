import asyncio
from collections import deque
from collections.abc import Awaitable, Callable

import numpy as np
import sounddevice as sd

from .devices import resolve_device
from .noise import AdaptiveNoiseSuppressor
from .vad import create_vad

UtteranceCallback = Callable[[np.ndarray], Awaitable[None]]
PartialCallback = Callable[[np.ndarray], Awaitable[None]]
EventCallback = Callable[[str, dict], Awaitable[None]]


class VoiceCapture:
    def __init__(self, vad_engine: str, input_device: str, on_utterance: UtteranceCallback, on_partial: PartialCallback, on_event: EventCallback, partial_enabled: bool, partial_interval_ms: int, noise_suppression: bool = True, noise_strength: float = 0.56, silence_ms: int = 1450, max_seconds: int = 120, hold_to_talk: bool = False) -> None:
        self._vad = create_vad(vad_engine)
        self._noise = AdaptiveNoiseSuppressor(noise_suppression, noise_strength)
        self._device = resolve_device(input_device)
        self._on_utterance = on_utterance
        self._on_partial = on_partial
        self._on_event = on_event
        self._partial_enabled = partial_enabled
        self._partial_interval_ms = partial_interval_ms
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=120)
        self._task: asyncio.Task | None = None
        self._partials: set[asyncio.Task] = set()
        self._running = False
        self._paused = False
        self._speaking = False
        self._flush_requested = False
        self._flush_done = asyncio.Event()
        self._accept_input = True
        self._silence_ms = max(400, min(4000, int(silence_ms)))
        self._max_seconds = max(10, min(600, int(max_seconds)))
        self._hold_to_talk = hold_to_talk

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._accept_input = True
        self._vad.reset()
        self._noise.reset()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except BaseException:
                pass
            self._task = None
        for task in list(self._partials):
            task.cancel()
        if self._partials:
            await asyncio.gather(*self._partials, return_exceptions=True)
        self._partials.clear()

    async def flush(self) -> None:
        if not self._running:
            return
        self._accept_input = False
        self._flush_done.clear()
        self._flush_requested = True
        self._push(b"")
        await self._flush_done.wait()

    async def pause(self) -> None:
        self._paused = True
        self._speaking = False
        self._vad.reset()
        self._noise.reset()
        await self._on_event("audio.input.muted", {})

    async def resume(self) -> None:
        self._paused = False
        self._vad.reset()
        self._noise.reset()
        await self._on_event("audio.input.active", {})

    def _schedule_partial(self, audio: np.ndarray) -> None:
        task = asyncio.create_task(self._on_partial(audio))
        self._partials.add(task)
        task.add_done_callback(self._partials.discard)

    def _push(self, data: bytes) -> None:
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except Exception:
                pass
        self._queue.put_nowait(data)

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        frame_samples = self._vad.frame_samples
        pre_roll = deque(maxlen=max(1, int(16000 * 0.35 / frame_samples)))
        frames: list[bytes] = []
        silence = 0
        silence_limit = max(1, int(16000 * self._silence_ms / 1000 / frame_samples))
        max_frames = max(1, int(16000 * self._max_seconds / frame_samples))
        partial_frames = max(1, int(16000 * self._partial_interval_ms / 1000 / frame_samples))
        next_partial = partial_frames
        meter = 0

        def callback(indata, frame_count, time_info, status) -> None:
            if self._accept_input:
                loop.call_soon_threadsafe(self._push, bytes(indata))

        try:
            with sd.RawInputStream(samplerate=16000, blocksize=frame_samples, dtype="int16", channels=1, device=self._device, callback=callback):
                await self._on_event("assistant.listening", {})
                while self._running:
                    raw = await self._queue.get()
                    if self._flush_requested:
                        self._flush_requested = False
                        if self._speaking and frames:
                            pcm = b"".join(frames)
                            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                            self._speaking = False
                            frames = []
                            silence = 0
                            pre_roll.clear()
                            await self._on_utterance(audio)
                        self._flush_done.set()
                        continue
                    if self._paused:
                        continue
                    data = self._noise.process_frame(raw, self._speaking)
                    values = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                    level = float(min(1.0, np.sqrt(np.mean(values * values) + 1e-8) / 9000.0))
                    meter += 1
                    if meter % 2 == 0:
                        await self._on_event("audio.level", {"value": level, "channel": "input"})
                    speech = self._vad.is_speech(data)
                    if speech:
                        if not self._speaking:
                            self._speaking = True
                            frames = list(pre_roll)
                            next_partial = len(frames) + partial_frames
                            await self._on_event("assistant.speech_detected", {})
                        frames.append(data)
                        silence = 0
                        if self._partial_enabled and not self._hold_to_talk and len(frames) >= next_partial:
                            next_partial = len(frames) + partial_frames
                            audio = np.frombuffer(b"".join(frames), dtype=np.int16).astype(np.float32) / 32768.0
                            self._schedule_partial(audio)
                    elif self._speaking:
                        frames.append(data)
                        silence += 1
                        if (not self._hold_to_talk and silence >= silence_limit) or len(frames) >= max_frames:
                            pcm = b"".join(frames)
                            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                            self._speaking = False
                            frames = []
                            silence = 0
                            pre_roll.clear()
                            await self._on_utterance(audio)
                    else:
                        pre_roll.append(data)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._on_event("assistant.error", {"message": f"Микрофон: {error}"})
