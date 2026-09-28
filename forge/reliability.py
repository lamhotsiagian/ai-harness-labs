"""Reliability engineering: chaos injection, circuit breakers, canaries (Chapter 22)."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from .messages import Message, ModelResponse, ToolCall


class ProviderError(Exception):
    """Stands in for HTTP 429 / 5xx / timeout from a model provider."""


class ChaosModel:
    """Wraps a model and injects the failures production actually sees."""

    def __init__(self, inner, error_rate: float = 0.0, malformed_rate: float = 0.0,
                 empty_rate: float = 0.0, seed: int = 0):
        self.inner, self.name = inner, f"chaos({inner.name})"
        self.error_rate, self.malformed_rate, self.empty_rate = error_rate, malformed_rate, empty_rate
        self.rng = random.Random(seed)
        self.injected: dict[str, int] = {"error": 0, "malformed": 0, "empty": 0}

    @property
    def prices(self):
        return self.inner.prices

    def complete(self, system, messages, tools, max_output_tokens=2048) -> ModelResponse:
        roll = self.rng.random()
        if roll < self.error_rate:
            self.injected["error"] += 1
            raise ProviderError("503 upstream overloaded")
        resp = self.inner.complete(system, messages, tools, max_output_tokens)
        roll = self.rng.random()
        if resp.message.tool_calls and roll < self.malformed_rate:
            self.injected["malformed"] += 1
            bad = resp.message.tool_calls[0]
            resp.message.tool_calls = [ToolCall(bad.id, bad.name, {"pathh": "oops"})]   # schema violation
        elif roll < self.malformed_rate + self.empty_rate:
            self.injected["empty"] += 1
            resp.message = Message("assistant", "")                                  # empty completion
        return resp


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    reset_after_s: float = 30.0
    failures: int = 0
    opened_at: float | None = None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        if time.time() - self.opened_at > self.reset_after_s:
            self.opened_at, self.failures = None, 0        # half-open: try again
            return True
        return False

    def record(self, ok: bool) -> None:
        if ok:
            self.failures = 0
            return
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time.time()


class ResilientModel:
    """Retry with jittered exponential backoff behind a circuit breaker."""

    def __init__(self, inner, retries: int = 3, base_delay: float = 0.0, seed: int = 0):
        self.inner, self.name = inner, f"resilient({inner.name})"
        self.retries, self.base_delay = retries, base_delay
        self.breaker = CircuitBreaker()
        self.rng = random.Random(seed)
        self.retry_count = 0

    @property
    def prices(self):
        return self.inner.prices

    def complete(self, system, messages, tools, max_output_tokens=2048) -> ModelResponse:
        for attempt in range(self.retries + 1):
            if not self.breaker.allow():
                raise ProviderError("circuit open")
            try:
                resp = self.inner.complete(system, messages, tools, max_output_tokens)
                self.breaker.record(True)
                if not resp.message.content and not resp.message.tool_calls and attempt < self.retries:
                    self.retry_count += 1          # empty completion: retry, do not treat as "done"
                    continue
                return resp
            except ProviderError:
                self.breaker.record(False)
                self.retry_count += 1
                if attempt == self.retries:
                    raise
                time.sleep(self.base_delay * (2 ** attempt) * (0.5 + self.rng.random()))
        raise ProviderError("retries exhausted")


@dataclass
class CanaryDecision:
    promote: bool
    baseline_rate: float
    canary_rate: float
    reason: str


def canary_gate(baseline: list[bool], canary: list[bool], max_drop: float = 0.05,
                min_samples: int = 20) -> CanaryDecision:
    """Promote a harness change only if the canary slice does not regress."""
    if len(canary) < min_samples:
        return CanaryDecision(False, 0, 0, f"need {min_samples} canary runs, have {len(canary)}")
    b = sum(baseline) / len(baseline)
    c = sum(canary) / len(canary)
    if c < b - max_drop:
        return CanaryDecision(False, b, c, f"regression {b - c:.1%} exceeds {max_drop:.0%}: roll back")
    return CanaryDecision(True, b, c, "within tolerance: promote")
