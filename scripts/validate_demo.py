"""Reproduce the milestone against genuine sample markup and a persistent local graph."""

import argparse
import json
from pathlib import Path

from pehchan.annotations import load_annotations
from pehchan.graph import GraphStore
from pehchan.ingestion import load_prepared, prepare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", default="pehchan_demo")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = root / "artifacts/demo"
    destination.mkdir(parents=True, exist_ok=True)
    prepared = destination / "claims.jsonl"
    prepare(
        root / "data/samples/claimreviews.json",
        prepared,
        destination / "preparation.json",
        source="Data Commons ClaimReview feed; see data/samples/manifest.json",
    )
    records = load_prepared(prepared)
    annotations = load_annotations(root / "data/samples/annotations.json", records)
    store = GraphStore(args.graph)
    try:
        store.init_schema()
        initial = store.ingest(records, annotations)
        after_repeat = store.ingest(records, annotations)
        result = store.validate(records, require_narrative=True)
        result["idempotent_reingestion"] = initial == after_repeat
        submitted = "A microchip reader for pets detected a chip in a vaccinated arm"
        candidates = store.candidates(submitted)
        first_id = candidates[0]["variant_id"] if candidates else ""
        citations = [
            {k: e[k] for k in ("url", "verdict_original", "publisher")}
            for e in store.evidence(first_id)
        ]
        result["submitted_claim_example"] = {
            "text": submitted,
            "candidates": candidates,
            "candidate_sources": citations,
            "interpretation": "Unverified lexical candidates; no new verdict.",
        }
        result["entity_bridge_example"] = store.shortest_path(
            "variant_700ff916add10df61b609425", "variant_9e4e7b29e161704389906809"
        )
        unknown = "Underwater quartz clocks transmit encrypted rainfall forecasts"
        unknown_candidates = store.candidates(unknown)
        result["no_match_example"] = {
            "text": unknown,
            "candidates": unknown_candidates,
            "interpretation": "No matching record in this sample; truth is undetermined.",
        }
        result["ok"] = (
            result["ok"]
            and result["idempotent_reingestion"]
            and first_id == "variant_b798bbbaab3675372ee8c4c3"
            and bool(result["entity_bridge_example"])
            and not unknown_candidates
        )
        output = destination / "validation.json"
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": result["ok"],
                    "graph": args.graph,
                    "checked_records": len(records),
                    "report": str(output),
                },
                indent=2,
            )
        )
        return 0 if result["ok"] else 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
