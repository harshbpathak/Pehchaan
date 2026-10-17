"""Exercise discovery and all seven tools with the official MCP HTTP client."""

import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    base = os.getenv("PEHCHAN_API_URL", "http://127.0.0.1:8000")
    token = os.getenv("PEHCHAN_WRITE_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    report = {"transport": "Streamable HTTP", "url": base + "/mcp/", "calls": []}
    async with (
        streamablehttp_client(base + "/mcp/", headers=headers, timeout=180) as (read, write, _),
        ClientSession(read, write) as client,
    ):
        await client.initialize()
        tools = await client.list_tools()
        report["tools"] = [t.name for t in tools.tools]
        calls = [
            ("get_claim_evidence", {"variant_id": "variant_b798bbbaab3675372ee8c4c3"}),
            ("explore_narrative_graph", {"variant_id": "variant_c33c5ad75f0189bd1179dcf3"}),
            (
                "find_evidence_path",
                {
                    "from_id": "variant_700ff916add10df61b609425",
                    "to_id": "variant_9e4e7b29e161704389906809",
                },
            ),
            (
                "find_similar_claims",
                {"claim": "Underwater quartz clocks transmit encrypted rainfall forecasts."},
            ),
            (
                "assemble_evidence_dossier",
                {"claim": "Underwater quartz clocks transmit encrypted rainfall forecasts."},
            ),
            (
                "create_review_case",
                {
                    "claim": "Underwater quartz clocks transmit encrypted rainfall forecasts.",
                    "request_id": "mcp-smoke-review-v1",
                },
            ),
            (
                "investigate_claim",
                {
                    "claim": "A Rockefeller patent proves that 5G and mRNA vaccines can remotely control human cells.",
                    "request_id": "mcp-smoke-known-v1",
                },
            ),
        ]
        for name, args in calls:
            response = await client.call_tool(name, args)
            if response.isError:
                raise AssertionError(f"{name} returned a tool error: {response.content}")
            structured = response.structuredContent
            report["calls"].append(
                {"tool": name, "ok": True, "structured_result": structured is not None}
            )
            print(f"PASS {name}", flush=True)
    assert len(report["tools"]) == 7 and len(report["calls"]) == 7
    report["ok"] = True
    path = Path("artifacts/mcp-smoke.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
