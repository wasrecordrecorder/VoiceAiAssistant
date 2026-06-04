import asyncio
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from .agent.loop import AgentLoop
from .agent.policy import ApprovalManager
from .agent.tools import ToolRegistry
from .audio.activation import ActivationGate
from .audio.capture import VoiceCapture
from .audio.devices import list_devices
from .audio.stt import SpeechToText, create_stt
from .audio.tts import SpeechOutput
from .audio.vad import create_vad
from .core.catalog import catalog_payload
from .core.events import EventBus
from .core.history import ConversationStore
from .core.memory import MemoryStore
from .core.settings import SettingsStore
from .core.style_matrix import StylePreferenceMatrix
from .core.todos import TodoStore
from .providers.base import Provider
from .providers.factory import create_provider


class AssistantRuntime:
    def __init__(self, store: SettingsStore, events: EventBus, data_dir: Path) -> None:
        self._store = store
        self._events = events
        self._history = ConversationStore(data_dir)
        self._todos = TodoStore(data_dir)
        self._memory = MemoryStore(data_dir, store.settings.memory_max_chars)
        self._styles = StylePreferenceMatrix(data_dir)
        self._gate = ActivationGate(store.settings.activation_mode, store.settings.wake_phrases, store.settings.follow_up_seconds)
        self._capture: VoiceCapture | None = None
        self._stt: SpeechToText | None = None
        self._tts: SpeechOutput | None = None
        self._provider: Provider | None = None
        self._generation: asyncio.Task | None = None
        self._transcribing = False
        self._partial_busy = False
        self._partial_epoch = 0
        self._state = "idle"
        self._activated = False
        self._preparing = False
        self._ptt_active = False
        self._dictation_active = False
        self._subagents: dict[str, dict[str, Any]] = {}
        self._request_web_search = True
        self._models = {
            "vad": {"state": "idle", "label": "Voice activity detection", "model": ""},
            "stt": {"state": "idle", "label": "Распознавание речи", "model": ""},
            "tts": {"state": "idle", "label": "Озвучка", "model": ""},
        }
        self._approvals = ApprovalManager(self.event)

    async def event(self, event: str, payload: dict[str, Any] | None = None) -> None:
        value = payload or {}
        if event.startswith("assistant."):
            self._state = event.split(".", 1)[1]
        if event in {"model.loading", "model.ready", "model.error"}:
            component = str(value.get("component", ""))
            if component in self._models:
                state = {"model.loading": "loading", "model.ready": "ready", "model.error": "error"}[event]
                self._models[component] = {
                    **self._models[component],
                    "state": state,
                    "model": str(value.get("model", self._models[component].get("model", ""))),
                    "message": str(value.get("message", "")),
                }
                await self._events.emit("models.status", self.model_status())
        await self._events.emit(event, value)

    async def activate(self) -> None:
        if self._activated:
            return
        self._activated = True
        if self._store.settings.auto_listen and self._store.settings.ui_mode == "voice":
            await self.start_listening()

    async def refresh_settings(self) -> None:
        await self.stop_listening()
        if self._generation and not self._generation.done():
            await self.interrupt()
        settings = self._store.settings
        self._gate.configure(settings.activation_mode, settings.wake_phrases, settings.follow_up_seconds)
        self._memory.configure(settings.memory_max_chars)
        self._stt = None
        self._tts = None
        self._provider = None
        self._models["stt"]["state"] = "idle"
        self._models["tts"]["state"] = "idle"
        await self.event("settings.changed", self._store.public())
        await self.event("models.status", self.model_status())
        await self.event("memory.current", self.memory())
        if settings.auto_listen and settings.ui_mode == "voice":
            await self.start_listening()

    async def start_listening(self) -> None:
        if self._capture is not None:
            await self._settle_state()
            return
        settings = self._store.settings
        try:
            self._capture = VoiceCapture(
                settings.vad_engine,
                settings.input_device,
                self._utterance,
                self._partial_utterance,
                self._capture_event,
                settings.partial_transcription,
                settings.partial_interval_ms,
                settings.noise_suppression,
                settings.noise_strength,
                settings.utterance_silence_ms,
                settings.utterance_max_seconds,
                settings.activation_mode == "ptt",
            )
            await self._capture.start()
            await self._settle_state()
        except Exception as error:
            self._capture = None
            await self.event("assistant.error", {"scope": "microphone", "message": f"Микрофон: {error}"})

    async def arm_listening(self) -> None:
        await self.start_listening()
        self._gate.arm()
        await self.event("assistant.armed", {"message": "Слушаю следующую команду"})

    async def ptt_down(self) -> None:
        if self._store.settings.activation_mode != "ptt" or self._ptt_active:
            return
        self._ptt_active = True
        await self.start_listening()
        self._gate.arm()
        await self.event("assistant.ptt", {"pressed": True, "message": "Рация активна. Отправка после отпускания клавиши."})

    async def ptt_up(self) -> None:
        if self._store.settings.activation_mode != "ptt" or not self._ptt_active:
            return
        self._ptt_active = False
        self._dictation_active = False
        if self._capture is not None:
            await self.event("assistant.transcribing", {"message": "Распознаю записанную команду"})
            await self._capture.flush()
            await self.stop_listening()
        await self.event("assistant.ptt", {"pressed": False, "message": "Рация отпущена"})

    async def start_dictation(self) -> None:
        self._dictation_active = True
        await self.start_listening()
        self._gate.arm()
        await self.event("assistant.dictating", {"message": "Диктуйте текст. Он появится в поле ввода."})

    async def stop_listening(self) -> None:
        self._dictation_active = False
        if self._capture is not None:
            await self._capture.stop()
            self._capture = None
        self._partial_epoch += 1
        await self.event("transcript.partial", {"text": ""})
        if self._state in {"listening", "speech_detected", "transcribing", "monitoring", "armed", "follow_up"}:
            await self.event("assistant.idle", {})

    async def interrupt(self) -> None:
        self._approvals.cancel_all()
        if self._provider is not None:
            await self._provider.abort()
        if self._tts is not None:
            await self._tts.stop()
        if self._generation and not self._generation.done():
            self._generation.cancel()
            try:
                await self._generation
            except BaseException:
                pass
        self._generation = None
        self._partial_epoch += 1
        await self.event("transcript.partial", {"text": ""})
        await self._restore_capture()
        await self.event("assistant.interrupted", {})
        await self._settle_state()

    async def approve(self, approval_id: str, approved: bool) -> None:
        await self._approvals.resolve(approval_id, approved)

    async def submit(self, text: str, attachments: list[dict[str, Any]] | None = None, web_search: bool | None = None) -> None:
        value = text.strip()
        items = attachments or []
        if not value and not items:
            return
        self._gate.extend()
        if self._generation and not self._generation.done():
            await self.interrupt()
        updated_preferences = self._styles.observe(value)
        if updated_preferences:
            await self.event("preferences.updated", {"items": updated_preferences})
        context = self._history.context(self._store.settings.max_context_turns)
        display = value or "Вложения"
        if items:
            display = f"{display}\n\nВложения: " + ", ".join(str(item.get("name", "файл")) for item in items[:8])
        self._history.append("user", display)
        await self.event("conversation.current", self.sessions())
        allow_web = self._store.settings.web_search_enabled if web_search is None else bool(web_search)
        self._generation = asyncio.create_task(self._answer(value, context, items, allow_web))

    async def test_voice(self, text: str) -> None:
        await self.event("voice.test.started", {})
        if self._tts is None:
            self._tts = SpeechOutput(self._store.settings, self.event)
        await self._guard_capture()
        try:
            await self._tts.speak(text)
        except Exception:
            return
        else:
            await self.event("voice.test.finished", {})
        finally:
            await self._restore_capture()
            await self._settle_state()

    async def preload_models(self) -> None:
        if self._preparing:
            return
        self._preparing = True
        components = ["vad", "stt"] + (["tts"] if self._store.settings.tts_enabled else [])
        total = len(components)
        completed = 0
        await self.event("preparation.started", {"components": components, "total": total})
        try:
            await self.event("model.loading", {"component": "vad", "model": self._store.settings.vad_engine, "detail": "Проверяю детектор голоса"})
            await asyncio.to_thread(create_vad, self._store.settings.vad_engine)
            await self.event("model.ready", {"component": "vad", "model": self._store.settings.vad_engine})
            completed += 1
            await self.event("preparation.progress", {"completed": completed, "total": total})
            if self._stt is None:
                self._stt = create_stt(self._store.settings, self.event)
            await self._stt.prepare()
            completed += 1
            await self.event("preparation.progress", {"completed": completed, "total": total})
            if self._store.settings.tts_enabled:
                if self._tts is None:
                    self._tts = SpeechOutput(self._store.settings, self.event)
                await self._tts.prepare()
                completed += 1
                await self.event("preparation.progress", {"completed": completed, "total": total})
            await self.event("preparation.finished", {"completed": completed, "total": total})
            await self.event("step.add", {"kind": "complete", "text": "Голосовые модели подготовлены"})
        except Exception as error:
            await self.event("preparation.failed", {"message": str(error), "completed": completed, "total": total})
            await self.event("assistant.error", {"scope": "setup", "message": str(error)})
        finally:
            self._preparing = False

    async def _capture_event(self, event: str, payload: dict) -> None:
        passive = self._gate.passive()
        if event == "assistant.speech_detected":
            self._partial_epoch += 1
            await self.event("transcript.partial", {"text": ""})
            if self._state == "speaking" and self._store.settings.barge_in:
                await self.interrupt()
            if passive:
                return
        if event == "assistant.listening" and passive:
            await self.event("assistant.monitoring", {"message": "Жду обращения по ключевой фразе"})
            return
        await self.event(event, payload)

    async def _partial_utterance(self, audio: np.ndarray) -> None:
        if self._store.settings.activation_mode == "ptt":
            return
        if self._transcribing or self._partial_busy or not self._store.settings.partial_transcription or (self._gate.passive() and not self._dictation_active):
            return
        self._partial_busy = True
        epoch = self._partial_epoch
        try:
            if self._stt is None:
                self._stt = create_stt(self._store.settings, self.event)
            text = await self._stt.transcribe_partial(audio)
            if epoch == self._partial_epoch and text:
                await self.event("dictation.partial" if self._dictation_active else "transcript.partial", {"text": text})
        except Exception as error:
            await self.event("transcript.partial_error", {"message": str(error)})
        finally:
            self._partial_busy = False

    async def _utterance(self, audio: np.ndarray) -> None:
        if self._transcribing:
            return
        self._partial_epoch += 1
        self._transcribing = True
        passive = self._gate.passive()
        try:
            if not passive:
                await self.event("assistant.transcribing", {})
            if self._stt is None:
                self._stt = create_stt(self._store.settings, self.event)
            text = await self._stt.transcribe(audio)
            await self.event("transcript.partial", {"text": ""})
            if self._dictation_active:
                self._dictation_active = False
                await self.event("dictation.final", {"text": text.strip()})
                await self._settle_state()
                return
            result = self._gate.process(text)
            if result.awakened and not result.accepted:
                await self.event("assistant.armed", {"message": "Да, слушаю"})
                return
            if result.accepted:
                await self.event("transcript.final", {"text": result.text})
                await self.submit(result.text)
                return
            if result.ignored:
                await self.event("assistant.monitoring", {"message": "Фраза не адресована ассистенту"})
                return
            await self._settle_state()
        except Exception as error:
            await self.event("assistant.error", {"scope": "stt", "message": f"STT: {error}"})
        finally:
            self._transcribing = False

    async def _answer(self, text: str, history: list[dict[str, str]], attachments: list[dict[str, Any]] | None = None, web_search: bool = True) -> None:
        response = ""
        speech_buffer = ""
        streaming_voice = False
        voice_available = self._store.settings.tts_enabled and self._store.settings.ui_mode == "voice"
        capture_guarded = False
        try:
            self._request_web_search = bool(web_search)
            await self.event("assistant.thinking", {"query": text})
            await self.event("step.add", {"kind": "input", "text": f"Запрос: {text}"})
            memory_context = self._memory.context(text) if self._store.settings.memory_enabled else ""
            self._provider = create_provider(self._store, memory_context, style_context=self._styles.prompt())
            model_text = await self._with_attachments(text, attachments or [])
            if voice_available and self._tts is None:
                self._tts = SpeechOutput(self._store.settings, self.event)

            async def on_delta(delta: str) -> None:
                nonlocal response, speech_buffer, streaming_voice, capture_guarded, voice_available
                response += delta
                speech_buffer += delta
                await self.event("response.delta", {"text": delta})
                if self._tts is not None and voice_available:
                    try:
                        chunks, speech_buffer = self._tts.consume_chunks(speech_buffer)
                        if chunks and not streaming_voice:
                            await self._guard_capture()
                            capture_guarded = True
                            await self._tts.begin()
                            streaming_voice = True
                        for chunk in chunks:
                            await self._tts.add(chunk)
                    except Exception as error:
                        voice_available = False
                        await self.event("voice.error", {"component": "tts", "message": str(error)})

            async def on_step(kind: str, value: str) -> None:
                await self.event("step.add", {"kind": kind, "text": value})

            if self._store.settings.agent_enabled:
                tools = ToolRegistry(self._store.settings, self._approvals, self._todos, self._memory, self.event, self._run_subagents, False, self._inspect_screen, web_search)
                loop = AgentLoop(self._provider, tools, self._store.settings.agent_max_steps, self.event)
                final = await loop.run(model_text, history, on_delta, on_step)
            else:
                final = await self._provider.answer(model_text, history, on_delta, on_step)
            if final and not response:
                response = final
                speech_buffer = final
            if not response.strip():
                raise RuntimeError("Модель вернула пустой ответ.")
            self._history.append("assistant", response)
            await self.event("response.final", {"text": response})
            await self.event("step.add", {"kind": "complete", "text": "Ответ сформирован"})
            if self._tts is not None and voice_available:
                if speech_buffer.strip():
                    if not streaming_voice:
                        await self._guard_capture()
                        capture_guarded = True
                        await self._tts.begin()
                        streaming_voice = True
                    await self._tts.add(speech_buffer)
                if streaming_voice:
                    try:
                        await self._tts.finish()
                    except Exception:
                        voice_available = False
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if streaming_voice and self._tts is not None:
                await self._tts.stop()
            await self.event("assistant.error", {"scope": "provider", "message": str(error)})
        finally:
            if capture_guarded:
                await self._restore_capture()
            self._generation = None
            self._gate.extend()
            if self._state != "error":
                await self._settle_state()
            await self.event("conversation.current", self.sessions())

    async def _with_attachments(self, text: str, attachments: list[dict[str, Any]]) -> str:
        if not attachments:
            return text
        sections = []
        for item in attachments[:8]:
            name = str(item.get("name", "file"))[:180]
            mime = str(item.get("type", "application/octet-stream"))[:80]
            size = int(item.get("size", 0) or 0)
            content = str(item.get("content", ""))
            data_url = str(item.get("data_url", ""))
            if mime.startswith("image/") and data_url and self._provider is not None:
                try:
                    description = await self._provider.vision(f"Опиши содержимое вложенного изображения {name} для дальнейшего ответа пользователю.", data_url)
                    sections.append(f"Вложение-изображение {name} ({size} байт):\n{description}")
                except Exception as error:
                    sections.append(f"Вложение-изображение {name} ({size} байт) не удалось проанализировать: {error}")
            elif content:
                excerpt = content[:180000]
                suffix = "\n[содержимое обрезано]" if len(content) > len(excerpt) else ""
                sections.append(f"Вложение {name} ({mime}, {size} байт):\n```\n{excerpt}{suffix}\n```")
            else:
                sections.append(f"Вложение {name} ({mime}, {size} байт).")
        base = text.strip() or "Проанализируй вложения."
        return base + "\n\nПереданные пользователем вложения:\n" + "\n\n".join(sections)

    async def _inspect_screen(self, question: str, image_data_url: str) -> str:
        if self._provider is None:
            raise RuntimeError("Провайдер ещё не инициализирован.")
        await self.event("step.add", {"kind": "tool", "text": "Анализирую снимок экрана"})
        result = await self._provider.vision(question, image_data_url)
        if not result.strip():
            raise RuntimeError("Vision-модель не смогла описать экран.")
        return result.strip()

    async def _run_subagents(self, tasks: list[dict[str, str]]) -> list[dict[str, Any]]:
        maximum = min(3, max(1, int(self._store.settings.subagent_max_parallel)))
        semaphore = asyncio.Semaphore(maximum)

        async def run_one(index: int, task: dict[str, str]) -> dict[str, Any]:
            async with semaphore:
                subagent_id = uuid.uuid4().hex[:10]
                title = str(task.get("title", f"Субагент {index + 1}")).strip()[:100] or f"Субагент {index + 1}"
                instruction = str(task.get("instruction", "")).strip()
                state = {"id": subagent_id, "title": title, "state": "running", "detail": "Анализирую задачу"}
                self._subagents[subagent_id] = state
                await self.event("subagent.started", state)

                async def child_event(name: str, payload: dict[str, Any]) -> None:
                    if name == "agent.tool_started":
                        await self.event("subagent.progress", {"id": subagent_id, "title": title, "detail": f"Инструмент: {payload.get('name', '')}"})
                    elif name == "agent.tool_finished":
                        await self.event("subagent.progress", {"id": subagent_id, "title": title, "detail": f"Готово: {payload.get('name', '')}"})

                async def child_delta(value: str) -> None:
                    return None

                async def child_step(kind: str, value: str) -> None:
                    await self.event("subagent.progress", {"id": subagent_id, "title": title, "detail": value[:180]})

                extra_prompt = (
                    "Ты субагент основного ассистента. Выполни только порученное исследование. "
                    "Тебе доступны безопасные инструменты чтения и поиска. Ничего не изменяй, "
                    "не запускай программы и не общайся с пользователем напрямую. "
                    "Верни короткий точный вывод основному агенту."
                )
                try:
                    memory_context = self._memory.context(instruction) if self._store.settings.memory_enabled else ""
                    provider = create_provider(self._store, memory_context, extra_prompt, self._styles.prompt())
                    tools = ToolRegistry(self._store.settings, self._approvals, self._todos, self._memory, self.event, None, True, None, self._request_web_search)
                    loop = AgentLoop(provider, tools, min(8, self._store.settings.agent_max_steps), child_event)
                    output = await loop.run(instruction, [], child_delta, child_step)
                    result = {"id": subagent_id, "title": title, "ok": True, "output": output[:5000]}
                    self._subagents[subagent_id] = {**state, "state": "done", "detail": output[:160]}
                    await self.event("subagent.finished", self._subagents[subagent_id])
                    return result
                except Exception as error:
                    result = {"id": subagent_id, "title": title, "ok": False, "error": str(error)}
                    self._subagents[subagent_id] = {**state, "state": "error", "detail": str(error)[:160]}
                    await self.event("subagent.finished", self._subagents[subagent_id])
                    return result

        selected = tasks[:maximum]
        return await asyncio.gather(*(run_one(index, task) for index, task in enumerate(selected)))

    async def _guard_capture(self) -> None:
        if self._capture is not None and self._store.settings.echo_guard:
            await self._capture.pause()

    async def _restore_capture(self) -> None:
        if self._capture is not None and self._store.settings.echo_guard:
            await self._capture.resume()

    async def _settle_state(self) -> None:
        if self._capture is None:
            await self.event("assistant.idle", {})
        elif self._store.settings.activation_mode == "ptt":
            await self.event("assistant.idle", {"message": f"Удерживайте {self._store.settings.ptt_key}, чтобы говорить"})
        elif self._gate.passive():
            await self.event("assistant.monitoring", {"message": "Скажите ключевую фразу для обращения"})
        else:
            await self.event("assistant.follow_up", {"message": "Жду продолжение разговора"})

    def settings(self) -> dict[str, Any]:
        return self._store.public()

    def catalog(self) -> dict[str, Any]:
        return catalog_payload()

    def devices(self) -> dict[str, Any]:
        try:
            return list_devices()
        except Exception as error:
            return {"inputs": [], "outputs": [], "error": str(error)}

    def sessions(self) -> dict[str, Any]:
        return {"items": self._history.sessions(), "active_id": self._history.active_id, "messages": self._history.messages()}

    def model_status(self) -> dict[str, Any]:
        return {"models": self._models, "preparing": self._preparing}

    def todos(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        value = filters or {}
        return {
            "items": self._todos.list(str(value.get("status", "")), str(value.get("kind", "")), bool(value.get("important_only", False)), str(value.get("query", ""))),
            "summary": self._todos.summary(),
        }

    async def todo_create(self, payload: dict[str, Any]) -> None:
        self._todos.create(str(payload.get("title", "")), str(payload.get("body", "")), str(payload.get("kind", "task")), str(payload.get("status", "todo")), str(payload.get("priority", "normal")), str(payload.get("due_at", "")), payload.get("tags", []))
        await self.event("todo.current", self.todos())

    async def todo_update(self, payload: dict[str, Any]) -> None:
        item_id = str(payload.get("id", ""))
        self._todos.update(item_id, {key: payload[key] for key in ("title", "body", "kind", "status", "priority", "due_at", "tags") if key in payload})
        await self.event("todo.current", self.todos())

    async def todo_delete(self, item_id: str) -> None:
        self._todos.delete(item_id)
        await self.event("todo.current", self.todos())

    def memory(self) -> dict[str, Any]:
        return self._memory.public()

    async def memory_add(self, payload: dict[str, Any]) -> None:
        self._memory.add(str(payload.get("text", "")), str(payload.get("category", "fact")), int(payload.get("importance", 3)))
        await self.event("memory.current", self.memory())

    async def memory_update(self, payload: dict[str, Any]) -> None:
        self._memory.update(str(payload.get("id", "")), str(payload.get("text", "")), payload.get("category"), payload.get("importance"))
        await self.event("memory.current", self.memory())

    async def memory_delete(self, item_id: str) -> None:
        self._memory.delete(item_id)
        await self.event("memory.current", self.memory())

    async def new_session(self) -> None:
        self._history.new()
        await self.event("conversation.current", self.sessions())

    async def select_session(self, session_id: str) -> None:
        if not self._history.select(session_id):
            raise RuntimeError("Диалог не найден.")
        await self.event("conversation.current", self.sessions())

    async def rename_session(self, session_id: str, title: str) -> None:
        if not self._history.rename(session_id, title):
            raise RuntimeError("Диалог не найден.")
        await self.event("conversation.current", self.sessions())

    async def archive_session(self, session_id: str, archived: bool) -> None:
        if not self._history.archive(session_id, archived):
            raise RuntimeError("Диалог не найден.")
        await self.event("conversation.current", self.sessions())

    async def delete_session(self, session_id: str) -> None:
        if not self._history.delete(session_id):
            raise RuntimeError("Диалог не найден.")
        await self.event("conversation.current", self.sessions())

    async def clear_session(self) -> None:
        self._history.clear()
        await self.event("conversation.current", self.sessions())

    def snapshot(self) -> dict[str, Any]:
        return {"state": self._state, "listening": self._capture is not None, "agent_enabled": self._store.settings.agent_enabled, "activation_mode": self._store.settings.activation_mode, "follow_up_seconds": self._gate.remaining_seconds()}
