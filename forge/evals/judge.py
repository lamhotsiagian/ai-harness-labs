"""LLM-as-judge calibration against human labels (Chapter 24).

The simulated judge has the biases real judges show: leniency toward confident
final answers and a verbosity bias. Calibration picks the decision threshold on
a labelled calibration split and reports agreement on a separate test split.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from .stats import cohen_kappa


@dataclass
class JudgeItem:
    item_id: str
    true_success: bool          # ground truth (hidden tests)
    human_label: bool           # human reviewer (small label noise)
    confident_claim: bool       # final answer says DONE
    length: int                 # transcript length (verbosity bias)


def simulated_judge_score(item: JudgeItem, seed: int = 0) -> float:
    """Score in [0, 10]. Leniency: a confident DONE adds points even when wrong."""
    rng = random.Random(f"{seed}|{item.item_id}")
    base = 7.0 if item.true_success else 3.2
    base += 2.0 if item.confident_claim else -1.0
    base += min(1.5, item.length / 4000)
    return max(0.0, min(10.0, base + rng.gauss(0, 1.3)))


def calibrate(items: list[JudgeItem], scores: list[float]) -> dict:
    best = (-1.0, 5.0)
    for t10 in range(0, 101):
        t = t10 / 10
        k = cohen_kappa([s >= t for s in scores], [i.human_label for i in items])
        best = max(best, (k, t))
    return {"threshold": best[1], "kappa": best[0]}


def agreement(items: list[JudgeItem], scores: list[float], threshold: float) -> dict:
    pred = [s >= threshold for s in scores]
    human = [i.human_label for i in items]
    tp = sum(p and h for p, h in zip(pred, human))
    tn = sum((not p) and (not h) for p, h in zip(pred, human))
    pos, neg = sum(human), len(human) - sum(human)
    return {"kappa": round(cohen_kappa(pred, human), 3), "tpr": round(tp / max(1, pos), 3),
            "tnr": round(tn / max(1, neg), 3), "judge_pass_rate": round(sum(pred) / len(pred), 3),
            "human_pass_rate": round(sum(human) / len(human), 3)}
