"""Harness Cards: document a harness the way model cards document a model (Chapter 3).

A benchmark number without its harness is unreproducible. The card records the
seven layers, budgets, permissions, known failure modes, and eval results, and
it is regenerated from code so it cannot drift from the running system.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from .config import HarnessConfig

LAYERS = ["instruction", "tools", "memory", "execution", "policy", "observability", "evaluation"]


@dataclass
class HarnessCard:
    name: str
    version: str
    fingerprint: str
    harness_type: str                       # agent | agentic | eval
    intended_use: str
    layers: dict[str, str]
    budgets: dict
    permissions: str
    known_failure_modes: list[str] = field(default_factory=list)
    eval_results: list[dict] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [f"# Harness Card: {self.name} {self.version}", "",
                 f"- **Fingerprint:** `{self.fingerprint}`", f"- **Type:** {self.harness_type}",
                 f"- **Intended use:** {self.intended_use}", f"- **Permissions:** {self.permissions}",
                 f"- **Budgets:** {json.dumps(self.budgets)}", "", "## Seven layers", "",
                 "| Layer | Implementation |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in self.layers.items()]
        lines += ["", "## Known failure modes"] + [f"- {x}" for x in self.known_failure_modes]
        lines += ["", "## Out of scope"] + [f"- {x}" for x in self.out_of_scope]
        if self.eval_results:
            lines += ["", "## Evaluation results", "", "| Suite | Metric | Value | CI95 | n |", "|---|---|---|---|---|"]
            lines += [f"| {r['suite']} | {r['metric']} | {r['value']} | {r.get('ci', '')} | {r.get('n', '')} |"
                      for r in self.eval_results]
        return "\n".join(lines) + "\n"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1)


def forge_card(config: HarnessConfig, tool_names: list[str], eval_results: list[dict] | None = None) -> HarnessCard:
    layers = {
        "instruction": "BASE_ROLE + AGENTS.md" + (" (guides on)" if config.enable_guides else " (guides off)")
                       + "; Skills via progressive disclosure",
        "tools": ", ".join(tool_names),
        "memory": f"transcript; compaction={config.compaction}; progress ledger for long-horizon runs",
        "execution": "per-task temp workspace, path jail, command allowlist, scrubbed env; container optional",
        "policy": f"permission_mode={config.permission_mode}; lethal-trifecta block; protect_tests={config.protect_tests}"
                  f"; egress allowlist={config.egress_allowlist}",
        "observability": "OTel GenAI-style spans with harness version and config fingerprint; JSONL export",
        "evaluation": "hidden pristine tests; tamper detector; trajectory grader; red-team suite",
    }
    return HarnessCard(
        config.name, config.version, config.fingerprint(), "agent",
        "Fix defects and maintain CI/CD configuration in a single Python repository.",
        layers, asdict(config.budgets), config.permission_mode,
        ["edits tests after repeated failures (reward hacking) unless protect_tests is on",
         "accuracy decays on long transcripts without compaction",
         "follows planted instructions in unspotlighted content at a model-dependent rate"],
        eval_results or [],
        ["multi-repository changes", "production deploys without human approval", "secrets management"])


# Seven-layer teardown summaries used in Chapter 14 (public, high-level facts only).
REFERENCE_HARNESSES = {
    "Claude Code / Agent SDK": {
        "instruction": "CLAUDE.md hierarchy, system prompt, Skills (progressive disclosure)",
        "tools": "file read/edit, bash, grep/glob, web fetch, MCP servers, subagents",
        "memory": "transcript with auto-compaction; CLAUDE.md as durable memory",
        "execution": "local shell with permission prompts; optional OS-level sandboxing",
        "policy": "permission modes and allow/deny rules; hooks (PreToolUse, PostToolUse, Stop, ...)",
        "observability": "OpenTelemetry metrics/events export; transcripts",
        "evaluation": "left to the user (tests, hooks, CI)"},
    "OpenAI Codex CLI": {
        "instruction": "AGENTS.md discovery, system prompt",
        "tools": "shell and apply_patch style editing, MCP",
        "memory": "session transcript with compaction; resumable sessions",
        "execution": "OS sandboxing (Seatbelt on macOS, Landlock/seccomp on Linux), network off by default",
        "policy": "approval modes from read-only to full auto",
        "observability": "session logs; OpenTelemetry export",
        "evaluation": "user tests/CI"},
    "OpenHands": {
        "instruction": "agent prompts and microagents",
        "tools": "bash, editor, browser, Jupyter",
        "memory": "event stream with condensers",
        "execution": "Docker runtime per session",
        "policy": "confirmation mode, security analyzer",
        "observability": "event stream persisted",
        "evaluation": "benchmark harness (SWE-bench and others)"},
    "Aider": {
        "instruction": "conventions files, repo map",
        "tools": "edit formats (diff, whole, udiff) instead of tool calls",
        "memory": "chat history plus repository map",
        "execution": "local; runs lint/test commands and feeds errors back",
        "policy": "git commits for every change (easy undo)",
        "observability": "chat and git history",
        "evaluation": "public edit-format and polyglot leaderboards"},
    "mini-SWE-agent": {
        "instruction": "short system prompt",
        "tools": "bash only (no tool-calling interface)",
        "memory": "linear history",
        "execution": "subprocess or container per action",
        "policy": "minimal",
        "observability": "trajectory files",
        "evaluation": "SWE-bench runner"},
    "Terminus-2 (Harbor)": {
        "instruction": "minimal prompt",
        "tools": "a single tmux terminal session",
        "memory": "transcript with summarization when long",
        "execution": "containerized task environment",
        "policy": "task-level isolation",
        "observability": "trajectories",
        "evaluation": "Terminal-Bench style tests via Harbor"},
    "Hermes Agent": {
        "instruction": "configurable persona and skills",
        "tools": "tool registry, MCP, messaging gateways",
        "memory": "persistent cross-session memory and user modelling",
        "execution": "local or remote backends",
        "policy": "configurable approvals",
        "observability": "session logs",
        "evaluation": "community"},
}
