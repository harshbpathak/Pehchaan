import asyncio
import sys
import urllib.request

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

base = sys.argv[1].rstrip("/")
for path in ("/", "/health", "/api/config"):
    with urllib.request.urlopen(base + path, timeout=30) as r:
        print(path, r.status)
try:
    urllib.request.urlopen(base + "/api/investigations", timeout=30)
    print("/api/investigations OPEN (unexpected)")
except urllib.error.HTTPError as e:
    print("/api/investigations", e.code, "(protected)")


async def main():
    async with streamablehttp_client(base + "/public/mcp/") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", sorted(t.name for t in tools.tools))
            result = await session.call_tool(
                "assemble_evidence_dossier",
                {"claim": "Putin has banned 5G in Russia and destroyed all the towers."},
            )
            data = result.structuredContent
            print("dossier:", data["finding"], data["status"])
            print(data["draft_reply"]["text"].splitlines()[1][:160])


asyncio.run(main())
