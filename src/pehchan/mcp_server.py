"""Official MCP SDK, Streamable HTTP, eight narrowly scoped investigation tools."""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations


def create_mcp(service, public_hosts: list[str] | None = None):
    hosts = ["127.0.0.1:*", "localhost:*", "testserver", *(public_hosts or [])]
    mcp = FastMCP(
        "Pehchan AI",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        instructions="Investigate recorded claims. Ratings belong to their original publishers. "
        "Use investigate_claim to assemble and persist a case; use the read tools for exploration.",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=[
                "http://localhost:*",
                "http://127.0.0.1:*",
                *[f"https://{h}" for h in public_hosts or []],
            ],
        ),
    )
    read = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )
    write = ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
    )

    @mcp.tool(annotations=read)
    def find_similar_claims(claim: str, limit: int = 10) -> dict[str, Any]:
        """Retrieve graph-indexed semantic candidates and assess relevance; this is not a truth verdict."""
        return service.call("find_similar_claims", claim, limit)

    @mcp.tool(annotations=read)
    def get_claim_evidence(variant_id: str) -> list[dict[str, Any]]:
        """Retrieve original source URLs, publisher ratings and provenance for a stored claim variant."""
        return service.call("get_claim_evidence", variant_id)

    @mcp.tool(annotations=read)
    def explore_narrative_graph(variant_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Return explicit shared-frame paths and inference provenance, not evidence of coordination."""
        return service.call("explore_narrative_graph", variant_id, limit)

    @mcp.tool(annotations=read)
    def find_evidence_path(from_id: str, to_id: str) -> list[Any]:
        """Return one shortest connection within an eight-hop graph bound, including entity bridges."""
        return service.call("find_evidence_path", from_id, to_id)

    @mcp.tool(annotations=read)
    def expand_narrative_context(claim: str, limit: int = 10) -> dict[str, Any]:
        """Widen through entities/frames tagged in the claim to related fact-checked claims; context only."""
        return service.call("expand_narrative_context", claim, limit)

    @mcp.tool(annotations=read)
    def assemble_evidence_dossier(claim: str) -> dict[str, Any]:
        """Run specialist handoffs and assemble a dossier from graph evidence without saving a case."""
        return service.call("assemble_evidence_dossier", claim)

    @mcp.tool(annotations=write)
    def create_review_case(claim: str, request_id: str | None = None) -> dict[str, Any]:
        """Investigate and persist a case explicitly requiring human review. Optional request ID deduplicates retries."""
        return service.call("create_review_case", claim, request_id)

    @mcp.tool(annotations=write)
    def investigate_claim(claim: str, request_id: str | None = None) -> dict[str, Any]:
        """Run the complete specialist workflow, choose an evidence/review action, and persist its exact citations."""
        return service.call("investigate_claim", claim, request_id)

    return mcp
