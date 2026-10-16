"""Run explicitly with PEHCHAN_INTEGRATION=1 against the local FalkorDB container."""

import copy
import os
import uuid
from pathlib import Path

import pytest

from pehchan.annotations import load_annotations
from pehchan.graph import GraphStore
from pehchan.ingestion import load_prepared, prepare
from pehchan.records import normalize_review, stable_id

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("PEHCHAN_INTEGRATION") != "1",
        reason="set PEHCHAN_INTEGRATION=1 for live database tests",
    ),
]


def test_real_database_idempotence_paths_and_no_match(review):
    # A new, explicitly owned graph is deleted in finally; existing graphs are never cleared.
    store = GraphStore("pehchan_test_" + uuid.uuid4().hex[:16])
    try:
        related = copy.deepcopy(review)
        related["claimReviewed"] = "The town bridge runs on moonlight."
        related["url"] = "https://checks.example/review/bridge"
        records = [
            normalize_review(r, "synthetic integration test", "test", i)
            for i, r in enumerate([review, related], 1)
        ]
        annotations = [
            {
                "kind": "frame",
                "claim_id": r["claim_id"],
                "id": stable_id("frame", "synthetic moonlight frame"),
                "name": "Synthetic moonlight frame",
                "description": "test-only inference",
                "type": "",
                "evidence_span": "",
                "reviewed_by": "integration test",
                "rationale": "Synthetic test relationship",
                "source_variant_id": r["variant_id"],
            }
            for r in records
        ]
        store.init_schema()
        first = store.ingest(records, annotations)
        store.init_schema()
        second = store.ingest(records, annotations)
        assert first == second
        assert second["nodes"]["ClaimVariant"] == 2
        report = store.validate(records, require_narrative=True)
        assert report["ok"], report
        path = report["narrative_path_example"]
        assert path["relationships"] == ["EXPRESSES", "USES_FRAME", "USES_FRAME", "EXPRESSES"]
        assert len(path["node_ids"]) == 5
        assert path["relevance"] == "narrative_context_only"
        assert store.candidates("zzzxxyyq unrelated") == []
        assert store.evidence("nonexistent") == []
        malicious = "x'}) MATCH (n) DETACH DELETE n //"
        assert store.evidence(malicious) == []
        assert store.stats() == second
    finally:
        store.graph.delete()
        store.close()


def test_genuine_source_sample_and_entity_bridge(tmp_path):
    root = Path(__file__).resolve().parents[1]
    prepared = tmp_path / "sample.jsonl"
    prepare(
        root / "data/samples/claimreviews.json",
        prepared,
        tmp_path / "report.json",
        source="Data Commons; see data/samples/manifest.json",
    )
    records = load_prepared(prepared)
    annotations = load_annotations(root / "data/samples/annotations.json", records)
    store = GraphStore("pehchan_test_" + uuid.uuid4().hex[:16])
    try:
        store.init_schema()
        first = store.ingest(records, annotations)
        assert first == store.ingest(records, annotations)
        assert store.validate(records, require_narrative=True)["ok"]
        candidates = store.candidates(
            "A microchip reader for pets detected a chip in a vaccinated arm"
        )
        assert candidates[0]["variant_id"] == "variant_b798bbbaab3675372ee8c4c3"
        assert store.evidence(candidates[0]["variant_id"])[0]["publisher"] == "FactCheck.org"
        # Distinct frames connect through the explicitly mentioned 5G entity.
        bridge = store.shortest_path(
            "variant_700ff916add10df61b609425", "variant_9e4e7b29e161704389906809"
        )
        assert "MENTIONS" in bridge[0][1]
        assert (
            store.candidates("Underwater quartz clocks transmit encrypted rainfall forecasts") == []
        )
    finally:
        store.graph.delete()
        store.close()
