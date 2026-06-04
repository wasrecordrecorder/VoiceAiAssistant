import difflib
import re
import time
from dataclasses import dataclass


@dataclass
class ActivationResult:
    accepted: bool
    text: str
    awakened: bool = False
    ignored: bool = False


class ActivationGate:
    _fillers = {"эй", "окей", "слушай", "ну", "алло"}
    _aliases = {
        "ассистент": {"ассистент", "асистент", "ассистенте", "асистенте", "ассистэнт", "ассист"},
        "вебви": {"вебви", "веб ви", "вебвью", "веб вью", "webvi"},
    }

    def __init__(self, mode: str, phrases: str, follow_up_seconds: int) -> None:
        self._manual_armed = False
        self._awake_until = 0.0
        self.configure(mode, phrases, follow_up_seconds)

    def configure(self, mode: str, phrases: str, follow_up_seconds: int) -> None:
        self.mode = mode
        self.phrases = [self._normalize(item) for item in phrases.split(",") if item.strip()] or ["ассистент"]
        self.follow_up_seconds = max(4, int(follow_up_seconds))

    @staticmethod
    def _normalize(value: str) -> str:
        lowered = value.casefold().replace("ё", "е")
        lowered = re.sub(r"[^a-zа-я0-9\s]+", " ", lowered)
        return re.sub(r"\s+", " ", lowered).strip()

    def _targets(self) -> set[str]:
        values = set(self.phrases)
        for phrase in self.phrases:
            values.update(self._aliases.get(phrase, set()))
        return values

    def arm(self) -> None:
        self._manual_armed = True
        self.extend()

    def extend(self) -> None:
        if self.mode == "wake":
            self._awake_until = time.monotonic() + self.follow_up_seconds

    def active(self) -> bool:
        return self.mode == "wake" and time.monotonic() < self._awake_until

    def passive(self) -> bool:
        if self.mode == "wake":
            return not self._manual_armed and not self.active()
        return self.mode == "ptt" and not self._manual_armed

    def remaining_seconds(self) -> int:
        return max(0, int(self._awake_until - time.monotonic()))

    def _match_wake(self, text: str) -> tuple[bool, str]:
        normalized = self._normalize(text)
        words = normalized.split()
        if not words:
            return False, ""
        for offset in range(0, min(3, len(words))):
            if offset and any(word not in self._fillers for word in words[:offset]):
                continue
            for target in self._targets():
                target_words = target.split()
                candidate = " ".join(words[offset:offset + len(target_words)])
                if not candidate:
                    continue
                score = difflib.SequenceMatcher(None, candidate, target).ratio()
                threshold = 0.74 if len(target.replace(" ", "")) >= 6 else 0.82
                if candidate == target or score >= threshold:
                    remainder = " ".join(words[offset + len(target_words):]).strip()
                    return True, remainder
        return False, ""

    def process(self, text: str) -> ActivationResult:
        value = text.strip()
        if not value:
            return ActivationResult(False, "")
        if self.mode == "continuous":
            return ActivationResult(True, value)
        if self._manual_armed:
            self._manual_armed = False
            self.extend()
            return ActivationResult(True, value)
        if self.mode in {"manual", "ptt"}:
            return ActivationResult(False, "", ignored=True)
        if self.active():
            self.extend()
            return ActivationResult(True, value)
        matched, remainder = self._match_wake(value)
        if matched:
            self.extend()
            if remainder:
                return ActivationResult(True, remainder, awakened=True)
            return ActivationResult(False, "", awakened=True)
        return ActivationResult(False, "", ignored=True)
