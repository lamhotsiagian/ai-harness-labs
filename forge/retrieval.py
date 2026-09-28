"""Retrieval primitives: BM25, a dense proxy, hybrid fusion, reranking, agentic search.

The dense retriever is a character-trigram TF-IDF cosine model: no downloads, no
GPU, yet it behaves like an embedding model in the ways that matter for the
labs (fuzzy lexical matching, weaker on exact identifiers than BM25).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "docs"
STOP = set("the a an of to in on for and or is are was were be by with at from what which why how do does "
           "did i we our you it this that when who can".split())


def tokenize(text: str) -> list[str]:
    # keep dotted identifiers (db.pool.in_use, test_retry.py) but drop sentence-final dots
    return [t for t in re.findall(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*", text.lower()) if t not in STOP]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.4, b: float = 0.75):
        self.docs = [tokenize(d) for d in docs]
        self.k1, self.b = k1, b
        self.avgdl = sum(map(len, self.docs)) / max(1, len(self.docs))
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, d in zip(self.tf, self.docs):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avgdl))
            out.append(s)
        return out


class TrigramDense:
    """Dense-retriever stand-in: TF-IDF over character trigrams, cosine similarity."""

    def __init__(self, docs: list[str]):
        grams = [self._grams(d) for d in docs]
        df = Counter(g for d in grams for g in set(d))
        self.idf = {g: math.log(len(docs) / (1 + f)) + 1 for g, f in df.items()}
        self.vecs = [self._vec(g) for g in grams]

    @staticmethod
    def _grams(text: str) -> Counter:
        t = re.sub(r"\s+", " ", text.lower())
        return Counter(t[i:i + 3] for i in range(len(t) - 2))

    def _vec(self, grams: Counter) -> dict[str, float]:
        v = {g: c * self.idf.get(g, 1.0) for g, c in grams.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {g: x / norm for g, x in v.items()}

    def scores(self, query: str) -> list[float]:
        q = self._vec(self._grams(query))
        return [sum(w * d.get(g, 0.0) for g, w in q.items()) for d in self.vecs]


def rrf(rankings: list[list[int]], k: int = 60) -> list[int]:
    """Reciprocal rank fusion: robust hybrid without score calibration."""
    score: Counter = Counter()
    for ranking in rankings:
        for rank, doc in enumerate(ranking):
            score[doc] += 1.0 / (k + rank + 1)
    return [d for d, _ in score.most_common()]


@dataclass
class Doc:
    id: str
    text: str
    path: Path


def load_corpus(root: Path = DOCS_DIR) -> list[Doc]:
    return [Doc(p.stem.split("-")[0] + "-" + p.stem.split("-")[1], p.read_text(), p)
            for p in sorted(root.glob("*.md"))]


class HybridRetriever:
    def __init__(self, docs: list[Doc]):
        self.docs = docs
        texts = [d.text for d in docs]
        self.bm25, self.dense = BM25(texts), TrigramDense(texts)

    def _rank(self, scores: list[float]) -> list[int]:
        return sorted(range(len(scores)), key=lambda i: -scores[i])

    def search(self, query: str, k: int = 3, mode: str = "hybrid", rerank: bool = True) -> list[Doc]:
        if mode == "bm25":
            order = self._rank(self.bm25.scores(query))
        elif mode == "dense":
            order = self._rank(self.dense.scores(query))
        else:
            order = rrf([self._rank(self.bm25.scores(query)), self._rank(self.dense.scores(query))])
        candidates = order[: max(k * 3, 6)]
        if rerank:
            # Second stage sees (query, doc) jointly: normalized lexical + dense + title evidence.
            bm, de = self.bm25.scores(query), self.dense.scores(query)
            top_bm, top_de = max(bm) or 1.0, max(de) or 1.0
            joint = {i: bm[i] / top_bm + de[i] / top_de + 0.15 * self._cross_score(query, self.docs[i].text)
                     for i in candidates}
            candidates = sorted(candidates, key=lambda i: -joint[i])
        return [self.docs[i] for i in candidates[:k]]

    @staticmethod
    def _cross_score(query: str, text: str) -> float:
        """Cheap cross-encoder stand-in: query-term coverage of the doc's first lines."""
        q = set(tokenize(query))
        head = set(tokenize(" ".join(text.splitlines()[:4])))
        body = set(tokenize(text))
        return 2.0 * len(q & head) + len(q & body)


def agentic_search(question: str, docs: list[Doc], max_steps: int = 4) -> tuple[list[Doc], list[str], int]:
    """grep-style iterative search, the way coding agents retrieve.

    Step 1 greps the most specific query terms; each later step greps identifiers
    discovered in what was read (doc ids, file paths). Returns hits, the action
    log, and the characters read (a proxy for tokens consumed).
    """
    terms = sorted(set(tokenize(question)), key=lambda t: -len(t))[:3]
    log, seen, chars = [], [], 0
    queue = list(terms)
    for _ in range(max_steps):
        if not queue:
            break
        term = queue.pop(0)
        hits = [d for d in docs if term in d.text.lower() and d not in seen]
        log.append(f"grep '{term}' -> {[d.id for d in hits]}")
        for d in hits[:2]:
            seen.append(d)
            chars += len(d.text)
            # follow references: RB-00x / INC-20xx ids mentioned in the document
            for ref in re.findall(r"\b(?:RB|INC)-\d{3,4}\b", d.text):
                if ref.lower() not in queue and ref != d.id:
                    queue.append(ref.lower())
    ranked = sorted(seen, key=lambda d: -HybridRetriever._cross_score(question, d.text))
    return ranked, log, chars
