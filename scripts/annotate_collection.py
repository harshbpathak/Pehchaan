"""Rule-based narrative, topic and entity annotation of a prepared collection.

Every rule is an explicit, reviewable pattern. Entity spans are copied from the claim text, so
the loader's evidence-span check still applies. Output is an inference awaiting human review,
never publisher markup. Curated sample annotations are kept and merged for matching variants.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from pehchan.ingestion import load_prepared
from pehchan.records import normalize_text
from pehchan.rules import tag

REVIEWED_BY = "Claude Code (rule-based keyword annotation, scripts/annotate_collection.py; human review pending)"
RATIONALE = (
    "Assigned by an explicit keyword rule over the recorded claim text. This annotation is an "
    "inference, not publisher markup, proof of claim equivalence, or coordination."
)
FRAME_NOTE = "Rule-assigned thematic connection; propositions may differ."


def annotate(record: dict) -> dict:
    tags = tag(record["text"])
    if any(
        normalize_text(e["evidence_span"]) not in record["normalized_text"]
        for e in tags["entities"]
    ):
        raise ValueError("entity span must occur in the normalized claim text")
    return {
        "variant_id": record["variant_id"],
        "reviewed_by": REVIEWED_BY,
        "rationale": RATIONALE,
        "frames": [{"name": n, "description": FRAME_NOTE} for n in tags["frames"]],
        "topics": [{"name": n} for n in tags["topics"]],
        "entities": tags["entities"],
    }


def merge(rule_row: dict, curated: dict | None) -> dict:
    if curated is None:
        return rule_row
    merged = dict(curated)
    for key in ("frames", "topics", "entities"):
        names = {item["name"] for item in curated[key]}
        merged[key] = curated[key] + [i for i in rule_row[key] if i["name"] not in names]
    return merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prepared_feed", type=Path)
    parser.add_argument("--curated", type=Path, default=Path("data/samples/annotations.json"))
    parser.add_argument("--output", type=Path, default=Path("data/annotations/collection.json"))
    args = parser.parse_args()
    curated = {r["variant_id"]: r for r in json.loads(args.curated.read_text(encoding="utf-8"))}
    rows, seen = [], set()
    for record in load_prepared(args.prepared_feed):
        if record["variant_id"] in seen:
            continue
        seen.add(record["variant_id"])
        row = merge(annotate(record), curated.get(record["variant_id"]))
        if row["frames"] or row["topics"] or row["entities"]:
            rows.append(row)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {
        k: Counter(i["name"] for r in rows for i in r[k]) for k in ("frames", "topics", "entities")
    }
    print(f"Annotated {len(rows)} of {len(seen)} variants -> {args.output}")
    for key, counter in counts.items():
        print(f"{key}: {len(counter)} distinct, {sum(counter.values())} links")
        for name, n in counter.most_common():
            print(f"  {n:4d}  {name}")


if __name__ == "__main__":
    main()
