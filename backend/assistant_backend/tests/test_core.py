import tempfile
import unittest
from pathlib import Path

from assistant_backend.core.catalog import route_for
from assistant_backend.core.history import ConversationStore
from assistant_backend.core.memory import MemoryStore
from assistant_backend.core.todos import TodoStore
from assistant_backend.audio.activation import ActivationGate
from assistant_backend.audio.noise import AdaptiveNoiseSuppressor
import numpy as np
from assistant_backend.core.settings import SettingsStore
from assistant_backend.audio.speech_text import normalize_for_speech


class CatalogTests(unittest.TestCase):
    def test_go_routes_protocol_by_model(self) -> None:
        self.assertEqual(route_for("opencode_go", "kimi-k2.6").protocol, "chat")
        self.assertEqual(route_for("opencode_go", "qwen3.6-plus").protocol, "messages")

    def test_zen_routes_protocol_by_model(self) -> None:
        self.assertEqual(route_for("opencode_zen", "gpt-5.5").protocol, "responses")
        self.assertEqual(route_for("opencode_zen", "claude-sonnet-4-6").protocol, "messages")
        self.assertEqual(route_for("opencode_zen", "gemini-3-flash").protocol, "google")


class SettingsTests(unittest.TestCase):
    def test_invalid_zen_model_resets_to_catalog_default(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            value = store.update({"provider": "opencode_zen", "model": "invalid"})
            self.assertEqual(value["model"], "deepseek-v4-flash-free")


    def test_powerful_whisper_models_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            self.assertEqual(store.update({"stt_model": "medium"})["stt_model"], "medium")
            self.assertEqual(store.update({"stt_model": "large-v3"})["stt_model"], "large-v3")
            self.assertEqual(store.update({"stt_model": "turbo"})["stt_model"], "turbo")

    def test_new_install_exposes_agent_tools_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            self.assertTrue(store.settings.agent_enabled)

    def test_legacy_release_settings_enable_agent_once(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            config = Path(path) / "settings.json"
            config.write_text('{"agent_enabled": false}', encoding="utf-8")
            store = SettingsStore(Path(path))
            self.assertTrue(store.settings.agent_enabled)
            self.assertTrue(store.settings.agent_setup_completed)

    def test_echo_guard_disables_barge_in(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            value = store.update({"echo_guard": True, "barge_in": True})
            self.assertFalse(value["barge_in"])


    def test_ptt_mode_disables_auto_listen_and_normalizes_key(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            value = store.update({"activation_mode": "ptt", "ptt_key": "F9", "auto_listen": True})
            self.assertFalse(value["auto_listen"])
            self.assertEqual(value["ptt_key"], "F9")

    def test_custom_ptt_binding_and_dictation_limits_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            value = store.update({"activation_mode": "ptt", "ptt_key": "Ctrl + Space", "ptt_vk": 32, "ptt_modifiers": 1, "utterance_silence_ms": 2100, "utterance_max_seconds": 240})
            self.assertEqual(value["ptt_key"], "CTRL + SPACE")
            self.assertEqual(value["ptt_vk"], 32)
            self.assertEqual(value["ptt_modifiers"], 1)
            self.assertEqual(value["utterance_silence_ms"], 2100)
            self.assertEqual(value["utterance_max_seconds"], 240)

    def test_edge_tts_normalizes_legacy_silero_voice(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            value = store.update({"tts_engine": "edge", "tts_voice": "xenia"})
            self.assertEqual(value["tts_voice"], "ru-RU-SvetlanaNeural")

    def test_silero_tts_normalizes_edge_voice(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            value = store.update({"tts_engine": "silero", "tts_voice": "ru-RU-SvetlanaNeural"})
            self.assertEqual(value["tts_voice"], "xenia")



class SpeechTextTests(unittest.TestCase):
    def test_removes_emoji_and_markdown_symbols(self) -> None:
        value = normalize_for_speech("✅ **Готово** | [документ](https://example.com)")
        self.assertNotIn("✅", value)
        self.assertNotIn("*", value)
        self.assertNotIn("|", value)
        self.assertNotIn("https", value)

    def test_verbalizes_range_and_units(self) -> None:
        value = normalize_for_speech("Около 30–35 ГБ.")
        self.assertIn("от тридцати до тридцати пяти гигабайт", value)
        self.assertNotIn("30", value)
        self.assertNotIn("ГБ", value)


class HistoryTests(unittest.TestCase):
    def test_conversation_context_persists_messages(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            history = ConversationStore(Path(path))
            history.append("user", "Привет")
            history.append("assistant", "Здравствуйте")
            self.assertEqual(len(history.context(2)), 2)
            self.assertEqual(history.context(2)[0]["content"], "Привет")


if __name__ == "__main__":
    unittest.main()


class ActivationTests(unittest.TestCase):
    def test_wake_phrase_accepts_only_addressed_command(self) -> None:
        gate = ActivationGate("wake", "ассистент, вебви", 20)
        self.assertTrue(gate.process("ассистент открой задачи").accepted)
        passive = ActivationGate("wake", "ассистент", 20)
        self.assertTrue(passive.process("поговорим о погоде").ignored)
        self.assertTrue(passive.process("сегодня я обсуждал голосовой ассистент в проекте").ignored)

    def test_wake_phrase_opens_follow_up_window(self) -> None:
        gate = ActivationGate("wake", "ассистент", 20)
        first = gate.process("ассистент")
        self.assertTrue(first.awakened)
        self.assertFalse(first.accepted)
        self.assertTrue(gate.process("добавь задачу").accepted)

    def test_wake_phrase_tolerates_common_transcription_variant(self) -> None:
        gate = ActivationGate("wake", "ассистент", 20)
        result = gate.process("асистент открой задачи")
        self.assertTrue(result.accepted)
        self.assertEqual(result.text, "открой задачи")


    def test_ptt_mode_accepts_only_armed_utterance(self) -> None:
        gate = ActivationGate("ptt", "ассистент", 20)
        self.assertTrue(gate.process("фоновая речь").ignored)
        gate.arm()
        accepted = gate.process("проверь задачи")
        self.assertTrue(accepted.accepted)
        self.assertEqual(accepted.text, "проверь задачи")

    def test_extend_keeps_follow_up_dialog_active(self) -> None:
        gate = ActivationGate("wake", "ассистент", 20)
        gate.process("ассистент скажи привет")
        gate._awake_until = 0.0
        gate.extend()
        self.assertTrue(gate.process("продолжай без обращения").accepted)


class TodoTests(unittest.TestCase):
    def test_create_and_update_task(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = TodoStore(Path(path))
            item = store.create("Купить кабель", "USB C", "task", "todo", "important")
            updated = store.update(item["id"], {"status": "done"})
            self.assertEqual(updated["status"], "done")
            self.assertEqual(store.summary()["done"], 1)


class MemoryTests(unittest.TestCase):
    def test_memory_is_markdown_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = MemoryStore(Path(path), 2000)
            item = store.add("Пользователь предпочитает краткие ответы.", "preference", 5)
            self.assertIn(item.id, store.path.read_text(encoding="utf-8"))
            self.assertIn("краткие", store.context("ответы"))
            store.delete(item.id)
            self.assertNotIn("краткие", store.path.read_text(encoding="utf-8"))


class NoiseSuppressionTests(unittest.TestCase):
    def test_noise_suppressor_preserves_frame_shape(self) -> None:
        suppressor = AdaptiveNoiseSuppressor(True, 0.6)
        frame = (np.ones(512, dtype=np.int16) * 120).tobytes()
        cleaned = suppressor.process_frame(frame, False)
        self.assertEqual(len(cleaned), len(frame))

from assistant_backend.core.style_matrix import StylePreferenceMatrix


class TextModeSettingsTests(unittest.TestCase):
    def test_agent_step_limit_accepts_large_loops(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            value = store.update({"agent_max_steps": 180, "ui_mode": "text", "agent_strategy": "hermes_duo"})
            self.assertEqual(value["agent_max_steps"], 180)
            self.assertEqual(value["ui_mode"], "text")
            self.assertEqual(value["agent_strategy"], "hermes_duo")

    def test_agent_step_limit_is_capped_safely(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            self.assertEqual(store.update({"agent_max_steps": 999})["agent_max_steps"], 256)


class StyleMatrixTests(unittest.TestCase):
    def test_explicit_style_corrections_build_persistent_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            matrix = StylePreferenceMatrix(Path(path))
            matrix.observe("Пиши кратко, без воды и без комментариев в коде")
            prompt = matrix.prompt()
            self.assertIn("предельно сжато", prompt)
            self.assertIn("комментарии", prompt)


class ConversationManagementTests(unittest.TestCase):
    def test_rename_archive_restore_and_delete_chat(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = ConversationStore(Path(path))
            first = store.active_id
            second = store.new()
            self.assertTrue(store.rename(first, "Проект Syntax"))
            self.assertTrue(store.archive(first, True))
            archived = [item for item in store.sessions() if item["id"] == first][0]
            self.assertEqual(archived["title"], "Проект Syntax")
            self.assertTrue(archived["archived"])
            self.assertTrue(store.archive(first, False))
            self.assertFalse([item for item in store.sessions() if item["id"] == first][0]["archived"])
            self.assertTrue(store.delete(second))
            self.assertNotIn(second, [item["id"] for item in store.sessions()])

    def test_web_search_setting_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            self.assertFalse(store.update({"web_search_enabled": False})["web_search_enabled"])
