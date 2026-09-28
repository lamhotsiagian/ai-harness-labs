"""Self-improving harnesses: capture corrections, gate changes, export trajectories (Chapter 23)."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .messages import Message
from .loop import RunResult


@dataclass
class Correction:
    reviewer: str
    comment: str
    run_id: str


RULE_PATTERNS = [
    (r"(don't|do not|never) (edit|touch|modify) tests?", "Never edit files under tests/; fix the implementation."),
    (r"run (the )?tests", "Run the module tests after every edit before reporting DONE."),
    (r"(smaller|minimal) (patch|change|diff)", "Keep patches minimal: change one expression per defect."),
    (r"(read|check) (the )?(runbook|docs?)", "Read the matching runbook before proposing an incident action."),
]


def correction_to_rule(c: Correction) -> str | None:
    for pattern, rule in RULE_PATTERNS:
        if re.search(pattern, c.comment, re.I):
            return rule
    return None


def update_agents_md(path: Path, rules: list[tuple[str, Correction]]) -> list[str]:
    """Append deduplicated rules with provenance under '## Learned rules'."""
    text = path.read_text()
    if "## Learned rules" not in text:
        text += "\n## Learned rules\n"
    added = []
    for rule, c in rules:
        if rule in text:
            continue
        text += f"- {rule} <!-- source: {c.reviewer}, run {c.run_id}, {time.strftime('%Y-%m-%d')} -->\n"
        added.append(rule)
    path.write_text(text)
    return added


def improvement_gate(evaluate: Callable[[Any, str], list[bool]], baseline: Any, candidate: Any,
                     min_gain: float = 0.0, safety: Callable[[Any], float] | None = None) -> dict:
    """propose -> test on held-out -> gate -> merge. Dev results never decide a merge."""
    from .evals.stats import mcnemar_exact, paired_bootstrap
    dev_b, dev_c = evaluate(baseline, "dev"), evaluate(candidate, "dev")
    held_b, held_c = evaluate(baseline, "heldout"), evaluate(candidate, "heldout")
    boot = paired_bootstrap([float(x) for x in held_b], [float(x) for x in held_c])
    mc = mcnemar_exact(held_b, held_c)
    safe = True
    if safety:
        safe = safety(candidate) <= safety(baseline)
    merge = boot["lo"] > min_gain and safe
    return {"dev_baseline": sum(dev_b) / len(dev_b), "dev_candidate": sum(dev_c) / len(dev_c),
            "heldout_baseline": sum(held_b) / len(held_b), "heldout_candidate": sum(held_c) / len(held_c),
            "heldout_diff_ci": (round(boot["lo"], 3), round(boot["hi"], 3)), "mcnemar_p": round(mc["p_value"], 4),
            "safety_ok": safe, "merge": merge}


def to_openai_chat(system: str, messages: list[Message], tools: list[dict]) -> dict:
    """One trajectory in the chat format TRL's SFTTrainer accepts (messages + tools)."""
    out = [{"role": "system", "content": system}]
    for m in messages:
        if m.role == "assistant":
            entry: dict = {"role": "assistant", "content": m.content}
            if m.tool_calls:
                entry["tool_calls"] = [{"id": c.id, "type": "function",
                                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                                       for c in m.tool_calls]
            out.append(entry)
        elif m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        else:
            out.append({"role": m.role, "content": m.content})
    return {"messages": out, "tools": [{"type": "function", "function": t} for t in tools]}


def export_trajectories(results: list[tuple[RunResult, str, list[dict]]], sft_path: Path,
                        pref_path: Path | None = None) -> dict:
    """SFT: successful, untampered, leak-free runs. Preferences: success vs failure on the same task."""
    sft_path.parent.mkdir(parents=True, exist_ok=True)
    kept = dropped = 0
    by_task: dict[str, dict[str, Any]] = {}
    with sft_path.open("w") as fh:
        for r, system, tools in results:
            record = to_openai_chat(system, r.messages, tools)
            record["metadata"] = {"task": r.task_id, "harness": r.config_fingerprint, "steps": r.steps}
            slot = by_task.setdefault(r.task_id.split("#")[0], {})
            if r.success and not r.leaked_secret:
                fh.write(json.dumps(record) + "\n")
                kept += 1
                slot.setdefault("chosen", record)
            else:
                dropped += 1
                slot.setdefault("rejected", record)
    pairs = 0
    if pref_path:
        with pref_path.open("w") as fh:
            for task, slot in by_task.items():
                if "chosen" in slot and "rejected" in slot:
                    fh.write(json.dumps({"prompt": slot["chosen"]["messages"][:2],
                                         "chosen": slot["chosen"]["messages"][2:],
                                         "rejected": slot["rejected"]["messages"][2:]}) + "\n")
                    pairs += 1
    return {"sft_kept": kept, "sft_dropped": dropped, "preference_pairs": pairs}
