"""Constrained specialist workflow with graph-derived decisions and persisted actions.

These are model-assisted and deterministic specialists, not free-form chat agents.
Each specialist has an explicit policy, narrow tool access, and structured handoff.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from .records import normalize_text
from .semantic import ClaimScout


@dataclass(frozen=True)
class AgentPolicy:
    name: str
    instruction: str
    allowed_tools: tuple[str, ...]


SCOUT_POLICY = AgentPolicy(
    "Claim Scout",
    "Retrieve recorded candidates; distinguish equivalence, "
    "contradiction and context. Never infer factual truth from a model score.",
    ("find_similar_claims",),
)
DETECTIVE_POLICY = AgentPolicy(
    "Graph Detective",
    "Follow existing graph edges only. Return paths "
    "with provenance; shared narratives and entities are not evidence of coordination.",
    ("explore_narrative_graph", "find_evidence_path", "breadth_first_search"),
)
RESPONSE_POLICY = AgentPolicy(
    "Evidence & Response",
    "Re-fetch publisher evidence from the graph. "
    "Keep source ratings attached to their original claims, disclose uncertainty and choose a "
    "dossier/review/insufficient-evidence action; never invent sources or assign truth.",
    ("get_claim_evidence",),
)


class Specialist:
    def __init__(self, policy: AgentPolicy, tools: dict, trace: list):
        if set(tools) != set(policy.allowed_tools):
            raise ValueError("Tool capabilities must exactly match specialist policy.")
        self.policy, self.tools, self.trace = policy, tools, trace

    def call(self, name: str, *args):
        if name not in self.policy.allowed_tools:
            raise PermissionError("Tool is outside this specialist's capability set.")
        started = time.perf_counter()
        result = self.tools[name](*args)
        self.trace.append(
            {
                "agent": self.policy.name,
                "tool": name,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "status": "completed",
            }
        )
        return result


class GraphDetective(Specialist):
    def run(self, scout: dict) -> dict:
        ids = scout["handoff_variant_ids"][:3]
        paths, algorithms, connections = [], [], []
        for variant_id in ids:
            for path in self.call("explore_narrative_graph", variant_id):
                paths.append({"from_id": variant_id, **path})
            algorithms.append(
                {"from_id": variant_id, "result": self.call("breadth_first_search", variant_id)}
            )
        if len(ids) >= 2:
            connections = self.call("find_evidence_path", ids[0], ids[1])
        elif paths:
            connections = self.call("find_evidence_path", ids[0], paths[0]["related_id"])
        return {
            "narrative_paths": paths,
            "bfs": algorithms,
            "connection": connections,
            "uncertainty": "Graph context is a recorded or curated connection, not proof of truth or coordination.",
        }


class EvidenceResponse(Specialist):
    def run(self, scout: dict, graph_findings: dict, *, force_review: bool = False) -> dict:
        citations, warnings = [], []
        # Re-read every cited source through this agent's own permitted tool.
        relevant = scout["matches"] + [
            c for c in scout["context"] if c["assessment"]["relation"] == "CONTRADICTION"
        ]
        for candidate in relevant:
            for source in self.call("get_claim_evidence", candidate["variant_id"]):
                if normalize_text(
                    source["source_record"].get("claimReviewed", "")
                ) != normalize_text(candidate["text"]):
                    warnings.append(
                        f"Excluded source with mismatched reviewed wording: {source['factcheck_id']}"
                    )
                    continue
                citations.append(
                    {
                        **source,
                        "variant_id": candidate["variant_id"],
                        "reviewed_claim": candidate["text"],
                        "relevance": candidate["assessment"]["relation"],
                    }
                )
                if not source["review_date"]:
                    warnings.append(f"Review date unavailable: {source['factcheck_id']}")
        direct = [c for c in citations if c["relevance"] == "SAME_PROPOSITION"]
        contradictory = [c for c in citations if c["relevance"] == "CONTRADICTION"]
        ratings = {normalize_text(c["verdict_original"]) for c in direct}
        unsupported_language = any(
            c["assessment"]["relation"] == "UNCERTAIN" for c in scout["context"]
        )
        if force_review:
            status, reason = "NEEDS_HUMAN_REVIEW", "USER_REQUESTED_REVIEW"
        elif direct and len(ratings) == 1 and not contradictory:
            status, reason = "EVIDENCE_DOSSIER_READY", "RELEVANT_PUBLISHED_REVIEWS_FOUND"
        elif direct or contradictory or unsupported_language:
            status, reason = (
                "NEEDS_HUMAN_REVIEW",
                (
                    "SOURCE_RATINGS_REQUIRE_RECONCILIATION"
                    if len(ratings) > 1
                    else "CONTRADICTION_OR_UNCERTAIN_RELEVANCE"
                ),
            )
        else:
            status, reason = "INSUFFICIENT_EVIDENCE", "NO_RELEVANT_FACT_CHECK_FOUND"
        return {
            "submitted_claim": scout["submitted_claim"],
            "status": status,
            "reason": reason,
            "recommended_action": {
                "EVIDENCE_DOSSIER_READY": "Review the assembled source-backed dossier.",
                "NEEDS_HUMAN_REVIEW": "Have a researcher assess relevance and source context.",
                "INSUFFICIENT_EVIDENCE": "Collect additional evidence; no claim verdict is assigned.",
            }[status],
            "citations": citations,
            "quality": {
                "direct_reviews": len(direct),
                "publisher_count": len({c["publisher"] for c in direct}),
                "warnings": sorted(set(warnings)),
            },
            "graph_findings": graph_findings,
            "scout": scout,
            "uncertainties": [
                "The system has not independently verified the articles' contents.",
                "Relevance classifications are model assessments, not factual verdicts.",
                "Original publisher ratings apply to the original reviewed claims.",
                "Narrative annotations are AI-assisted inferences; human review is pending.",
            ],
            "priority": "HIGH" if status == "NEEDS_HUMAN_REVIEW" else "NORMAL",
        }


class CaseStore:
    def __init__(self, store):
        self.store = store

    def get(self, investigation_id: str) -> dict | None:
        rows = self.store.read(
            "MATCH (i:Investigation {id:$id}) RETURN i.report_json,i.review_state,i.review_note",
            {"id": investigation_id},
        )
        if not rows:
            return None
        report = json.loads(rows[0][0])
        report.update(review_state=rows[0][1], review_note=rows[0][2] or "")
        return report

    def list(self, limit: int = 50) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be 1–100")
        rows = self.store.read(
            "MATCH (i:Investigation) RETURN i.id,i.submitted_claim,i.status,i.created_at,"
            "i.review_state,i.priority ORDER BY i.created_at DESC LIMIT $limit",
            {"limit": limit},
        )
        return [
            dict(
                zip(
                    ("id", "submitted_claim", "status", "created_at", "review_state", "priority"), r
                )
            )
            for r in rows
        ]

    def identity(self, request_id: str | None) -> str:
        if request_id is None:
            return "INV-" + uuid.uuid4().hex[:20]
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request_id):
            raise ValueError("request_id must be a simple identifier of 1–128 characters")
        return "INV-" + hashlib.sha256(request_id.encode()).hexdigest()[:24]

    def save(self, report: dict, investigation_id: str) -> dict:
        report = {
            **report,
            "investigation_id": investigation_id,
            "created_at": datetime.now(UTC).isoformat(),
            "review_state": "OPEN",
        }
        variants = sorted({c["variant_id"] for c in report["citations"]})
        sources = sorted({c["factcheck_id"] for c in report["citations"]})
        query = """
        OPTIONAL MATCH (v:ClaimVariant) WHERE v.id IN $variants
        WITH collect(v) AS variants
        OPTIONAL MATCH (fc:FactCheck) WHERE fc.id IN $sources
        WITH variants, collect(fc) AS sources
        WHERE size(variants)=size($variants) AND size(sources)=size($sources)
        MERGE (i:Investigation {id:$id})
        SET i.submitted_claim=$claim, i.status=$status, i.created_at=$created_at,
            i.report_json=$report, i.review_state='OPEN', i.priority=$priority
        FOREACH (v IN variants | MERGE (i)-[:EXAMINES]->(v))
        FOREACH (fc IN sources | MERGE (i)-[:CITES]->(fc))
        RETURN i.id
        """
        rows = self.store.graph.query(
            query,
            {
                "variants": variants,
                "sources": sources,
                "id": investigation_id,
                "claim": report["submitted_claim"],
                "status": report["status"],
                "created_at": report["created_at"],
                "report": json.dumps(report, ensure_ascii=False),
                "priority": report["priority"],
            },
        ).result_set
        if not rows:
            raise RuntimeError("Investigation could not be persisted.")
        return report

    def update_review(self, investigation_id: str, state: str, note: str = "") -> dict:
        if state not in {"OPEN", "IN_PROGRESS", "RESOLVED"} or len(note) > 4000:
            raise ValueError("Invalid review state or note length.")
        rows = self.store.graph.query(
            "MATCH (i:Investigation {id:$id}) SET i.review_state=$state,i.review_note=$note RETURN i.id",
            {"id": investigation_id, "state": state, "note": note},
        ).result_set
        if not rows:
            raise ValueError("Investigation not found.")
        return self.get(investigation_id)


class Orchestrator:
    def __init__(self, store, scout: ClaimScout | None = None, *, inference=None):
        self.store = store
        self.scout = scout or ClaimScout(store)
        self.inference = inference

    def assemble(self, claim: str, *, force_review: bool = False) -> dict:
        if self.inference is not None:
            return self.inference.assemble(self.store, self.scout, claim, force_review=force_review)
        trace = []
        scout_agent = Specialist(SCOUT_POLICY, {"find_similar_claims": self.scout.scout}, trace)
        scout = scout_agent.call("find_similar_claims", claim)
        if scout["handoff_variant_ids"]:
            detective = GraphDetective(
                DETECTIVE_POLICY,
                {
                    "explore_narrative_graph": self.store.narrative_paths,
                    "find_evidence_path": self.store.shortest_path,
                    "breadth_first_search": self.store.bfs,
                },
                trace,
            )
            findings = detective.run(scout)
        else:
            findings = {
                "narrative_paths": [],
                "bfs": [],
                "connection": [],
                "skipped_reason": "NO_CONFIDENT_CANDIDATE_MATCH",
            }
            trace.append(
                {
                    "agent": "Graph Detective",
                    "status": "skipped",
                    "reason": "NO_CONFIDENT_CANDIDATE_MATCH",
                }
            )
        response = EvidenceResponse(
            RESPONSE_POLICY, {"get_claim_evidence": self.store.evidence}, trace
        )
        report = response.run(scout, findings, force_review=force_review)
        if not relevant_trace(trace):
            trace.append(
                {
                    "agent": "Evidence & Response",
                    "status": "completed",
                    "reason": "No directly relevant publisher evidence to retrieve.",
                }
            )
        report["agent_trace"] = trace
        report["inference"] = {"mode": "deterministic"}
        report["specialists"] = [
            asdict(p) for p in (SCOUT_POLICY, DETECTIVE_POLICY, RESPONSE_POLICY)
        ]
        return report

    def investigate(
        self, claim: str, request_id: str | None = None, *, force_review: bool = False
    ) -> dict:
        cases = CaseStore(self.store)
        investigation_id = cases.identity(request_id)
        existing = cases.get(investigation_id)
        if existing:
            if (
                existing["submitted_claim"] != claim.strip()
                or existing.get("force_review", False) != force_review
            ):
                raise ValueError("request_id already belongs to a different investigation request.")
            return existing
        report = self.assemble(claim, force_review=force_review)
        report["force_review"] = force_review
        report["agent_trace"].append(
            {
                "agent": "Orchestrator",
                "tool": "create_review_case",
                "status": "persisted",
                "investigation_id": investigation_id,
            }
        )
        return cases.save(report, investigation_id)


def relevant_trace(trace: list) -> bool:
    return any(t["agent"] == "Evidence & Response" for t in trace)
