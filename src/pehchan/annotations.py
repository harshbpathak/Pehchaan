"""Explicitly curated enrichment. Source markup does not supply narrative labels."""

import json
from pathlib import Path

from .records import RecordError, normalize_text, stable_id, text


def load_annotations(path: Path | None, records: list[dict]) -> list[dict]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise RecordError("annotations must be a JSON array")
    by_id = {r["variant_id"]: r for r in records}
    annotations = []
    for row in payload:
        if not isinstance(row, dict) or row.get("variant_id") not in by_id:
            raise RecordError("annotation refers to an unknown variant")
        if not text(row.get("reviewed_by")) or not text(row.get("rationale")):
            raise RecordError("annotation requires reviewed_by and rationale")
        record = by_id[row["variant_id"]]
        for collection, kind in (("frames", "frame"), ("topics", "topic"), ("entities", "entity")):
            items = row.get(collection, [])
            if not isinstance(items, list):
                raise RecordError(f"{collection} must be an array")
            for item in items:
                if not isinstance(item, dict) or not text(item.get("name")):
                    raise RecordError(f"{collection} entries require a name")
                if kind == "entity":
                    span = text(item.get("evidence_span"))
                    if not span or normalize_text(span) not in record["normalized_text"]:
                        raise RecordError("entity evidence_span must occur in the claim text")
                identity = [normalize_text(item["name"])]
                if kind == "entity":
                    if not text(item.get("type")):
                        raise RecordError("entity requires type")
                    identity.append(normalize_text(item["type"]))
                annotations.append(
                    {
                        "kind": kind,
                        "claim_id": record["claim_id"],
                        "id": stable_id(kind, *identity),
                        "name": text(item["name"]),
                        "description": text(item.get("description")),
                        "type": text(item.get("type")),
                        "evidence_span": text(item.get("evidence_span")),
                        "reviewed_by": text(row["reviewed_by"]),
                        "rationale": text(row["rationale"]),
                        "source_variant_id": record["variant_id"],
                    }
                )
    return annotations
