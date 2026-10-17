import copy
import os
import uuid

import pytest

from pehchan.graph import GraphStore
from pehchan.investigation import (
    RESPONSE_POLICY,
    SCOUT_POLICY,
    CaseStore,
    EvidenceResponse,
    Orchestrator,
    Specialist,
    decide,
)
from pehchan.records import normalize_review


def test_capabilities_reject_unapproved_tools():
    agent = Specialist(SCOUT_POLICY, {"find_similar_claims": lambda claim: {}}, [])
    with pytest.raises(PermissionError):
        agent.call("delete_graph")


@pytest.mark.integration
def test_tool_calling_case_persists_only_after_validated_completion(case_graph):
    from pehchan.inference import GeminiInference

    store, record = case_graph

    class Provider:
        model = "scripted-integration-model"

        def __init__(self, fail=False):
            self.turn = 0
            self.fail = fail

        def generate(self, contents):
            self.turn += 1
            if self.fail:
                raise RuntimeError("Simulated provider failure")
            turns = [
                [("find_similar_claims", {"claim": "Synthetic query"})],
                [
                    ("get_claim_evidence", {"variant_id": record["variant_id"]}),
                    ("explore_narrative_graph", {"variant_id": record["variant_id"]}),
                ],
                [
                    (
                        "finish_investigation",
                        {
                            "analyst_note": "Inspect the original review.",
                            "factcheck_ids": [record["factcheck_id"]],
                        },
                    )
                ],
            ]
            return {
                "role": "model",
                "parts": [
                    {"functionCall": {"name": name, "args": args}}
                    for name, args in turns[self.turn - 1]
                ],
            }

    failed = Orchestrator(store, StubScout(record), inference=GeminiInference(Provider(fail=True)))
    with pytest.raises(RuntimeError, match="provider failure"):
        failed.investigate("Synthetic query", "failed-llm-request")
    cases = CaseStore(store)
    assert cases.get(cases.identity("failed-llm-request")) is None
    engine = Orchestrator(store, StubScout(record), inference=GeminiInference(Provider()))
    report = engine.investigate("Synthetic query", "llm-request")
    assert report["status"] == "EVIDENCE_DOSSIER_READY"
    assert report["citations"][0]["factcheck_id"] == record["factcheck_id"]
    assert cases.get(report["investigation_id"])["inference"]["model"] == Provider.model
    assert engine.investigate("Synthetic query", "llm-request") == cases.get(
        report["investigation_id"]
    )
    assert store.stats()["relationships"]["CITES"] == 1


def test_response_excludes_mismatched_source_wording(review):
    record = normalize_review(review, "test", "hash", 1)
    source = {
        "source_record": {"claimReviewed": "A different claim"},
        "factcheck_id": record["factcheck_id"],
    }
    response = EvidenceResponse(RESPONSE_POLICY, {"get_claim_evidence": lambda _: [source]}, [])
    scout = StubScout(record).scout("Submitted claim")
    report = response.run(scout, {"narrative_paths": []})
    assert report["status"] == "INSUFFICIENT_EVIDENCE"
    assert report["citations"] == []
    assert "mismatched reviewed wording" in report["quality"]["warnings"][0]


class StubScout:
    def __init__(self, record, relation="SAME_PROPOSITION"):
        self.record, self.relation = record, relation

    def scout(self, claim):
        candidates = (
            []
            if self.relation is None
            else [
                {
                    "variant_id": self.record["variant_id"],
                    "text": self.record["text"],
                    "assessment": {"relation": self.relation},
                    "similarity": 0.99,
                }
            ]
        )
        matched = candidates if self.relation == "SAME_PROPOSITION" else []
        return {
            "submitted_claim": claim.strip(),
            "matches": matched,
            "context": [] if matched else candidates,
            "rejected": [],
            "handoff_variant_ids": [c["variant_id"] for c in matched],
        }


