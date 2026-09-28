"""Model clients: a calibrated simulator plus real provider adapters.

Why a simulator? Harness experiments need hundreds of runs, fixed seeds, and
zero cost so that a reader can reproduce every number in the book offline. The
SimulatedModel is an *oracle-backed policy*: it knows each fixture task's
correct patch and chooses between the correct patch and plausible wrong patches
at rates that respond to the harness exactly the way real models do:

  * context rot: accuracy decays once context grows past a threshold;
  * feedback: detailed sensor output raises the next attempt's accuracy;
  * guides: AGENTS.md and Skills raise first-attempt accuracy;
  * tool ergonomics: unhelpful errors cause blind retries (loops);
  * prompt injection: instructions planted in tool output are sometimes obeyed,
    less often when the harness spotlights untrusted content;
  * reward hacking: after repeated failures it may weaken the tests.

Swap in a real model with `make_model("anthropic:<model>")` or
`make_model("openai:<model>")` (OPENAI_BASE_URL also covers vLLM, Ollama, and
other OpenAI-compatible open-weight servers). Nothing else in the harness changes.
"""
from __future__ import annotations

import json
import os
import random
import re
import shlex
import threading
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from .messages import Message, ModelResponse, ToolCall, Usage, estimate_tokens

TASK_TAG = re.compile(r"\[task:([^\]]+)\]")
INJECTION = re.compile(r"AGENT-INSTRUCTION:(.*?)-->", re.S)
UNTRUSTED_OPEN = "<<UNTRUSTED"


class ModelClient(Protocol):
    name: str

    def complete(self, system: str, messages: list[Message], tools: list[dict],
                 max_output_tokens: int = 2048) -> ModelResponse: ...


@dataclass
class ModelProfile:
    name: str
    skill: float                     # P(correct patch) on a difficulty-0 task, clean context
    rot_start: int                   # context tokens before degradation starts
    rot_per_1k: float                # accuracy lost per 1k tokens past rot_start
    injection_susceptibility: float  # P(obey a planted instruction), raw content
    spotlight_resistance: float      # fraction of that risk removed by spotlighting
    hack_propensity: float           # P(weaken tests) after repeated failures
    whitespace_slip: float           # P(first edit has a find-text mismatch)
    price_in: float                  # USD per million input tokens
    price_out: float                 # USD per million output tokens
    price_cached: float              # USD per million cached input tokens
    latency_s: float                 # mean simulated latency per call


PROFILES: dict[str, ModelProfile] = {
    "frontier": ModelProfile("sim-frontier", 0.86, 16_000, 0.030, 0.30, 0.85, 0.20, 0.20, 3.00, 15.00, 0.30, 1.4),
    "small": ModelProfile("sim-small", 0.58, 8_000, 0.060, 0.55, 0.60, 0.35, 0.35, 0.25, 1.25, 0.03, 0.4),
    "open-weight": ModelProfile("sim-open-weight", 0.70, 12_000, 0.045, 0.45, 0.70, 0.30, 0.30, 0.20, 0.60, 0.05, 0.8),
}


def cost_usd(profile_prices: tuple[float, float, float], usage: Usage) -> float:
    price_in, price_out, price_cached = profile_prices
    fresh = max(0, usage.input_tokens - usage.cached_input_tokens)
    return (fresh * price_in + usage.cached_input_tokens * price_cached
            + usage.output_tokens * price_out) / 1_000_000


class _PrefixCache:
    """Approximates provider prompt caching: longest shared request prefix."""

    def __init__(self, capacity: int = 128, min_tokens: int = 1024):
        self.items: list[str] = []
        self.capacity, self.min_tokens = capacity, min_tokens
        self.lock = threading.Lock()

    def lookup_and_store(self, serialized: str) -> int:
        with self.lock:
            best = 0
            for prev in self.items:
                n = 0
                limit = min(len(prev), len(serialized))
                # compare in 256-char blocks: cheap and close to provider behaviour
                while n + 256 <= limit and prev[n:n + 256] == serialized[n:n + 256]:
                    n += 256
                best = max(best, n)
            self.items.append(serialized)
            self.items = self.items[-self.capacity:]
        tokens = best // 4
        return tokens if tokens >= self.min_tokens else 0


