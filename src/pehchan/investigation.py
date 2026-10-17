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

from . import queries
from .models import EMBED_MODEL, EMBED_REVISION
from .records import normalize_text, stable_id
from .rules import tag
from .semantic import ClaimScout, SubmissionIndex

# Cosine similarity at which a new submission is treated as the same forward as an earlier one.
RECALL_SIMILARITY = 0.95
# Semantic context strong enough to call a submission a variant of a known narrative.
NARRATIVE_CONTEXT_SIMILARITY = 0.6
# Minimum widening score (sum of 1/degree of shared nodes). 0.05 means a hit must share at
# least one node used by 20 or fewer claims; hubs such as "5G" alone do not qualify.
MIN_SHARED_CONTEXT_SCORE = 0.05


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
    "with provenance; shared narratives and entities are not evidence of coordination. "
    "With no direct match, widen through entities and frames shared with the submission.",
    (
        "explore_narrative_graph",
        "find_evidence_path",
        "breadth_first_search",
        "expand_shared_context",
    ),
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

    def widen(self, claim: str, exclude: list[str]) -> dict:
        tags = tag(claim)
        reached = self.call(
            "expand_shared_context",
            [e["name"] for e in tags["entities"]],
            tags["frames"],
            exclude,
        )
        related = [r for r in reached if r["score"] >= MIN_SHARED_CONTEXT_SCORE]
        self.trace[-1]["reason"] = (
            f"No direct match; widened through {len(tags['entities'])} entities and "
            f"{len(tags['frames'])} frames tagged in the submission, reaching {len(reached)} "
            f"fact-checked claims; kept {len(related)} not connected only through hub nodes."
        )
        return {
            "submission_tags": tags,
            "related": related,
            "uncertainty": "Shared frames/entities are rule-based inferences; related reviews "
            "concern different claims and are context, not evidence for this submission.",
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
            "i.review_state,i.priority,i.finding ORDER BY i.created_at DESC LIMIT $limit",
            {"limit": limit},
        )
        return [
            dict(
                zip(
                    (
                        "id",
                        "submitted_claim",
                        "status",
                        "created_at",
                        "review_state",
                        "priority",
                        "finding",
                    ),
                    r,
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

    def save(self, report: dict, investigation_id: str, vector: list | None = None) -> dict:
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
            i.report_json=$report, i.review_state='OPEN', i.priority=$priority,
            i.finding=$finding
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
                "finding": report.get("finding"),
            },
        ).result_set
        if not rows:
            raise RuntimeError("Investigation could not be persisted.")
        if vector is not None:
            self.link_submission(report, investigation_id, vector)
        return report

    def link_submission(self, report: dict, investigation_id: str, vector: list) -> None:
        """Write the submitted wording back into the graph with the links the agent established."""
        SubmissionIndex(self.store).ensure()
        claim = report["submitted_claim"]
        submission_id = stable_id("submission", normalize_text(claim))
        matches = [
            {
                "variant_id": m["variant_id"],
                "relation": m["assessment"]["relation"],
                "similarity": m["similarity"],
                "assessment_json": json.dumps(m["assessment"], ensure_ascii=False),
            }
            for m in report["scout"]["matches"]
        ]
        self.store.graph.query(
            queries.LINK_SUBMISSION,
            {
                "investigation_id": investigation_id,
                "id": submission_id,
                "text": claim,
                "normalized_text": normalize_text(claim),
                "vector": vector,
                "model": EMBED_MODEL,
                "revision": EMBED_REVISION,
                "created_at": report["created_at"],
                "matches": matches,
            },
        )
        items = submission_context(claim)
        if items:
            self.store.graph.query(
                queries.LINK_SUBMISSION_CONTEXT, {"id": submission_id, "items": items}
            )

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
        return self._assemble(claim, force_review=force_review)[0]

    def _assemble(self, claim: str, *, force_review: bool = False) -> tuple[dict, dict | None]:
        claim = claim.strip()
        trace: list = []
        memory = self._recall(claim, trace)
        prior = memory["prior"] if memory else None
        if prior and prior["reusable"] and not force_review:
            report = self._specialists(self._recalled_scout(claim, prior), trace, force_review)
            report["inference"] = {"mode": "graph_recall"}
        elif self.inference is not None:
            report = self.inference.assemble(
                self.store, self.scout, claim, force_review=force_review
            )
            trace = trace + report.get("agent_trace", [])
        else:
            scout_agent = Specialist(SCOUT_POLICY, {"find_similar_claims": self.scout.scout}, trace)
            scout = scout_agent.call("find_similar_claims", claim)
            report = self._specialists(scout, trace, force_review)
            report["inference"] = {"mode": "deterministic"}
        report["widening"] = self._widen(report, trace)
        report["prior_submission"] = prior
        decide(report, force_review=force_review)
        report["agent_trace"] = trace
        report["specialists"] = [
            asdict(p) for p in (SCOUT_POLICY, DETECTIVE_POLICY, RESPONSE_POLICY)
        ]
        return report, memory

    def _detective(self, trace: list) -> GraphDetective:
        return GraphDetective(
            DETECTIVE_POLICY,
            {
                "explore_narrative_graph": self.store.narrative_paths,
                "find_evidence_path": self.store.shortest_path,
                "breadth_first_search": self.store.bfs,
                "expand_shared_context": self.store.shared_context,
            },
            trace,
        )

    def _specialists(self, scout: dict, trace: list, force_review: bool) -> dict:
        if scout["handoff_variant_ids"]:
            findings = self._detective(trace).run(scout)
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
        return report

    def _widen(self, report: dict, trace: list) -> dict | None:
        if any(c["relevance"] == "SAME_PROPOSITION" for c in report["citations"]):
            return None
        exclude = sorted({c["variant_id"] for c in report["citations"]})
        return self._detective(trace).widen(report["submitted_claim"], exclude)

    def _recall(self, claim: str, trace: list) -> dict | None:
        """Look the wording up among earlier submissions through the Submission vector index."""
        if not hasattr(self.scout, "embed"):
            return None
        started = time.perf_counter()
        vector = self.scout.embed(claim)
        hits = SubmissionIndex(self.store).recall(vector, 1)
        prior = None
        if hits and hits[0]["similarity"] >= RECALL_SIMILARITY:
            prior = hits[0]
            prior["reusable"] = any(m["relation"] == "SAME_PROPOSITION" for m in prior["matches"])
        entry = {
            "agent": "Orchestrator",
            "tool": "recall_prior_submission",
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "status": "completed",
        }
        if prior and prior["reusable"]:
            entry["reason"] = (
                f"Near-identical wording (similarity {prior['similarity']:.3f}) was investigated "
                f"in {prior['investigation_id']}; following its MATCHES edges instead of rerunning "
                "retrieval and relevance models."
            )
        elif prior:
            entry["reason"] = (
                f"Seen before in {prior['investigation_id']} ({prior['finding']}) without a "
                "direct match; running a full investigation."
            )
        else:
            entry["reason"] = "No earlier submission of this wording."
        trace.append(entry)
        return {"vector": vector, "prior": prior}

    def _recalled_scout(self, claim: str, prior: dict) -> dict:
        matches = []
        for link in prior["matches"]:
            if link["relation"] != "SAME_PROPOSITION":
                continue
            matches.append(
                {
                    "variant_id": link["variant_id"],
                    "text": link["text"],
                    "similarity": link["similarity"],
                    "assessment": json.loads(link["assessment_json"]),
                    "direct_match": True,
                    "recalled_via": f"Submission {prior['submission_id']} -[:MATCHES]->",
                    "evidence": self.store.evidence(link["variant_id"]),
                }
            )
        return {
            "submitted_claim": claim,
            "language": {"code": "recalled", "score": 1.0},
            "matches": matches,
            "context": [],
            "rejected": [],
            "handoff_variant_ids": [m["variant_id"] for m in matches],
            "outcome": "RECALLED_FROM_PRIOR_SUBMISSION",
            "models": {"embedding": EMBED_MODEL, "embedding_revision": EMBED_REVISION},
            "uncertainty": "Relevance was assessed for the earlier, near-identical submission "
            "and reused through its MATCHES edges.",
        }

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
        report, memory = self._assemble(claim, force_review=force_review)
        report["force_review"] = force_review
        report["agent_trace"].append(
            {
                "agent": "Orchestrator",
                "tool": "create_review_case",
                "status": "persisted",
                "investigation_id": investigation_id,
            }
        )
        if memory:
            report["agent_trace"].append(
                {
                    "agent": "Orchestrator",
                    "tool": "link_submission",
                    "status": "persisted",
                    "reason": "Submission node linked to the investigation, its direct matches "
                    "(MATCHES) and its tagged entities/frames, so a repeat forward is recalled "
                    "through these edges.",
                }
            )
        return cases.save(report, investigation_id, memory["vector"] if memory else None)


def decide(report: dict, *, force_review: bool = False) -> None:
    """Classify the finding, adjust the action for narrative context and draft a cited reply."""
    direct = [c for c in report["citations"] if c["relevance"] == "SAME_PROPOSITION"]
    related = (report.get("widening") or {}).get("related", [])
    strong_context = [
        c
        for c in report["scout"]["context"]
        if c.get("similarity", 0) >= NARRATIVE_CONTEXT_SIMILARITY
    ]
    if direct:
        finding = "KNOWN_RECYCLED_CLAIM"
    elif related or strong_context:
        finding = "KNOWN_NARRATIVE_VARIANT"
    else:
        finding = "NEW_CLAIM"
    if (
        finding == "KNOWN_NARRATIVE_VARIANT"
        and report["status"] == "INSUFFICIENT_EVIDENCE"
        and not force_review
    ):
        report.update(
            status="NEEDS_HUMAN_REVIEW",
            reason="RELATED_NARRATIVE_CONTEXT_FOUND",
            recommended_action="Have a researcher compare this claim with the related reviewed "
            "claims; no review of this exact claim was found.",
        )
    queued = finding == "NEW_CLAIM" or report["status"] == "NEEDS_HUMAN_REVIEW"
    if queued:
        report["priority"] = "HIGH"
    report["finding"] = finding
    report["review_queue"] = {
        "queued": queued,
        "reason": {
            "KNOWN_RECYCLED_CLAIM": "Published reviews exist; approve the drafted reply.",
            "KNOWN_NARRATIVE_VARIANT": "Related narrative reviewed; this wording needs a checker.",
            "NEW_CLAIM": "No recorded review or narrative match; send to a fact-checker.",
        }[finding],
    }
    report["draft_reply"] = draft_reply(finding, direct, strong_context, related, force_review)
    report["uncertainties"] = report["uncertainties"] + [
        "The drafted reply is a template filled only from graph records and needs approval."
    ]


def draft_reply(finding: str, direct: list, close: list, related: list, force_review: bool) -> dict:
    lines, cites = [], []
    if finding == "KNOWN_RECYCLED_CLAIM":
        lines.append("This claim has already been reviewed by fact-checkers:")
        for c in direct[:3]:
            date = f", {c['review_date']}" if c.get("review_date") else ""
            lines.append(
                f'- {c["publisher"]} rated "{unquote(c["reviewed_claim"])}" as "{c["verdict_original"]}"'
                f"{date}: {c['url']}"
            )
            cites.append(c["factcheck_id"])
        lines.append("Ratings belong to the publishers and apply to the wording they reviewed.")
    elif finding == "KNOWN_NARRATIVE_VARIANT" and (close or related):
        lines.append(
            "We have not confirmed a fact-check of this exact claim. Fact-checkers have reviewed "
            "closely related claims:"
        )
        for c in close[:3]:
            for source in c.get("evidence", [])[:1]:
                lines.append(
                    f'- {source["publisher"]} rated "{unquote(c["text"])}" as '
                    f'"{source["verdict_original"]}" (closest recorded wording, similarity '
                    f"{c['similarity']:.2f}; {c['assessment']['relation'].lower()} relevance): "
                    f"{source['url']}"
                )
                cites.append(source["factcheck_id"])
        for r in related[: max(0, 3 - len(cites))]:
            shared = ", ".join(sorted({s["name"] for s in r["shared"]}))
            lines.append(
                f'- {r["publisher"]} rated "{unquote(r["text"])}" as "{r["verdict_original"]}" '
                f"(shares: {shared}): {r['url']}"
            )
            cites.append(r["factcheck_id"])
        lines.append(
            "These reviews may concern different wordings; their relevance to this one is not "
            "confirmed. A researcher is checking it."
        )
    elif finding == "KNOWN_NARRATIVE_VARIANT":
        lines.append(
            "We have not found a fact-check of this exact claim, but similar recorded claims "
            "exist. A researcher is comparing them before any reply is sent."
        )
    else:
        lines.append(
            "We could not find a published fact-check for this claim. It has been queued for "
            "review by a fact-checker."
        )
    if force_review:
        lines.append("A human review was explicitly requested.")
    return {"text": "\n".join(lines), "cites": cites, "status": "DRAFT_REQUIRES_HUMAN_APPROVAL"}


def unquote(text: str) -> str:
    return text.strip().strip('"“”')


def submission_context(claim: str) -> list[dict]:
    tags = tag(claim)
    items = [
        {
            "node_id": stable_id("entity", normalize_text(e["name"]), normalize_text(e["type"])),
            "evidence_span": e["evidence_span"],
        }
        for e in tags["entities"]
    ]
    items += [
        {"node_id": stable_id("frame", normalize_text(f)), "evidence_span": ""}
        for f in tags["frames"]
    ]
    return items


def relevant_trace(trace: list) -> bool:
    return any(t["agent"] == "Evidence & Response" for t in trace)
