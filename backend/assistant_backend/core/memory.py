from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class MemoryItem:
    id: str
    category: str
    importance: int
    updated_at: str
    text: str


class MemoryStore:
    _pattern = re.compile(
        r"## (?P<id>[a-z0-9_-]+)\ncategory: (?P<category>[^\n]+)\nimportance: (?P<importance>\d+)\nupdated: (?P<updated>[^\n]+)\n\n(?P<text>.*?)(?=\n\n## |\Z)",
        re.S,
    )

    def __init__(self, data_dir: Path, max_chars: int = 12000) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "memory.md"
        self.max_chars = max_chars
        if not self.path.exists():
            self._save([])

    def configure(self, max_chars: int) -> None:
        self.max_chars = max(2000, min(50000, int(max_chars)))
        self._save(self._trim(self.list()))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _category(value: str) -> str:
        return value if value in {"preference", "fact", "instruction", "context"} else "fact"

    def list(self) -> list[MemoryItem]:
        content = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        result = []
        for match in self._pattern.finditer(content):
            result.append(
                MemoryItem(
                    match.group("id"),
                    self._category(match.group("category").strip()),
                    max(1, min(5, int(match.group("importance")))),
                    match.group("updated").strip(),
                    match.group("text").strip(),
                )
            )
        return result

    def public(self) -> dict[str, Any]:
        items = self.list()
        return {
            "path": str(self.path),
            "max_chars": self.max_chars,
            "size_chars": len(self.path.read_text(encoding="utf-8")),
            "items": [item.__dict__ for item in sorted(items, key=lambda value: (-value.importance, value.updated_at), reverse=False)],
        }

    def add(self, text: str, category: str = "fact", importance: int = 3) -> MemoryItem:
        value = text.strip()
        if not value:
            raise RuntimeError("Память не может быть пустой.")
        items = self.list()
        lowered = value.casefold()
        for item in items:
            if item.text.casefold() == lowered:
                return self.update(item.id, value, category, importance)
        item = MemoryItem(uuid.uuid4().hex[:10], self._category(category), max(1, min(5, int(importance))), self._now(), value[:3000])
        items.append(item)
        items = self._trim(items)
        if item.id not in {value.id for value in items}:
            raise RuntimeError("Запись не помещается в лимит памяти.")
        self._save(items)
        return item

    def update(self, item_id: str, text: str, category: str | None = None, importance: int | None = None) -> MemoryItem:
        items = self.list()
        found = None
        for index, item in enumerate(items):
            if item.id == item_id:
                found = MemoryItem(
                    item.id,
                    self._category(category or item.category),
                    max(1, min(5, int(importance if importance is not None else item.importance))),
                    self._now(),
                    text.strip()[:3000],
                )
                if not found.text:
                    raise RuntimeError("Память не может быть пустой.")
                items[index] = found
                break
        if found is None:
            raise RuntimeError("Запись памяти не найдена.")
        items = self._trim(items)
        if found.id not in {value.id for value in items}:
            raise RuntimeError("Обновлённая запись не помещается в лимит памяти.")
        self._save(items)
        return found

    def delete(self, item_id: str) -> None:
        items = self.list()
        result = [item for item in items if item.id != item_id]
        if len(items) == len(result):
            raise RuntimeError("Запись памяти не найдена.")
        self._save(result)

    def search(self, query: str, limit: int = 10) -> list[MemoryItem]:
        tokens = {part.casefold() for part in re.findall(r"[а-яА-ЯёЁa-zA-Z0-9]{3,}", query)}
        scored = []
        for item in self.list():
            lowered = item.text.casefold()
            score = item.importance * 2 + sum(4 for token in tokens if token in lowered)
            if not tokens or score > item.importance * 2:
                scored.append((score, item.updated_at, item))
        scored.sort(key=lambda value: (value[0], value[1]), reverse=True)
        return [value[2] for value in scored[:limit]]

    def context(self, query: str, limit_chars: int = 2500) -> str:
        items = self.search(query, 12)
        if not items:
            items = sorted(self.list(), key=lambda item: (item.importance, item.updated_at), reverse=True)[:4]
        lines = []
        size = 0
        for item in items:
            line = f"- [{item.category}] {item.text}"
            if size + len(line) + 1 > limit_chars:
                break
            lines.append(line)
            size += len(line) + 1
        return "\n".join(lines)

    def _render(self, items: list[MemoryItem]) -> str:
        header = "# Память ассистента\n\nФайл хранит только устойчивые факты, предпочтения и важные инструкции пользователя.\n"
        body = []
        for item in sorted(items, key=lambda value: (value.importance, value.updated_at), reverse=True):
            body.append(f"## {item.id}\ncategory: {item.category}\nimportance: {item.importance}\nupdated: {item.updated_at}\n\n{item.text}")
        return header + ("\n\n" + "\n\n".join(body) + "\n" if body else "\n")

    def _trim(self, items: list[MemoryItem]) -> list[MemoryItem]:
        current = list(items)
        while len(self._render(current)) > self.max_chars and current:
            removable = sorted(current, key=lambda item: (item.importance, item.updated_at))[0]
            current = [item for item in current if item.id != removable.id]
        return current

    def _save(self, items: list[MemoryItem]) -> None:
        self.path.write_text(self._render(items), encoding="utf-8", newline="\n")
