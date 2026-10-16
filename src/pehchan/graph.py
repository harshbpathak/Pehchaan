"""FalkorDB is the sole relationship store; there is no in-memory graph fallback."""

from __future__ import annotations

import json
import os
import re
from collections import Counter

from falkordb import FalkorDB
from redis.exceptions import ResponseError

from . import queries
from .records import normalize_text


class GraphStore:
    def __init__(self, graph_name: str | None = None):
        self.graph_name = graph_name or os.getenv("FALKORDB_GRAPH", "pehchan")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", self.graph_name):
            raise ValueError("graph name must be a simple identifier of at most 64 characters")
        self.db = FalkorDB(
            host=os.getenv("FALKORDB_HOST", "127.0.0.1"),
            port=int(os.getenv("FALKORDB_PORT", "16379")),
            password=os.getenv("FALKORDB_PASSWORD") or None,
            username=os.getenv("FALKORDB_USERNAME") or None,
            ssl=os.getenv("FALKORDB_SSL", "false").lower() == "true",
            socket_connect_timeout=5,
            socket_timeout=30,
        )
        self.graph = self.db.select_graph(self.graph_name)

    def close(self):
        self.db.close()

    def read(self, query: str, params: dict | None = None) -> list:
        return self.graph.ro_query(query, params or {}, timeout=10000).result_set

    def init_schema(self):
        for label in queries.LABELS:
            try:
                self.graph.create_node_range_index(label, "id")
            except ResponseError as exc:
                if str(exc) != "Attribute 'id' is already indexed":
                    raise

    def ingest(self, records: list[dict], annotations: list[dict]) -> dict:
        for record in records:
            params = {k: v for k, v in record.items() if isinstance(v, (str, int, float, bool))}
            params.update(
                rating_original_json=json.dumps(record["rating_original"], ensure_ascii=False),
                source_record_json=json.dumps(record["raw"], ensure_ascii=False),
                license_original_json=json.dumps(record["license_original"], ensure_ascii=False),
            )
            self.graph.query(queries.UPSERT_REVIEW, params)
        # Labels and relationship names come exclusively from this fixed allowlist.
        enrichment = {
            "frame": ("NarrativeFrame", "USES_FRAME"),
            "topic": ("Topic", "ABOUT_TOPIC"),
            "entity": ("Entity", "MENTIONS"),
        }
        for item in annotations:
            label, relation = enrichment[item["kind"]]
            query = f"""
            MATCH (c:Claim {{id: $claim_id}})
            MERGE (n:{label} {{id: $id}})
            SET n.name = $name, n.description = $description, n.type = $type
            MERGE (c)-[r:{relation}]->(n)
            SET r.basis = 'curated_inference', r.reviewed_by = $reviewed_by,
                r.rationale = $rationale, r.source_variant_id = $source_variant_id,
                r.evidence_span = $evidence_span
            RETURN n.id
            """
            self.graph.query(query, item)
        return self.stats()

    def stats(self) -> dict:
        return {
            "nodes": dict(self.read("MATCH (n) RETURN labels(n)[0], count(n)")),
            "relationships": dict(self.read("MATCH ()-[r]->() RETURN type(r), count(r)")),
        }

    def evidence(self, variant_id: str) -> list[dict]:
        keys = (
            "factcheck_id",
            "url",
            "verdict_original",
            "review_date",
            "publisher",
            "source",
            "source_sha256",
            "source_record_index",
            "rating_original_json",
            "source_record_json",
        )
        results = [
            dict(zip(keys, row)) for row in self.read(queries.EVIDENCE, {"variant_id": variant_id})
        ]
        for result in results:
            result["rating_original"] = json.loads(result.pop("rating_original_json"))
            result["source_record"] = json.loads(result.pop("source_record_json"))
        return results

    def narrative_paths(self, variant_id: str, limit: int = 20) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        keys = (
            "related_id",
            "related_claim",
            "frame",
            "node_ids",
            "relationships",
            "factcheck_url",
            "verdict_original",
            "publisher",
            "edge_provenance",
            "factcheck_id",
            "publisher_id",
        )
        results = [
            dict(zip(keys, row))
            for row in self.read(
                queries.NARRATIVE_PATHS, {"variant_id": variant_id, "limit": limit}
            )
        ]
        for result in results:
            result["relevance"] = "narrative_context_only"
            result["uncertainty"] = (
                "Shared curated frame does not establish claim equivalence or coordination."
            )
        return results

    def shortest_path(self, from_id: str, to_id: str) -> list:
        return self.read(queries.SHORTEST_PATH, {"from_id": from_id, "to_id": to_id})

    def bfs(self, variant_id: str, depth: int = 3) -> list:
        if not 1 <= depth <= 6:
            raise ValueError("depth must be between 1 and 6")
        return self.read(queries.BFS, {"variant_id": variant_id, "depth": depth})

    def candidates(self, submitted_claim: str, limit: int = 5) -> list[dict]:
        """Transparent lexical baseline, not semantic or factual equivalence detection."""
        if not 1 <= limit <= 20 or not submitted_claim.strip():
            raise ValueError("claim must be nonempty and limit between 1 and 20")
        query = Counter(re.findall(r"\w+", normalize_text(submitted_claim)))
        results = []
        for variant_id, claim_text, normalized in self.read(queries.VARIANTS):
            candidate = Counter(re.findall(r"\w+", normalized))
            denominator = sum((query | candidate).values())
            score = sum((query & candidate).values()) / denominator if denominator else 0
            if score:
                results.append(
                    {
                        "variant_id": variant_id,
                        "text": claim_text,
                        "score": round(score, 6),
                        "method": "token_jaccard_baseline",
                        "relevance": "unverified_candidate",
                    }
                )
        return sorted(results, key=lambda r: (-r["score"], r["variant_id"]))[:limit]

    def validate(self, records: list[dict], *, require_narrative: bool = False) -> dict:
        failures = []
        for record in records:
            evidence = self.evidence(record["variant_id"])
            if not any(
                e["factcheck_id"] == record["factcheck_id"]
                and e["url"] == record["url"]
                and e["verdict_original"] == record["verdict_original"]
                and e["source_record"] == record["raw"]
                and e["rating_original"] == record["rating_original"]
                and e["source_sha256"] == record["source_sha256"]
                and e["source_record_index"] == record["source_record_index"]
                for e in evidence
            ):
                failures.append(f"missing or changed evidence: {record['factcheck_id']}")
        # Single-writer ingestion is intentional; also detect corruption or duplicate IDs.
        duplicates = self.read(
            "MATCH (n) WITH labels(n)[0] AS label, n.id AS id, count(n) AS total "
            "WHERE total > 1 RETURN label, id, total"
        )
        if duplicates:
            failures.append(f"duplicate node IDs: {duplicates}")
        orphaned = self.read(
            "MATCH (fc:FactCheck) WHERE NOT (fc)-[:CHECKS]->(:ClaimVariant) "
            "OR NOT (fc)-[:PUBLISHED_BY]->(:Publisher) RETURN fc.id"
        )
        if orphaned:
            failures.append(f"orphaned fact-checks: {orphaned}")
        invalid_variants = self.read(
            "MATCH (v:ClaimVariant) OPTIONAL MATCH (v)-[:EXPRESSES]->(c:Claim) "
            "WITH v, count(c) AS total WHERE total <> 1 RETURN v.id, total"
        )
        if invalid_variants:
            failures.append(
                f"variants must express exactly one canonical claim: {invalid_variants}"
            )
        first = records[0]["variant_id"]
        algorithm = self.bfs(first)
        if not algorithm or not algorithm[0][0]:
            failures.append("BFS returned no reachable nodes")
        example = None
        for record in records:
            paths = self.narrative_paths(record["variant_id"], limit=1)
            if paths:
                example = {"from_id": record["variant_id"], **paths[0]}
                break
        if require_narrative and example is None:
            failures.append("no multi-hop narrative evidence path found")
        if example:
            shortest = self.shortest_path(example["from_id"], example["related_id"])
            if not shortest:
                failures.append("bounded shortest path could not reproduce a connected pair")
        else:
            shortest = []
        return {
            "ok": not failures,
            "graph": self.graph_name,
            "checked_records": len(records),
            "failures": failures,
            "stats": self.stats(),
            "bfs_example": algorithm,
            "narrative_path_example": example,
            "shortest_path_example": shortest,
        }
