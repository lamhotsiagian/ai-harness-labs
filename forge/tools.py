"""Tool registry: schemas, validation, dispatch, and LLM-friendly results.

Design rules implemented here (Chapter 8):
  * every tool declares its side-effect class (read, write, external) so the
    policy layer can gate it without knowing what it does;
  * arguments are validated against the JSON schema before dispatch, and the
    validation error tells the model exactly which field to fix;
  * results are truncated with an explicit marker that says how to get more;
  * idempotent write tools accept an idempotency key and replay the stored
    result instead of executing twice.
"""
from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

JSON = dict[str, Any]


class ToolError(Exception):
    """An error meant for the model: message plus an actionable hint."""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: JSON
    handler: Callable[..., Any]
    side_effect: str = "read"          # read | write | external
    idempotent: bool = True
    requires_approval: bool = False
    max_result_chars: int = 6000

    def schema(self) -> JSON:
        """Provider-neutral function schema sent to the model."""
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


@dataclass
class ToolResult:
    ok: bool
    content: str
    truncated: bool = False
    meta: dict = field(default_factory=dict)


def validate_args(schema: JSON, args: JSON) -> list[str]:
    """Validate the subset of JSON Schema that tool definitions actually use."""
    problems: list[str] = []
    props = schema.get("properties", {})
    for req in schema.get("required", []):
        if req not in args:
            problems.append(f"missing required field '{req}'")
    if schema.get("additionalProperties") is False:
        for key in args:
            if key not in props:
                problems.append(f"unknown field '{key}' (allowed: {sorted(props)})")
    type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
                "array": list, "object": dict}
    for key, value in args.items():
        spec = props.get(key)
        if not spec:
            continue
        expected = type_map.get(spec.get("type", ""))
        if expected and not isinstance(value, expected):
            problems.append(f"field '{key}' must be {spec['type']}, got {type(value).__name__}")
        if "enum" in spec and value not in spec["enum"]:
            problems.append(f"field '{key}' must be one of {spec['enum']}")
        if isinstance(value, (int, float)) and "minimum" in spec and value < spec["minimum"]:
            problems.append(f"field '{key}' must be >= {spec['minimum']}")
        if isinstance(value, str) and "maxLength" in spec and len(value) > spec["maxLength"]:
            problems.append(f"field '{key}' exceeds maxLength {spec['maxLength']}")
    return problems


def truncate(text: str, limit: int, hint: str) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    omitted = len(text) - limit
    return text[:limit] + f"\n...[truncated {omitted} chars; {hint}]", True


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._idem_cache: dict[str, ToolResult] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool {spec.name}")
        self._tools[spec.name] = spec

    def remove(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[JSON]:
        # Sorted, stable order keeps the tool block cache-friendly (Chapter 4).
        return [self._tools[n].schema() for n in sorted(self._tools)]

    def call(self, name: str, args: JSON, idempotency_key: str | None = None) -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(False, f"ERROR: unknown tool '{name}'. hint: available tools are {self.names()}")
        problems = validate_args(spec.parameters, args)
        if problems:
            return ToolResult(False, "ERROR: invalid arguments: " + "; ".join(problems)
                              + f". hint: schema is {json.dumps(spec.parameters)}")
        if idempotency_key and idempotency_key in self._idem_cache:
            cached = self._idem_cache[idempotency_key]
            return ToolResult(cached.ok, cached.content, cached.truncated, {**cached.meta, "replayed": True})
        try:
            raw = spec.handler(**args)
            text = raw if isinstance(raw, str) else json.dumps(raw, indent=1, default=str)
            text, cut = truncate(text, spec.max_result_chars, "narrow the request or page with offset")
            result = ToolResult(True, text, cut)
        except ToolError as exc:
            msg = f"ERROR: {exc}"
            if exc.hint:
                msg += f" hint: {exc.hint}"
            result = ToolResult(False, msg)
        except Exception as exc:  # never let a tool crash the loop
            result = ToolResult(False, f"ERROR: {type(exc).__name__}: {exc}",
                                meta={"traceback": traceback.format_exc(limit=3)})
        if idempotency_key and spec.side_effect != "read":
            self._idem_cache[idempotency_key] = result
        return result
