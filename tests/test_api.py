from fastapi.testclient import TestClient

from pehchan.api import create_app


class FakeService:
    def __init__(self):
        self.calls = []

    def call(self, operation, *args, **kwargs):
        self.calls.append((operation, args))
        if operation == "health":
            return {"status": "ready", "graph": "test", "embeddings": {"total": 2, "ready": 2}}
        if operation == "case":
            return None
        return {"operation": operation}

    def close(self):
        pass


def test_auth_read_write_boundaries_and_invalid_requests():
    service = FakeService()
    app = create_app(service, read_token="test-read", write_token="test-write")
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/status").status_code == 401
        read = {"Authorization": "Bearer test-read"}
        write = {"Authorization": "Bearer test-write"}
        assert client.get("/api/status", headers=read).status_code == 200
        assert (
            client.post("/api/scout", json={"claim": "recorded claim"}, headers=read).status_code
            == 200
        )
        assert (
            client.post("/api/investigations", json={"claim": "test"}, headers=read).status_code
            == 403
        )
        assert client.post("/mcp/", json={}, headers=read).status_code == 403
        assert (
            client.post("/api/investigations", json={"claim": "test"}, headers=write).status_code
            == 200
        )
        assert (
            client.post(
                "/api/investigations", json={"claim": "x" * 4001}, headers=write
            ).status_code
            == 422
        )
        assert client.get("/api/investigations/missing", headers=read).status_code == 404
        assert (
            client.get(
                "/api/status", headers={**write, "Origin": "https://untrusted.example"}
            ).status_code
            == 403
        )
        assert client.get("/health", headers={"Host": "untrusted.example"}).status_code == 400


def test_default_local_access_and_public_host_configuration(monkeypatch):
    import pytest

    service = FakeService()
    with TestClient(create_app(service, read_token="", write_token="")) as client:
        assert client.get("/api/status").status_code == 200
    monkeypatch.setenv("PEHCHAN_PUBLIC_HOSTS", "investigation.example")
    with pytest.raises(RuntimeError, match="distinct"):
        create_app(service, read_token="", write_token="")


def test_mcp_tool_registration_and_annotations():
    import asyncio

    app = create_app(FakeService(), read_token="", write_token="")
    tools = asyncio.run(app.state.mcp.list_tools())
    assert {t.name for t in tools} == {
        "find_similar_claims",
        "get_claim_evidence",
        "explore_narrative_graph",
        "find_evidence_path",
        "assemble_evidence_dossier",
        "create_review_case",
        "investigate_claim",
    }
    for tool in tools:
        assert tool.annotations.readOnlyHint == (
            tool.name not in {"create_review_case", "investigate_claim"}
        )
