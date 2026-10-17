import json
from types import SimpleNamespace

import httpx
import pytest

from pehchan.inference import (
    GeminiInference,
    GeminiProvider,
    configuration,
    configured_inference,
)
from pehchan.investigation import Orchestrator


def call(name, **args):
    return {"functionCall": {"name": name, "args": args, "id": name + "-id"}}


class ScriptedProvider:
    model = "scripted-test-model"

    def __init__(self, *turns):
        self.turns = iter(turns)
        self.histories = []

    def generate(self, contents):
        self.histories.append(json.loads(json.dumps(contents)))
        return {"role": "model", "parts": next(self.turns)}


@pytest.fixture
def setup():
    candidate = {
        "variant_id": "v1",
        "text": "Original claim",
        "assessment": {"relation": "SAME_PROPOSITION"},
    }
    source = {
        "factcheck_id": "fc1",
        "url": "https://publisher.example/review",
        "verdict_original": "False",
        "review_date": "2026-01-01",
        "publisher": "Publisher",
        "source_record": {"claimReviewed": "Original claim"},
        "source_sha256": "hash",
    }
    scout = {
        "submitted_claim": "Original claim",
        "matches": [candidate],
        "context": [],
        "handoff_variant_ids": ["v1"],
    }
    counts = {"evidence": 0}

    def evidence(variant_id):
        assert variant_id == "v1"
        counts["evidence"] += 1
        return [source]

    store = SimpleNamespace(
        evidence=evidence,
        narrative_paths=lambda _: [],
        bfs=lambda _: [],
        shortest_path=lambda a, b: [],
    )
    agent = SimpleNamespace(scout=lambda claim: scout)
    return store, agent, counts


def successful_provider():
    return ScriptedProvider(
        [call("find_similar_claims", claim="Original claim")],
        [
            call("get_claim_evidence", variant_id="v1"),
            call("explore_narrative_graph", variant_id="v1"),
        ],
        [
            call(
                "finish_investigation",
                analyst_note="A publisher review was retrieved; check its context.",
                factcheck_ids=["fc1"],
            )
        ],
    )


def test_real_tool_dispatch_preserves_sources_and_authoritative_decision(setup):
    store, agent, counts = setup
    provider = successful_provider()
    result = Orchestrator(store, agent, inference=GeminiInference(provider)).assemble(
        "Original claim", force_review=True
    )
    assert counts["evidence"] == 1
    assert result["status"] == "NEEDS_HUMAN_REVIEW"
    assert result["citations"][0]["verdict_original"] == "False"
    assert result["citations"][0]["url"] == "https://publisher.example/review"
    assert result["inference"]["tool_calls"] == 4
    history = provider.histories[-1]
    assert history[1]["parts"][0]["functionCall"]["id"] == "find_similar_claims-id"
    assert history[2]["parts"][0]["functionResponse"]["id"] == "find_similar_claims-id"
    assert "source_record" not in json.dumps(history)
    assert result["citations"][0]["source_record"]  # retained locally


@pytest.mark.parametrize(
    "bad_call",
    [
        call("delete_graph"),
        call("find_similar_claims", claim="Rewritten claim"),
        call("get_claim_evidence", variant_id="invented"),
        call("find_similar_claims", claim="Original claim", extra=True),
        call("find_similar_claims", claim=42),
    ],
)
def test_forbidden_or_malformed_first_call_fails_closed(setup, bad_call):
    store, agent, counts = setup
    with pytest.raises(RuntimeError):
        GeminiInference(ScriptedProvider([bad_call])).assemble(store, agent, "Original claim")
    assert counts["evidence"] == 0


@pytest.mark.parametrize(
    "final",
    [
        call("get_claim_evidence", variant_id="invented"),
        call("find_evidence_path", from_id="v1", to_id="invented"),
        call("explore_narrative_graph", variant_id="invented"),
        call("finish_investigation", analyst_note="Done", factcheck_ids=[]),
    ],
)
def test_unknown_ids_and_incomplete_retrieval_are_rejected(setup, final):
    store, agent, _ = setup
    provider = ScriptedProvider([call("find_similar_claims", claim="Original claim")], [final])
    with pytest.raises(RuntimeError):
        GeminiInference(provider).assemble(store, agent, "Original claim")


