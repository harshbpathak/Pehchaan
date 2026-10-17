"""Held-out retrieval comparison: word overlap vs. embeddings vs. embeddings + graph widening.

Each method returns a ranked list of claim variants. A case is a hit at k when any of the top-k
variants is an accepted recorded wording of the same claim. Weights are fixed before running;
they are not tuned on these cases.
"""

import argparse
import json
from pathlib import Path

from pehchan.graph import GraphStore
from pehchan.models import Embedder
from pehchan.rules import tag
from pehchan.semantic import VectorIndex, valid_vector

POOL = 20  # embedding candidates considered by the graph-widened method
GRAPH_WEIGHT = 0.1  # bonus per unit of shared-context score (sum of 1/degree), capped at 1


def resolve(store, cases):
    rows = store.read("MATCH (v:ClaimVariant) RETURN v.id, v.text")
    for case in cases:
        case["expected"] = {vid for vid, text in rows if any(a in text for a in case["accept"])}
        if not case["expected"]:
            raise SystemExit(f"No recorded wording matches accepted texts for: {case['query']}")


def lexical(store, query, k):
    return [c["variant_id"] for c in store.candidates(query, k)]


def embedding(index, vector, k):
    return [c["variant_id"] for c in index.search(vector, k)]


def widened(store, index, vector, query, k):
    scores = {c["variant_id"]: c["similarity"] for c in index.search(vector, POOL)}
    tags = tag(query)
    bonus = {}
    for row in store.shared_context([e["name"] for e in tags["entities"]], tags["frames"], [], 50):
        bonus[row["variant_id"]] = max(bonus.get(row["variant_id"], 0), min(row["score"], 1.0))
    missing = [vid for vid in bonus if vid not in scores]
    if missing:
        for vid, stored in store.read(
            "MATCH (v:ClaimVariant) WHERE v.id IN $ids RETURN v.id, v.embedding", {"ids": missing}
        ):
            scores[vid] = sum(a * b for a, b in zip(vector, valid_vector(stored)))
    ranked = sorted(scores, key=lambda v: (-(scores[v] + GRAPH_WEIGHT * bonus.get(v, 0)), v))
    return ranked[:k]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", default="pehchan")
    parser.add_argument("--cases", type=Path, default=Path("data/evaluation/heldout_cases.json"))
    parser.add_argument("--output", type=Path, default=Path("Docs/retrieval-evaluation.json"))
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    store = GraphStore(args.graph)
    index, embedder = VectorIndex(store), Embedder()
    resolve(store, cases)
    methods = ("word_overlap", "embeddings", "embeddings_plus_graph")
    totals = {m: {"hit@1": 0, "hit@5": 0} for m in methods}
    rows = []
    for case in cases:
        vector = valid_vector(embedder.encode([case["query"]])[0])
        ranked = {
            "word_overlap": lexical(store, case["query"], 5),
            "embeddings": embedding(index, vector, 5),
            "embeddings_plus_graph": widened(store, index, vector, case["query"], 5),
        }
        row = {"query": case["query"], "kind": case["kind"]}
        for method, ids in ranked.items():
            hit1, hit5 = (
                bool(ids[:1] and ids[0] in case["expected"]),
                bool(set(ids) & case["expected"]),
            )
            totals[method]["hit@1"] += hit1
            totals[method]["hit@5"] += hit5
            row[method] = {"hit@1": hit1, "hit@5": hit5}
        rows.append(row)
    n = len(cases)
    summary = {
        m: {key: f"{value}/{n} ({value / n:.0%})" for key, value in totals[m].items()}
        for m in methods
    }
    by_kind = {}
    for row in rows:
        kind = "translation" if row["kind"].startswith("translation") else row["kind"]
        bucket = by_kind.setdefault(kind, {m: 0 for m in methods} | {"cases": 0})
        bucket["cases"] += 1
        for m in methods:
            bucket[m] += row[m]["hit@5"]
    report = {
        "graph": args.graph,
        "cases": n,
        "metric": "hit@k: an accepted recorded wording of the same claim appears in the top k",
        "settings": {"pool": POOL, "graph_weight": GRAPH_WEIGHT},
        "summary": summary,
        "hit@5_by_kind": by_kind,
        "results": rows,
        "limits": "30 author-written queries over a 248-variant graph; a smoke-scale comparison, "
        "not a calibrated accuracy estimate.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"summary": summary, "hit@5_by_kind": by_kind}, indent=2))
    store.close()


if __name__ == "__main__":
    main()
