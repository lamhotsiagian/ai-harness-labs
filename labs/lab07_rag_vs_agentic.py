"""Lab 7: RAG vs agentic search on the incident-investigation corpus."""
from __future__ import annotations

import json

from labs.common import ROOT, LabReport, finish, lab_args
from forge.retrieval import HybridRetriever, agentic_search, load_corpus


def metrics(ranked_ids: list[list[str]], gold: list[list[str]]) -> dict:
    r1 = sum(r[:1] and r[0] in g for r, g in zip(ranked_ids, gold)) / len(gold)
    r3 = sum(any(x in g for x in r[:3]) for r, g in zip(ranked_ids, gold)) / len(gold)
    mrr = sum(next((1 / (i + 1) for i, x in enumerate(r) if x in g), 0) for r, g in zip(ranked_ids, gold)) / len(gold)
    return {"recall@1": round(r1, 3), "recall@3": round(r3, 3), "mrr": round(mrr, 3)}


def run(model: str = "sim:frontier", seeds: int = 1) -> LabReport:
    all_qs = json.loads((ROOT / "fixtures" / "rag_questions.json").read_text())
    docs = load_corpus()
    retriever = HybridRetriever(docs)
    rows, steps = [], 0
    for category in ("nl", "identifier"):
        qs = [(q, g) for q, g, c in all_qs if c == category]
        gold = [g for _, g in qs]
        for mode in ("bm25", "dense", "hybrid"):
            for rerank in (False, True):
                ranked = [[d.id for d in retriever.search(q, 5, mode, rerank)] for q, _ in qs]
                # pre-retrieval injects the top-3 documents into the context up front
                chars = sum(sum(len(d.text) for d in retriever.search(q, 3, mode, rerank)) for q, _ in qs)
                rows.append({"questions": category, "method": f"{mode}{'+rerank' if rerank else ''}",
                             **metrics(ranked, gold), "chars_per_q": chars // len(qs)})
        ranked, chars = [], 0
        for q, _ in qs:
            hits, log, c = agentic_search(q, docs)
            ranked.append([d.id for d in hits])
            chars += c
            steps += len(log)
        rows.append({"questions": category, "method": "agentic grep", **metrics(ranked, gold),
                     "chars_per_q": chars // len(qs)})
    qs = all_qs
    example = agentic_search(all_qs[-5][0], docs)[1]
    return LabReport("07", "RAG vs agentic search", f"{len(qs)} questions, {len(docs)} runbooks and postmortems.",
                     {"agentic_search_steps_total": steps, "example_trace": " | ".join(example)}, rows,
                     {"x": "method", "y": ["recall@1", "mrr"], "kind": "bar"})


def main() -> None:
    a = lab_args(__doc__, seeds=1)
    finish(run(a.model, a.seeds), a.json)


if __name__ == "__main__":
    main()
