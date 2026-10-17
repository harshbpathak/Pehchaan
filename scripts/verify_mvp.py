"""Live API smoke test: evidence, graph, persisted action, retry, follow-up and no-match branch."""

import json
import os
from pathlib import Path

import httpx


def main():
    token = os.getenv("PEHCHAN_WRITE_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    base = os.getenv("PEHCHAN_API_URL", "http://127.0.0.1:8000")
    report = {"checks": {}}
    with httpx.Client(base_url=base, headers=headers, timeout=180) as client:
        health = client.get("/health")
        health.raise_for_status()
        report["checks"]["ready"] = health.json()["status"] == "ready"
        payload = {
            "claim": "A Rockefeller patent proves that 5G and mRNA vaccines can remotely control human cells.",
            "request_id": "mvp-live-known-v1",
        }
        response = client.post("/api/investigations", json=payload)
        response.raise_for_status()
        known = response.json()
        report["checks"]["source_backed_case"] = bool(known["citations"])
        ready = client.post(
            "/api/investigations",
            json={
                "claim": "Scientists have had to pause the Climate Change Hoax Scam",
                "request_id": "mvp-live-ready-v1",
            },
        )
        ready.raise_for_status()
        ready_report = ready.json()
        report["checks"]["dossier_ready_action"] = (
            ready_report["status"] == "EVIDENCE_DOSSIER_READY"
        )
        report["ready_case"] = {
            "id": ready_report["investigation_id"],
            "status": ready_report["status"],
        }
        repeated = client.post("/api/investigations", json=payload)
        repeated.raise_for_status()
        report["checks"]["idempotency"] = (
            repeated.json()["investigation_id"] == known["investigation_id"]
        )
        loaded = client.get("/api/investigations/" + known["investigation_id"])
        loaded.raise_for_status()
        report["checks"]["persisted_case"] = loaded.json()["submitted_claim"] == payload["claim"]
        unknown = client.post(
            "/api/investigations",
            json={
                "claim": "Underwater quartz clocks transmit encrypted rainfall forecasts.",
                "request_id": "mvp-live-unknown-v1",
            },
        )
        unknown.raise_for_status()
        unresolved = unknown.json()
        report["checks"]["no_match_safety"] = (
            unresolved["status"] == "INSUFFICIENT_EVIDENCE"
            and unresolved["citations"] == []
            and bool(unresolved["graph_findings"].get("skipped_reason"))
        )
        review = client.patch(
            "/api/investigations/" + unresolved["investigation_id"],
            json={"state": "IN_PROGRESS", "note": "Demo follow-up: additional sources required."},
        )
        review.raise_for_status()
        report["checks"]["follow_up_persisted"] = review.json()["review_state"] == "IN_PROGRESS"
        graph = client.get("/api/graph", params={"variant_id": "variant_700ff916add10df61b609425"})
        graph.raise_for_status()
        report["checks"]["graph_connections"] = bool(
            graph.json()["nodes"] and graph.json()["edges"]
        )
        for key, path in (
            ("evidence", "/api/evidence/variant_b798bbbaab3675372ee8c4c3"),
            ("narratives", "/api/narratives/variant_c33c5ad75f0189bd1179dcf3"),
        ):
            response = client.get(path)
            response.raise_for_status()
            report["checks"][key] = bool(response.json())
        report["known_case"] = {"id": known["investigation_id"], "status": known["status"]}
        report["unresolved_case"] = {
            "id": unresolved["investigation_id"],
            "status": unresolved["status"],
        }
    report["ok"] = all(report["checks"].values())
    output = Path("artifacts/mvp-live-verification.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
