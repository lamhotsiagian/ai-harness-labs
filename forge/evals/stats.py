"""Statistics for agent evals (Chapters 24 and 26). Standard library only.

Every reported number should carry an interval. Agents are stochastic, suites
are small, and a two-point "improvement" is usually noise.
"""
from __future__ import annotations

import math
import random
from statistics import mean
from typing import Callable, Sequence


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (well-behaved near 0 and 1)."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_ci(values: Sequence[float], stat: Callable[[Sequence[float]], float] = mean,
                 n_boot: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float, float]:
    rng = random.Random(seed)
    n = len(values)
    boots = sorted(stat([values[rng.randrange(n)] for _ in range(n)]) for _ in range(n_boot))
    lo, hi = boots[int(alpha / 2 * n_boot)], boots[int((1 - alpha / 2) * n_boot) - 1]
    return stat(values), lo, hi


def clustered_bootstrap(per_task: dict[str, list[float]], n_boot: int = 2000, alpha: float = 0.05,
                        seed: int = 0) -> tuple[float, float, float]:
    """Resample tasks (clusters), then trials: honest CIs when trials repeat per task."""
    rng = random.Random(seed)
    tasks = list(per_task)
    point = mean(v for vs in per_task.values() for v in vs)
    boots = []
    for _ in range(n_boot):
        sample = []
        for _ in tasks:
            vs = per_task[tasks[rng.randrange(len(tasks))]]
            sample += [vs[rng.randrange(len(vs))] for _ in vs]
        boots.append(mean(sample))
    boots.sort()
    return point, boots[int(alpha / 2 * n_boot)], boots[int((1 - alpha / 2) * n_boot) - 1]


def paired_bootstrap(a: Sequence[float], b: Sequence[float], n_boot: int = 4000,
                     seed: int = 0) -> dict[str, float]:
    """Difference b - a on the *same* tasks. Pairing removes task-difficulty variance."""
    assert len(a) == len(b), "paired comparison needs aligned task lists"
    rng = random.Random(seed)
    n = len(a)
    diffs = [y - x for x, y in zip(a, b)]
    boots = sorted(mean(diffs[rng.randrange(n)] for _ in range(n)) for _ in range(n_boot))
    p_le_zero = sum(d <= 0 for d in boots) / n_boot
    return {"diff": mean(diffs), "lo": boots[int(0.025 * n_boot)], "hi": boots[int(0.975 * n_boot) - 1],
            "p_one_sided": p_le_zero}


def mcnemar_exact(a: Sequence[bool], b: Sequence[bool]) -> dict[str, float]:
    """Exact McNemar test on discordant pairs for paired pass/fail outcomes."""
    b_only = sum((not x) and y for x, y in zip(a, b))
    a_only = sum(x and (not y) for x, y in zip(a, b))
    n = a_only + b_only
    if n == 0:
        return {"a_only": 0, "b_only": 0, "p_value": 1.0}
    k = min(a_only, b_only)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return {"a_only": a_only, "b_only": b_only, "p_value": min(1.0, 2 * tail)}


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased estimator of P(at least one of k samples passes) (Chen et al., 2021)."""
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k: P(all k independent trials pass), the reliability view (Yao et al., 2024)."""
    if c < k:
        return 0.0
    return math.comb(c, k) / math.comb(n, k)


def mde_two_proportions(p: float, n_per_arm: int, alpha: float = 0.05, power: float = 0.8) -> float:
    """Minimum detectable absolute effect for an unpaired two-arm comparison."""
    z_a = 1.959963984540054 if alpha == 0.05 else _z(1 - alpha / 2)
    z_b = 0.8416212335729143 if power == 0.8 else _z(power)
    return (z_a + z_b) * math.sqrt(2 * p * (1 - p) / n_per_arm)


def _z(q: float) -> float:
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def cohen_kappa(a: Sequence[bool], b: Sequence[bool]) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)
