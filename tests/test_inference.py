import json
from types import SimpleNamespace

import httpx
import pytest

from pehchan.inference import (
    GeminiInference,
    GeminiProvider,
    OpenRouterProvider,
    ProviderChain,
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
        parts = next(self.turns, None)
        if parts is None:
            raise RuntimeError("Scripted provider has no more turns.")
        return {"role": "model", "parts": parts}


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
        [call("find_similar_claims")],
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
    store, agent, counts = setup
    provider = ScriptedProvider([call("find_similar_claims")], [final])
    with pytest.raises(RuntimeError):
        GeminiInference(provider).assemble(store, agent, "Original claim")
    # Out-of-scope calls are refused back to the model; nothing is read for them.
    assert counts["evidence"] == 0
    last = provider.histories[-1][-1]["parts"][0]["functionResponse"]["response"]["result"]
    assert "error" in last


def test_fabricated_citation_is_dropped_and_disclosed(setup):
    provider = successful_provider()
    provider.turns = iter(
        [
            [call("find_similar_claims")],
            [
                call("get_claim_evidence", variant_id="v1"),
                call("explore_narrative_graph", variant_id="v1"),
            ],
            [call("finish_investigation", analyst_note="Done", factcheck_ids=["fabricated"])],
        ]
    )
    report = GeminiInference(provider).assemble(*setup[:2], "Original claim")
    assert report["inference"]["factcheck_ids"] == []
    assert report["inference"]["dropped_references"] == ["fabricated"]
    assert "fabricated" not in {c["factcheck_id"] for c in report["citations"]}
    assert any("dropped" in w for w in report["quality"]["warnings"])


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
        [call("find_similar_claims")],
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
            [call("find_similar_claims")],
            *[[call("breadth_first_search", variant_id="v1")]] * 7,
        ),
    ):
        with pytest.raises(RuntimeError, match="budget"):
            GeminiInference(provider).assemble(store, agent, "Original claim")


def test_missing_key_and_explicit_baseline(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
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
        assert str(request.url).endswith("/gemma-4-31b-it:generateContent")
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
                            "parts": [call("find_similar_claims")],
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


def test_auto_chains_free_ai_studio_before_openrouter(monkeypatch):
    for name in ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "PEHCHAN_INFERENCE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    config = configuration()
    assert (config["mode"], config["provider"], config["model"]) == (
        "gemini",
        "google_ai_studio",
        "gemma-4-31b-it",
    )
    assert [c["provider"] for c in config["chain"]] == ["google_ai_studio", "openrouter"]
    chain = configured_inference().provider
    assert isinstance(chain, ProviderChain)
    monkeypatch.delenv("GEMINI_API_KEY")
    assert isinstance(configured_inference().provider, OpenRouterProvider)
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("PEHCHAN_INFERENCE", "openrouter")
    assert not configuration()["configured"]
    with pytest.raises(RuntimeError, match="requires OPENROUTER_API_KEY"):
        OpenRouterProvider().generate([])


def test_chain_hands_over_after_failure_and_records_it():
    class Failing:
        mode, provider_name, model = "gemini", "google_ai_studio", "free-model"

        def generate(self, contents):
            raise RuntimeError("HTTP 429")

    class Working(Failing):
        mode, provider_name, model = "openrouter", "openrouter", "paid-model"
        calls = 0

        def generate(self, contents):
            Working.calls += 1
            return {"role": "model", "parts": []}

    chain = ProviderChain([Failing(), Working()])
    assert chain.generate([]) == {"role": "model", "parts": []}
    assert chain.generate([]) == {"role": "model", "parts": []}
    assert Working.calls == 2 and chain.provider_name == "openrouter"
    assert chain.failures == ["google_ai_studio (free-model): HTTP 429"]
    with pytest.raises(RuntimeError, match="All hosted providers failed"):
        ProviderChain([Failing()]).generate([])


def test_openrouter_translates_tools_both_ways_without_leaking_key():
    seen = []

    def handle(request):
        assert request.headers["authorization"] == "Bearer or-secret"
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_claim_evidence",
                                        "arguments": json.dumps({"variant_id": "v1"}),
                                    },
                                }
                            ],
                        },
                    }
                ]
            },
        )

    provider = OpenRouterProvider(key="or-secret", transport=httpx.MockTransport(handle))
    history = [
        {"role": "user", "parts": [{"text": '{"submitted_claim": "x"}'}]},
        {"role": "model", "parts": [call("find_similar_claims")]},
        {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": "find_similar_claims",
                        "id": "find_similar_claims-id",
                        "response": {"result": {"matches": []}},
                    }
                }
            ],
        },
    ]
    content = provider.generate(history)
    assert content == {
        "role": "model",
        "parts": [
            {
                "functionCall": {
                    "id": "call_1",
                    "name": "get_claim_evidence",
                    "args": {"variant_id": "v1"},
                }
            }
        ],
    }
    body = seen[0]
    assert body["model"] == "openai/gpt-oss-120b" and body["tool_choice"] == "required"
    assert len(body["tools"]) == 6
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert body["messages"][2]["tool_calls"][0]["id"] == "find_similar_claims-id"
    assert body["messages"][3]["tool_call_id"] == "find_similar_claims-id"
    for response in (
        httpx.Response(402, text="or-secret"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {}}]}),
    ):
        provider.transport = httpx.MockTransport(lambda request, response=response: response)
        with pytest.raises(RuntimeError) as error:
            provider.generate([])
        assert "or-secret" not in str(error.value)
