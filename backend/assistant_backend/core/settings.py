import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .catalog import DEFAULT_MODELS, route_for

try:
    import keyring
except Exception:
    keyring = None


@dataclass
class Settings:
    provider: str = "openrouter"
    model: str = "openai/gpt-4.1-mini"
    custom_base_url: str = "https://api.openai.com/v1"
    custom_protocol: str = "chat"
    ollama_base_url: str = "http://localhost:11434"
    voice_profile: str = "balanced"
    stt_engine: str = "faster-whisper"
    stt_model: str = "small"
    vosk_model_path: str = ""
    vad_engine: str = "silero"
    noise_suppression: bool = True
    noise_strength: float = 0.56
    partial_transcription: bool = True
    partial_interval_ms: int = 950
    activation_mode: str = "wake"
    ptt_key: str = "F8"
    ptt_vk: int = 119
    ptt_modifiers: int = 0
    tray_widget_enabled: bool = True
    widget_orientation: str = "horizontal"
    reasoning_effort: str = "medium"
    reasoning_visible: bool = False
    ui_mode: str = "voice"
    agent_strategy: str = "standard"
    web_search_enabled: bool = True
    utterance_silence_ms: int = 1450
    utterance_max_seconds: int = 120
    wake_phrases: str = "ассистент, вебви"
    follow_up_seconds: int = 60
    tts_enabled: bool = True
    tts_engine: str = "edge"
    tts_voice: str = "ru-RU-SvetlanaNeural"
    tts_speed: float = 1.0
    tts_prefetch_ms: int = 170
    tts_batch_chars: int = 240
    auto_listen: bool = True
    echo_guard: bool = True
    barge_in: bool = False
    input_device: str = ""
    output_device: str = ""
    agent_enabled: bool = True
    agent_setup_completed: bool = True
    workspace_path: str = ""
    agent_allow_edits: bool = False
    agent_allow_commands: bool = False
    agent_max_steps: int = 12
    agent_command_timeout: int = 45
    subagent_max_parallel: int = 3
    max_context_turns: int = 12
    memory_enabled: bool = True
    memory_max_chars: int = 12000
    screen_vision_enabled: bool = True
    screen_capture_without_confirmation: bool = False
    system_prompt: str = "Ты голосовой ассистент. Отвечай по-русски, кратко и по делу."


PROFILES = {
    "lite": {"stt_engine": "vosk", "vad_engine": "webrtc"},
    "balanced": {"stt_engine": "faster-whisper", "stt_model": "small", "vad_engine": "silero"},
    "fast": {"stt_engine": "faster-whisper", "stt_model": "base", "vad_engine": "silero"},
}
PROVIDERS = {"openrouter", "opencode_zen", "opencode_go", "freemodel_gpt", "ollama", "custom"}
PROTOCOLS = {"chat", "responses", "messages"}
ACTIVATION_MODES = {"wake", "manual", "continuous", "ptt"}
REASONING_EFFORTS = {"off", "low", "medium", "high"}
WIDGET_ORIENTATIONS = {"horizontal", "vertical"}
UI_MODES = {"voice", "text"}
AGENT_STRATEGIES = {"standard", "hermes_duo"}


