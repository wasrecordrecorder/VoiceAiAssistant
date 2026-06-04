import json
import re
from pathlib import Path
from typing import Any


class StylePreferenceMatrix:
    _patterns = {
        "ultra_concise": (r"без воды|кратк|сжат|короче|по делу", 3),
        "zero_filler": (r"не надо.*вод|убери.*вод|лишн(ее|ие).*объяс|без лишн", 3),
        "no_code_comments": (r"без комментар|убери комментар|не пиши комментар", 4),
        "clean_code": (r"чист(ый|ого) код|clean code", 2),
        "spoken_numbers": (r"полными букв|словами.*чис|не сокращ", 2),
        "compact_ui": (r"не сжат|больше места|удобн.*интерфейс", 1),
    }

    _rules = {
        "ultra_concise": "Отвечай предельно сжато и только по существу.",
        "zero_filler": "Не добавляй вводные фразы, повтор запроса и лишние объяснения.",
        "no_code_comments": "В создаваемом и редактируемом коде не добавляй комментарии без прямой просьбы.",
        "clean_code": "Предпочитай чистые небольшие изменения без лишних обёрток.",
        "spoken_numbers": "Для голосовой озвучки формулируй числа и размеры естественными словами.",
        "compact_ui": "При работе над интерфейсом предпочитай свободную и читаемую компоновку.",
    }

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "style_matrix.json"
        self._values = self._load()

    def _load(self) -> dict[str, int]:
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
            return {str(key): min(30, max(0, int(score))) for key, score in value.items() if key in self._rules}
        except Exception:
            return {}

    def observe(self, text: str) -> list[dict[str, Any]]:
        source = text.lower()
        updated = []
        for key, (pattern, delta) in self._patterns.items():
            if re.search(pattern, source):
                self._values[key] = min(30, self._values.get(key, 0) + delta)
                updated.append({"key": key, "weight": self._values[key]})
        if updated:
            self._path.write_text(json.dumps(self._values, ensure_ascii=False, indent=2), encoding="utf-8")
        return updated

    def prompt(self) -> str:
        active = [
            (weight, key, self._rules[key])
            for key, weight in self._values.items()
            if weight >= 2 and key in self._rules
        ]
        active.sort(reverse=True)
        if not active:
            return ""
        rules = "\n".join(f"- {rule}" for _, _, rule in active[:6])
        return f"Устойчивые предпочтения стиля пользователя, выведенные из его исправлений:\n{rules}"

    def public(self) -> dict[str, int]:
        return dict(self._values)
