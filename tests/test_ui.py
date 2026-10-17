import copy
from pathlib import Path

from streamlit.testing.v1 import AppTest

from pehchan.ui_support import ApiClient, render_graph

APP = Path(__file__).resolve().parents[1] / "src/pehchan/ui.py"
REPORT = {
    "investigation_id": "INV-ui-test",
    "submitted_claim": "Unknown claim",
    "status": "INSUFFICIENT_EVIDENCE",
    "recommended_action": "Collect additional evidence.",
    "quality": {"direct_reviews": 0, "publisher_count": 0, "warnings": []},
    "graph_findings": {"narrative_paths": []},
    "citations": [],
    "scout": {"matches": [], "context": []},
    "uncertainties": ["Truth is undetermined."],
    "agent_trace": [{"agent": "Claim Scout", "status": "completed"}],
    "review_state": "OPEN",
}


def test_claim_form_empty_validation_dossier_and_case_library(monkeypatch):
    saved = []

    def request(self, method, path, **kwargs):
        if path == "/health":
            return {"status": "ready", "claims": 12}
        if path == "/api/investigations" and method == "POST":
            saved.append(copy.deepcopy(REPORT))
            return saved[-1]
        if path == "/api/investigations":
            return [
                {"id": r["investigation_id"], "submitted_claim": r["submitted_claim"]}
                for r in saved
            ]
        if path.startswith("/api/investigations/"):
            if method == "PATCH":
                saved[0]["review_state"] = kwargs["json"]["state"]
            return saved[0]
        raise AssertionError(path)

    monkeypatch.setattr(ApiClient, "request", request)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert not app.exception
    app.button[0].click().run()
    assert "Enter a claim" in app.warning[0].value
    app.text_area[0].set_value("Unknown claim")
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state["report"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert any("Evidence is insufficient" in item.value for item in app.subheader)
    app.sidebar.radio[0].set_value("Dossiers & cases").run()
    assert not app.exception
    assert any("Dossiers & review cases" in item.value for item in app.title)
    app.selectbox[-1].set_value("IN_PROGRESS")
    app.button[-1].click().run()
    assert not app.exception
    assert saved[0]["review_state"] == "IN_PROGRESS"


def test_source_text_cannot_inject_script_into_graph():
    malicious = "</script><script>alert('source')</script>"
    html = render_graph(
        {"nodes": [{"id": "source", "type": "ClaimVariant", "label": malicious}], "edges": []}
    )
    assert malicious not in html
    assert "\\u003c/script\\u003e" in html
