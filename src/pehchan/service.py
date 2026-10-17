"""One serialized application service shared by HTTP and MCP adapters."""

import threading

from .graph import GraphStore
from .inference import configuration, configured_inference
from .investigation import CaseStore, Orchestrator
from .models import model_root
from .semantic import ClaimScout, VectorIndex


class ApplicationService:
    def __init__(self, store=None):
        self._store = store
        self._scout = None
        self.lock = threading.RLock()

    @property
    def store(self):
        if self._store is None:
            self._store = GraphStore()
        return self._store

    @property
    def scout_agent(self):
        if self._scout is None:
            self._scout = ClaimScout(self.store)
        return self._scout

    def call(self, operation: str, *args, **kwargs):
        # This method is internal to adapters; there is no arbitrary-operation HTTP tool.
        with self.lock:
            store = self.store
        operations = {
            "health": self.health,
            "find_similar_claims": self.find_similar_claims,
            "get_claim_evidence": store.evidence,
            "explore_narrative_graph": store.narrative_paths,
            "find_evidence_path": store.shortest_path,
            "assemble_evidence_dossier": self.assemble_evidence_dossier,
            "create_review_case": self.create_review_case,
            "investigate_claim": self.investigate_claim,
            "cases": self.cases,
            "case": self.case,
            "review": self.review,
            "graph": self.graph,
        }
        if operation not in operations:
            raise ValueError("Unknown application operation.")
        with self.lock:
            return operations[operation](*args, **kwargs)

    def health(self):
        status = VectorIndex(self.store).status()
        models_present = all(
            (model_root() / kind / "pehchan-model.json").exists() for kind in ("embedding", "nli")
        )
        inference = configuration()
        return {
            "status": "ready"
            if status["total"]
            and not status["stale_ids"]
            and status["index_operational"]
            and models_present
            and inference["configured"]
            else "setup_required",
            "graph": self.store.graph_name,
            "statistics": self.store.stats(),
            "embeddings": status,
            "models_present": models_present,
            "inference": inference,
        }

    def find_similar_claims(self, claim: str, limit: int = 10):
        return self.scout_agent.scout(claim, limit)

    def assemble_evidence_dossier(self, claim: str):
        return self.orchestrator().assemble(claim)

    def investigate_claim(self, claim: str, request_id: str | None = None):
        return self.orchestrator().investigate(claim, request_id)

    def create_review_case(self, claim: str, request_id: str | None = None):
        return self.orchestrator().investigate(claim, request_id, force_review=True)

    def orchestrator(self):
        return Orchestrator(self.store, self.scout_agent, inference=configured_inference())

    def cases(self, limit: int = 50):
        return CaseStore(self.store).list(limit)

    def case(self, investigation_id: str):
        return CaseStore(self.store).get(investigation_id)

    def review(self, investigation_id: str, state: str, note: str = ""):
        return CaseStore(self.store).update_review(investigation_id, state, note)

    def graph(self, variant_id: str | None = None, limit: int = 80):
        if not 1 <= limit <= 150:
            raise ValueError("Graph limit must be 1–150")
        if variant_id:
            # Explore semantic connections; never traverse a shared publisher as a bridge.
            query = """
            MATCH p=(v:ClaimVariant {id:$id})-[:EXPRESSES|USES_FRAME|MENTIONS*1..4]-(b)
            UNWIND relationships(p) AS r
            WITH DISTINCT r LIMIT $limit
            RETURN startNode(r).id,labels(startNode(r))[0],
                   coalesce(startNode(r).text,startNode(r).canonical_text,startNode(r).name),
                   endNode(r).id,labels(endNode(r))[0],
                   coalesce(endNode(r).text,endNode(r).canonical_text,endNode(r).name),
                   type(r),r.basis,r.rationale
            """
        else:
            query = """
            MATCH (a)-[r]->(b) WHERE type(r)<>'CITES' AND type(r)<>'EXAMINES'
            RETURN a.id,labels(a)[0],coalesce(a.text,a.canonical_text,a.name,a.url),
                   b.id,labels(b)[0],coalesce(b.text,b.canonical_text,b.name,b.url),
                   type(r),r.basis,r.rationale LIMIT $limit
            """
        nodes, edges = {}, []
        for a, at, al, b, bt, bl, relation, basis, rationale in self.store.read(
            query, {"id": variant_id, "limit": limit}
        ):
            nodes[a] = {"id": a, "type": at, "label": al or a}
            nodes[b] = {"id": b, "type": bt, "label": bl or b}
            edges.append(
                {
                    "source": a,
                    "target": b,
                    "type": relation,
                    "basis": basis or "source_record",
                    "rationale": rationale or "",
                }
            )
        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "edge_limit": limit,
            "note": "Bounded view. Curated inference edges are distinct from source relationships.",
        }

    def close(self):
        if self._store is not None:
            self._store.close()
