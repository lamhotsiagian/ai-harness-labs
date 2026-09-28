"""Provider-neutral message and tool-call types.

Every model adapter converts to and from these types, so the loop, the tracer,
the context manager, and the eval harness never see provider-specific JSON.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


def estimate_tokens(text: str) -> int:
    """Cheap, deterministic token estimate (about 4 characters per token)."""
    return max(1, len(text) // 4) if text else 0


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def signature(self) -> str:
        """Stable key used by loop detection and idempotency caches."""
        return f"{self.name}:{json.dumps(self.arguments, sort_keys=True)}"


@dataclass
class Message:
    role: str                      # system | user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None        # tool name for role == "tool"
    meta: dict[str, Any] = field(default_factory=dict)

    def tokens(self) -> int:
        calls = "".join(c.signature() for c in self.tool_calls)
        return estimate_tokens(self.content) + estimate_tokens(calls)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in self.tool_calls
            ]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cached_input_tokens + other.cached_input_tokens,
        )


@dataclass
class ModelResponse:
    message: Message
    usage: Usage
    stop_reason: str               # "tool_use" | "end_turn" | "max_tokens"
    model: str = ""
