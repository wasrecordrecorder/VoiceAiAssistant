import asyncio
import csv
import difflib
import ctypes
import fnmatch
import io
import json
import os
import re
import shutil
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any

from ..core.memory import MemoryStore
from ..core.settings import Settings
from ..core.todos import TodoStore
from .policy import ApprovalManager
from .web_tools import WebTools
from .windows_input import KeyboardTools
from .screen_tools import ScreenTools, VisionCallback
from .desktop_tools import DesktopInteractionTools


DelegateCallback = Callable[[list[dict[str, str]]], Awaitable[list[dict[str, Any]]]]


class Workspace:
    def __init__(self, root: str) -> None:
        value = Path(os.path.expandvars(root)).expanduser() if root.strip() else None
        if value is None:
            raise RuntimeError("Укажите рабочую папку агента в настройках.")
        self.root = value.resolve()
        if not self.root.is_dir():
            raise RuntimeError("Рабочая папка агента не существует.")

    def resolve(self, relative: str, must_exist: bool = False) -> Path:
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise RuntimeError("Доступ за пределами рабочей папки запрещён.") from error
        if must_exist and not candidate.exists():
            raise RuntimeError(f"Путь не найден: {relative}")
        return candidate

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


class SystemPaths:
    def __init__(self, workspace: Workspace | None) -> None:
        self.home = Path.home().resolve()
        self.workspace = workspace
        self.safe_roots = [self.home]
        if workspace is not None and workspace.root != self.home:
            self.safe_roots.append(workspace.root)
        windows = os.environ.get("WINDIR", r"C:\Windows")
        self.protected_roots = [Path(windows).resolve()]
        for key in ("ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
            value = os.environ.get(key)
            if value:
                self.protected_roots.append(Path(value).resolve())

    def resolve(self, raw: str, must_exist: bool = False) -> Path:
        text = os.path.expandvars(str(raw or "")).strip()
        if not text:
            raise RuntimeError("Путь не указан.")
        value = Path(text).expanduser()
        candidate = value.resolve() if value.is_absolute() else (self.home / value).resolve()
        if must_exist and not candidate.exists():
            raise RuntimeError(f"Путь не найден: {candidate}")
        return candidate

    def trusted(self, path: Path) -> bool:
        return any(self._inside(path, root) for root in self.safe_roots)

    def require_mutable(self, path: Path) -> None:
        if not self.trusted(path):
            raise RuntimeError("Изменять файлы разрешено только в профиле пользователя или рабочей папке агента.")
        if any(path == root for root in self.safe_roots):
            raise RuntimeError("Нельзя изменить или удалить корневую разрешённую папку.")
        if any(self._inside(path, root) for root in self.protected_roots):
            raise RuntimeError("Изменение защищённых системных папок запрещено.")
        if path.anchor and path == Path(path.anchor):
            raise RuntimeError("Изменение корня диска запрещено.")

    @staticmethod
    def _inside(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False


class ToolRegistry:
    _ignored_directories = {".git", ".venv", "node_modules", "__pycache__", ".idea", ".vs"}

    _readonly_tools = {
        "todo_list",
        "memory_list",
        "memory_search",
        "get_known_folders",
        "recycle_bin_status",
        "list_processes",
        "path_info",
        "list_directory",
        "read_text_file",
        "web_search",
        "web_news_search",
        "music_search",
        "web_video_search",
        "web_read_page",
        "list_files",
        "read_file",
        "search_text",
        "visualize_panel",
    }

    def __init__(
        self,
        settings: Settings,
        approvals: ApprovalManager,
        todos: TodoStore | None = None,
        memory: MemoryStore | None = None,
        event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
        delegate: DelegateCallback | None = None,
        read_only: bool = False,
        vision: VisionCallback | None = None,
        web_search_enabled: bool = True,
    ) -> None:
        self._settings = settings
        self._workspace = Workspace(settings.workspace_path) if settings.workspace_path.strip() else None
        self._paths = SystemPaths(self._workspace)
        self._approvals = approvals
        self._web = WebTools(approvals, settings.agent_allow_commands, event)
        self._keyboard = KeyboardTools(approvals, settings.agent_allow_commands)
        self._screen = ScreenTools(settings, approvals, vision)
        self._desktop = DesktopInteractionTools(approvals, settings.agent_allow_commands)
        self._todos = todos
        self._memory = memory
        self._event = event
        self._delegate = delegate
        self._read_only = read_only
        self._web_search_enabled = bool(web_search_enabled)

    def schemas(self) -> list[dict[str, Any]]:
        schemas = [
            self._schema(
                "todo_list",
                "List the user's saved tasks and notes. Use when the user asks what they need to do, what is important, or what was saved for later.",
                {"type": "object", "properties": {"status": {"type": "string", "enum": ["todo", "later", "done"]}, "kind": {"type": "string", "enum": ["task", "note"]}, "important_only": {"type": "boolean"}, "query": {"type": "string"}}},
            ),
            self._schema(
                "todo_create",
                "Create a task or note in the user's organizer when the user asks to remember a task, create a note, or add something for later.",
                {"type": "object", "properties": {"kind": {"type": "string", "enum": ["task", "note"]}, "title": {"type": "string"}, "body": {"type": "string"}, "status": {"type": "string", "enum": ["todo", "later", "done"]}, "priority": {"type": "string", "enum": ["normal", "important"]}, "due_at": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["title"]},
            ),
            self._schema(
                "todo_update",
                "Update, mark important, postpone, or complete a saved task or note. First use todo_list to find the id.",
                {"type": "object", "properties": {"id": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"}, "status": {"type": "string", "enum": ["todo", "later", "done"]}, "priority": {"type": "string", "enum": ["normal", "important"]}, "due_at": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["id"]},
            ),
            self._schema(
                "todo_delete",
                "Delete a saved task or note after the user directly asks to remove it. First use todo_list to find the id.",
                {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            ),
            self._schema(
                "memory_list",
                "List long-term memory entries kept about the user.",
                {"type": "object", "properties": {}},
            ),
            self._schema(
                "memory_search",
                "Search long-term memory for relevant stable facts, preferences or instructions.",
                {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            ),
            self._schema(
                "memory_remember",
                "Save a stable fact, preference or instruction to long-term memory only when the user explicitly asks to remember it or it is clearly a persistent preference.",
                {"type": "object", "properties": {"text": {"type": "string"}, "category": {"type": "string", "enum": ["preference", "fact", "instruction", "context"]}, "importance": {"type": "integer", "minimum": 1, "maximum": 5}}, "required": ["text"]},
            ),
            self._schema(
                "memory_update",
                "Correct an existing long-term memory entry after finding it with memory_list or memory_search.",
                {"type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}, "category": {"type": "string", "enum": ["preference", "fact", "instruction", "context"]}, "importance": {"type": "integer", "minimum": 1, "maximum": 5}}, "required": ["id", "text"]},
            ),
            self._schema(
                "memory_forget",
                "Delete an existing long-term memory entry only when the user asks to forget or delete that memory.",
                {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            ),
            self._schema(
                "get_known_folders",
                "Return the user's common Windows folders such as home, Desktop, Documents and Downloads. Use before acting on user files when the path is not known.",
                {"type": "object", "properties": {}},
            ),
            self._schema(
                "recycle_bin_status",
                "Get Windows Recycle Bin item count and total stored size. Use this for questions about whether the recycle bin is empty.",
                {"type": "object", "properties": {}},
            ),
            self._schema(
                "empty_recycle_bin",
                "Empty the Windows Recycle Bin after user confirmation. This is destructive.",
                {"type": "object", "properties": {}},
            ),
            self._schema(
                "list_processes",
                "List running Windows processes with image name, process id and memory usage.",
                {"type": "object", "properties": {"filter": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}},
            ),
            self._schema(
                "path_info",
                "Read metadata for a local file or directory path. External paths may require user approval.",
                {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            ),
            self._schema(
                "list_directory",
                "List files and directories at a local path on the user's computer. External paths may require user approval.",
                {"type": "object", "properties": {"path": {"type": "string"}, "max_items": {"type": "integer", "minimum": 1, "maximum": 300}}, "required": ["path"]},
            ),
            self._schema(
                "read_text_file",
                "Read a UTF-8 text file by local path. External paths may require user approval.",
                {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}}, "required": ["path"]},
            ),
            self._schema(
                "write_text_file",
                "Create or replace a UTF-8 text file under the user's profile or workspace. Requires user confirmation unless file edits were explicitly allowed.",
                {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
            ),
            self._schema(
                "create_directory",
                "Create a directory under the user's profile or workspace. Requires user confirmation unless file edits were explicitly allowed.",
                {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            ),
            self._schema(
                "copy_path",
                "Copy a local file or directory within the user's profile or workspace. Requires user confirmation unless file edits were explicitly allowed.",
                {"type": "object", "properties": {"source": {"type": "string"}, "destination": {"type": "string"}}, "required": ["source", "destination"]},
            ),
            self._schema(
                "move_path",
                "Move or rename a local file or directory within the user's profile or workspace. Requires user confirmation unless file edits were explicitly allowed.",
                {"type": "object", "properties": {"source": {"type": "string"}, "destination": {"type": "string"}}, "required": ["source", "destination"]},
            ),
            self._schema(
                "move_to_recycle_bin",
                "Delete a user file or directory by moving it to the Windows Recycle Bin. Prefer this over permanent deletion. Requires confirmation.",
                {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            ),
            self._schema(
                "delete_path_permanently",
                "Permanently delete a user file or directory. Use only when the user explicitly asks for irreversible deletion. Always requires confirmation.",
                {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            ),
            self._schema(
                "open_path",
                "Open an existing file or directory using the Windows default application. Requires confirmation unless command execution was explicitly allowed.",
                {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            ),
            self._schema(
                "launch_application",
                "Launch an application executable with optional arguments. Requires confirmation unless command execution was explicitly allowed.",
                {"type": "object", "properties": {"executable": {"type": "string"}, "arguments": {"type": "array", "items": {"type": "string"}, "maxItems": 40}}, "required": ["executable"]},
            ),
            self._schema(
                "run_cmd",
                "Run a Windows Command Prompt command and capture output. Requires confirmation unless command execution was explicitly allowed.",
                {"type": "object", "properties": {"command": {"type": "string"}, "cwd": {"type": "string"}, "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 180}}, "required": ["command"]},
            ),
            self._schema(
                "run_powershell",
                "Run a PowerShell command and capture output. Requires confirmation unless command execution was explicitly allowed.",
                {"type": "object", "properties": {"script": {"type": "string"}, "cwd": {"type": "string"}, "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 180}}, "required": ["script"]},
            ),
        ]
        web_schemas = self._web.schemas()
        if not self._web_search_enabled:
            searchable = {"web_search", "web_news_search", "music_search", "play_music", "web_video_search", "web_read_page"}
            web_schemas = [schema for schema in web_schemas if schema["function"]["name"] not in searchable]
        schemas.extend(web_schemas)
        schemas.extend(self._keyboard.schemas())
        if not self._read_only:
            schemas.extend(self._desktop.schemas())
        if self._settings.screen_vision_enabled and not self._read_only:
            schemas.extend(self._screen.schemas())
        if not self._read_only:
            schemas.append(
                self._schema(
                    "visualize_panel",
                    "Show, update or hide a live whiteboard panel in the assistant UI. Use it when the user asks to visualize an explanation or when a diagram would clearly help. Use action show or replace first, then append or replace for gradual updates, and hide when finished.",
                    {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["show", "replace", "append", "hide"]},
                            "title": {"type": "string"},
                            "html": {"type": "string"}
                        },
                        "required": ["action"]
                    },
                )
            )
        if self._delegate is not None and not self._read_only:
            schemas.append(
                self._schema(
                    "delegate_to_subagents",
                    "Delegate up to three independent read-only investigations to parallel subagents. Use when separate research or inspection tasks can run concurrently. The main agent must perform final changes and user-facing conclusions.",
                    {
                        "type": "object",
                        "properties": {
                            "tasks": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 3,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "instruction": {"type": "string"},
                                    },
                                    "required": ["title", "instruction"],
                                },
                            }
                        },
                        "required": ["tasks"],
                    },
                )
            )
        if self._delegate is not None and not self._read_only:
            schemas.append(
                self._schema(
                    "hermes_team",
                    "Run the specialized Hermes_Coder and Hermes_AntiDebugger QA reviewers in parallel for a coding or project task. Use this in Hermes Duo strategy before risky edits or when the user asks for multi-agent review.",
                    {
                        "type": "object",
                        "properties": {
                            "task": {"type": "string"},
                            "focus": {"type": "string"}
                        },
                        "required": ["task"]
                    },
                )
            )
        if self._workspace is not None:
            schemas.extend([
            self._schema(
                "list_files",
                "List files inside the configured project workspace.",
                {"type": "object", "properties": {"path": {"type": "string"}, "glob": {"type": "string"}, "max_depth": {"type": "integer", "minimum": 1, "maximum": 12}}},
            ),
            self._schema(
                "read_file",
                "Read UTF-8 text from a project workspace file with optional line range.",
                {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}}, "required": ["path"]},
            ),
            self._schema(
                "search_text",
                "Search text or a regular expression inside project workspace files.",
                {"type": "object", "properties": {"query": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"}, "regex": {"type": "boolean"}, "max_results": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": ["query"]},
            ),
            self._schema(
                "write_file",
                "Create or replace a UTF-8 text file inside the project workspace.",
                {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
            ),
            self._schema(
                "replace_in_file",
                "Replace an exact text fragment in one UTF-8 project workspace file.",
                {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}, "replace_all": {"type": "boolean"}}, "required": ["path", "old_text", "new_text"]},
            ),
            self._schema(
                "run_command",
                "Run an executable with arguments inside the project workspace without shell expansion.",
                {"type": "object", "properties": {"argv": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 40}, "cwd": {"type": "string"}, "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 180}}, "required": ["argv"]},
            ),
        ])
        if self._read_only:
            schemas = [schema for schema in schemas if schema["function"]["name"] in self._readonly_tools]
        return schemas

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if self._read_only and name not in self._readonly_tools:
            return self._result(False, error="Субагентам разрешены только чтение и исследование. Изменяющее действие должен выполнить основной агент.")
        if name == "delegate_to_subagents":
            return await self._delegate_to_subagents(arguments)
        if name == "hermes_team":
            return await self._hermes_team(arguments)
        if name in {"web_search", "web_news_search", "music_search", "play_music", "web_video_search", "web_read_page"} and not self._web_search_enabled:
            return self._result(False, error="Веб-поиск выключен пользователем для этого запроса.")
        if name in {"web_search", "web_news_search", "music_search", "play_music", "music_control", "web_video_search", "web_read_page", "open_url"}:
            return await self._web.execute(name, arguments)
        if name in {"send_hotkey", "type_text", "media_control", "browser_action"}:
            return await self._keyboard.execute(name, arguments)
        if name in {"screen_metrics", "window_list", "window_activate", "mouse_move", "mouse_click", "mouse_drag", "mouse_scroll"}:
            return await self._desktop.execute(name, arguments)
        if name == "inspect_screen":
            return await self._screen.execute(arguments)
        if name == "visualize_panel":
            return await self._visualize_panel(arguments)
        handlers = {
            "todo_list": self._todo_list,
            "todo_create": self._todo_create,
            "todo_update": self._todo_update,
            "todo_delete": self._todo_delete,
            "memory_list": self._memory_list,
            "memory_search": self._memory_search,
            "memory_remember": self._memory_remember,
            "memory_update": self._memory_update,
            "memory_forget": self._memory_forget,
            "get_known_folders": self._get_known_folders,
            "recycle_bin_status": self._recycle_bin_status,
            "empty_recycle_bin": self._empty_recycle_bin,
            "list_processes": self._list_processes,
            "path_info": self._path_info,
            "list_directory": self._list_directory,
            "read_text_file": self._read_text_file,
            "write_text_file": self._write_text_file,
            "create_directory": self._create_directory,
            "copy_path": self._copy_path,
            "move_path": self._move_path,
            "move_to_recycle_bin": self._move_to_recycle_bin,
            "delete_path_permanently": self._delete_path_permanently,
            "open_path": self._open_path,
            "launch_application": self._launch_application,
            "run_cmd": self._run_cmd,
            "run_powershell": self._run_powershell,
            "list_files": self._list_files,
            "read_file": self._read_file,
            "search_text": self._search_text,
            "write_file": self._write_file,
            "replace_in_file": self._replace_in_file,
            "run_command": self._run_command,
        }
        handler = handlers.get(name)
        if handler is None:
            return self._result(False, error=f"Неизвестный инструмент: {name}")
        try:
            return await handler(arguments)
        except Exception as error:
            return self._result(False, error=str(error))


    async def _visualize_panel(self, arguments: dict[str, Any]) -> str:
        action = str(arguments.get("action", "")).strip().lower()
        if action not in {"show", "replace", "append", "hide"}:
            raise RuntimeError("Неизвестное действие visualize_panel.")
        title = str(arguments.get("title", "")).strip()[:120]
        html_value = str(arguments.get("html", ""))
        if action in {"show", "replace", "append"} and not html_value.strip():
            raise RuntimeError("Для показа или обновления панели нужен html.")
        payload = {"action": action, "title": title, "html": html_value}
        await self._broadcast("visualization.update", payload)
        return self._result(True, **payload)

    async def _broadcast(self, event: str, payload: dict[str, Any]) -> None:
        if self._event is not None:
            await self._event(event, payload)

    async def _delegate_to_subagents(self, arguments: dict[str, Any]) -> str:
        if self._delegate is None:
            raise RuntimeError("Диспетчер субагентов недоступен.")
        raw_tasks = arguments.get("tasks", [])
        if not isinstance(raw_tasks, list):
            raise RuntimeError("Задачи субагентов должны быть массивом.")
        tasks = []
        for value in raw_tasks[:3]:
            if not isinstance(value, dict):
                continue
            title = str(value.get("title", "")).strip()[:100]
            instruction = str(value.get("instruction", "")).strip()[:2000]
            if title and instruction:
                tasks.append({"title": title, "instruction": instruction})
        if not tasks:
            raise RuntimeError("Не переданы корректные задачи для субагентов.")
        results = await self._delegate(tasks)
        return self._result(True, results=results)

    async def _hermes_team(self, arguments: dict[str, Any]) -> str:
        if self._delegate is None:
            raise RuntimeError("Диспетчер субагентов недоступен.")
        task = str(arguments.get("task", "")).strip()[:3000]
        focus = str(arguments.get("focus", "")).strip()[:800]
        if not task:
            raise RuntimeError("Не указана задача Hermes team.")
        tasks = [
            {"title": "Hermes_Coder", "instruction": f"Ты Hermes_Coder. Исследуй задачу и предложи минимальные чистые изменения без комментариев в коде. Задача: {task}. Фокус: {focus}"},
            {"title": "Hermes_AntiDebugger / QA-Tester", "instruction": f"Ты Hermes_AntiDebugger и QA-Tester. Найди риски, регрессии и необходимые тесты для задачи. Задача: {task}. Фокус: {focus}"},
        ]
        results = await self._delegate(tasks)
        return self._result(True, strategy="hermes_duo", results=results)

    async def _emit_edit(self, path: str, before: str, after: str) -> None:
        added = 0
        removed = 0
        for line in difflib.ndiff(before.splitlines(), after.splitlines()):
            if line.startswith("+ "):
                added += 1
            elif line.startswith("- "):
                removed += 1
        await self._broadcast("file.edit", {"path": path, "added": added, "removed": removed})

    async def _todo_list(self, arguments: dict[str, Any]) -> str:
        if self._todos is None:
            raise RuntimeError("Хранилище задач недоступно.")
        items = self._todos.list(str(arguments.get("status", "")), str(arguments.get("kind", "")), bool(arguments.get("important_only", False)), str(arguments.get("query", "")))
        return self._result(True, items=items, summary=self._todos.summary())

    async def _todo_create(self, arguments: dict[str, Any]) -> str:
        if self._todos is None:
            raise RuntimeError("Хранилище задач недоступно.")
        item = self._todos.create(str(arguments.get("title", "")), str(arguments.get("body", "")), str(arguments.get("kind", "task")), str(arguments.get("status", "todo")), str(arguments.get("priority", "normal")), str(arguments.get("due_at", "")), arguments.get("tags", []))
        await self._broadcast("todo.current", {"items": self._todos.list(), "summary": self._todos.summary()})
        return self._result(True, item=item)

    async def _todo_update(self, arguments: dict[str, Any]) -> str:
        if self._todos is None:
            raise RuntimeError("Хранилище задач недоступно.")
        item_id = str(arguments.get("id", ""))
        changes = {key: arguments[key] for key in ("title", "body", "kind", "status", "priority", "due_at", "tags") if key in arguments}
        item = self._todos.update(item_id, changes)
        await self._broadcast("todo.current", {"items": self._todos.list(), "summary": self._todos.summary()})
        return self._result(True, item=item)

    async def _todo_delete(self, arguments: dict[str, Any]) -> str:
        if self._todos is None:
            raise RuntimeError("Хранилище задач недоступно.")
        self._todos.delete(str(arguments.get("id", "")))
        await self._broadcast("todo.current", {"items": self._todos.list(), "summary": self._todos.summary()})
        return self._result(True, deleted=True)

    async def _memory_list(self, arguments: dict[str, Any]) -> str:
        if self._memory is None:
            raise RuntimeError("Память недоступна.")
        return self._result(True, **self._memory.public())

    async def _memory_search(self, arguments: dict[str, Any]) -> str:
        if self._memory is None:
            raise RuntimeError("Память недоступна.")
        items = [item.__dict__ for item in self._memory.search(str(arguments.get("query", "")))]
        return self._result(True, items=items)

    async def _memory_remember(self, arguments: dict[str, Any]) -> str:
        if self._memory is None:
            raise RuntimeError("Память недоступна.")
        item = self._memory.add(str(arguments.get("text", "")), str(arguments.get("category", "fact")), int(arguments.get("importance", 3)))
        await self._broadcast("memory.current", self._memory.public())
        return self._result(True, item=item.__dict__)

    async def _memory_update(self, arguments: dict[str, Any]) -> str:
        if self._memory is None:
            raise RuntimeError("Память недоступна.")
        item = self._memory.update(str(arguments.get("id", "")), str(arguments.get("text", "")), arguments.get("category"), arguments.get("importance"))
        await self._broadcast("memory.current", self._memory.public())
        return self._result(True, item=item.__dict__)

    async def _memory_forget(self, arguments: dict[str, Any]) -> str:
        if self._memory is None:
            raise RuntimeError("Память недоступна.")
        self._memory.delete(str(arguments.get("id", "")))
        await self._broadcast("memory.current", self._memory.public())
        return self._result(True, deleted=True)

    def _schema(self, name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}

    def _require_workspace(self) -> Workspace:
        if self._workspace is None:
            raise RuntimeError("Для инструментов проекта укажите рабочую папку агента.")
        return self._workspace

    async def _approve_external_read(self, path: Path, action: str) -> None:
        if self._paths.trusted(path):
            return
        approved = await self._approvals.request(action, f"Прочитать внешний путь {path}", {"path": str(path)})
        if not approved:
            raise RuntimeError("Пользователь отклонил чтение внешнего пути.")

    async def _approve_edit(self, action: str, summary: str, details: dict[str, Any], always: bool = False) -> bool:
        if not always and self._settings.agent_allow_edits:
            return True
        return await self._approvals.request(action, summary, details)

    async def _approve_command(self, action: str, summary: str, details: dict[str, Any]) -> bool:
        if self._settings.agent_allow_commands:
            return True
        return await self._approvals.request(action, summary, details)

    async def _get_known_folders(self, arguments: dict[str, Any]) -> str:
        home = self._paths.home
        folders = {"home": str(home)}
        for name in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"):
            candidate = home / name
            if candidate.exists():
                folders[name.lower()] = str(candidate)
        if self._workspace is not None:
            folders["workspace"] = str(self._workspace.root)
        return self._result(True, folders=folders)

    async def _recycle_bin_status(self, arguments: dict[str, Any]) -> str:
        if os.name != "nt":
            raise RuntimeError("Проверка корзины поддерживается только на Windows.")
        class QueryInfo(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]
        info = QueryInfo()
        info.cbSize = ctypes.sizeof(QueryInfo)
        result = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        if result != 0:
            raise RuntimeError(f"Windows не смогла прочитать состояние корзины: HRESULT 0x{result & 0xFFFFFFFF:08X}.")
        return self._result(True, empty=info.i64NumItems == 0, item_count=int(info.i64NumItems), size_bytes=int(info.i64Size))

    async def _empty_recycle_bin(self, arguments: dict[str, Any]) -> str:
        if os.name != "nt":
            raise RuntimeError("Очистка корзины поддерживается только на Windows.")
        permitted = await self._approvals.request("empty_recycle_bin", "Безвозвратно очистить корзину Windows", {})
        if not permitted:
            return self._result(False, error="Пользователь отклонил очистку корзины.")
        flags = 0x00000001 | 0x00000002 | 0x00000004
        result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
        if result != 0:
            raise RuntimeError(f"Windows не смогла очистить корзину: HRESULT 0x{result & 0xFFFFFFFF:08X}.")
        return self._result(True, emptied=True)

    async def _list_processes(self, arguments: dict[str, Any]) -> str:
        if os.name != "nt":
            raise RuntimeError("Список процессов поддерживается только на Windows.")
        query = str(arguments.get("filter", "")).lower().strip()
        limit = min(100, max(1, int(arguments.get("limit", 40))))
        process = await asyncio.create_subprocess_exec("tasklist.exe", "/FO", "CSV", "/NH", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        output, error = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(error.decode(errors="replace") or "Не удалось получить список процессов.")
        text = output.decode("mbcs", errors="replace")
        items = []
        for row in csv.reader(io.StringIO(text)):
            if len(row) < 5 or (query and query not in row[0].lower()):
                continue
            items.append({"name": row[0], "pid": row[1], "memory": row[4]})
            if len(items) >= limit:
                break
        return self._result(True, processes=items, truncated=len(items) >= limit)

    async def _path_info(self, arguments: dict[str, Any]) -> str:
        path = self._paths.resolve(str(arguments.get("path", "")), True)
        await self._approve_external_read(path, "path_info")
        stat = path.stat()
        return self._result(True, path=str(path), kind="directory" if path.is_dir() else "file", size_bytes=stat.st_size, modified_ns=stat.st_mtime_ns)

    async def _list_directory(self, arguments: dict[str, Any]) -> str:
        path = self._paths.resolve(str(arguments.get("path", "")), True)
        await self._approve_external_read(path, "list_directory")
        if not path.is_dir():
            raise RuntimeError("Путь для list_directory должен быть папкой.")
        limit = min(300, max(1, int(arguments.get("max_items", 120))))
        items = []
        for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            try:
                stat = child.stat()
                items.append({"name": child.name, "path": str(child), "kind": "directory" if child.is_dir() else "file", "size_bytes": stat.st_size if child.is_file() else None})
            except OSError:
                items.append({"name": child.name, "path": str(child), "kind": "unavailable"})
            if len(items) >= limit:
                break
        return self._result(True, path=str(path), items=items, truncated=len(items) >= limit)

    async def _read_text_file(self, arguments: dict[str, Any]) -> str:
        path = self._paths.resolve(str(arguments.get("path", "")), True)
        await self._approve_external_read(path, "read_text_file")
        if not path.is_file():
            raise RuntimeError("Путь для read_text_file должен быть файлом.")
        if path.stat().st_size > 2_000_000:
            raise RuntimeError("Файл слишком большой для чтения агентом.")
        return self._read_lines(path, str(path), arguments)

    async def _write_text_file(self, arguments: dict[str, Any]) -> str:
        path = self._paths.resolve(str(arguments.get("path", "")))
        self._paths.require_mutable(path)
        content = str(arguments.get("content", ""))
        before = path.read_text(encoding="utf-8", errors="replace") if path.exists() and path.is_file() else ""
        permitted = await self._approve_edit("write_text_file", f"Записать файл {path}", {"path": str(path), "size": len(content)})
        if not permitted:
            return self._result(False, error="Пользователь отклонил запись файла.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        await self._emit_edit(str(path), before, content)
        return self._result(True, path=str(path), bytes=len(content.encode("utf-8")))

    async def _create_directory(self, arguments: dict[str, Any]) -> str:
        path = self._paths.resolve(str(arguments.get("path", "")))
        self._paths.require_mutable(path)
        permitted = await self._approve_edit("create_directory", f"Создать папку {path}", {"path": str(path)})
        if not permitted:
            return self._result(False, error="Пользователь отклонил создание папки.")
        path.mkdir(parents=True, exist_ok=True)
        return self._result(True, path=str(path))

    async def _copy_path(self, arguments: dict[str, Any]) -> str:
        source = self._paths.resolve(str(arguments.get("source", "")), True)
        await self._approve_external_read(source, "copy_path")
        destination = self._paths.resolve(str(arguments.get("destination", "")))
        self._paths.require_mutable(destination)
        permitted = await self._approve_edit("copy_path", f"Копировать {source.name}", {"source": str(source), "destination": str(destination)})
        if not permitted:
            return self._result(False, error="Пользователь отклонил копирование.")
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=False)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        return self._result(True, source=str(source), destination=str(destination))

    async def _move_path(self, arguments: dict[str, Any]) -> str:
        source = self._paths.resolve(str(arguments.get("source", "")), True)
        destination = self._paths.resolve(str(arguments.get("destination", "")))
        self._paths.require_mutable(source)
        self._paths.require_mutable(destination)
        permitted = await self._approve_edit("move_path", f"Переместить {source.name}", {"source": str(source), "destination": str(destination)})
        if not permitted:
            return self._result(False, error="Пользователь отклонил перемещение.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        moved = shutil.move(str(source), str(destination))
        return self._result(True, destination=moved)

    async def _move_to_recycle_bin(self, arguments: dict[str, Any]) -> str:
        if os.name != "nt":
            raise RuntimeError("Корзина поддерживается только на Windows.")
        path = self._paths.resolve(str(arguments.get("path", "")), True)
        self._paths.require_mutable(path)
        permitted = await self._approvals.request("move_to_recycle_bin", f"Удалить в корзину {path}", {"path": str(path)})
        if not permitted:
            return self._result(False, error="Пользователь отклонил удаление.")
        class FileOperation(ctypes.Structure):
            _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p), ("pTo", ctypes.c_wchar_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int), ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]
        source = str(path) + "\0\0"
        operation = FileOperation(None, 3, source, None, 0x0040 | 0x0010 | 0x0004 | 0x0400, 0, None, None)
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
        if result != 0 or operation.fAnyOperationsAborted:
            raise RuntimeError(f"Windows не смогла переместить путь в корзину: код {result}.")
        return self._result(True, recycled=str(path))

    async def _delete_path_permanently(self, arguments: dict[str, Any]) -> str:
        path = self._paths.resolve(str(arguments.get("path", "")), True)
        self._paths.require_mutable(path)
        permitted = await self._approve_edit("delete_path_permanently", f"Безвозвратно удалить {path}", {"path": str(path), "irreversible": True}, always=True)
        if not permitted:
            return self._result(False, error="Пользователь отклонил безвозвратное удаление.")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return self._result(True, deleted=str(path), permanent=True)

    async def _open_path(self, arguments: dict[str, Any]) -> str:
        if os.name != "nt":
            raise RuntimeError("Открытие пути поддерживается только на Windows.")
        path = self._paths.resolve(str(arguments.get("path", "")), True)
        permitted = await self._approve_command("open_path", f"Открыть {path}", {"path": str(path)})
        if not permitted:
            return self._result(False, error="Пользователь отклонил открытие пути.")
        os.startfile(str(path))
        return self._result(True, opened=str(path))

    async def _launch_application(self, arguments: dict[str, Any]) -> str:
        if os.name != "nt":
            raise RuntimeError("Запуск приложений поддерживается только на Windows.")
        executable = str(arguments.get("executable", "")).strip()
        argv = arguments.get("arguments", []) or []
        if not executable or not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            raise RuntimeError("Укажите executable и массив arguments.")
        permitted = await self._approve_command("launch_application", f"Запустить {executable}", {"executable": executable, "arguments": argv})
        if not permitted:
            return self._result(False, error="Пользователь отклонил запуск приложения.")
        process = await asyncio.create_subprocess_exec(executable, *argv)
        return self._result(True, pid=process.pid, executable=executable)

    async def _run_cmd(self, arguments: dict[str, Any]) -> str:
        return await self._run_shell("cmd", str(arguments.get("command", "")), arguments)

    async def _run_powershell(self, arguments: dict[str, Any]) -> str:
        return await self._run_shell("powershell", str(arguments.get("script", "")), arguments)

    async def _run_shell(self, shell: str, command: str, arguments: dict[str, Any]) -> str:
        if os.name != "nt":
            raise RuntimeError("Запуск Windows-команд поддерживается только на Windows.")
        if not command.strip():
            raise RuntimeError("Команда не указана.")
        cwd = self._resolve_cwd(arguments.get("cwd", ""))
        timeout = min(180, max(1, int(arguments.get("timeout_seconds", self._settings.agent_command_timeout))))
        permitted = await self._approve_command(f"run_{shell}", f"Запустить {shell}", {"command": command, "cwd": str(cwd), "timeout_seconds": timeout})
        if not permitted:
            return self._result(False, error="Пользователь отклонил запуск команды.")
        argv = ["cmd.exe", "/D", "/S", "/C", command] if shell == "cmd" else ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command]
        return await self._capture_process(argv, cwd, timeout)

    def _resolve_cwd(self, raw: Any) -> Path:
        if str(raw or "").strip():
            path = self._paths.resolve(str(raw), True)
            if not path.is_dir():
                raise RuntimeError("Рабочая директория команды должна быть папкой.")
            return path
        return self._workspace.root if self._workspace is not None else self._paths.home

    async def _capture_process(self, argv: list[str], cwd: Path, timeout: int) -> str:
        process = await asyncio.create_subprocess_exec(*argv, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=os.environ.copy())
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return self._result(False, error=f"Команда остановлена по таймауту {timeout} с.")
        text = output.decode("utf-8", errors="replace")[-20000:]
        return self._result(process.returncode == 0, exit_code=process.returncode, output=text)

    async def _list_files(self, arguments: dict[str, Any]) -> str:
        workspace = self._require_workspace()
        base = workspace.resolve(str(arguments.get("path", "")), True)
        if not base.is_dir():
            raise RuntimeError("Путь для list_files должен быть папкой.")
        pattern = str(arguments.get("glob", "*") or "*")
        max_depth = min(12, max(1, int(arguments.get("max_depth", 4))))
        items: list[str] = []
        for path in sorted(base.rglob("*")):
            try:
                path.resolve().relative_to(workspace.root)
            except ValueError:
                continue
            relative_to_base = path.relative_to(base)
            if any(part in self._ignored_directories for part in relative_to_base.parts):
                continue
            if len(relative_to_base.parts) > max_depth or not fnmatch.fnmatch(path.name, pattern):
                continue
            items.append(workspace.relative(path) + ("/" if path.is_dir() else ""))
            if len(items) >= 240:
                break
        return self._result(True, items=items, truncated=len(items) >= 240)

    async def _read_file(self, arguments: dict[str, Any]) -> str:
        workspace = self._require_workspace()
        relative = str(arguments.get("path", ""))
        path = workspace.resolve(relative, True)
        if not path.is_file():
            raise RuntimeError("Путь для read_file должен быть файлом.")
        if path.stat().st_size > 2_000_000:
            raise RuntimeError("Файл слишком большой для чтения агентом.")
        return self._read_lines(path, relative, arguments)

    def _read_lines(self, path: Path, name: str, arguments: dict[str, Any]) -> str:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(1, int(arguments.get("start_line", 1)))
        end = min(len(lines), int(arguments.get("end_line", min(len(lines), start + 399))))
        numbered = "\n".join(f"{index}: {lines[index - 1]}" for index in range(start, end + 1))
        return self._result(True, path=name, start_line=start, end_line=end, content=numbered)

    async def _search_text(self, arguments: dict[str, Any]) -> str:
        workspace = self._require_workspace()
        query = str(arguments.get("query", ""))
        if not query:
            raise RuntimeError("Пустой поисковый запрос.")
        base = workspace.resolve(str(arguments.get("path", "")), True)
        glob = str(arguments.get("glob", "*") or "*")
        use_regex = bool(arguments.get("regex", False))
        limit = min(100, max(1, int(arguments.get("max_results", 30))))
        expression = re.compile(query) if use_regex else None
        results: list[dict[str, Any]] = []
        candidates = [base] if base.is_file() else base.rglob("*")
        for path in candidates:
            try:
                path.resolve().relative_to(workspace.root)
            except ValueError:
                continue
            if any(part in self._ignored_directories for part in path.relative_to(workspace.root).parts):
                continue
            if not path.is_file() or not fnmatch.fnmatch(path.name, glob) or path.stat().st_size > 2_000_000:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for line_number, line in enumerate(lines, 1):
                matched = bool(expression.search(line)) if expression else query.lower() in line.lower()
                if matched:
                    results.append({"path": workspace.relative(path), "line": line_number, "text": line[:260]})
                    if len(results) >= limit:
                        return self._result(True, matches=results, truncated=True)
        return self._result(True, matches=results, truncated=False)

    async def _write_file(self, arguments: dict[str, Any]) -> str:
        workspace = self._require_workspace()
        relative = str(arguments.get("path", ""))
        content = str(arguments.get("content", ""))
        path = workspace.resolve(relative)
        before = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        if not self._settings.agent_allow_edits:
            permitted = await self._approvals.request("write_file", f"Записать файл {relative}", {"path": relative, "size": len(content)})
            if not permitted:
                return self._result(False, error="Пользователь отклонил запись файла.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        await self._emit_edit(relative, before, content)
        return self._result(True, path=relative, bytes=len(content.encode("utf-8")))

    async def _replace_in_file(self, arguments: dict[str, Any]) -> str:
        workspace = self._require_workspace()
        relative = str(arguments.get("path", ""))
        path = workspace.resolve(relative, True)
        old = str(arguments.get("old_text", ""))
        new = str(arguments.get("new_text", ""))
        if not old:
            raise RuntimeError("old_text не может быть пустым.")
        text = path.read_text(encoding="utf-8", errors="strict")
        count = text.count(old)
        if count == 0:
            raise RuntimeError("Искомый фрагмент в файле не найден.")
        replace_all = bool(arguments.get("replace_all", False))
        if not replace_all and count != 1:
            raise RuntimeError("Фрагмент встречается несколько раз; уточните replacement или включите replace_all.")
        if not self._settings.agent_allow_edits:
            permitted = await self._approvals.request("replace_in_file", f"Изменить файл {relative}", {"path": relative, "replacements": count if replace_all else 1})
            if not permitted:
                return self._result(False, error="Пользователь отклонил изменение файла.")
        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        path.write_text(updated, encoding="utf-8", newline="\n")
        await self._emit_edit(relative, text, updated)
        return self._result(True, path=relative, replacements=count if replace_all else 1)

    async def _run_command(self, arguments: dict[str, Any]) -> str:
        workspace = self._require_workspace()
        argv = arguments.get("argv", [])
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item.strip() for item in argv):
            raise RuntimeError("argv должен быть непустым массивом аргументов.")
        if any(any(char in item for char in "|;&><`\n\r") for item in argv):
            raise RuntimeError("Shell-операторы запрещены. Для командной оболочки используйте run_cmd или run_powershell с подтверждением.")
        cwd_relative = str(arguments.get("cwd", ""))
        cwd = workspace.resolve(cwd_relative, True)
        if not cwd.is_dir():
            raise RuntimeError("cwd должен быть папкой внутри workspace.")
        timeout = min(180, max(1, int(arguments.get("timeout_seconds", self._settings.agent_command_timeout))))
        if not self._settings.agent_allow_commands:
            permitted = await self._approvals.request("run_command", "Запустить команду проекта", {"argv": argv, "cwd": cwd_relative or ".", "timeout_seconds": timeout})
            if not permitted:
                return self._result(False, error="Пользователь отклонил запуск команды.")
        return await self._capture_process(argv, cwd, timeout)

    def _result(self, ok: bool, **payload: Any) -> str:
        return json.dumps({"ok": ok, **payload}, ensure_ascii=False)