def test_fabricated_citation_is_rejected(setup):
    provider = successful_provider()
    provider.turns = iter(
        [
            [call("find_similar_claims", claim="Original claim")],
            [
                call("get_claim_evidence", variant_id="v1"),
                call("explore_narrative_graph", variant_id="v1"),
            ],
            [call("finish_investigation", analyst_note="Done", factcheck_ids=["fabricated"])],
        ]
    )
    with pytest.raises(RuntimeError, match="unsupported evidence"):
        GeminiInference(provider).assemble(*setup[:2], "Original claim")


def test_no_match_can_finish_without_fabricating_sources():
    scout = SimpleNamespace(
        scout=lambda claim: {
            "submitted_claim": claim,
            "matches": [],
            "context": [],
            "handoff_variant_ids": [],
        }
    )
    provider = ScriptedProvider(
        [call("find_similar_claims", claim="Unknown")],
        [call("finish_investigation", analyst_note="No recorded match.", factcheck_ids=[])],
    )
    report = GeminiInference(provider).assemble(SimpleNamespace(), scout, "Unknown")
    assert report["status"] == "INSUFFICIENT_EVIDENCE"
    assert not report["citations"]


def test_turn_budget_exhaustion_and_plain_text_fail(setup):
    store, agent, _ = setup
    for provider in (
        ScriptedProvider([{"text": "Trust me, it is true"}]),
        ScriptedProvider(
            [call("find_similar_claims", claim="Original claim")],
            *[[call("breadth_first_search", variant_id="v1")]] * 7,
        ),
    ):
        with pytest.raises(RuntimeError, match="budget"):
            GeminiInference(provider).assemble(store, agent, "Original claim")


def test_missing_key_and_explicit_baseline(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("PEHCHAN_INFERENCE", raising=False)
    assert configuration()["requested"] == "auto"
    assert configuration()["mode"] == "deterministic"
    assert configuration()["configured"]
    assert configured_inference() is None
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert configuration()["mode"] == "gemini"
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setenv("PEHCHAN_INFERENCE", "gemini")
    assert configuration()["mode"] == "gemini"
    assert not configuration()["configured"]
    with pytest.raises(RuntimeError, match="requires GEMINI_API_KEY"):
        GeminiProvider().generate([])
    monkeypatch.setenv("PEHCHAN_INFERENCE", "deterministic")
    assert configured_inference() is None
    monkeypatch.setenv("PEHCHAN_INFERENCE", "unknown")
    with pytest.raises(RuntimeError):
        configuration()


def test_rest_protocol_and_secret_safe_errors():
    seen = []

    def handle(request):
        assert request.headers["x-goog-api-key"] == "test-secret"
        assert str(request.url).endswith("/gemma-4-26b-a4b-it:generateContent")
        assert "test-secret" not in str(request.url)
        body = json.loads(request.content)
        assert body["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"
        assert len(body["tools"][0]["functionDeclarations"]) == 6
        seen.append(body)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "role": "model",
                            "parts": [call("find_similar_claims", claim="Original claim")],
                        },
                    }
                ]
            },
        )

    provider = GeminiProvider(key="test-secret", transport=httpx.MockTransport(handle))
    assert provider.generate([])["parts"][0]["functionCall"]["name"] == "find_similar_claims"
    assert seen
    for response in (
        httpx.Response(429, text="test-secret"),
        httpx.Response(200, json={"candidates": []}),
        httpx.Response(200, json={"candidates": [{"finishReason": "MAX_TOKENS"}]}),
    ):
        provider.transport = httpx.MockTransport(lambda request, response=response: response)
        with pytest.raises(RuntimeError) as error:
            provider.generate([])
        assert "test-secret" not in str(error.value)
