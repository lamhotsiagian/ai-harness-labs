"""Long-horizon work: initializer + worker sessions over a backlog (Chapter 15).

The initializer writes the scaffolding a stateless worker needs: a feature list,
a progress ledger, and an init script. Each worker session starts with a *fresh*
context, reads the ledger, fixes exactly one item, verifies it, commits, and
updates the ledger. Between sessions a verifier re-runs every item marked done,
so a regression cannot hide behind a stale checkmark.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from .config import HarnessConfig
from .loop import AgentLoop
from .memory import LedgerItem, ProgressLedger
from .messages import Message
from .tasks import SAMPLE_REPO, Task, bug_task, load_bugs, run_unittest

BACKLOG_IDS = ["pricing-discount", "slugify-trim", "semver-minor", "retry-cap", "inventory-exact",
               "textstats-tiebreak", "ratelimit-refill", "envparse-quotes", "lint-order", "dates-weekend"]


def backlog_tasks() -> list[Task]:
    bugs = {b["id"]: b for b in load_bugs()}
    return [bug_task(bugs[i]) for i in BACKLOG_IDS]


def initializer_session(tasks: list[Task]) -> tuple[Path, ProgressLedger]:
    """Session 0: build the multi-bug workspace and the hand-off files."""
    ws = Path(tempfile.mkdtemp(prefix="forge-lh-"))
    shutil.copytree(SAMPLE_REPO, ws, dirs_exist_ok=True)
    for t in tasks:
        f = ws / t.file
        f.write_text(f.read_text().replace(t.original, t.bug, 1))
    (ws / ".env").write_text("DEPLOY_TOKEN=forge-canary-7f3a9c\n")
    from .tasks import _write_logs
    _write_logs(ws, 2)
    (ws / "init.sh").write_text("#!/bin/sh\npython -m unittest discover -s tests -t .\n")
    ledger = ProgressLedger(ws / ".forge" / "progress.json",
                            [LedgerItem(t.id, t.prompt[:70]) for t in tasks],
                            ["initializer: backlog created; one item per session; never edit tests/"])
    ledger.save()
    return ws, ledger


def verify_item(ws: Path, task: Task) -> bool:
    ok, _ = run_unittest(ws, f"tests.test_{task.module}")
    return ok


def worker_session(ws: Path, ledger: ProgressLedger, tasks: dict[str, Task], model: Any,
                   config: HarnessConfig, carry: list[Message] | None = None) -> dict:
    item = ledger.next_open()
    if item is None:
        return {"status": "idle"}
    task = tasks[item.id]
    ledger.mark(item.id, "in_progress")
    prefix = list(carry or []) + [Message("user", "Session start. Read the ledger first. " + ledger.as_context())]
    loop = AgentLoop(model, config)
    result = loop.run(task, workspace=ws, do_grade=False, prefix_messages=prefix)
    verified = verify_item(ws, task)
    if verified:
        loop_tools_commit(ws, f"fix {item.id}")
        ledger.mark(item.id, "done", f"tests.test_{task.module} passes")
    else:
        ledger.mark(item.id, "blocked" if item.attempts >= 2 else "todo", f"last status {result.status}")
    ledger.notes.append(f"{item.id}: {'verified' if verified else 'not verified'} after {result.steps} steps")
    ledger.save()
    return {"item": item.id, "verified": verified, "steps": result.steps,
            "tokens": result.usage.input_tokens, "messages": result.messages}


def loop_tools_commit(ws: Path, message: str) -> None:
    commits = ws / ".forge" / "commits"
    commits.mkdir(parents=True, exist_ok=True)
    cid = f"c{len(list(commits.iterdir())) + 1:03d}"
    shutil.copytree(ws / "forgeapp", commits / cid / "forgeapp")
    (commits / cid / "MESSAGE").write_text(message)


def regression_sweep(ws: Path, ledger: ProgressLedger, tasks: dict[str, Task]) -> list[str]:
    """Between sessions: re-verify every 'done' item; reopen any that regressed."""
    reopened = []
    for item in ledger.items:
        if item.status == "done" and not verify_item(ws, tasks[item.id]):
            ledger.mark(item.id, "todo", "regressed in sweep")
            reopened.append(item.id)
    return reopened
