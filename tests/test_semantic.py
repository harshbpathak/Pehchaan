import math
import os
import uuid

import pytest

from pehchan.graph import GraphStore
from pehchan.models import DIMENSION
from pehchan.records import normalize_review
from pehchan.semantic import ClaimScout, VectorIndex, classify, valid_vector


def probabilities(entailment=0.01, contradiction=0.01):
    return {
        "entailment": entailment,
        "contradiction": contradiction,
        "neutral": 1 - entailment - contradiction,
    }


@pytest.mark.parametrize(
    "forward,reverse,similarity,expected",
    [
        (probabilities(0.95), probabilities(0.94), 0.9, "SAME_PROPOSITION"),
        (
            probabilities(contradiction=0.95),
            probabilities(contradiction=0.94),
            0.95,
            "CONTRADICTION",
        ),
        (probabilities(0.95), probabilities(), 0.9, "RELATED_CONTEXT"),
        (probabilities(contradiction=0.95), probabilities(), 0.9, "UNCERTAIN"),
        (probabilities(), probabilities(), 0.7, "RELATED_CONTEXT"),
        (probabilities(), probabilities(), 0.3, "IRRELEVANT"),
    ],
)
def test_relevance_requires_two_directions(forward, reverse, similarity, expected):
    assert classify(forward, reverse, similarity).relation == expected


@pytest.mark.parametrize(
    "vector", [[0.0] * DIMENSION, [1.0] * 3, [math.nan] * DIMENSION, [True] * DIMENSION]
)
def test_reject_invalid_vectors(vector):
    with pytest.raises(ValueError):
        valid_vector(vector)


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("PEHCHAN_INTEGRATION") != "1", reason="requires live FalkorDB")
def test_vector_distance_incremental_updates_and_staleness(review):
    store = GraphStore("pehchan_test_" + uuid.uuid4().hex[:12])

    class Encoder:
        calls = 0

        def encode(self, texts):
            self.calls += 1
            return [[1.0] + [0.0] * (DIMENSION - 1) for _ in texts]

    try:
        store.init_schema()
        record = normalize_review(review, "test", "hash", 1)
        store.ingest([record], [])
        encoder = Encoder()
        index = VectorIndex(store)
        assert index.build(encoder)["written"] == 1
        assert index.build(encoder)["written"] == 0
        assert encoder.calls == 1
        result = index.search([1.0] + [0.0] * (DIMENSION - 1))[0]
        assert result["cosine_distance"] == pytest.approx(0, abs=1e-6)
        assert result["similarity"] == pytest.approx(1)
        assert result["variant_id"] == record["variant_id"]
        store.graph.query("MATCH (v:ClaimVariant) SET v.text='changed text'")
        with pytest.raises(RuntimeError, match="stale"):
            index.search([1.0] + [0.0] * (DIMENSION - 1))
    finally:
        store.graph.delete()
        store.close()


def test_scout_abstains_for_non_english(monkeypatch):
    pytest.importorskip("langdetect")

    class Encoder:
        def encode(self, texts):
            return [[1.0] * DIMENSION for _ in texts]

    class Store:
        def evidence(self, variant_id):
            return [{"url": "https://checks.example/source", "verdict_original": "source rating"}]

    monkeypatch.setattr(
        VectorIndex,
        "search",
        lambda *args: [
            {"variant_id": "test", "text": "5G technology spreads coronavirus.", "similarity": 0.99}
        ],
    )
    report = ClaimScout(Store(), Encoder()).scout("टीकों में लोगों को ट्रैक करने वाली माइक्रोचिप होती है।")
    assert report["matches"] == []
    assert report["context"][0]["assessment"]["relation"] == "UNCERTAIN"
    assert report["outcome"] == "NO_CONFIDENT_MATCH"
