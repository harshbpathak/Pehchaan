# Pehchan AI

Graph-native misinformation investigation with local semantic retrieval, cooperating specialists, traceable publisher evidence and persistent review cases.

The local MVP imports real ClaimReview records, embeds claims in FalkorDB, assesses textual relevance, traces connected narratives, assembles dossiers and records the recommended action. A FastAPI service, seven real Streamable HTTP MCP tools and a Streamlit interface use the same investigation logic.

Investigation now defaults to Gemma tool-calling inference through Google AI Studio. Gemma selects local semantic retrieval, source evidence and graph tools; local embedding/NLI models still assess relevance. Application code validates citations and selects the final case status. Publisher ratings remain attached to their original reviewed claims. An explicit deterministic mode retains the earlier offline specialist workflow.

## Configure Gemma inference

The default model is `gemma-4-26b-a4b-it`; Google's [Gemma API guide](https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api) documents hosted Gemma 4 and native function calling. Set `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) in the backend process environment using your Google AI Studio key. Do not put it in chat or tracked files. Python does not implicitly load `.env`.

```powershell
$env:PEHCHAN_INFERENCE = "gemini"
$env:PEHCHAN_LLM_MODEL = "gemma-4-26b-a4b-it"
# Read the key without displaying it or recording it as a command literal.
$taskKey = Read-Host "Google AI Studio API key" -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new('', $taskKey).Password
Remove-Variable taskKey
.\.tools\python\python.exe scripts/run_local.py
.\.tools\python\python.exe scripts/smoke_inference.py
```

Restart an already running backend from that configured environment: the launcher leaves healthy processes running, so it cannot update their environment. `/health` reports inference mode/model and whether a key is present; presence does not establish valid credentials or model access. Missing keys, quota/authentication failures, malformed calls and exhausted budgets return explicit errors and do not create a case. The live smoke command makes actual API calls, saves an ignored local report, and creates no Investigation.

Gemma receives submitted claim text and selected retrieved evidence/context over HTTPS. Raw ClaimReview markup and file provenance metadata remain local. No arbitrary Cypher or write function is offered to the model. It must retrieve relevant sources and bounded narrative context before completing; application checks remain authoritative. Generated analyst notes are labeled commentary requiring review, not independently verified findings.

To run the original offline workflow, explicitly set `$env:PEHCHAN_INFERENCE = "deterministic"` before starting the backend/CLI. Local models and graph setup are still required. Install `.[llm]` for CLI-only LLM use; the server extra already includes its HTTP dependency. The tool loop uses the documented `generateContent` REST API with no additional SDK dependency.

## Open the running MVP

