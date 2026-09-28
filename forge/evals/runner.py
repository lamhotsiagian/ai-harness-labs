"""Eval runner: fan out tasks x trials x harness configs, with budgets (Chapter 25)."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import HarnessConfig
from ..loop import AgentLoop
from ..models import make_model
from ..tasks import FIXTURES, Task


@dataclass
class EvalRecord:
    task_id: str
    split: str
    config: str
    trial: int
    success: bool
    status: str
    steps: int
    cost_usd: float
    tokens: int
    tampered: bool
    leaked_secret: bool
    interventions: int
    seconds: float


class RateLimiter:
    """Token bucket shared by worker threads (provider RPM limits are per key)."""

    def __init__(self, per_second: float):
        self.per_second, self.tokens, self.last = per_second, per_second, time.time()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.time()
                self.tokens = min(self.per_second, self.tokens + (now - self.last) * self.per_second)
                self.last = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
            time.sleep(0.01)


def manifest(model_spec: str, configs: dict[str, HarnessConfig], seed: int) -> dict:
    """Everything needed to reproduce a run: harness, model, seed, fixtures, runtime."""
    fx = hashlib.sha256()
    for p in sorted(FIXTURES.rglob("*")):
        if p.is_file() and "__pycache__" not in str(p):
            fx.update(p.read_bytes())
    return {"model": model_spec, "seed": seed, "python": sys.version.split()[0], "platform": platform.platform(),
            "fixtures_sha256": fx.hexdigest()[:16],
            "configs": {k: v.fingerprint() for k, v in configs.items()}, "created": time.time()}


@dataclass
class EvalRunner:
    configs: dict[str, HarnessConfig]
    model_spec: str = "sim:frontier"
    trials: int = 1
    max_workers: int = 8
    requests_per_second: float = 50.0
    budget_usd: float = 25.0
    seed: int = 0
    model_factory: Callable[[str, int], Any] | None = None
    spent: float = 0.0
    records: list[EvalRecord] = field(default_factory=list)

    def _one(self, task: Task, cfg_name: str, trial: int, limiter: RateLimiter) -> EvalRecord:
        limiter.acquire()
        factory = self.model_factory or (lambda spec, seed: make_model(spec, seed))
        model = factory(self.model_spec, self.seed * 1000 + trial)
        t0 = time.time()
        r = AgentLoop(model, self.configs[cfg_name]).run(task)
        return EvalRecord(task.id, task.split, cfg_name, trial, r.success, r.status, r.steps, r.cost_usd,
                          r.usage.input_tokens + r.usage.output_tokens, bool(r.grade and r.grade["tampered"]),
                          r.leaked_secret, len(r.interventions), time.time() - t0)

    def run(self, tasks: list[Task], out: Path | None = None) -> list[EvalRecord]:
        limiter = RateLimiter(self.requests_per_second)
        jobs = [(t, c, k) for t in tasks for c in self.configs for k in range(self.trials)]
        with ThreadPoolExecutor(self.max_workers) as pool:
            futures = {pool.submit(self._one, t, c, k, limiter): (t, c, k) for t, c, k in jobs}
            for fut in as_completed(futures):
                rec = fut.result()
                self.records.append(rec)
                self.spent += rec.cost_usd
                if self.spent > self.budget_usd:          # hard stop: cancel queued work
                    for f in futures:
                        f.cancel()
                    break
        self.records.sort(key=lambda r: (r.config, r.task_id, r.trial))
        if out:
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w") as fh:
                for r in self.records:
                    fh.write(json.dumps(r.__dict__) + "\n")
            out.with_suffix(".manifest.json").write_text(
                json.dumps(manifest(self.model_spec, self.configs, self.seed), indent=1))
        return self.records


def by_config(records: list[EvalRecord]) -> dict[str, list[EvalRecord]]:
    out: dict[str, list[EvalRecord]] = {}
    for r in records:
        out.setdefault(r.config, []).append(r)
    return out
