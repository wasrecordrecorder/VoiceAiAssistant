import json
import tempfile
import unittest
from pathlib import Path

from assistant_backend.agent.loop import AgentLoop
from assistant_backend.agent.policy import ApprovalManager
from assistant_backend.agent.tools import ToolRegistry, Workspace
from assistant_backend.agent.types import AssistantTurn, ToolCall
from assistant_backend.agent.web_tools import WebTools
from assistant_backend.core.settings import Settings
from assistant_backend.core.todos import TodoStore
from assistant_backend.core.memory import MemoryStore


class NullApprovals:
    async def request(self, action, summary, details):
        return True


class FakeProvider:
    def __init__(self) -> None:
        self.turns = 0
        self.received = []

    async def turn(self, messages, tools, on_delta, on_step):
        self.turns += 1
        self.received.append(messages)
        if self.turns == 1:
            return AssistantTurn("", [ToolCall("call-1", "read_file", {"path": "main.txt"})], "opaque-provider-state")
        return AssistantTurn("Готово", [])


class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_is_scoped_to_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            (root / "main.txt").write_text("alpha\nbeta", encoding="utf-8")
            registry = ToolRegistry(Settings(workspace_path=value), NullApprovals())
            result = json.loads(await registry.execute("read_file", {"path": "main.txt"}))
            self.assertTrue(result["ok"])
            self.assertIn("alpha", result["content"])

    async def test_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            registry = ToolRegistry(Settings(workspace_path=value), NullApprovals())
            result = json.loads(await registry.execute("read_file", {"path": "../outside.txt"}))
            self.assertFalse(result["ok"])
            self.assertIn("пределами", result["error"])

    async def test_write_file_can_be_approved(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            registry = ToolRegistry(Settings(workspace_path=value), NullApprovals())
            result = json.loads(await registry.execute("write_file", {"path": "out.txt", "content": "ready"}))
            self.assertTrue(result["ok"])
            self.assertEqual((Path(value) / "out.txt").read_text(encoding="utf-8"), "ready")

    async def test_search_ignores_symlink_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as value, tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "secret.txt"
            external.write_text("hidden token", encoding="utf-8")
            link = Path(value) / "linked.txt"
            try:
                link.symlink_to(external)
            except OSError:
                self.skipTest("Symlinks are unavailable")
            registry = ToolRegistry(Settings(workspace_path=value), NullApprovals())
            result = json.loads(await registry.execute("search_text", {"query": "hidden"}))
            self.assertTrue(result["ok"])
            self.assertEqual(result["matches"], [])


class AgentLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_result_returns_to_model(self) -> None:
        events = []
        deltas = []
        with tempfile.TemporaryDirectory() as value:
            (Path(value) / "main.txt").write_text("hello", encoding="utf-8")
            registry = ToolRegistry(Settings(workspace_path=value, agent_allow_edits=True), NullApprovals())

            async def event(name, payload):
                events.append(name)

            async def delta(text):
                deltas.append(text)

            async def step(kind, text):
                return None

            provider = FakeProvider()
            loop = AgentLoop(provider, registry, 4, event)
            result = await loop.run("read", [], delta, step)
            self.assertEqual(result, "Готово")
            self.assertEqual(provider.turns, 2)
            self.assertIn("agent.tool_finished", events)
            self.assertEqual(deltas, ["Готово"])
            self.assertEqual(provider.received[1][1]["reasoning_content"], "opaque-provider-state")

    async def test_system_tools_do_not_require_workspace(self) -> None:
        registry = ToolRegistry(Settings(workspace_path=""), NullApprovals())
        names = [schema["function"]["name"] for schema in registry.schemas()]
        self.assertIn("recycle_bin_status", names)
        self.assertIn("list_directory", names)
        self.assertIn("run_cmd", names)
        self.assertIn("run_powershell", names)
        self.assertIn("move_to_recycle_bin", names)
        self.assertIn("delete_path_permanently", names)
        self.assertIn("web_search", names)
        self.assertIn("music_search", names)
        self.assertIn("play_music", names)
        self.assertIn("music_control", names)
        self.assertIn("web_video_search", names)
        self.assertIn("web_read_page", names)
        self.assertIn("open_url", names)
        self.assertIn("send_hotkey", names)
        self.assertIn("type_text", names)
        self.assertIn("media_control", names)
        self.assertIn("screen_metrics", names)
        self.assertIn("window_list", names)
        self.assertIn("window_activate", names)
        self.assertIn("mouse_click", names)
        self.assertIn("mouse_drag", names)
        self.assertIn("mouse_scroll", names)
        self.assertIn("todo_create", names)
        self.assertIn("memory_remember", names)
        self.assertNotIn("read_file", names)

    async def test_main_agent_can_delegate_three_read_only_subagents(self) -> None:
        called = []

        async def delegate(tasks):
            called.extend(tasks)
            return [{"title": item["title"], "ok": True, "output": "готово"} for item in tasks]

        registry = ToolRegistry(Settings(), NullApprovals(), delegate=delegate)
        names = [schema["function"]["name"] for schema in registry.schemas()]
        self.assertIn("delegate_to_subagents", names)
        result = json.loads(await registry.execute("delegate_to_subagents", {"tasks": [
            {"title": "один", "instruction": "проверить один"},
            {"title": "два", "instruction": "проверить два"},
            {"title": "три", "instruction": "проверить три"},
        ]}))
        self.assertTrue(result["ok"])
        self.assertEqual(len(called), 3)

    async def test_web_tools_can_be_disabled_for_a_request(self) -> None:
        registry = ToolRegistry(Settings(), NullApprovals(), web_search_enabled=False)
        names = [schema["function"]["name"] for schema in registry.schemas()]
        self.assertNotIn("web_search", names)
        self.assertNotIn("web_read_page", names)
        self.assertIn("music_control", names)
        denied = json.loads(await registry.execute("web_search", {"query": "latest"}))
        self.assertFalse(denied["ok"])

    async def test_read_only_subagent_has_no_mutating_tools(self) -> None:
        registry = ToolRegistry(Settings(), NullApprovals(), read_only=True)
        names = [schema["function"]["name"] for schema in registry.schemas()]
        self.assertIn("web_search", names)
        self.assertNotIn("run_cmd", names)
        self.assertNotIn("todo_create", names)
        self.assertNotIn("mouse_click", names)
        denied = json.loads(await registry.execute("run_cmd", {"command": "whoami"}))
        self.assertFalse(denied["ok"])


    async def test_vision_tool_is_exposed_for_main_agent(self) -> None:
        registry = ToolRegistry(Settings(screen_vision_enabled=True), NullApprovals(), vision=lambda question, image: None)
        names = [schema["function"]["name"] for schema in registry.schemas()]
        self.assertIn("inspect_screen", names)

    async def test_system_tools_and_workspace_tools_are_exposed_together(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            registry = ToolRegistry(Settings(workspace_path=value), NullApprovals())
            names = [schema["function"]["name"] for schema in registry.schemas()]
            self.assertIn("read_text_file", names)
            self.assertIn("read_file", names)
            self.assertIn("run_command", names)

    async def test_list_directory_reads_approved_external_path(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            (root / "visible.txt").write_text("ready", encoding="utf-8")
            registry = ToolRegistry(Settings(workspace_path=""), NullApprovals())
            result = json.loads(await registry.execute("list_directory", {"path": value}))
            self.assertTrue(result["ok"])
            self.assertEqual(result["items"][0]["name"], "visible.txt")


class WebToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_play_music_targets_embedded_player(self) -> None:
        events = []
        async def event(name, payload):
            events.append((name, payload))
        tools = WebTools(NullApprovals(), True, event)
        async def music(arguments):
            return json.dumps({"ok": True, "results": [{"title": "Track", "url": "https://www.youtube.com/watch?v=abc123def45"}]})
        tools._music = music
        result = json.loads(await tools.execute("play_music", {"query": "track"}))
        self.assertTrue(result["ok"])
        self.assertEqual(result["player"], "embedded")
        self.assertEqual(events[0][0], "media.play")
        self.assertEqual(events[0][1]["video_id"], "abc123def45")

    async def test_localhost_page_fetch_is_blocked(self) -> None:
        tools = WebTools(NullApprovals(), False)
        result = json.loads(await tools.execute("web_read_page", {"url": "http://localhost/private"}))
        self.assertFalse(result["ok"])
        self.assertIn("Локальные", result["error"])


if __name__ == "__main__":
    unittest.main()


class OrganizerToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_can_manage_todos_and_memory(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            data = Path(value)
            todos = TodoStore(data)
            memory = MemoryStore(data, 3000)
            registry = ToolRegistry(Settings(), NullApprovals(), todos, memory)
            task = json.loads(await registry.execute("todo_create", {"title": "Написать отчёт", "priority": "important"}))
            self.assertTrue(task["ok"])
            stored = json.loads(await registry.execute("todo_list", {"important_only": True}))
            self.assertEqual(stored["items"][0]["title"], "Написать отчёт")
            remembered = json.loads(await registry.execute("memory_remember", {"text": "Писать кратко.", "category": "instruction", "importance": 5}))
            self.assertTrue(remembered["ok"])
            found = json.loads(await registry.execute("memory_search", {"query": "кратко"}))
            self.assertEqual(len(found["items"]), 1)

class TextModeAgentToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_hermes_team_delegates_coder_and_qa(self) -> None:
        received = []
        async def delegate(tasks):
            received.extend(tasks)
            return [{"title": item["title"], "ok": True} for item in tasks]
        registry = ToolRegistry(Settings(agent_strategy="hermes_duo"), NullApprovals(), delegate=delegate)
        result = json.loads(await registry.execute("hermes_team", {"task": "исправить баг"}))
        self.assertTrue(result["ok"])
        self.assertEqual([item["title"] for item in received], ["Hermes_Coder", "Hermes_AntiDebugger / QA-Tester"])

    async def test_file_edit_emits_compact_diff_statistics(self) -> None:
        events = []
        async def event(name, payload):
            events.append((name, payload))
        with tempfile.TemporaryDirectory() as value:
            path = Path(value) / "Test.java"
            path.write_text("class Test {}\n", encoding="utf-8")
            registry = ToolRegistry(Settings(workspace_path=value, agent_allow_edits=True), NullApprovals(), event=event)
            result = json.loads(await registry.execute("write_file", {"path": "Test.java", "content": "class Test {\n    int value;\n}\n"}))
            self.assertTrue(result["ok"])
            changed = [payload for name, payload in events if name == "file.edit"]
            self.assertTrue(changed)
            self.assertGreater(changed[0]["added"], 0)