@pytest.fixture
def case_graph(review):
    if os.getenv("PEHCHAN_INTEGRATION") != "1":
        pytest.skip("requires live FalkorDB")
    store = GraphStore("pehchan_test_" + uuid.uuid4().hex[:12])
    record = normalize_review(review, "test", "test", 1)
    store.init_schema()
    store.ingest([record], [])
    try:
        yield store, record
    finally:
        store.graph.delete()
        store.close()


@pytest.mark.integration
def test_dossier_persistence_links_idempotency_and_review(case_graph):
    store, record = case_graph
    engine = Orchestrator(store, StubScout(record))
    report = engine.investigate("Synthetic query", "request-1")
    assert report["status"] == "EVIDENCE_DOSSIER_READY"
    assert report["citations"][0]["verdict_original"] == record["verdict_original"]
    assert (
        engine.investigate("Synthetic query", "request-1")["investigation_id"]
        == report["investigation_id"]
    )
    assert store.stats()["nodes"]["Investigation"] == 1
    assert store.stats()["relationships"]["CITES"] == 1
    assert store.stats()["relationships"]["EXAMINES"] == 1
    assert {t["agent"] for t in report["agent_trace"]} >= {
        "Claim Scout",
        "Graph Detective",
        "Evidence & Response",
    }
    with pytest.raises(ValueError, match="different"):
        engine.investigate("Different request", "request-1")
    updated = CaseStore(store).update_review(
        report["investigation_id"], "IN_PROGRESS", "Checking sources"
    )
    assert updated["review_state"] == "IN_PROGRESS"
    assert updated["status"] == report["status"]


@pytest.mark.integration
def test_unmatched_case_persists_without_invented_links(case_graph):
    store, record = case_graph
    report = Orchestrator(store, StubScout(record, None)).investigate("Unknown claim")
    assert report["status"] == "INSUFFICIENT_EVIDENCE"
    assert report["reason"] == "NO_RELEVANT_FACT_CHECK_FOUND"
    assert report["citations"] == []
    assert report["graph_findings"]["skipped_reason"]
    assert CaseStore(store).get(report["investigation_id"])["submitted_claim"] == "Unknown claim"
    assert "CITES" not in store.stats()["relationships"]


@pytest.mark.integration
def test_contradiction_and_conflicting_source_ratings_require_review(case_graph, review):
    store, record = case_graph
    contradictory = Orchestrator(store, StubScout(record, "CONTRADICTION")).investigate(
        "Negated claim"
    )
    assert contradictory["status"] == "NEEDS_HUMAN_REVIEW"
    other = copy.deepcopy(review)
    other["url"] = "https://other.example/review"
    other["reviewRating"]["alternateName"] = "Different source rating"
    store.ingest([normalize_review(other, "test", "test", 2)], [])
    conflicting = Orchestrator(store, StubScout(record)).assemble("Synthetic query")
    assert conflicting["status"] == "NEEDS_HUMAN_REVIEW"
    assert conflicting["reason"] == "SOURCE_RATINGS_REQUIRE_RECONCILIATION"


def report_stub(citations=(), context=(), related=(), status="INSUFFICIENT_EVIDENCE"):
    return {
        "status": status,
        "citations": list(citations),
        "scout": {"context": list(context)},
        "widening": {"related": list(related)},
        "uncertainties": [],
        "priority": "NORMAL",
    }


