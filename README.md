# Pehchan AI

Graph-native misinformation investigation, beginning with a tested ClaimReview ingestion and FalkorDB foundation.

This milestone imports real source records, preserves publisher ratings and provenance, and proves that a submitted claim can retrieve candidate records, published evidence, and connected narrative paths. LLM agents, embeddings, MCP, investigation persistence, and a frontend are subsequent milestones.

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

The live database tests and source-sample checks passed. See [the validation snapshot](docs/validation.json), [graph design](docs/graph-schema.md), and [data notes](data/samples/README.md). All source URLs and ratings in reports come from records; Pehchan does not assign a new truth verdict.

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

## Tests

```powershell
python -m pytest -q -m "not integration"
$env:PEHCHAN_INTEGRATION = "1"
python -m pytest -q
python -m ruff check --isolated src tests scripts
```

On macOS/Linux run `PEHCHAN_INTEGRATION=1 python -m pytest -q`. Integration tests create uniquely named `pehchan_test_*` graphs and delete only those graphs afterward. They exercise a synthetic fixture and the real sample, repeated ingestion, publisher evidence, inference paths, native BFS, an entity bridge, unmatched input, and query-injection resistance.

## Attribution

The dataset compilation is credited to Data Commons / Google Fact Check Tools and the publishers identified in each record. Compilation licensing and publisher-content licensing are distinct; see [the source's licensing notes](https://datacommons.org/factcheck/download) and [sample manifest](data/samples/manifest.json). This repository contains selected structured markup, not downloaded article bodies. The implementation and sample annotations were produced with Codex AI coding assistance.

The next engineering step is semantic candidate retrieval and structured specialist handoffs on top of these validated graph operations.
