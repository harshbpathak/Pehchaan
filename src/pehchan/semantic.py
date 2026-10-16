"""Graph-backed vector retrieval, conservative relevance assessment and typed handoffs."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, field

from .models import DIMENSION, EMBED_MODEL, EMBED_REVISION, NLI_MODEL, NLI_REVISION

VECTOR_SEARCH = """
CALL db.idx.vector.queryNodes('ClaimVariant', 'embedding', $limit, vecf32($vector))
YIELD node, score
RETURN node.id, node.text, score, node.embedding_model, node.embedding_revision,
       node.embedding_text_sha256
ORDER BY score ASC, node.id
"""


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def valid_vector(vector: list[float]) -> list[float]:
    if len(vector) != DIMENSION or any(isinstance(x, bool) or not math.isfinite(x) for x in vector):
        raise ValueError(f"Vector must contain {DIMENSION} finite numbers.")
    norm = math.sqrt(sum(x * x for x in vector))
    if norm < 1e-12:
        raise ValueError("Zero embedding vectors are invalid.")
    return [float(x / norm) for x in vector]


class VectorIndex:
    def __init__(self, store):
        self.store = store

    def status(self) -> dict:
        rows = self.store.read(
            "MATCH (v:ClaimVariant) RETURN v.id,v.text,v.embedding_model,"
            "v.embedding_revision,v.embedding_text_sha256,v.embedding IS NOT NULL"
        )
        stale = [
            row[0]
            for row in rows
            if row[2:] != [EMBED_MODEL, EMBED_REVISION, text_hash(row[1]), True]
        ]
        index = self.index_info()
        return {
            "total": len(rows),
            "ready": len(rows) - len(stale),
            "stale_ids": stale,
            "index_operational": index is not None and index["status"] == "OPERATIONAL",
            "model": EMBED_MODEL,
            "revision": EMBED_REVISION,
            "dimension": DIMENSION,
        }

    def index_info(self) -> dict | None:
        result = self.store.graph.list_indices()
        headers = [item[1] for item in result.header]
        for row in result.result_set:
            item = dict(zip(headers, row))
            if item["label"] == "ClaimVariant" and "VECTOR" in item["types"].get("embedding", []):
                options = item["options"]["embedding"]
                if options["dimension"] != DIMENSION or options["similarityFunction"] != "cosine":
                    raise RuntimeError(
                        "Existing embedding index has incompatible dimensions/metric."
                    )
                return item
        return None

    def build(self, embedder, batch_size: int = 16) -> dict:
        if not 1 <= batch_size <= 64:
            raise ValueError("batch_size must be 1–64")
        rows = self.store.read("MATCH (v:ClaimVariant) RETURN v.id,v.text ORDER BY v.id")
        if not rows:
            raise ValueError("Ingest source records before building embeddings.")
        before = self.status()
        stale = set(before["stale_ids"])
        pending = [r for r in rows if r[0] in stale]
        if self.index_info() is None:
            self.store.graph.create_node_vector_index(
                "ClaimVariant", "embedding", dim=DIMENSION, similarity_function="cosine"
            )
        written = 0
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            vectors = embedder.encode([r[1] for r in batch])
            if len(vectors) != len(batch):
                raise RuntimeError("Embedding batch size mismatch.")
            validated = [valid_vector(vector) for vector in vectors]
            for (variant_id, text), vector in zip(batch, validated):
                result = self.store.graph.query(
                    "MATCH (v:ClaimVariant {id:$id}) WHERE v.text=$text "
                    "SET v.embedding=vecf32($vector), v.embedding_model=$model, "
                    "v.embedding_revision=$revision, v.embedding_text_sha256=$hash "
                    "RETURN v.id",
                    {
                        "id": variant_id,
                        "text": text,
                        "vector": vector,
                        "model": EMBED_MODEL,
                        "revision": EMBED_REVISION,
                        "hash": text_hash(text),
                    },
                ).result_set
                if not result:
                    raise RuntimeError("Claim changed during embedding; rerun embed.")
                written += 1
        return {**self.status(), "written": written, "skipped": len(rows) - len(pending)}

    def search(self, vector: list[float], limit: int = 10) -> list[dict]:
        if not 1 <= limit <= 20:
            raise ValueError("limit must be 1–20")
        state = self.status()
        if not state["total"]:
            raise ValueError("The graph contains no claims.")
        if state["stale_ids"] or not state["index_operational"]:
            raise RuntimeError("Embeddings are missing, stale or not indexed. Run embed first.")
        results = []
        for variant_id, text, distance, model, revision, digest in self.store.read(
            VECTOR_SEARCH, {"vector": valid_vector(vector), "limit": min(limit, state["total"])}
        ):
            if model != EMBED_MODEL or revision != EMBED_REVISION or digest != text_hash(text):
                raise RuntimeError("Embedding provenance changed during retrieval.")
            # Live FalkorDB 4.22.1 returns cosine DISTANCE: identical vectors score zero.
            similarity = max(-1.0, min(1.0, 1.0 - float(distance)))
            results.append(
                {
                    "variant_id": variant_id,
                    "text": text,
                    "similarity": round(similarity, 6),
                    "cosine_distance": float(distance),
                }
            )
        return results


@dataclass(frozen=True)
class Assessment:
    relation: str
    reason: str
    forward: dict = field(default_factory=dict)
    reverse: dict = field(default_factory=dict)


def classify(forward: dict, reverse: dict, similarity: float, threshold: float = 0.8) -> Assessment:
    if min(forward["contradiction"], reverse["contradiction"]) >= threshold:
        return Assessment(
            "CONTRADICTION",
            "Bidirectional NLI contradiction; this is not a truth verdict.",
            forward,
            reverse,
        )
    if min(forward["entailment"], reverse["entailment"]) >= threshold:
        return Assessment(
            "SAME_PROPOSITION",
            "Both textual directions meet the entailment threshold; model assessment requires review.",
            forward,
            reverse,
        )
    if max(forward["contradiction"], reverse["contradiction"]) >= threshold:
        return Assessment(
            "UNCERTAIN",
            "NLI directions disagree about contradiction; human review required.",
            forward,
            reverse,
        )
    relation = "RELATED_CONTEXT" if similarity >= 0.5 else "IRRELEVANT"
    return Assessment(
        relation,
        "Text similarity or one-way entailment does not establish the same proposition.",
        forward,
        reverse,
    )


class ClaimScout:
    """Specialist A: retrieval and relevance, without access to graph write operations."""

    def __init__(self, store, embedder=None, relevance_model=None):
        self.store = store
        self._embedder = embedder
        self._relevance_model = relevance_model

    def scout(self, submitted_claim: str, limit: int = 10) -> dict:
        from .models import Embedder, RelevanceModel, language

        claim = submitted_claim.strip()
        if not claim or len(claim) > 4000:
            raise ValueError("Claim must contain 1–4000 characters.")
        self._embedder = self._embedder or Embedder()
        candidates = VectorIndex(self.store).search(self._embedder.encode([claim])[0], limit)
        query_language = language(claim)
        assessments: dict[int, Assessment] = {}
        pairs = []
        pending = []
        for i, candidate in enumerate(candidates):
            if candidate["similarity"] < 0.45:
                assessments[i] = Assessment(
                    "IRRELEVANT", "Below the semantic candidate similarity floor."
                )
                continue
            candidate_language = language(candidate["text"])
            candidate["language"] = candidate_language
            if any(
                x["code"] != "en" or x["score"] < 0.9 for x in (query_language, candidate_language)
            ):
                assessments[i] = Assessment(
                    "UNCERTAIN", "English relevance model cannot verify this language reliably."
                )
                continue
            self._relevance_model = self._relevance_model or RelevanceModel()
            if not self._relevance_model.fits(claim, candidate["text"]):
                assessments[i] = Assessment(
                    "UNCERTAIN", "Pair exceeds model token limit; no silent NLI truncation."
                )
                continue
            pending.append(i)
            pairs.extend([(claim, candidate["text"]), (candidate["text"], claim)])
        if pairs:
            predictions = self._relevance_model.assess_pairs(pairs)
            if len(predictions) != len(pairs):
                raise RuntimeError("Relevance model returned an incomplete batch.")
            for n, i in enumerate(pending):
                assessments[i] = classify(
                    predictions[2 * n], predictions[2 * n + 1], candidates[i]["similarity"]
                )
        matches, context = [], []
        for i, candidate in enumerate(candidates):
            assessment = assessments[i]
            candidate["assessment"] = asdict(assessment)
            candidate["direct_match"] = assessment.relation == "SAME_PROPOSITION"
            if assessment.relation != "IRRELEVANT":
                candidate["evidence"] = self.store.evidence(candidate["variant_id"])
                (matches if candidate["direct_match"] else context).append(candidate)
        return {
            "submitted_claim": claim,
            "language": query_language,
            "matches": matches,
            "context": context,
            "rejected": [c for c in candidates if c["assessment"]["relation"] == "IRRELEVANT"],
            "handoff_variant_ids": [c["variant_id"] for c in matches],
            "outcome": "CANDIDATE_MATCHES_FOUND" if matches else "NO_CONFIDENT_MATCH",
            "models": {
                "embedding": EMBED_MODEL,
                "embedding_revision": EMBED_REVISION,
                "relevance": NLI_MODEL,
                "relevance_revision": NLI_REVISION,
            },
            "uncertainty": "Model relevance is not factual truth. Published ratings apply only to their original reviewed claims.",
        }