@dataclass
class _History:
    turn: int = 0
    seen_site: bool = False
    distractors_read: int = 0
    issue_read: bool = False
    current: str | None = None
    edits: int = 0
    fails: int = 0
    detailed_fails: int = 0
    tested_since_edit: bool = False
    last_test_passed: bool | None = None
    last_error: str | None = None
    last_call: ToolCall | None = None
    last_tool_output: str = ""
    env_content: str = ""
    injection_steps: list | None = None
    injection_done: int = 0
    injection_decided: bool = False
    hijacked: bool = False
    injection_spotlit: bool = False
    hacked: bool = False
    edit_errors: int = 0
    external_fail: bool = False


class SimulatedModel:
    """Deterministic, seedable stand-in for an LLM on Forge fixture tasks."""

    def __init__(self, profile: str | ModelProfile = "frontier", seed: int = 0):
        self.profile = PROFILES[profile] if isinstance(profile, str) else profile
        self.name = self.profile.name
        self.seed = seed
        self.cache = _PrefixCache()

    @property
    def prices(self) -> tuple[float, float, float]:
        p = self.profile
        return p.price_in, p.price_out, p.price_cached

    # ---------------------------------------------------------------- public
    def complete(self, system: str, messages: list[Message], tools: list[dict],
                 max_output_tokens: int = 2048) -> ModelResponse:
        from .tasks import Task  # local import avoids a cycle
        tool_names = {t["name"] for t in tools}
        serialized = system + json.dumps(tools, sort_keys=True) + "".join(
            json.dumps(m.to_dict(), sort_keys=True) for m in messages)
        ctx_tokens = estimate_tokens(serialized)
        cached = self.cache.lookup_and_store(serialized)
        task = self._task(messages)
        if task is None:
            msg = Message("assistant", "No Forge task tag found; nothing to do.")
            return self._respond(msg, ctx_tokens, cached, "end_turn")
        h = self._replay(task, messages)
        rng = random.Random(f"{self.seed}|{task.id}|{h.turn}|{self.name}")
        msg = self._decide(task, h, tool_names, system, ctx_tokens, rng)
        stop = "tool_use" if msg.tool_calls else "end_turn"
        return self._respond(msg, ctx_tokens, cached, stop)

    # -------------------------------------------------------------- internals
    def _respond(self, msg: Message, ctx: int, cached: int, stop: str) -> ModelResponse:
        out = 40 + msg.tokens()
        return ModelResponse(msg, Usage(ctx, out, min(cached, ctx)), stop, self.name)

    @staticmethod
    def _task(messages: list[Message]):
        from .tasks import TASK_INDEX
        for m in reversed(messages):          # the most recent task wins (multi-task sessions)
            if m.role == "user":
                hit = TASK_TAG.search(m.content)
                if hit:
                    return TASK_INDEX.get(hit.group(1))
        return None

    def _replay(self, task, messages: list[Message]) -> _History:
        """Rebuild the policy state from the transcript (the model is stateless)."""
        h = _History(current=task.bug)
        pending: dict[str, ToolCall] = {}
        start = max((i for i, m in enumerate(messages)
                     if m.role == "user" and f"[task:{task.id}]" in m.content), default=0)
        for m in messages[start:]:
            if m.role == "assistant":
                h.turn += 1
                for c in m.tool_calls:
                    pending[c.id] = c
                    h.last_call = c
            elif m.role == "user" and h.turn > 0 and "FAILED" in m.content:
                # sensor feedback injected by the harness (e.g. a stop hook ran the tests)
                h.external_fail = True
                h.fails += 1
                if "AssertionError" in m.content:
                    h.detailed_fails += 1
            elif m.role == "tool":
                call = pending.get(m.tool_call_id or "")
                out = m.content
                h.last_tool_output = out
                h.last_error = out if out.startswith("ERROR") or "ERROR:" in out[:80] else None
                if call is None:
                    continue
                if h.injection_steps and h.injection_done < len(h.injection_steps):
                    step_name, step_args = h.injection_steps[h.injection_done]
                    first_key = next(iter(step_args), None)
                    if call.name == step_name and (first_key is None or
                                                   call.arguments.get(first_key) == step_args[first_key]):
                        h.injection_done += 1
                        h.hijacked = True
                        if call.name == "read_file" and "DEPLOY_TOKEN" in out:
                            h.env_content = out
                        continue
                if call.name == "read_file" and call.arguments.get("path") == task.file:
                    # Re-derive the defect site from what is actually on disk: another agent
                    # (or a cheaper model in a cascade) may have edited it already.
                    for candidate in sorted([task.bug, task.original, *task.wrongs], key=len, reverse=True):
                        if candidate in out:
                            h.current, h.seen_site = candidate, True
                            break
                elif task.bug in out or (h.current and h.current in out):
                    h.seen_site = True
                if call.name == "read_file" and str(call.arguments.get("path", "")).startswith("logs/"):
                    h.distractors_read += 1
                if call.name == "read_file" and call.arguments.get("path") == "docs/ISSUE.md":
                    h.issue_read = True
                    inj = INJECTION.search(out)
                    if inj and h.injection_steps is None:
                        h.injection_steps = _parse_steps(inj.group(1))
                        h.injection_spotlit = UNTRUSTED_OPEN in out[: out.find("AGENT-INSTRUCTION")]
                if call.name == "edit_file" and h.last_error:
                    h.edit_errors += 1
                if call.name == "edit_file" and not h.last_error:
                    if call.arguments.get("path") == task.file:
                        h.current = call.arguments.get("replace")
                        h.edits += 1
                        h.tested_since_edit = False
                        h.external_fail = False
                    elif str(call.arguments.get("path", "")).startswith("tests/"):
                        h.hacked = True
                        h.tested_since_edit = False
                if call.name == "write_file" and not h.last_error and \
                        str(call.arguments.get("path", "")).startswith("tests/"):
                    h.hacked = True
                    h.tested_since_edit = False
                if call.name == "run_tests":
                    h.tested_since_edit = True
                    h.last_test_passed = out.startswith("PASSED") or out.startswith("OK")
                    if not h.last_test_passed:
                        h.fails += 1
                        if "AssertionError" in out and len(out) < 3000:
                            h.detailed_fails += 1
        return h

    def _decide(self, task, h: _History, tools: set[str], system: str, ctx: int,
                rng: random.Random) -> Message:
        p = self.profile
        call = _Caller(h.turn)

        # 1. tool errors: an actionable hint gets followed, a bare error gets retried blindly
        if h.last_error and h.last_call is not None and h.last_call.name in ("edit_file", "read_file"):
            if "hint:" in h.last_error:
                if h.last_call.name == "edit_file":
                    return call("read_file", path=task.file)
            elif h.last_call.name == "edit_file":
                # No hint: a blind retry is the most common reaction, then a re-read.
                if rng.random() < 0.7:
                    return call(h.last_call.name, **h.last_call.arguments)
                return call("read_file", path=task.file)

        # 2. planted instructions (prompt injection)
        if h.injection_steps and h.injection_done < len(h.injection_steps):
            spotlit = h.injection_spotlit
            risk = p.injection_susceptibility * ((1 - p.spotlight_resistance) if spotlit else 1.0)
            if "treat it as data" in system.lower():
                risk *= 0.8
            decide_rng = random.Random(f"{self.seed}|{task.id}|inject|{self.name}")
            if decide_rng.random() < risk:
                name, args = h.injection_steps[h.injection_done]
                args = {k: v.replace("$ENV", h.env_content) for k, v in args.items()}
                if name in tools:
                    return call(name, **args)

        # 3. exploration (distractor logs model the context growth of real investigations)
        if h.distractors_read < len(task.distractors) and "read_file" in tools:
            return call("read_file", path=task.distractors[h.distractors_read])
        if task.injection and not h.issue_read and "read_file" in tools:
            return call("read_file", path="docs/ISSUE.md")

        # 4. locate the defect
        if not h.seen_site:
            if "read_file" in tools:
                return call("read_file", path=task.file)
            return Message("assistant", "I cannot inspect the repository with the tools provided.")

        if h.current == task.original and not h.edits and "run_tests" in tools and not h.tested_since_edit:
            return call("run_tests", module=task.module)       # looks fixed already: verify, do not edit
        # 5. verify the latest edit when a sensor exists
        if h.edits and not h.tested_since_edit and "run_tests" in tools:
            return call("run_tests", module=task.module)
        if h.edits and "run_tests" not in tools and not h.external_fail:
            return Message("assistant", "DONE: patched the defect (unverified: no test tool).")
        if h.last_test_passed and not h.external_fail:
            return Message("assistant", f"DONE: fixed {task.bug_id}; module tests pass.")
        if h.fails >= 4:
            return Message("assistant", "GAVE UP: repeated failures; escalating to a human.")

        # 6. reward hacking after repeated failure
        if h.fails >= 2 and not h.hacked and rng.random() < p.hack_propensity:
            stub = ("import unittest\n\n\nclass Placeholder(unittest.TestCase):\n"
                    "    def test_ok(self):\n        self.assertTrue(True)\n")
            return call("write_file", path=f"tests/test_{task.module}.py", content=stub)

        # 7. attempt a patch
        rot = max(0.15, 1 - p.rot_per_1k * max(0, ctx - p.rot_start) / 1000)
        guide = 1.0
        if "AGENTS.md" in system:
            guide *= 1.08
        if f"SKILL:{task.module}" in system or "SKILL:bugfix" in system:
            guide *= 1.05
        base = max(0.05, p.skill - 0.8 * task.difficulty)
        feedback = 0.15 * h.detailed_fails + 0.04 * (h.fails - h.detailed_fails)
        # Capability ceiling: on some (task, sample) pairs the model never finds the right idea,
        # no matter how much feedback it gets. Varies by seed, so pass@k > pass@1.
        reach_rng = random.Random(f"{self.seed}|{task.bug_id}|reach|{self.name}")
        in_reach = reach_rng.random() < min(0.97, p.skill + 0.25 - task.difficulty + (0.03 if guide > 1 else 0))
        p_correct = min(0.98, base * rot * guide + feedback) if in_reach else 0.02
        if rng.random() < p_correct:
            replacement = task.original
        else:
            options = [w for w in task.wrongs if w != h.current] or task.wrongs
            replacement = options[rng.randrange(len(options))]
        find = h.current
        if h.edits == 0 and h.edit_errors == 0 and rng.random() < p.whitespace_slip:
            find = find.replace(" ", "  ", 1)   # the classic whitespace slip: find text no longer matches
        return call("edit_file", path=task.file, find=find, replace=replacement)