- Product interface: [http://localhost:8501](http://localhost:8501)
- API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)
- MCP transport: `http://localhost:8000/mcp/`
- Database browser: [http://localhost:3000](http://localhost:3000)

This workspace has the 250-review main collection, 248 indexed variants, downloaded models and saved demo investigations. Start its API/UI with:

```powershell
.\.tools\python\python.exe scripts/run_local.py
```

The launcher uses background processes, leaves healthy existing services running, and writes logs under `artifacts/`. It does not change PowerShell execution policy.

## Set up the complete MVP from a fresh clone

Use Python 3.12 for the tested pinned environment, Docker's Linux engine, and enough disk/RAM for PyTorch and the two local model checkpoints. The package code targets Python 3.11+, but other interpreters may need compatible dependency resolution rather than this exact constraints snapshot. Retrieval/NLI uses local checkpoints; default Gemma inference additionally requires network access and an AI Studio key configured above.

Windows PowerShell, with no activation-script requirement:

```powershell
python -m venv .venv
$taskPython = ".\.venv\Scripts\python.exe"
& $taskPython -m pip install "torch==2.14.1" --index-url https://download.pytorch.org/whl/cpu
& $taskPython -m pip install -c requirements.lock -e ".[semantic,server,ui,dev]"
docker compose up -d --wait
& $taskPython scripts/validate_demo.py
& $taskPython -m pehchan.cli download-models
& $taskPython -m pehchan.cli --graph pehchan_demo embed
$env:FALKORDB_GRAPH = "pehchan_demo"
& $taskPython scripts/run_local.py
```

On macOS/Linux, create/activate the virtual environment normally, use `python` in place of `& $taskPython`, and `export FALKORDB_GRAPH=pehchan_demo`. The included sample gives a stable 12-review demo; the larger feed import below is optional. The database must already be running before the application becomes ready.

For foreground service logs instead of the launcher:

```text
python -m uvicorn pehchan.api:app --host 127.0.0.1 --port 8000 --workers 1
python -m streamlit run src/pehchan/ui.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

Run these in separate terminals with the same graph/model/token environment. One API worker serializes local model work and graph actions.

## Complete investigation flow

1. Submit a claim in the product UI, CLI or MCP client.
2. Claim Scout retrieves native FalkorDB vector neighbors and checks bidirectional textual relevance.
3. Gemma chooses evidence and bounded graph tool calls, including required narrative exploration for direct handoffs; BFS and connection paths are optional. The deterministic mode uses Graph Detective's original fixed sequence.
4. Evidence & Response validates retrieved publisher records, records uncertainties and selects `EVIDENCE_DOSSIER_READY`, `NEEDS_HUMAN_REVIEW`, or `INSUFFICIENT_EVIDENCE`. Gemma's analyst note is kept separate from this decision.
5. The orchestrator saves an Investigation and its exact `EXAMINES`/`CITES` links. Unmatched cases are saved without invented evidence nodes or links.
6. Researchers inspect sources/graph context, download JSON dossiers, and update follow-up state in the case library.

```powershell
python -m pehchan.cli scout "Coronavirus is being spread by 5G technology."
python -m pehchan.cli investigate "Underwater quartz clocks transmit encrypted rainfall forecasts." --request-id researcher-example-1
python -m pehchan.cli cases
python -m pehchan.cli dossier "Scientists have had to pause the Climate Change Hoax Scam"
```

`dossier` assembles without saving. `investigate` persists. The optional request ID deduplicates identical retries and rejects reuse for another claim; new investigations after data/model changes need a new ID. `review CASE_ID --state IN_PROGRESS --note "Checking sources"` changes follow-up, not the evidence decision.

## Semantic retrieval and its limits

Vectors use the pinned multilingual MiniLM model; relevance uses pinned English DeBERTa NLI in both directions. Unsupported languages or overlong NLI pairs are explicitly uncertain. Native FalkorDB cosine distance is converted to similarity correctly. Claims, model versions and text hashes are checked before retrieval; missing/stale coverage fails rather than falling back silently.

```powershell
python -m pehchan.cli embedding-status
python -m pehchan.cli embed
python -m pehchan.cli semantic-search "Coronavirus is being spread by 5G technology."
```

Run `embed` again after expanding the collection; already fresh vectors are skipped. The original `search` command remains an explicit lexical comparison baseline.

The fixed real-model smoke evaluation passes **10 of 11 strict examples**, with one recorded conservative false negative: “5G mobile technology spreads the coronavirus” retrieves its source but receives context rather than direct-equivalence status. Both contradiction examples and all distractor, unfamiliar and unsupported-language cases pass. This small smoke set does not establish calibrated real-world accuracy. Model false contradictions can also send usable evidence to human review; no NLI label or source-neighbor score is a new truth verdict.

## MCP and access control

The official Python MCP SDK exposes:

| Tool | Effect |
| --- | --- |
| `find_similar_claims` | Semantic candidates, relevance and evidence handoff |
| `get_claim_evidence` | Original publisher evidence and provenance |
| `explore_narrative_graph` | Explicit shared-frame paths with inference origins |
| `find_evidence_path` | One bounded graph connection, including entity bridges |
| `assemble_evidence_dossier` | Read-only specialist workflow |
| `create_review_case` | Persist an explicitly requested human-review case |
| `investigate_claim` | Run the full workflow and persist its action |

The local endpoint is Streamable HTTP, not legacy SSE. Compatible local clients can use `http://localhost:8000/mcp/`. All seven tools were discovered and called with the official HTTP client.

Local listeners are loopback-only by default. Set `PEHCHAN_API_TOKEN` for read access and a distinct `PEHCHAN_WRITE_TOKEN` for case writes. The combined MCP endpoint requires the write credential when tokens are configured. `PEHCHAN_UI_TOKEN` supplies the UI's backend credential; otherwise the UI uses configured write/read token environment values. Public-host configuration requires distinct credentials. Host/Origin checks are enabled. There is no arbitrary-Cypher or ingestion HTTP tool.

A cloud MCP connector cannot reach localhost. Public deployment requires an HTTPS reverse proxy/reachable host, `PEHCHAN_PUBLIC_HOSTS`, persistent database/model storage, and a client that supports the configured bearer authorization. OAuth and a public deployment/Claude cloud connector have not been verified. See [deployment notes](Docs/Deployment.md).

## Run the verified sample

Requires Python 3.11+ and Docker with its Linux engine running. The tested environment uses Python 3.12.10, FalkorDB server 4.22.1, and Python SDK 1.8.0. The container image is pinned by digest.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -c requirements.lock -e ".[dev]"
docker compose up -d --wait
python scripts/validate_demo.py
```

On macOS/Linux, activate with `source .venv/bin/activate`. The remaining commands are the same.

The demo loads the included **12 genuine ClaimReview records**, applies separate annotations, ingests twice to check idempotence, and verifies evidence, a four-hop narrative path, an entity bridge, native BFS, and an unmatched query. It keeps the `pehchan_demo` graph and writes `artifacts/demo/validation.json`. Failures exit nonzero. Stop the database with `docker compose stop`; its named volume retains data.

For this workspace, a portable Python runtime is already available:

```powershell
.\.tools\python\python.exe scripts/validate_demo.py
```

## What was validated

On October 18, 2026 (IST), the official feed was downloaded and 250 records were selected using the reproducible filters below. The local `pehchan` graph contains:

| Records | Count |
| --- | ---: |
| FactCheck | 250 |
| ClaimVariant / Claim | 248 each |
| Publisher domains | 53 |
| NarrativeFrame | 5 |
| Topic | 4 |
| Entity | 2 |

Two pairs of fact-checks review identical claim wording, so 250 reviews produce 248 variants. Narrative, topic, and entity annotations cover only 12 inspected claims. The 250-record selection is an initial substring-filtered seed; it includes uncurated and multilingual records, not 250 validated narrative memberships.

The live database tests and source-sample checks passed. See [the validation snapshot](Docs/validation.json), [graph design](Docs/graph-schema.md), and [data notes](data/samples/README.md). All source URLs and ratings in reports come from records; Pehchan does not assign a new truth verdict.

The [architectural decision register](Docs/Decision.md) records what we chose, why, and the consequences. The [flow register](Docs/Flow.md) describes every implemented command, data path, operational workflow, and failure branch. Update these registers alongside architectural or workflow changes.

## Import the larger feed

The [Data Commons download page](https://datacommons.org/factcheck/download) links the official current ClaimReview feed. Its historical research download returned HTML during setup, so this milestone uses the current feed. The full downloaded file and prepared 250-record subset are already present locally under ignored `data/raw/` and `data/processed/` directories.

To reproduce from a new download (the feed changes over time):

```powershell
New-Item -ItemType Directory -Force data/raw | Out-Null
curl.exe --fail --location https://storage.googleapis.com/datacommons-feeds/claimreview/latest/data.json --output data/raw/claimreview-latest.json
python -m pehchan.cli prepare data/raw/claimreview-latest.json --output data/processed/claims.jsonl --report data/processed/preparation-report.json --source https://storage.googleapis.com/datacommons-feeds/claimreview/latest/data.json --contains microchip --contains 5g --contains "climate change" --contains "moon landing" --limit 250
python -m pehchan.cli --graph pehchan ingest data/processed/claims.jsonl
python -m pehchan.cli --graph pehchan validate data/processed/claims.jsonl --output artifacts/validation.json
```

`--contains` performs OR substring selection, not topic classification. Omit it to import all records. `--limit` caps accepted unique reviews, and the report records how much input was scanned. The included annotations refer to exact variant IDs from this snapshot. Apply them to the full subset only if those IDs are present:

```powershell
python -m pehchan.cli --graph pehchan ingest data/processed/claims.jsonl --annotations data/samples/annotations.json
python -m pehchan.cli --graph pehchan validate data/processed/claims.jsonl --require-narrative --output artifacts/validation.json
```

For a stable demo independent of feed changes, use the included sample instead of redownloading. `scripts/build_sample.py` documents the exact record selection used to produce it.

## Inspect evidence and connections

```powershell
python -m pehchan.cli --graph pehchan_demo search "A microchip reader for pets detected a chip in a vaccinated arm"
python -m pehchan.cli --graph pehchan_demo evidence variant_b798bbbaab3675372ee8c4c3
python -m pehchan.cli --graph pehchan_demo narratives variant_b798bbbaab3675372ee8c4c3
python -m pehchan.cli --graph pehchan_demo path variant_700ff916add10df61b609425 variant_9e4e7b29e161704389906809
python -m pehchan.cli --graph pehchan_demo bfs variant_700ff916add10df61b609425
python -m pehchan.cli --graph pehchan_demo stats
```

Search uses a transparent token Jaccard baseline over variants fetched from FalkorDB. Its scores represent lexical overlap and every result is an **unverified candidate**. Semantic matching and proposition verification remain future work. No matching record establishes neither truth nor falsity.

## Data guarantees and current limits

- Readers accept ClaimReview JSON objects, arrays, JSON-LD `@graph`, DataFeed items, JSONL/NDJSON, and gzip versions. DataFeed input is streamed.
- Stable IDs separate exact wording, conservatively normalized claims, source reviews, and publisher domains. Punctuation, negation, and numbers remain in canonical text; similar claims are not automatically merged.
- Original markup, rating objects including numeric scales, URLs, source-file SHA-256, record indices, licenses when supplied, and review dates are retained. Missing dates remain missing. `itemReviewed.author` is never used as the fact-check publisher; `sdPublisher` is also excluded from publisher attribution.
- Invalid required fields are audited as rejections. Identical source reviews are deduplicated. Conflicting ratings for the same URL and claim abort preparation and preserve any previous output.
- All prepared records and annotations are validated before graph writes. `MERGE` and ID indexes support sequential reruns. Each review is written atomically; the whole dataset is not a single transaction. A failed import can be rerun.
- Run one ingestion process per graph. Concurrent ingestion, uniqueness constraints, dataset reconciliation, and annotation removal/version history are not implemented. Reingestion merges records; it does not clear existing data.
- Narrative annotations are explicitly marked **AI-assisted inferences, human review pending**. They are not publisher verdicts or evidence of coordination. Entity annotations must include a text span actually present in the claim.
- Removing FalkorDB breaks evidence retrieval, relationships, path queries, and graph validation. There is no fallback graph or mocked query result.

Connection settings are in [.env.example](.env.example). Set them as environment variables; `.env` is not automatically loaded. The default server is `127.0.0.1:16379` and default graph is `pehchan`. Compose binds the database to localhost. Port 16379 avoids the service already occupying 6379 on this machine.

The FalkorDB graph browser is available at [http://localhost:3000](http://localhost:3000). Its connection to the database runs inside the container: use host `127.0.0.1`, port `6379`, and no password for this local setup. Select `pehchan` for the 250-record graph or `pehchan_demo` for the reproducible sample. Applications running on your laptop use database port `16379` instead.

## Tests

Install the full MVP extras before running the entire suite. A foundation-only environment can run `python -m pytest -q tests/test_ingestion.py` separately.

```powershell
python -m pytest -q -m "not integration"
$env:PEHCHAN_INTEGRATION = "1"
python -m pytest -q
python -m ruff check --isolated src tests scripts
```

On macOS/Linux run `PEHCHAN_INTEGRATION=1 python -m pytest -q`. Integration tests create uniquely named `pehchan_test_*` graphs and delete only those graphs afterward. They exercise a synthetic fixture and the real sample, repeated ingestion, publisher evidence, inference paths, native BFS, an entity bridge, unmatched input, and query-injection resistance.

## Attribution

The dataset compilation is credited to Data Commons / Google Fact Check Tools and the publishers identified in each record. Compilation licensing and publisher-content licensing are distinct; see [the source's licensing notes](https://datacommons.org/factcheck/download) and [sample manifest](data/samples/manifest.json). This repository contains selected structured markup, not downloaded article bodies. The implementation and sample annotations were produced with Codex AI coding assistance.

## Verify each milestone

```powershell
$env:PEHCHAN_INTEGRATION = "1"
$env:PEHCHAN_MODELS = "1"
python -m pytest -q
python -m ruff check --isolated src tests scripts
python scripts/evaluate_semantic.py --graph pehchan
python scripts/verify_mvp.py
python scripts/smoke_mcp.py
```

The last full pytest run has **38 passing tests**, including actual local-model inference, live database checks, API access boundaries and Streamlit AppTest interactions. Live API smoke checks exercise all three action statuses, persistent citations, retry deduplication, follow-up and no-match safety. Real MCP smoke checks discovery/calls over HTTP. The original foundation run is retained in `Docs/validation.json`; the full MVP snapshot is in [Docs/mvp-validation.json](Docs/mvp-validation.json). Local reports/logs remain under ignored `artifacts/`.

No public publishing of claims, background monitoring, unrestricted crawling, automatic notifications, tenant isolation or automatic production deployment is implemented. Dataset expansion remains a later step; ingest additional records and re-run embedding/index validation without changing existing claim identities. Live Gemma validation requires a configured key; mocked protocol tests do not establish live provider availability.
