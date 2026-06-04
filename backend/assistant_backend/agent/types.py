from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AssistantTurn:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str = ""