class SettingsStore:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "settings.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._volatile_secrets: dict[str, str] = {}
        self.settings = self._load()

    def _load(self) -> Settings:
        if not self._path.exists():
            return Settings()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            migrated = "agent_setup_completed" not in data
            if migrated:
                data["agent_enabled"] = True
                data["agent_setup_completed"] = True
            allowed = {item.name for item in fields(Settings)}
            value = self._normalize(Settings(**{key: value for key, value in data.items() if key in allowed}))
            if migrated:
                self._path.write_text(json.dumps(asdict(value), ensure_ascii=False, indent=2), encoding="utf-8")
            return value
        except Exception:
            return Settings()

    def _normalize(self, value: Settings) -> Settings:
        if value.provider not in PROVIDERS:
            value.provider = "openrouter"
        if not value.model.strip():
            value.model = DEFAULT_MODELS.get(value.provider, "")
        if value.provider in {"opencode_zen", "opencode_go", "freemodel_gpt"} and route_for(value.provider, value.model) is None:
            value.model = DEFAULT_MODELS[value.provider]
        if value.custom_protocol not in PROTOCOLS:
            value.custom_protocol = "chat"
        if value.voice_profile not in PROFILES:
            value.voice_profile = "balanced"
        if value.stt_engine not in {"faster-whisper", "vosk"}:
            value.stt_engine = "faster-whisper"
        if value.stt_model not in {"tiny", "base", "small", "medium", "large-v3", "turbo"}:
            value.stt_model = "small"
        if value.vad_engine not in {"silero", "webrtc"}:
            value.vad_engine = "silero"
        if value.activation_mode not in ACTIVATION_MODES:
            value.activation_mode = "wake"
        if value.widget_orientation not in WIDGET_ORIENTATIONS:
            value.widget_orientation = "horizontal"
        if value.reasoning_effort not in REASONING_EFFORTS:
            value.reasoning_effort = "medium"
        value.reasoning_visible = bool(value.reasoning_visible)
        if value.ui_mode not in UI_MODES:
            value.ui_mode = "voice"
        if value.agent_strategy not in AGENT_STRATEGIES:
            value.agent_strategy = "standard"
        value.web_search_enabled = bool(value.web_search_enabled)
        value.ptt_key = str(value.ptt_key).strip().upper() or "F8"
        value.ptt_vk = min(255, max(1, int(value.ptt_vk)))
        value.ptt_modifiers = min(15, max(0, int(value.ptt_modifiers)))
        if value.tts_engine not in {"edge", "silero"}:
            value.tts_engine = "edge"
        edge_voices = {"ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"}
        silero_voices = {"xenia", "baya", "kseniya", "aidar", "eugene"}
        if value.tts_engine == "edge" and value.tts_voice not in edge_voices:
            value.tts_voice = "ru-RU-SvetlanaNeural"
        if value.tts_engine == "silero" and value.tts_voice not in silero_voices:
            value.tts_voice = "xenia"
        value.tts_speed = min(1.35, max(0.7, float(value.tts_speed)))
        value.noise_strength = min(0.95, max(0.0, float(value.noise_strength)))
        value.partial_interval_ms = min(3000, max(450, int(value.partial_interval_ms)))
        value.follow_up_seconds = min(300, max(4, int(value.follow_up_seconds)))
        value.utterance_silence_ms = min(4000, max(400, int(value.utterance_silence_ms)))
        value.utterance_max_seconds = min(600, max(10, int(value.utterance_max_seconds)))
        value.tts_prefetch_ms = min(1000, max(0, int(value.tts_prefetch_ms)))
        value.tts_batch_chars = min(1000, max(80, int(value.tts_batch_chars)))
        value.agent_max_steps = min(256, max(1, int(value.agent_max_steps)))
        value.agent_command_timeout = min(180, max(1, int(value.agent_command_timeout)))
        value.subagent_max_parallel = min(3, max(1, int(value.subagent_max_parallel)))
        value.max_context_turns = min(120, max(1, int(value.max_context_turns)))
        value.memory_max_chars = min(50000, max(2000, int(value.memory_max_chars)))
        value.custom_base_url = value.custom_base_url.rstrip("/")
        value.ollama_base_url = value.ollama_base_url.rstrip("/") or "http://localhost:11434"
        if value.provider == "ollama" and not value.model.strip():
            value.model = DEFAULT_MODELS["ollama"]
        value.workspace_path = value.workspace_path.strip()
        value.wake_phrases = ", ".join(item.strip().lower() for item in value.wake_phrases.split(",") if item.strip()) or "ассистент"
        value.system_prompt = value.system_prompt.strip() or Settings.system_prompt
        if value.echo_guard:
            value.barge_in = False
        if value.activation_mode in {"manual", "ptt"}:
            value.auto_listen = False
        return value

    def public(self) -> dict[str, Any]:
        value = asdict(self.settings)
        value["has_api_key"] = bool(self.get_secret(self.settings.provider))
        value["profiles"] = PROFILES
        return value

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        allowed = {item.name for item in fields(Settings)}
        current_provider = self.settings.provider
        for key, value in data.items():
            if key in allowed:
                setattr(self.settings, key, value)
        if "agent_enabled" in data:
            self.settings.agent_setup_completed = True
        if data.get("apply_profile") in PROFILES:
            self.settings.voice_profile = str(data["apply_profile"])
            for key, value in PROFILES[self.settings.voice_profile].items():
                setattr(self.settings, key, value)
        if self.settings.provider != current_provider and not str(data.get("model", "")).strip():
            self.settings.model = DEFAULT_MODELS.get(self.settings.provider, "")
        self.settings = self._normalize(self.settings)
        self._path.write_text(json.dumps(asdict(self.settings), ensure_ascii=False, indent=2), encoding="utf-8")
        api_key = data.get("api_key")
        if isinstance(api_key, str) and api_key.strip():
            self.set_secret(self.settings.provider, api_key.strip())
        if data.get("clear_api_key") is True:
            self.delete_secret(self.settings.provider)
        return self.public()

    def set_secret(self, provider: str, value: str) -> None:
        self._volatile_secrets[provider] = value
        if keyring is not None:
            try:
                keyring.set_password("WebViewDA", provider, value)
            except Exception:
                pass

    def delete_secret(self, provider: str) -> None:
        self._volatile_secrets.pop(provider, None)
        if keyring is not None:
            try:
                keyring.delete_password("WebViewDA", provider)
            except Exception:
                pass

    def get_secret(self, provider: str) -> str:
        if provider in self._volatile_secrets:
            return self._volatile_secrets[provider]
        if keyring is not None:
            try:
                return keyring.get_password("WebViewDA", provider) or ""
            except Exception:
                return ""
        return ""
