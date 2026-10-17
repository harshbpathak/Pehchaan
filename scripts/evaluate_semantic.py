"""Run a fixed English relevance/abstention smoke benchmark with real local models."""

import argparse
import json
from pathlib import Path

from pehchan.graph import GraphStore
from pehchan.semantic import ClaimScout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", default="pehchan")
    parser.add_argument("--output", type=Path, default=Path("artifacts/semantic-evaluation.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "data/evaluation/semantic_cases.json").read_text(encoding="utf-8"))
    store = GraphStore(args.graph)
    results = []
    try:
        scout = ClaimScout(store)
        for case in cases:
            result = scout.scout(case["claim"])
            candidates = result["matches"] + result["context"] + result["rejected"]
            target = next((c for c in candidates if c["variant_id"] == case.get("target")), None)
            actual = (
                (target["assessment"]["relation"] if target else "TARGET_NOT_RETRIEVED")
                if case.get("target")
                else result["outcome"]
            )
            ok = actual == case["expected"]
            results.append(
                {
                    **case,
                    "actual": actual,
                    "passed": ok,
                    "candidate_summary": [
                        {
                            "variant_id": c["variant_id"],
                            "similarity": c["similarity"],
                            "assessment": c["assessment"],
                        }
                        for c in candidates
                    ],
                    "match_ids": result["handoff_variant_ids"],
                }
            )
            print(
                json.dumps(
                    {"id": case["id"], "expected": case["expected"], "actual": actual, "passed": ok}
                ),
                flush=True,
            )
        paraphrases = [r for r in results if r["kind"] == "paraphrase"]
        safety = [r for r in results if r["kind"] != "paraphrase"]
        recall = sum(r["passed"] for r in paraphrases) / len(paraphrases)
        report = {
            "ok": all(r["passed"] for r in safety) and recall >= 2 / 3,
            "strict_cases_passed": sum(r["passed"] for r in results),
            "total_cases": len(results),
            "paraphrase_direct_recall": recall,
            "release_gate": "All safety/abstention cases pass; at least 2/3 fixed paraphrases directly matched.",
            "known_false_negatives": [r["id"] for r in paraphrases if not r["passed"]],
            "graph": args.graph,
            "cases": results,
            "models": result["models"],
            "scope": "Fixed smoke evaluation, not calibrated misinformation accuracy.",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return 0 if report["ok"] else 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