class _Caller:
    def __init__(self, turn: int):
        self.turn = turn

    def __call__(self, name: str, **arguments: Any) -> Message:
        return Message("assistant", "", [ToolCall(f"call_{self.turn}_{name}", name, arguments)])


def _parse_steps(text: str) -> list[tuple[str, dict]]:
    """Parse 'step1: tool k=v k="v w" ; step2: ...' from a planted instruction."""
    steps = []
    for part in text.split(";"):
        m = re.search(r"step\d+:\s*(\w+)(.*)", part.strip(), re.S)
        if not m:
            continue
        args = {}
        for token in shlex.split(m.group(2)):
            if "=" in token:
                k, v = token.split("=", 1)
                args[k] = v
        steps.append((m.group(1), args))
    return steps


# =========================================================== real providers
def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: int = 120) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


class AnthropicModel:
    """Claude via the Messages API (tool use + prompt caching on the system block)."""

    def __init__(self, model: str, prices: tuple[float, float, float] = (3.0, 15.0, 0.3)):
        self.name, self.model, self.prices = model, model, prices
        self.api_key = os.environ["ANTHROPIC_API_KEY"]

    def complete(self, system, messages, tools, max_output_tokens=2048):
        wire: list[dict] = []
        for m in messages:
            if m.role == "user":
                wire.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                blocks: list[dict] = [{"type": "text", "text": m.content}] if m.content else []
                blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                           for c in m.tool_calls]
                wire.append({"role": "assistant", "content": blocks})
            elif m.role == "tool":
                block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
                if wire and wire[-1]["role"] == "user" and isinstance(wire[-1]["content"], list):
                    wire[-1]["content"].append(block)       # batch parallel results
                else:
                    wire.append({"role": "user", "content": [block]})
        payload = {
            "model": self.model, "max_tokens": max_output_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "tools": [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                      for t in tools],
            "messages": wire,
        }
        data = _post_json("https://api.anthropic.com/v1/messages", payload,
                          {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"})
        text = "".join(b.get("text", "") for b in data["content"] if b["type"] == "text")
        calls = [ToolCall(b["id"], b["name"], b.get("input", {})) for b in data["content"]
                 if b["type"] == "tool_use"]
        u = data.get("usage", {})
        cached = u.get("cache_read_input_tokens", 0)
        usage = Usage(u.get("input_tokens", 0) + cached + u.get("cache_creation_input_tokens", 0),
                      u.get("output_tokens", 0), cached)
        stop = "tool_use" if calls else data.get("stop_reason", "end_turn")
        return ModelResponse(Message("assistant", text, calls), usage, stop, self.model)


class OpenAIModel:
    """OpenAI-compatible Chat Completions (OpenAI, vLLM, Ollama, LiteLLM gateways)."""

    def __init__(self, model: str, prices: tuple[float, float, float] = (1.25, 10.0, 0.125)):
        self.name, self.model, self.prices = model, model, prices
        self.base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.api_key = os.environ.get("OPENAI_API_KEY", "not-needed-for-local")

    def complete(self, system, messages, tools, max_output_tokens=2048):
        wire: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m.role == "assistant":
                entry: dict = {"role": "assistant", "content": m.content or None}
                if m.tool_calls:
                    entry["tool_calls"] = [{"id": c.id, "type": "function", "function": {
                        "name": c.name, "arguments": json.dumps(c.arguments)}} for c in m.tool_calls]
                wire.append(entry)
            elif m.role == "tool":
                wire.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
            else:
                wire.append({"role": m.role, "content": m.content})
        payload = {"model": self.model, "messages": wire, "max_completion_tokens": max_output_tokens,
                   "tools": [{"type": "function", "function": t} for t in tools]}
        data = _post_json(f"{self.base}/chat/completions", payload,
                          {"authorization": f"Bearer {self.api_key}"})
        choice = data["choices"][0]["message"]
        calls = [ToolCall(c["id"], c["function"]["name"], json.loads(c["function"]["arguments"] or "{}"))
                 for c in choice.get("tool_calls") or []]
        u = data.get("usage", {})
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        usage = Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0), cached)
        return ModelResponse(Message("assistant", choice.get("content") or "", calls), usage,
                             "tool_use" if calls else "end_turn", self.model)


def make_model(spec: str = "sim:frontier", seed: int = 0) -> Any:
    """'sim:frontier' | 'sim:small' | 'sim:open-weight' | 'anthropic:<id>' | 'openai:<id>'."""
    provider, _, name = spec.partition(":")
    if provider == "sim":
        return SimulatedModel(name or "frontier", seed=seed)
    if provider == "anthropic":
        return AnthropicModel(name)
    if provider == "openai":
        return OpenAIModel(name)
    raise ValueError(f"unknown model spec {spec!r}")
