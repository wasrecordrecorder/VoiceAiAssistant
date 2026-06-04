from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TodoStore:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "organizer.db"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS todo_items (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL,
                priority TEXT NOT NULL,
                due_at TEXT NOT NULL,
                tags TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _normalize_kind(value: str) -> str:
        return value if value in {"task", "note"} else "task"

    @staticmethod
    def _normalize_status(value: str) -> str:
        return value if value in {"todo", "later", "done"} else "todo"

    @staticmethod
    def _normalize_priority(value: str) -> str:
        return value if value in {"normal", "important"} else "normal"

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["tags"] = json.loads(value.get("tags") or "[]")
        return value

    def list(self, status: str = "", kind: str = "", important_only: bool = False, query: str = "") -> list[dict[str, Any]]:
        clauses = []
        values: list[Any] = []
        if status in {"todo", "later", "done"}:
            clauses.append("status = ?")
            values.append(status)
        if kind in {"task", "note"}:
            clauses.append("kind = ?")
            values.append(kind)
        if important_only:
            clauses.append("priority = 'important'")
        if query.strip():
            clauses.append("(title LIKE ? OR body LIKE ? OR tags LIKE ?)")
            token = f"%{query.strip()}%"
            values.extend([token, token, token])
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"SELECT * FROM todo_items{where} ORDER BY CASE status WHEN 'todo' THEN 0 WHEN 'later' THEN 1 ELSE 2 END, CASE priority WHEN 'important' THEN 0 ELSE 1 END, updated_at DESC",
            values,
        ).fetchall()
        return [self._row(row) for row in rows]

    def create(self, title: str, body: str = "", kind: str = "task", status: str = "todo", priority: str = "normal", due_at: str = "", tags: list[str] | None = None) -> dict[str, Any]:
        name = title.strip()
        if not name:
            raise RuntimeError("У задачи или заметки должен быть заголовок.")
        item_id = uuid.uuid4().hex[:12]
        now = self._now()
        value = (
            item_id,
            self._normalize_kind(kind),
            name[:180],
            body.strip()[:8000],
            self._normalize_status(status),
            self._normalize_priority(priority),
            str(due_at or "").strip()[:64],
            json.dumps([str(tag).strip() for tag in (tags or []) if str(tag).strip()][:12], ensure_ascii=False),
            now,
            now,
        )
        self._connection.execute("INSERT INTO todo_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", value)
        self._connection.commit()
        return self.get(item_id)

    def get(self, item_id: str) -> dict[str, Any]:
        row = self._connection.execute("SELECT * FROM todo_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise RuntimeError("Задача или заметка не найдена.")
        return self._row(row)

    def update(self, item_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        current = self.get(item_id)
        allowed = {"title", "body", "kind", "status", "priority", "due_at", "tags"}
        merged = {**current, **{key: value for key, value in changes.items() if key in allowed}}
        title = str(merged["title"]).strip()
        if not title:
            raise RuntimeError("Заголовок не может быть пустым.")
        tags = merged["tags"] if isinstance(merged["tags"], list) else []
        self._connection.execute(
            "UPDATE todo_items SET kind = ?, title = ?, body = ?, status = ?, priority = ?, due_at = ?, tags = ?, updated_at = ? WHERE id = ?",
            (
                self._normalize_kind(str(merged["kind"])),
                title[:180],
                str(merged["body"]).strip()[:8000],
                self._normalize_status(str(merged["status"])),
                self._normalize_priority(str(merged["priority"])),
                str(merged["due_at"] or "").strip()[:64],
                json.dumps([str(tag).strip() for tag in tags if str(tag).strip()][:12], ensure_ascii=False),
                self._now(),
                item_id,
            ),
        )
        self._connection.commit()
        return self.get(item_id)

    def delete(self, item_id: str) -> None:
        if self._connection.execute("SELECT id FROM todo_items WHERE id = ?", (item_id,)).fetchone() is None:
            raise RuntimeError("Задача или заметка не найдена.")
        self._connection.execute("DELETE FROM todo_items WHERE id = ?", (item_id,))
        self._connection.commit()

    def summary(self) -> dict[str, int]:
        rows = self._connection.execute("SELECT status, COUNT(*) AS count FROM todo_items GROUP BY status").fetchall()
        values = {"todo": 0, "later": 0, "done": 0}
        for row in rows:
            values[row["status"]] = int(row["count"])
        values["important"] = int(self._connection.execute("SELECT COUNT(*) FROM todo_items WHERE priority = 'important' AND status != 'done'").fetchone()[0])
        return values
