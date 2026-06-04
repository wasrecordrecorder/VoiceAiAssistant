import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class ConversationStore:
    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self._path = data_dir / "conversations.sqlite3"
        with closing(self._connect()) as connection:
            connection.executescript(
                "CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);"
            )
            try:
                connection.execute("ALTER TABLE conversations ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            connection.commit()
        self.active_id = self._latest_id() or self.new()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _latest_id(self) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT id FROM conversations WHERE archived = 0 ORDER BY updated_at DESC LIMIT 1").fetchone()
        return str(row["id"]) if row else None

    def new(self) -> str:
        value = uuid.uuid4().hex
        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("INSERT INTO conversations(id, title, created_at, updated_at, archived) VALUES(?, ?, ?, ?, 0)", (value, "Новый диалог", now, now))
            connection.commit()
        self.active_id = value
        return value

    def select(self, value: str) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT id FROM conversations WHERE id = ?", (value,)).fetchone()
        if row is None:
            return False
        self.active_id = value
        return True

    def append(self, role: str, content: str) -> None:
        text = content.strip()
        if not text:
            return
        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute("INSERT INTO messages(conversation_id, role, content, created_at) VALUES(?, ?, ?, ?)", (self.active_id, role, text, now))
            if role == "user":
                title = text[:52]
                count = connection.execute("SELECT COUNT(*) AS c FROM messages WHERE conversation_id = ? AND role = 'user'", (self.active_id,)).fetchone()["c"]
                if count == 1:
                    connection.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, self.active_id))
            connection.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, self.active_id))
            connection.commit()

    def context(self, max_turns: int) -> list[dict[str, str]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
                (self.active_id, max_turns * 2),
            ).fetchall()
        return [{"role": str(row["role"]), "content": str(row["content"])} for row in reversed(rows)]

    def sessions(self) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT id, title, updated_at, archived FROM conversations ORDER BY archived ASC, updated_at DESC LIMIT 100").fetchall()
        return [{"id": str(row["id"]), "title": str(row["title"]), "updated_at": str(row["updated_at"]), "archived": bool(row["archived"]), "active": str(row["id"]) == self.active_id} for row in rows]

    def messages(self) -> list[dict[str, str]]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id", (self.active_id,)).fetchall()
        return [{"role": str(row["role"]), "content": str(row["content"]), "created_at": str(row["created_at"])} for row in rows]

    def rename(self, value: str, title: str) -> bool:
        clean = " ".join(title.split())[:72]
        if not clean:
            raise RuntimeError("Название чата не может быть пустым.")
        with closing(self._connect()) as connection:
            changed = connection.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?", (clean, self._now(), value)).rowcount
            connection.commit()
        return changed > 0

    def archive(self, value: str, archived: bool) -> bool:
        with closing(self._connect()) as connection:
            changed = connection.execute("UPDATE conversations SET archived = ?, updated_at = ? WHERE id = ?", (1 if archived else 0, self._now(), value)).rowcount
            connection.commit()
        if changed and value == self.active_id and archived:
            self.active_id = self._latest_id() or self.new()
        return changed > 0

    def delete(self, value: str) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT id FROM conversations WHERE id = ?", (value,)).fetchone()
            if row is None:
                return False
            connection.execute("DELETE FROM messages WHERE conversation_id = ?", (value,))
            connection.execute("DELETE FROM conversations WHERE id = ?", (value,))
            connection.commit()
        if value == self.active_id:
            self.active_id = self._latest_id() or self.new()
        return True

    def clear(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM messages WHERE conversation_id = ?", (self.active_id,))
            connection.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?", ("Новый диалог", self._now(), self.active_id))
            connection.commit()
