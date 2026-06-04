import tempfile
import unittest
from pathlib import Path

from assistant_backend.agent.types import ToolCall
from assistant_backend.core.settings import SettingsStore
from assistant_backend.providers.chat_completions import ChatCompletionsProvider
from assistant_backend.providers.factory import create_provider
from assistant_backend.providers.google import GoogleProvider
from assistant_backend.providers.messages import MessagesProvider
from assistant_backend.providers.responses import ResponsesProvider


class FakeHttp:
    def __init__(self, values):
        self.values = values

    async def sse(self, endpoint, headers, body):
        for value in self.values:
            yield value

    async def abort(self):
        return None


async def collect(provider):
    output = []
    steps = []

    async def delta(value):
        output.append(value)

    async def step(kind, value):
        steps.append((kind, value))

    turn = await provider.turn([{"role": "user", "content": "hello"}], [], delta, step)
    return turn, output, steps


class ProviderParsingTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_delta_stream(self) -> None:
        provider = ChatCompletionsProvider("http://local", "key", "m", "s")
        provider._http = FakeHttp([{"choices": [{"delta": {"content": "A"}}]}, {"choices": [{"delta": {"content": "B"}}]}])
        turn, output, _ = await collect(provider)
        self.assertEqual(turn.content, "AB")
        self.assertEqual(output, ["A", "B"])

    async def test_chat_tool_call_stream(self) -> None:
        provider = ChatCompletionsProvider("http://local", "key", "m", "s")
        provider._http = FakeHttp([
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "read_file", "arguments": "{\"path\":"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\"a.txt\"}"}}]}}]},
        ])
        turn, _, _ = await collect(provider)
        self.assertEqual(turn.tool_calls[0].name, "read_file")
        self.assertEqual(turn.tool_calls[0].arguments["path"], "a.txt")


    async def test_chat_preserves_reasoning_content_for_tool_continuation(self) -> None:
        provider = ChatCompletionsProvider("http://local", "key", "m", "s")
        provider._http = FakeHttp([
            {"choices": [{"delta": {"reasoning_content": "check "}}]},
            {"choices": [{"delta": {"reasoning_content": "files", "tool_calls": [{"index": 0, "id": "c1", "function": {"name": "read_file", "arguments": "{\\\"path\\\":\\\"a.txt\\\"}"}}]}}]},
        ])
        turn, _, _ = await collect(provider)
        self.assertEqual(turn.reasoning_content, "check files")
        converted = provider._convert([{"role": "assistant", "content": "", "tool_calls": turn.tool_calls, "reasoning_content": turn.reasoning_content}])
        self.assertEqual(converted[0]["reasoning_content"], "check files")

    async def test_messages_tool_call_stream(self) -> None:
        provider = MessagesProvider("http://local", "key", "m", "s")
        provider._http = FakeHttp([
            {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "c1", "name": "read_file", "input": {}}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": "{\"path\":\"a.txt\"}"}},
        ])
        turn, _, _ = await collect(provider)
        self.assertEqual(turn.tool_calls[0].arguments["path"], "a.txt")

    async def test_responses_tool_call_stream(self) -> None:
        provider = ResponsesProvider("http://local", "key", "m", "s")
        provider._http = FakeHttp([
            {"type": "response.output_item.added", "item": {"type": "function_call", "id": "i1", "call_id": "c1", "name": "read_file", "arguments": ""}},
            {"type": "response.function_call_arguments.delta", "item_id": "i1", "delta": "{\"path\":\"a.txt\"}"},
        ])
        turn, _, _ = await collect(provider)
        self.assertEqual(turn.tool_calls[0].name, "read_file")
        self.assertEqual(turn.tool_calls[0].arguments["path"], "a.txt")

    async def test_google_tool_call_stream(self) -> None:
        provider = GoogleProvider("http://local/model", "key", "m", "s")
        provider._http = FakeHttp([{"candidates": [{"content": {"parts": [{"functionCall": {"name": "read_file", "args": {"path": "a.txt"}}}]}}]}])
        turn, _, _ = await collect(provider)
        self.assertEqual(turn.tool_calls[0].name, "read_file")
        self.assertEqual(turn.tool_calls[0].arguments["path"], "a.txt")

    async def test_messages_combines_tool_results(self) -> None:
        provider = MessagesProvider("http://local", "key", "m", "s")
        converted = provider._convert([
            {"role": "assistant", "content": "", "tool_calls": [ToolCall("a", "read_file", {"path": "a"}), ToolCall("b", "read_file", {"path": "b"})]},
            {"role": "tool", "tool_call_id": "a", "name": "read_file", "content": "one"},
            {"role": "tool", "tool_call_id": "b", "name": "read_file", "content": "two"},
        ])
        self.assertEqual(len(converted), 2)
        self.assertEqual(len(converted[1]["content"]), 2)


class FactoryTests(unittest.TestCase):
    def test_go_qwen_creates_messages_provider(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            store.update({"provider": "opencode_go", "model": "qwen3.6-plus", "api_key": "key"})
            self.assertIsInstance(create_provider(store), MessagesProvider)

    def test_voice_style_prompt_is_always_attached(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            store.update({"provider": "openrouter", "model": "model", "api_key": "key"})
            provider = create_provider(store)
            self.assertIn("Не используй Markdown", provider._system_prompt)
            self.assertIn("Пиши числа", provider._system_prompt)


    def test_system_prompt_contains_current_time_context(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            store.update({"provider": "openrouter", "model": "model", "api_key": "key"})
            provider = create_provider(store)
            self.assertIn("Текущее локальное время пользователя", provider._system_prompt)

    def test_memory_context_is_injected_as_system_context(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            store.update({"provider": "openrouter", "model": "model", "api_key": "key"})
            provider = create_provider(store, "- [preference] Пользователь любит краткие ответы.")
            self.assertIn("Пользователь любит краткие ответы", provider._system_prompt)

    def test_zen_gpt_creates_responses_provider(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            store.update({"provider": "opencode_zen", "model": "gpt-5.5", "api_key": "key"})
            self.assertIsInstance(create_provider(store), ResponsesProvider)

    def test_freemodel_gpt_creates_chat_provider(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            store.update({"provider": "freemodel_gpt", "model": "gpt-5.5", "api_key": "key"})
            provider = create_provider(store)
            self.assertIsInstance(provider, ChatCompletionsProvider)
            self.assertEqual(provider._endpoint, "https://api.freemodel.dev/v1/chat/completions")

    def test_freemodel_rejects_unknown_model(self) -> None:
        with tempfile.TemporaryDirectory() as path:
            store = SettingsStore(Path(path))
            store.update({"provider": "freemodel_gpt", "model": "unknown", "api_key": "key"})
            provider = create_provider(store)
            self.assertEqual(provider._model, "gpt-5.5")


if __name__ == "__main__":
    unittest.main()