def test_decision_distinguishes_recycled_narrative_and_new_claims():
    direct = {
        "relevance": "SAME_PROPOSITION",
        "publisher": "Checks",
        "reviewed_claim": '"Quoted claim"',
        "verdict_original": "False",
        "review_date": "2024-01-01",
        "url": "https://checks.example/a",
        "factcheck_id": "fc_a",
    }
    recycled = report_stub([direct], status="EVIDENCE_DOSSIER_READY")
    decide(recycled)
    assert recycled["finding"] == "KNOWN_RECYCLED_CLAIM"
    assert recycled["draft_reply"]["cites"] == ["fc_a"]
    assert '""' not in recycled["draft_reply"]["text"]
    assert not recycled["review_queue"]["queued"]

    related = {
        "publisher": "Checks",
        "text": "A related claim",
        "verdict_original": "False",
        "url": "https://checks.example/b",
        "factcheck_id": "fc_b",
        "shared": [{"name": "Bill Gates"}],
    }
    variant = report_stub(related=[related])
    decide(variant)
    assert variant["finding"] == "KNOWN_NARRATIVE_VARIANT"
    assert variant["status"] == "NEEDS_HUMAN_REVIEW"
    assert variant["reason"] == "RELATED_NARRATIVE_CONTEXT_FOUND"
    assert "not confirmed" in variant["draft_reply"]["text"]

    new = report_stub()
    decide(new)
    assert new["finding"] == "NEW_CLAIM"
    assert new["status"] == "INSUFFICIENT_EVIDENCE"
    assert new["review_queue"]["queued"] and new["priority"] == "HIGH"
    assert new["draft_reply"]["cites"] == []


class MemoryScout(StubScout):
    """Stub scout with a fixed embedding so write-back and recall run against FalkorDB."""

    calls = 0

    def scout(self, claim):
        MemoryScout.calls += 1
        return super().scout(claim)

    def embed(self, text):
        return [1.0] + [0.0] * 383


@pytest.mark.integration
def test_written_submission_is_recalled_through_its_matches_edge(case_graph):
    store, record = case_graph
    MemoryScout.calls = 0
    first = Orchestrator(store, MemoryScout(record)).investigate("Synthetic query", "mem-1")
    assert first["finding"] == "KNOWN_RECYCLED_CLAIM"
    stats = store.stats()
    assert stats["nodes"]["Submission"] == 1
    assert stats["relationships"]["MATCHES"] == 1
    assert stats["relationships"]["SUBMITTED"] == 1

    second = Orchestrator(store, MemoryScout(record)).investigate("Synthetic query!", "mem-2")
    assert MemoryScout.calls == 1  # the repeat never reached retrieval/relevance models
    assert second["inference"]["mode"] == "graph_recall"
    assert second["prior_submission"]["investigation_id"] == first["investigation_id"]
    assert second["finding"] == "KNOWN_RECYCLED_CLAIM"
    assert second["citations"][0]["factcheck_id"] == record["factcheck_id"]
    assert store.stats()["nodes"]["Submission"] == 2


@pytest.mark.integration
def test_no_direct_match_widens_through_shared_entities(case_graph, review):
    from pehchan.annotations import load_annotations

    store, _ = case_graph
    other = copy.deepcopy(review)
    other["claimReviewed"] = "Bill Gates hides microchips in vaccines."
    other["url"] = "https://checks.example/review/gates"
    gates = normalize_review(other, "test", "test", 3)
    rows = [
        {
            "variant_id": gates["variant_id"],
            "reviewed_by": "test",
            "rationale": "test",
            "entities": [{"name": "Bill Gates", "type": "Person", "evidence_span": "Bill Gates"}],
        }
    ]
    store.ingest([gates], load_annotations_rows(load_annotations, rows, gates))
    report = Orchestrator(store, MemoryScout(gates, None)).investigate(
        "Bill Gates is funding a secret plot.", "widen-1"
    )
    assert report["finding"] == "KNOWN_NARRATIVE_VARIANT"
    assert report["widening"]["related"][0]["variant_id"] == gates["variant_id"]
    assert report["citations"] == []  # context is never promoted to evidence
    assert any(t.get("tool") == "expand_shared_context" for t in report["agent_trace"])
    assert store.stats()["relationships"]["MENTIONS"] == 2  # claim + written-back submission


def load_annotations_rows(loader, rows, record):
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "annotations.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        return loader(path, [record])
