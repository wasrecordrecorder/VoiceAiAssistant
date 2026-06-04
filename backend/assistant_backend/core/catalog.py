from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    id: str
    label: str
    protocol: str
    endpoint: str
    free: bool = False


ZEN_ENDPOINT = "https://opencode.ai/zen/v1"
GO_ENDPOINT = "https://opencode.ai/zen/go/v1"
FREEMODEL_ENDPOINT = "https://api.freemodel.dev/v1/chat/completions"
CATALOG_UPDATED = "2026-05-28"


def zen(model_id: str, label: str, protocol: str, free: bool = False) -> ModelRoute:
    endpoint = {
        "responses": f"{ZEN_ENDPOINT}/responses",
        "messages": f"{ZEN_ENDPOINT}/messages",
        "chat": f"{ZEN_ENDPOINT}/chat/completions",
        "google": f"{ZEN_ENDPOINT}/models/{model_id}",
    }[protocol]
    return ModelRoute("opencode_zen", model_id, label, protocol, endpoint, free)


def go(model_id: str, label: str, protocol: str) -> ModelRoute:
    endpoint = f"{GO_ENDPOINT}/messages" if protocol == "messages" else f"{GO_ENDPOINT}/chat/completions"
    return ModelRoute("opencode_go", model_id, label, protocol, endpoint)


def freemodel(model_id: str, label: str) -> ModelRoute:
    return ModelRoute("freemodel_gpt", model_id, label, "chat", FREEMODEL_ENDPOINT, True)


ZEN_MODELS = [
    zen("gpt-5.5", "GPT 5.5", "responses"),
    zen("gpt-5.5-pro", "GPT 5.5 Pro", "responses"),
    zen("gpt-5.4", "GPT 5.4", "responses"),
    zen("gpt-5.4-pro", "GPT 5.4 Pro", "responses"),
    zen("gpt-5.4-mini", "GPT 5.4 Mini", "responses"),
    zen("gpt-5.4-nano", "GPT 5.4 Nano", "responses"),
    zen("gpt-5.3-codex", "GPT 5.3 Codex", "responses"),
    zen("gpt-5.3-codex-spark", "GPT 5.3 Codex Spark", "responses"),
    zen("gpt-5.2", "GPT 5.2", "responses"),
    zen("gpt-5.2-codex", "GPT 5.2 Codex", "responses"),
    zen("gpt-5.1", "GPT 5.1", "responses"),
    zen("gpt-5.1-codex", "GPT 5.1 Codex", "responses"),
    zen("gpt-5.1-codex-max", "GPT 5.1 Codex Max", "responses"),
    zen("gpt-5.1-codex-mini", "GPT 5.1 Codex Mini", "responses"),
    zen("gpt-5", "GPT 5", "responses"),
    zen("gpt-5-codex", "GPT 5 Codex", "responses"),
    zen("gpt-5-nano", "GPT 5 Nano", "responses"),
    zen("claude-opus-4-7", "Claude Opus 4.7", "messages"),
    zen("claude-opus-4-6", "Claude Opus 4.6", "messages"),
    zen("claude-opus-4-5", "Claude Opus 4.5", "messages"),
    zen("claude-opus-4-1", "Claude Opus 4.1", "messages"),
    zen("claude-sonnet-4-6", "Claude Sonnet 4.6", "messages"),
    zen("claude-sonnet-4-5", "Claude Sonnet 4.5", "messages"),
    zen("claude-sonnet-4", "Claude Sonnet 4", "messages"),
    zen("claude-haiku-4-5", "Claude Haiku 4.5", "messages"),
    zen("claude-3-5-haiku", "Claude Haiku 3.5", "messages"),
    zen("gemini-3.5-flash", "Gemini 3.5 Flash", "google"),
    zen("gemini-3.1-pro", "Gemini 3.1 Pro", "google"),
    zen("gemini-3-flash", "Gemini 3 Flash", "google"),
    zen("qwen3.6-plus", "Qwen3.6 Plus", "messages"),
    zen("qwen3.5-plus", "Qwen3.5 Plus", "messages"),
    zen("minimax-m2.7", "MiniMax M2.7", "chat"),
    zen("minimax-m2.5", "MiniMax M2.5", "chat"),
    zen("glm-5.1", "GLM 5.1", "chat"),
    zen("glm-5", "GLM 5", "chat"),
    zen("kimi-k2.5", "Kimi K2.5", "chat"),
    zen("kimi-k2.6", "Kimi K2.6", "chat"),
    zen("grok-build-0.1", "Grok Build 0.1", "chat"),
    zen("big-pickle", "Big Pickle", "chat", True),
    zen("deepseek-v4-flash-free", "DeepSeek V4 Flash Free", "chat", True),
    zen("nemotron-3-super-free", "Nemotron 3 Super Free", "chat", True),
]

FREEMODEL_GPT_MODELS = [
    freemodel("gpt-5.5", "GPT 5.5"),
    freemodel("gpt-5.4", "GPT 5.4"),
    freemodel("gpt-5.4-mini", "GPT 5.4 Mini"),
    freemodel("gpt-5.3-codex", "GPT 5.3 Codex"),
]

GO_MODELS = [
    go("glm-5.1", "GLM 5.1", "chat"),
    go("glm-5", "GLM 5", "chat"),
    go("kimi-k2.5", "Kimi K2.5", "chat"),
    go("kimi-k2.6", "Kimi K2.6", "chat"),
    go("deepseek-v4-pro", "DeepSeek V4 Pro", "chat"),
    go("deepseek-v4-flash", "DeepSeek V4 Flash", "chat"),
    go("mimo-v2.5", "MiMo-V2.5", "chat"),
    go("mimo-v2.5-pro", "MiMo-V2.5-Pro", "chat"),
    go("minimax-m2.7", "MiniMax M2.7", "messages"),
    go("minimax-m2.5", "MiniMax M2.5", "messages"),
    go("qwen3.7-max", "Qwen3.7 Max", "messages"),
    go("qwen3.6-plus", "Qwen3.6 Plus", "messages"),
    go("qwen3.5-plus", "Qwen3.5 Plus", "messages"),
]

CATALOG = {"opencode_zen": ZEN_MODELS, "opencode_go": GO_MODELS, "freemodel_gpt": FREEMODEL_GPT_MODELS}
DEFAULT_MODELS = {"openrouter": "openai/gpt-4.1-mini", "opencode_zen": "deepseek-v4-flash-free", "opencode_go": "kimi-k2.6", "freemodel_gpt": "gpt-5.5", "ollama": "llama3.2", "custom": ""}


def models_for(provider: str) -> list[dict]:
    return [asdict(route) for route in CATALOG.get(provider, [])]


def route_for(provider: str, model: str) -> ModelRoute | None:
    return next((route for route in CATALOG.get(provider, []) if route.id == model), None)


def catalog_payload() -> dict:
    return {"updated": CATALOG_UPDATED, "providers": {key: models_for(key) for key in CATALOG}, "defaults": DEFAULT_MODELS}
