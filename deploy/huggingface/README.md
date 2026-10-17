---
title: Pehchan AI
emoji: 🔎
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Match forwards to existing fact-checks through a FalkorDB graph
---

# Pehchan AI

One false claim can shift a whole narrative. Pehchan matches a forwarded message to fact-checks that already exist, follows a FalkorDB graph to the narratives around it, and drafts a reply that cites only real records.

- Web app: this Space
- Public read-only MCP endpoint: `https://<this-space-host>/public/mcp/` (claude.ai, ChatGPT developer mode, Gemini CLI)
- Source: https://github.com/harshbpathak/Pehchaan

The graph is hosted on FalkorDB Cloud. Ratings belong to the publishers that wrote them; Pehchan does not decide what is true.
