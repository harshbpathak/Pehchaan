# Architectural decision register

Last reviewed: **18 October 2026 (Asia/Calcutta)**.

This register catalogues the architectural choices made for the implemented local MVP: ingestion, vector retrieval, specialist handoffs, case management, HTTP/MCP access, and the interface. Earlier milestone decisions are retained as history and explicitly qualified where later decisions extend them. The source code is the reference for current behavior.

Related documents: [flows](Flow.md), [graph schema and queries](graph-schema.md), [validation snapshot](validation.json), and [setup](../README.md).

## Maintaining this register

For every new architectural choice, append the next `ADR-NNN` entry with its status, decision, reason, consequences, source links, and affected flow IDs. Update the corresponding entry in [Flow.md](Flow.md) in the same change. When replacing a decision, retain the old reasoning and mark it superseded; reference the replacement. Do not describe a planned capability as implemented. Record the actual implementation date independently of Git commit timestamps.

**Status meanings:** implemented = present in current code/configuration; corrected = implemented replacement of an earlier faulty choice; deferred = proposed but not built. Known limitations are recorded here, not treated as future capabilities that already exist.

## ADR-001 — Deliver the graph foundation first

**Status:** Implemented. **Flows:** F-01 through F-21.

**Decision:** Limit this milestone to source ingestion, evidence retrieval, explicit graph relationships, algorithms, and validation. Build the foundation before adding LLMs, embeddings, MCP, case management, or a product frontend.

**Why:** The user selected ingestion and schema validation as the first milestone. A real record and a working multi-hop query establish that the graph is useful before agent output obscures data or query errors.

**Consequences at the first milestone:** This delivered a working foundation before vectorization, specialist decisions or review cases. Those capabilities are now implemented by ADR-030 through ADR-039. Public hosting, a demo recording and hackathon submission are not implied by the local MVP.

**Implementation:** [CLI](../src/pehchan/cli.py), [demo](../scripts/validate_demo.py).

## ADR-002 — Use a modular Python package and a CLI

**Status:** Implemented. **Flows:** F-01, F-20.

**Decision:** Use Python 3.11+, a `src/pehchan` package, and `argparse` entry points (`pehchan` and `python -m pehchan.cli`). Separate normalization, ingestion, annotations, fixed queries, and graph access into modules. Emit JSON results.

**Why:** One language and direct function calls keep the initial pipeline inspectable and easy to test. The modules can later sit behind an API or MCP server without requiring those services now.

**Consequences:** Commands remain synchronous local processes and the CLI emits UTF-8 JSON. The initial CLI-only boundary was subsequently extended by ADR-033/ADR-036/ADR-037: FastAPI, Streamable HTTP MCP and Streamlit now serve the same application workflow.

**Implementation:** [package metadata](../pyproject.toml), [CLI](../src/pehchan/cli.py).

## ADR-003 — Make FalkorDB the relationship system of record

**Status:** Implemented. **Flows:** F-08 through F-16.

**Decision:** Store claim/source/entity/narrative relationships in FalkorDB and execute relationship queries there. Use its official synchronous Python SDK. Do not implement an in-memory substitute graph.

**Why:** Connected investigation must depend on real graph operations. A visualization over independently computed relationships would not establish that foundation.

**Consequences:** Source preparation can run offline, but evidence reads, graph exploration, graph algorithms and validation require a reachable FalkorDB instance. Lexical scores are computed in Python over variants read from the database.

**Implementation:** [GraphStore](../src/pehchan/graph.py).

## ADR-004 — Use the official current ClaimReview feed

**Status:** Implemented; replaces the initial historical-download choice. **Flows:** F-03, F-04.

**Decision:** Import the current Google Data Commons / Fact Check Markup Tool DataFeed. Retain its origin and the downloaded file's SHA-256.

**Why:** The historical research download returned HTML during setup. The current feed supplied real ClaimReview records and required no API key for this milestone.

**Consequences:** Future downloads can change. Reproducible demonstrations use a saved sample, not an assumption that the latest feed remains identical. There is no Google Fact Check Tools API integration or automatic online enrichment.

**Implementation:** [sample manifest](../data/samples/manifest.json), [download commands](../README.md#import-the-larger-feed).

## ADR-005 — Retain structured markup and attribute its sources

**Status:** Implemented. **Flows:** F-03 through F-05, F-17.

**Decision:** Preserve ClaimReview markup and available licensing fields. Include source attribution and a separate sample manifest. Do not download article bodies.

**Why:** The investigation needs source URLs, publisher ratings and traceability. The dataset's structured markup does not provide full article contents, and compilation licensing does not replace publisher-content terms.

**Consequences:** Retrieval returns recorded metadata, not an assertion that the full article has been read or its evidence independently verified. Missing license fields stay missing.

**Implementation:** [normalization](../src/pehchan/records.py), [sample notes](../data/samples/README.md).

## ADR-006 — Use a small seed and a stable genuine sample

**Status:** Implemented. **Flows:** F-04, F-17, F-18.

**Decision:** Prepare 250 accepted unique reviews using OR substring filters for `microchip`, `5g`, `climate change`, and `moon landing`. Keep 12 explicitly selected source records and their separate annotations in the repository.

**Why:** A bounded seed makes initial inspection and graph validation practical. The small checked-in sample makes demonstrations independent of a large changing feed.

**Consequences:** Substring filters are selection aids, not semantic topic labels; they can include irrelevant matches and multilingual content. Only the 12 selected claims have narrative/entity annotations. Current counts are a snapshot, not fixed system guarantees.

**Implementation:** [prepare](../src/pehchan/ingestion.py), [sample selection](../scripts/build_sample.py).

## ADR-007 — Stream source containers and use JSONL between stages

**Status:** Implemented. **Flows:** F-04, F-06.

**Decision:** Use `ijson` to iterate JSON container items, recursively unwrap supported ClaimReview envelopes, and support JSONL/NDJSON plus gzip variants. Write one normalized record per JSONL line.

**Why:** The downloaded feed is large. A line-oriented intermediate artifact is easy to inspect, audit and rerun without embedding the source acquisition step in graph ingestion.

**Consequences:** This is not a constant-memory pipeline: preparation retains accepted records in its deduplication map, and `load_prepared` loads the prepared subset into a list. Readers expect the supported JSON structure and appropriate JSONL/NDJSON filename suffixes, not arbitrary text or HTML.

**Implementation:** [ingestion readers](../src/pehchan/ingestion.py).

## ADR-008 — Assign deterministic identities conservatively

**Status:** Implemented. **Flows:** F-05, F-09.

**Decision:** Prefix IDs by kind and derive their suffix from the first 24 hex characters of SHA-256 over JSON-encoded identity values. Variant identity uses NFC wording and language. Canonical claim identity uses NFKC, case folding, whitespace normalization and language. Review identity uses canonical URL, normalized claim and language. Publisher identity uses its domain; entity identity also includes type.

**Why:** Stable identities make sequential imports repeatable without merging claims just because they sound similar. Punctuation, numbers and negation must survive normalization.

**Consequences:** Wording variants can remain separate even if humans would call them paraphrases. Language defaults to `und`; language detection is absent. Changing identity rules requires an explicit migration decision. These IDs are deterministic identifiers, not evidence that a claim is true or equivalent to a paraphrase.

**Implementation:** [stable_id and normalize_review](../src/pehchan/records.py).

## ADR-009 — Canonicalize URLs but retain their original form

**Status:** Implemented. **Flows:** F-05.

**Decision:** Accept absolute HTTP(S) URLs, reject embedded credentials, normalize host/default ports, remove fragments and known tracking parameters, and sort remaining query parameters. Keep `url_original` alongside `url`.

**Why:** Tracking links should not create duplicate review identities; the source's submitted URL must still be available for audit.

**Consequences:** URL normalization is deterministic, not a redirect resolver or availability check. Query-order and fragment-based distinctions are not preserved in the canonical identity, though they remain in the original URL.

**Implementation:** [canonical_url](../src/pehchan/records.py).

## ADR-010 — Keep publisher ratings and dates source-derived

**Status:** Implemented. **Flows:** F-05, F-11.

**Decision:** Obtain the displayed original rating from `reviewRating.alternateName`, then `ratingValue`; retain the whole rating object including numeric scales. Parse review date from the review's `datePublished` and claim date only from `itemReviewed.datePublished`. Leave unavailable dates empty and record applicable warnings.

**Why:** Pehchan must not invent a verdict, reinterpret an unfamiliar numeric scale as a truth label, or confuse the date of an article with the date of a claim.

**Consequences:** No common true/false scale is synthesized. Original dates remain in raw markup; normalized dates have day precision. Missing or malformed dates do not automatically reject an otherwise usable record.

**Implementation:** [normalization](../src/pehchan/records.py), [evidence](../src/pehchan/graph.py).

## ADR-011 — Separate fact-check publisher from claim originator

**Status:** Implemented. **Flows:** F-05.

**Decision:** Prefer a suitable named organization in `publisher`, then review-level `author`; otherwise fall back to the review URL's domain. Exclude entries explicitly typed `Person`. Do not use `itemReviewed.author` or `sdPublisher` as the reviewing publisher.

**Why:** The person making a claim and the service distributing its markup are different from the organization reviewing it.

**Consequences:** Publisher naming follows the available markup and its types; it is not an independently verified publisher directory. A shared domain groups publisher records. When organization data is unavailable, the fallback basis and missing-name warning remain explicit.

**Implementation:** [organization and normalize_review](../src/pehchan/records.py).

## ADR-012 — Preserve provenance and check prepared-record consistency

**Status:** Implemented. **Flows:** F-05, F-06, F-11, F-16.

**Decision:** Keep the complete parsed source record, original rating, source label, file hash, one-based review index and license data. Before ingesting, recompute normalization from each prepared row's raw record and compare the entire normalized row.

**Why:** Readers need to trace reported values back to a particular source record and detect accidental edits to derived fields.

**Consequences:** This is a consistency check, not cryptographic authenticity verification: someone editing both raw and derived fields could pass it, and loading prepared data does not rehash the original downloaded file. Reingestion can replace stored source provenance for the same review ID; version history is not implemented.

**Implementation:** [load_prepared](../src/pehchan/ingestion.py), [UPSERT_REVIEW](../src/pehchan/queries.py).

## ADR-013 — Audit invalid records and abort rating conflicts

**Status:** Implemented. **Flows:** F-04, F-06.

**Decision:** Skip and report records missing required claim, source URL or rating data. Treat a repeated review ID with an equal rating object as a duplicate. Abort preparation if the same review identity has a different rating object. Write normalized output through a temporary sibling file, replacing the destination only after successful iteration.

**Why:** A broken record should be visible without stopping all usable records, but contradictory source ratings must not be resolved arbitrarily. An interrupted parse must not overwrite a previous normalized dataset with partial output.

**Consequences:** Duplicate detection is by review identity and rating, not byte-for-byte raw-record equality; other metadata differences do not create a second accepted row. Conflict reports are written before aborting. A parser/I/O failure does not guarantee a fresh report, and replacing output plus writing its report is not one atomic transaction. A limit only examines the scanned prefix of the feed.

**Implementation:** [prepare](../src/pehchan/ingestion.py), [ingestion tests](../tests/test_ingestion.py).

## ADR-014 — Separate curated relationships from source records

**Status:** Implemented. **Flows:** F-07, F-09, F-12.

**Decision:** Store frame, topic and entity annotations in a separate JSON array, referencing existing variant IDs. Require `reviewed_by` and `rationale`; require entity type and a normalized evidence span occurring in the claim. Store annotation origin on graph edges.

**Why:** ClaimReview markup does not itself supply the proposed narrative taxonomy. Text extraction and thematic interpretation must not be passed off as publisher evidence.

**Consequences:** The sample annotations disclose Codex assistance and pending human review. The span check establishes text presence, not correct entity disambiguation. Annotations attach to canonical claims, are merged in place, and do not have full version/removal history.

**Implementation:** [annotation validation](../src/pehchan/annotations.py), [sample annotations](../data/samples/annotations.json).

## ADR-015 — Separate claims, wordings, sources and context nodes

**Status:** Implemented; Investigation reservation activated by ADR-035. **Flows:** F-08, F-09, F-26.

**Decision:** Use `ClaimVariant`, `Claim`, `FactCheck`, `Publisher`, `Entity`, `NarrativeFrame`, and `Topic`. Reserve an ID index for `Investigation`. Link fact-checks to variants; link frames, topics and entities to canonical claims.

**Why:** Multiple publishers can review the same wording, and different claims can share context without becoming the same factual proposition. Investigation state should eventually remain distinct from the knowledge being examined.

**Consequences:** No placeholder investigation nodes are inserted. ADR-035 now creates real Investigation records with `EXAMINES` and `CITES`. Shared variant/publisher properties reflect the latest write; per-review raw markup remains the source for historical details.

**Implementation:** [schema](graph-schema.md), [query definitions](../src/pehchan/queries.py).

## ADR-016 — Use sequential, repeatable graph writes

**Status:** Implemented. **Flows:** F-08, F-09, F-21.

**Decision:** Create ID range indexes, tolerate only the known already-indexed response, and use parameterized `MERGE`. Write each source review in one query, then apply annotations in separate queries. Validate input before initiating writes. Operate with one ingestion process per graph.

**Why:** This keeps the milestone simple and supports safe sequential retries without requiring a whole-dataset transaction or concurrency system.

**Consequences:** An interrupted ingestion can leave a valid partial dataset; rerun to finish. Range indexes do not enforce uniqueness. Concurrent writers, stale-edge reconciliation, migrations, and dataset-wide rollback are not implemented. No deletion is implied by removing a row from an input file.

**Implementation:** [GraphStore.init_schema and ingest](../src/pehchan/graph.py).

## ADR-017 — Bound queries and separate graph reads from writes

**Status:** Implemented. **Flows:** F-08 through F-16, F-20.

**Decision:** Keep query templates in code and pass values as SDK parameters. Generate annotation labels/relationships only from a fixed allowlist. Use `ro_query` for exploration, a 10,000 ms read-query timeout, 5-second connection timeout and 30-second socket timeout. Validate graph names and expose bounded result/depth limits.

**Why:** User claim text and IDs should be data rather than executable Cypher. Expensive exploration needs limits and failures must surface without echoing credentials.

**Consequences:** These are application boundaries, not separate database-user permissions or remote authentication. Database/server limits may also apply. No general-purpose Cypher execution tool is exposed.

**Implementation:** [GraphStore](../src/pehchan/graph.py), [queries](../src/pehchan/queries.py), [CLI errors](../src/pehchan/cli.py).

## ADR-018 — Use a lexical retrieval baseline until semantic verification exists

**Status:** Retained as an explicit lexical baseline; semantic retrieval added by ADR-030/ADR-031. **Flows:** F-10, F-24.

**Decision:** Tokenize normalized claim text with `\w+`, use Counter-based Jaccard overlap, discard zero scores, and sort by descending rounded score with variant-ID tie breaking. Label results `unverified_candidate` and `token_jaccard_baseline`.

**Why:** A transparent baseline proves the source-to-graph retrieval flow without a model download, provider key, or unsupported semantic-equivalence claim.

**Consequences:** Counts of repeated tokens influence the baseline score. Its `search` command has no stopword removal, translation or confidence calibration. Nonzero overlap is a candidate, not proof of relevance; missing matches establish no truth verdict. This baseline reads all variants into Python. New `semantic-search`/`scout` commands use the separate indexed workflow rather than silently changing this command's meaning.

**Implementation:** [GraphStore.candidates](../src/pehchan/graph.py).

## ADR-019 — Return explicit narrative paths and uncertainty

**Status:** Implemented. **Flows:** F-11, F-12.

**Decision:** Traverse variant → claim → frame ← claim ← related variant, retrieve that related variant's review and publisher, and return ordered node IDs, relationship types, source URLs/ratings, and edge provenance. Mark every result `narrative_context_only`.

**Why:** The relationship supporting a finding should be inspectable, and a thematic neighbor's verdict must not become a verdict on the submitted claim.

**Consequences:** Only existing annotated connections can be returned. Shared frames or entities do not establish factual equivalence or coordinated activity. An absent path is an empty result, not a generated explanation.

**Implementation:** [NARRATIVE_PATHS](../src/pehchan/queries.py), [narrative_paths](../src/pehchan/graph.py).

## ADR-020 — Use a bounded undirected path query

**Status:** Corrected. **Flows:** F-13.

**Decision:** Enumerate undirected paths of one to eight relationships across `EXPRESSES`, `USES_FRAME`, and `MENTIONS`; return one minimum-length path within that bound.

**Why:** Live testing showed that this FalkorDB server rejects the attempted native undirected `shortestPath` form. A bounded Cypher path query supports the required mixed-direction narrative and entity connections. Excluding topic/publisher edges avoids weak shortcuts through broad subjects or reviewing organizations.

**Consequences:** The method name `shortest_path` describes a bounded result, not a native shortest-path algorithm or a guarantee about paths beyond eight hops. Dense annotated graphs can still make enumeration expensive. Native BFS is separately tested as the database algorithm.

**Implementation:** [SHORTEST_PATH](../src/pehchan/queries.py), [integration tests](../tests/test_graph_integration.py).

## ADR-021 — Execute native BFS with explicit traversal limits

**Status:** Implemented. **Flows:** F-14, F-16.

**Decision:** Call FalkorDB `algo.BFS` on a matched variant, passing depth and a null relationship filter. Default depth is 3; the application accepts 1–6.

**Why:** The milestone needs a genuinely executed graph algorithm, not a Python traversal over copied data.

**Consequences:** On the tested server BFS follows outgoing edges and returns reachable nodes after the starting node. It does not provide the mixed-direction narrative traversal. Its returned edge collection is not one evidence path. Missing start nodes return no matching query row.

**Implementation:** [BFS](../src/pehchan/queries.py), [bfs](../src/pehchan/graph.py).

## ADR-022 — Use environment-based connection configuration

**Status:** Implemented. **Flows:** F-01, F-20.

**Decision:** Read `FALKORDB_HOST`, `PORT`, `GRAPH`, `PASSWORD`, `USERNAME`, and `SSL` directly from process environment. Let `--graph` override the graph variable. Supply `.env.example`, but do not automatically load `.env` in Python.

**Why:** Connection behavior remains explicit and suitable for later deployment without requiring another configuration dependency.

**Consequences:** Copying `.env.example` alone does not configure the Python process. SSL is enabled by the literal case-insensitive value `true`. Defaults target the local development service, not a public deployment.

**Implementation:** [.env.example](../.env.example), [GraphStore constructor](../src/pehchan/graph.py).

## ADR-023 — Pin the database image and tested dependencies

**Status:** Implemented. **Flows:** F-01, F-02, F-19.

**Decision:** Use Docker Compose with the combined FalkorDB/server-browser image pinned by digest. Keep supported dependency ranges in `pyproject.toml` and the tested dependency versions in `requirements.lock`, used as pip constraints. Use pytest and Ruff for checks.

**Why:** Graph query compatibility and bundled browser behavior should be repeatable. Pinning the tested environment limits accidental changes during a short milestone.

**Consequences:** Image/dependency upgrades require fresh validation. The lock file is a version constraints list, not a hash-verified installer lock. The project remains installable as an editable package. The portable `.tools` runtime was a local workaround for missing Python on PATH, not a deployment requirement.

**Implementation:** [Compose](../compose.yaml), [metadata](../pyproject.toml), [constraints](../requirements.lock).

## ADR-024 — Expose separate local database and browser ports

**Status:** Corrected. **Flows:** F-02.

**Decision:** Bind host `127.0.0.1:16379` to container database port `6379`, and host `127.0.0.1:3000` to browser port `3000`.

**Why:** Host port 6379 was already occupied. The initial Compose file exposed only the database, so the browser running inside the container could not be reached from the laptop. Adding its mapping resolved the user's port-3000 issue.

**Consequences:** Laptop Python clients use port 16379. The bundled browser's server-side connection uses container-local port 6379. This is a localhost-only, passwordless development setup, not an authenticated remote service.

**Implementation:** [Compose](../compose.yaml), [browser instructions](../README.md).

## ADR-025 — Persist the actual database directory and enable AOF

**Status:** Corrected; supersedes the original `/data` mount and command-only flag configuration. **Flows:** F-02, F-21.

**Decision:** Mount the named volume at `/var/lib/falkordb/data` and pass `--appendonly yes --appendfsync everysec` through `REDIS_ARGS`.

**Why:** Inspecting the running image showed its data directory is `/var/lib/falkordb/data` and its startup script reads `REDIS_ARGS`, not the supplied command arguments. The first container recreation therefore cleared the unpersisted graphs. Both graphs were rebuilt from saved input, the configuration was corrected, and another recreation confirmed retention.

**Consequences:** The named volume retains the database through ordinary container recreation. AOF syncs every second, so this is not a promise of zero loss after an abrupt host failure. A volume is not an independent backup; deleting the volume still deletes its data. Source snapshots remain necessary for reproducibility and recovery.

**Implementation:** [Compose](../compose.yaml); observed `CONFIG GET dir appendonly` and post-recreation graph/statistics checks on 18 October 2026.

## ADR-026 — Separate main, demo and test graphs

**Status:** Implemented. **Flows:** F-09, F-18, F-19.

**Decision:** Use `pehchan` for the larger dataset, `pehchan_demo` for the stable sample, and unique `pehchan_test_*` names for integration tests. Delete only the test-owned graphs in test cleanup.

**Why:** Demo preparation hashes a different file from the original feed; importing its records into the main graph would replace provenance for shared review IDs. Test cleanup must not remove development data.

**Consequences:** Graph choice is part of every reproducible command. These are logical namespaces in one database, not separate credentials or access controls. The demo graph persists; tests clean up their temporary graphs.

**Implementation:** [demo runner](../scripts/validate_demo.py), [integration tests](../tests/test_graph_integration.py).

## ADR-027 — Validate source fidelity and real graph execution

**Status:** Implemented. **Flows:** F-16, F-18, F-19.

**Decision:** Compare retrieved review IDs, URLs, ratings, raw markup, file hashes and source indices against prepared input. Check duplicate node IDs, orphaned reviews and variant-to-claim cardinality. Execute BFS and look for a narrative path; require one with `--require-narrative`. Reproduce the connected pair with the bounded path query.

**Why:** Successful insertion alone does not prove that evidence can be recovered unchanged or that the connected workflow actually works.

**Consequences:** Validation returns structured failures and a nonzero exit code. It is a defined set of integrity checks, not a complete schema constraint system, complete source verification, or test of every edge. Snapshot reports are evidence of a past run, not live monitoring.

**Implementation:** [validate](../src/pehchan/graph.py), [snapshot](validation.json).

## ADR-028 — Keep source data, generated artifacts and fixtures distinct

**Status:** Implemented. **Flows:** F-03, F-17 through F-19, F-21.

**Decision:** Ignore large raw downloads, processed datasets, runtime environments, caches, `.env` and generated artifacts. Keep the small genuine sample, manifest, annotations, source code, tests, and reviewed validation snapshot in the repository. Restrict fabricated fixture records to tests with `.example` URLs.

**Why:** The repository should remain practical to clone and should distinguish genuine evidence records from synthetic tests and regenerable local output.

**Consequences:** A fresh clone can run the sample but must download or otherwise obtain the full feed to reproduce the larger dataset. Reports under `artifacts/` are local. No automated backup or report publication pipeline exists.

**Implementation:** [.gitignore](../.gitignore), [sample directory](../data/samples/), [test fixtures](../tests/conftest.py).

## ADR-029 — Maintain decision and flow registers together

**Status:** Implemented by this documentation change. **Flows:** F-22.

**Decision:** Use one capitalized `Docs` directory containing `Decision.md`, `Flow.md`, the graph reference, and the validation snapshot. Preserve historical decisions and give decisions/flows stable IDs. Link both registers from the README.

**Why:** The user requested a continuing catalogue of architecture and project flows. Consolidating the existing lowercase directory also avoids case-dependent links breaking on GitHub or Linux.

**Consequences:** Every future architectural or flow change should update the registers with its implementation. Root agent instructions reinforce this convention; no automated freshness enforcement exists.

**Implementation:** [this register](Decision.md), [flow register](Flow.md), [agent instructions](../AGENTS.md), [README](../README.md).

## ADR-030 — Run pinned local embedding and relevance models

**Status:** Implemented. **Flows:** F-23, F-24. **Replaces:** the embedding deferral in ADR-018/P-001.

**Decision:** Use Sentence Transformers `paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions) for retrieval and `cross-encoder/nli-deberta-v3-small` for relevance. Pin repository revisions, download safetensors/configuration files explicitly into ignored `.models`, and load with CPU inference, local-only files and no remote code. Keep model installation in the `semantic` extra.

**Why:** The mixed-language collection benefits from multilingual retrieval. A separate NLI model can test textual entailment and contradiction without an external LLM key or sending submitted claims to a provider.

**Consequences:** Setup needs model downloads and disk/RAM, but investigation inference is local afterward. Model-directory markers check expected identity; they are not signed authenticity attestations for a manually altered cache. English-only NLI is a separate limitation from multilingual retrieval. Embedding models truncate to their own sequence limit; retrieved candidates still need the relevance checks in ADR-032. Model scores are never publisher verdicts.

**Implementation:** [models](../src/pehchan/models.py), [model cards](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2), [NLI model card](https://huggingface.co/cross-encoder/nli-deberta-v3-small).

## ADR-031 — Keep vectors, index and freshness metadata in FalkorDB

**Status:** Implemented. **Flows:** F-23, F-24.

**Decision:** Store normalized float32 embeddings on ClaimVariant, with model ID, pinned revision and source-text SHA-256. Use a 384-dimensional cosine vector index and native `db.idx.vector.queryNodes`. Incrementally encode only missing/stale variants; reject semantic reads when the graph has incomplete/stale vector coverage or an incompatible index.

**Why:** Retrieval and connected reasoning should share one database. Explicit provenance prevents vectors from different model versions or changed text being silently mixed.

**Consequences:** The tested server returns cosine distance, verified with identical and orthogonal vectors. Convert distance to similarity with `1 - distance`; sort distance ascending. ANN retrieval is approximate. Freshness checks currently scan variant metadata and index status on each request, appropriate for this seed but not optimized for a large corpus. Indexing is single-writer and per-row; interrupted work is rerunnable. Dataset expansion requires another `embed` pass.

**Implementation:** [VectorIndex](../src/pehchan/semantic.py), [distance/staleness regression test](../tests/test_semantic.py), [FalkorDB vector reference](https://docs.falkordb.com/cypher/indexing/vector-index).

## ADR-032 — Require two-direction relevance and allow abstention

**Status:** Implemented. **Flows:** F-24.

**Decision:** Retrieve up to 20 neighbors; default 10. Below cosine similarity 0.45, label irrelevant. For remaining pairs, require both language detections to be English with score at least 0.9 and the full pair to fit the 512-token NLI budget. Both directional entailment scores must reach 0.8 for `SAME_PROPOSITION`; both contradiction scores must reach 0.8 for `CONTRADICTION`. A one-direction contradiction is uncertain. Remaining pairs are related context at similarity >=0.5, otherwise irrelevant. Unsupported language/length produces `UNCERTAIN` rather than a fabricated classification.

**Why:** Similar words, negation, shared entities or one-way entailment must not automatically become equivalent claims. Conservative misses are preferable to silently reassigning an unrelated review's verdict.

**Consequences:** These are explicit engineering thresholds, not calibrated correctness probabilities. NLI can still err, including false contradiction assessments, so its output remains labeled model inference. The fixed smoke evaluation has one known missed direct paraphrase, preserved in the report. Only same-proposition candidates go to Graph Detective; other context remains visible for human review. No learned model assigns factual truth.

**Implementation:** [ClaimScout/classify](../src/pehchan/semantic.py), [fixed evaluation cases](../data/evaluation/semantic_cases.json).

## ADR-033 — Use constrained specialist workflows and capability sets

**Status:** Implemented. **Flows:** F-25.

**Decision:** Claim Scout uses embedding/NLI models; Graph Detective invokes existing path/BFS tools; Evidence & Response re-fetches sources and applies an explicit decision policy. Each has its own instruction, allowed tool names, structured handoff and actual tool trace. A lightweight orchestrator conditionally delegates. Skip graph exploration when Scout has no direct candidate.

**Why:** The MVP needs collaborating specializations and traceable tool use without an external chat-model dependency or unconstrained generated decisions.

**Consequences:** This remains the explicit deterministic baseline. ADR-041 adds the default generative tool-calling investigator over the same local retrieval and evidence policy. Baseline specialist instructions remain code contracts. The capability wrapper rejects unapproved tool names; it is an application boundary, not an OS sandbox. Traces report real completed/skipped operations. The UI shows actual traces after execution, with a spinner while the synchronous workflow runs.

**Implementation:** [policies, specialists and Orchestrator](../src/pehchan/investigation.py).

## ADR-034 — Assemble evidence before selecting an action

**Status:** Implemented. **Flows:** F-25.

**Decision:** Evidence & Response independently retrieves candidate sources again, excludes sources whose original reviewed wording mismatches the candidate, and keeps every citation's original rating/URL/provenance. Direct reviews with one normalized original rating and no contradictory candidate yield `EVIDENCE_DOSSIER_READY`. Direct disagreements, contrary propositions or uncertain relevance yield `NEEDS_HUMAN_REVIEW`. Otherwise yield `INSUFFICIENT_EVIDENCE` / `NO_RELEVANT_FACT_CHECK_FOUND`. Explicit review requests force human review.

**Why:** A dossier must be assembled from records, not persuasive generated prose. A graph-driven action can be useful without pronouncing a new truth verdict.

**Consequences:** Different rating strings are conservatively sent for reconciliation even when a researcher might treat them as equivalent. Model false contradictions can also route otherwise usable evidence to review. Missing review dates remain quality warnings. Review priority is a simple explicit rule (human-review cases HIGH, others NORMAL), not a learned risk score. Source bodies are not fetched or independently verified.

**Implementation:** [EvidenceResponse](../src/pehchan/investigation.py), [integrity/decision tests](../tests/test_investigation.py).

## ADR-035 — Persist investigation snapshots and exact graph citations

**Status:** Implemented. **Flows:** F-26.

**Decision:** Store Investigation ID, submitted claim, action status, UTC creation timestamp, priority, JSON dossier snapshot and follow-up state. Link exactly cited variants/reviews through `EXAMINES` and `CITES`. Use random IDs by default or a hash of an explicit request ID for retry deduplication. Reject reuse for a different claim/review mode. Follow-up state (`OPEN`, `IN_PROGRESS`, `RESOLVED`) and notes can change separately from the evidence decision.

**Why:** The workflow must take a persistent action based on graph findings, including recording unresolved claims without inventing evidence edges.

**Consequences:** Saving a case and its links is one graph query. Empty-evidence cases remain valid and have no fabricated links. A repeated request returns the stored snapshot; it does not silently re-run changed models/data. Use a new request ID for a fresh investigation. Main/dossier source snapshots are retained in report JSON while underlying source nodes can evolve. Multi-process request races and globally enforced uniqueness remain outside this single-worker MVP.

**Implementation:** [CaseStore](../src/pehchan/investigation.py).

## ADR-036 — Share one service across HTTP and MCP, serialize local inference

**Status:** Implemented. **Flows:** F-27, F-28.

**Decision:** Use one ApplicationService, an RLock, lazy database/model initialization and cached model objects within the process. Provide FastAPI routes and an official Python MCP SDK 1.x maintenance-line server with stateless Streamable HTTP. Register six focused blueprint tools plus `investigate_claim`, with read/write annotations. Keep SDK `<2` because the implemented adapter uses the maintained FastMCP API.

**Why:** Both clients should invoke identical evidence and case logic. Local CPU models and single-writer case persistence need controlled concurrency. The SDK implements protocol lifecycle/transport rather than a handwritten MCP imitation.

**Consequences:** Use one API worker. Requests can wait behind model work; this is not a queue/multi-user scaling design. MCP annotations communicate behavior, while middleware enforces access. The service exposes no arbitrary Cypher, generic method-call endpoint, ingestion endpoint, or embedding-write tool. Public MCP hosting and an actual Claude cloud connector connection are not completed merely by serving localhost.

**Implementation:** [service](../src/pehchan/service.py), [API](../src/pehchan/api.py), [MCP](../src/pehchan/mcp_server.py).

## ADR-037 — Separate local access from authenticated public access

**Status:** Implemented. **Flows:** F-27, F-28.

**Decision:** Default to loopback listeners. Optional bearer read and write tokens are separate; read tokens cannot create/update cases. The combined MCP endpoint requires the write credential because it exposes action tools. Protect allowed Host/Origin values. Configuring public hosts requires distinct nonempty tokens; TLS is supplied by a deployment reverse proxy, not the localhost dev server.

**Why:** Read-only exploration and graph write actions need distinct capabilities before exposing the service beyond the laptop.

**Consequences:** This MVP has bearer-token access control, not OAuth, user accounts or tenant isolation. Health exposes only readiness/graph/coverage summary. The Streamlit UI reads its backend credential from environment; it does not publish the token as a widget. Dataset secrets/credentials are not embedded in source. Remote clients must support the configured authorization method; no unsupported cloud-client compatibility is claimed.

**Implementation:** [authorize middleware](../src/pehchan/api.py), [access tests](../tests/test_api.py), [.env.example](../.env.example).

## ADR-038 — Keep the product UI separate from database administration

**Status:** Implemented. **Flows:** F-29.

**Decision:** Use Streamlit on port 8501 for investigation, narrative exploration, dossiers and case follow-up. Fetch all application data/actions from the API. Render bounded interactive graphs with PyVis; distinguish curated edges with dashed styling. Allow node inspection, original source links and JSON dossier download. Keep the bundled FalkorDB browser on 3000 for direct database inspection.

**Why:** Users need a focused evidence workflow, not raw database configuration or a graph screenshot. One API also prevents the UI from duplicating decision logic.

**Consequences:** The UI has no direct graph/LLM write access. Source HTML is escaped/JSON-serialized, and only static CSS uses unsafe HTML rendering. Long source ratings are shortened only in headings; the original rating remains in the dossier body/export. The graph is a limited view, not the entire collection. UI workflow tests use Streamlit AppTest; live HTTP health/API tests complement them.

**Implementation:** [UI](../src/pehchan/ui.py), [dark theme with readable contrast](../.streamlit/config.toml), [adapter/rendering](../src/pehchan/ui_support.py), [UI tests](../tests/test_ui.py).

## ADR-039 — Test every milestone and report model limitations honestly

**Status:** Implemented. **Flows:** F-19, F-30.

**Decision:** Keep unit, live graph, local-model, API authorization, UI interaction, real MCP HTTP and real API smoke checks. Store fixed semantic examples and evaluation output. The semantic smoke gate requires all contradiction/distractor/unfamiliar/language-abstention cases and at least two of three illustrative paraphrases; report strict outcomes separately, including the known false negative.

**Why:** Data fidelity, model relevance, graph writes, protocol integration and interface behavior fail in different ways. A passing infrastructure suite must not be confused with perfect semantic accuracy.

**Consequences:** The current run has 38 passing pytest tests. Fixed semantic cases pass 10/11 strictly (2/3 direct paraphrases, all eight safety cases), not 100% model accuracy. The small examples are smoke checks, not a held-out calibration study. The official client discovered and called all seven MCP tools; the live API checks exercise all three action statuses. Results are recorded in a new MVP snapshot, preserving the earlier foundation snapshot.

**Implementation:** [MVP validation](mvp-validation.json), [semantic evaluation](../scripts/evaluate_semantic.py), [MCP smoke](../scripts/smoke_mcp.py), [API smoke](../scripts/verify_mvp.py).

## ADR-040 — Launch local services without weakening shell policy

**Status:** Implemented. **Flows:** F-31.

**Decision:** Provide a Python launcher that starts API/UI only when their health endpoints are unavailable and ports are free. Use the invoking Python environment, loopback listeners, hidden Windows processes, local logs and process-ID records. Keep foreground commands documented for other environments.

**Why:** This machine disallows PowerShell script execution. A Python launcher avoids modifying or bypassing that policy while keeping setup convenient.

**Consequences:** Startup is asynchronous; read logs/health after launch. The launcher does not install dependencies, ingest data, embed claims, or automatically restart an occupied unhealthy service. It is not a production process supervisor, TLS terminator or deployment platform.

**Implementation:** [run_local.py](../scripts/run_local.py).

## ADR-041 — Use hosted Gemma tool calling with authoritative evidence checks

**Status:** Implemented; live provider verification requires a configured key. Default-mode selection amended by ADR-043 (the default is now `auto`). **Flows:** F-25, F-26, F-27, F-28, F-29, F-32, F-33. Extends ADR-033/ADR-034/ADR-036.

**Decision:** Default application/CLI investigations to Google AI Studio's Gemini API, model `gemma-4-26b-a4b-it`, configurable through `PEHCHAN_LLM_MODEL`. Use documented generateContent REST via the existing HTTPX dependency, with an explicit manual model→tool→model loop. Preserve complete model content, call IDs and opaque thought signatures. Send six function declarations: semantic Scout, publisher evidence, narrative exploration, bounded path, BFS and structured completion. Preserve `PEHCHAN_INFERENCE=deterministic` as an explicit offline mode. Direct library Orchestrator users may inject an inference implementation; without one they retain the original deterministic behavior.

**Why:** The user selected Gemma 4 with AI Studio keys and requested actual tool-calling inference. Google documents this model and native function calling in its [Gemma API guide](https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api). The small REST adapter avoids a new SDK/version dependency while retaining provider-injected protocol tests. Local embedding/NLI relevance assessment and source policy already exist and should remain auditable.

**Consequences:** Gemma chooses the tool sequence; it must search the exact original claim once, fetch every direct/contradictory candidate's evidence and explore the first three direct handoffs before finishing. IDs and arguments are validated in code. Graph IDs are bounded to Scout handoffs; paths may also use returned narrative neighbors. No model write/Cypher/web-fetch capability exists. EvidenceResponse checks reviewed wording, preserves publisher records and decides case status; successful assembly precedes existing persistence. Analyst notes are unverified model commentary with validated reference IDs, not factual verdicts. The model cannot override statuses, URLs or ratings through its completion schema. The UI renders its note as plain text.

**Operational limits:** Eight model turns, 24 calls, 180,000 serialized context characters, 2,048 output tokens per response, 45-second HTTP timeouts and a 120-second elapsed check between turns. A running HTTP/tool call may overrun that between-turn threshold. No automatic retry or fallback hides provider failure; requests fail without creating a case. Existing request IDs still return historical snapshots. Keys stay in process environment/header, never in report, URL or error bodies. Submitted claims and selected source/context data leave the laptop; raw markup and file provenance metadata are removed recursively from provider results. Key presence is exposed as readiness configuration, not a successful credential/access check. The existing lock serializes this synchronous workflow; it is not a concurrent agent service.

**Implementation:** [inference loop/REST adapter](../src/pehchan/inference.py), [service](../src/pehchan/service.py), [CLI](../src/pehchan/cli.py), [protocol/guard tests](../tests/test_inference.py), [live smoke](../scripts/smoke_inference.py), [setup](../README.md#configure-gemma-inference).

## ADR-042 — Annotate the whole collection with explicit keyword rules

**Status:** Implemented 18 October 2026. **Flows:** F-07, F-09, F-12, F-13, F-34. Extends ADR-014; the curated 12-claim sample is retained unchanged.

**Decision:** Generate frame, topic and entity annotations for every prepared variant with [scripts/annotate_collection.py](../scripts/annotate_collection.py): fixed, reviewable regular-expression rules for 10 narrative frames, 4 topics and 53 named entities (people, organizations, places, technologies, events). Entity spans are copied from the matched claim text so ADR-014's span check still applies. Curated sample rows are merged first and keep their frames. Output goes to tracked `data/annotations/collection.json` and is ingested with the existing `--annotations` path.

**Why:** Only 12 of 248 claims were annotated (2 entities, 5 frames), so narrative traversal and entity bridges barely existed in the main graph. Track 1 multi-hop reasoning needs shared entities across claim clusters. Explicit rules are reproducible and auditable, unlike unrecorded manual or LLM labelling, and need no network access.

**Consequences:** The main graph now has 10 frames, 53 entities, 203 `USES_FRAME`, 252 `ABOUT_TOPIC` and 356 `MENTIONS` edges, enabling cross-topic bridges (for example a vaccine-microchip claim to a climate claim via `Bill Gates`). Rules are keyword matches, not disambiguation or proposition understanding: they can over- or under-assign, multilingual coverage is partial, and every edge is labelled `reviewed_by` the rule script with human review pending. Rule frames are thematic, not evidence of coordination. Ingestion merges, so removing a rule does not delete existing edges (ADR-014 limitation). Variant IDs depend on the local feed snapshot; a new download needs the script rerun.

**Implementation:** [annotator](../scripts/annotate_collection.py), [output](../data/annotations/collection.json), [loader](../src/pehchan/annotations.py).

## ADR-043 — Default to automatic inference-mode selection

**Status:** Implemented 18 October 2026. **Flows:** F-01, F-29, F-32, F-33. Amends ADR-041's default; ADR-041's Gemma loop and guards are unchanged.

**Decision:** `PEHCHAN_INFERENCE` accepts `auto` (new default), `gemini` and `deterministic`. `auto` resolves at configuration time: Gemma when `GEMINI_API_KEY`/`GOOGLE_API_KEY` is present, otherwise the offline specialist workflow. `configuration()` reports both `requested` and resolved `mode`; `/health` and the UI show which is active. Explicit `gemini` without a key still fails with HTTP 503.

**Why:** With the previous `gemini` default, a fresh clone or a judge without credentials received 503 for every investigation even though the complete offline workflow exists.

**Consequences:** Resolution happens per request at configuration time, never as a mid-request fallback: a provider/quota failure during a Gemma run still fails explicitly without a case (ADR-041). Operators who require hosted inference must set `gemini` explicitly to keep the fail-closed behavior.

**Implementation:** [configuration](../src/pehchan/inference.py), [UI indicator](../src/pehchan/ui.py), [test](../tests/test_inference.py), [.env.example](../.env.example).

## ADR-044 — Declare parameterized MCP return types

**Status:** Implemented 18 October 2026. **Flows:** F-28. Extends ADR-037.

**Decision:** Annotate MCP tool returns as `dict[str, Any]`, `list[dict[str, Any]]` or `list[Any]` instead of bare `dict`/`list`.

**Why:** The SDK generates an output schema and `structuredContent` only for parameterized annotations; `find_similar_claims`, `find_evidence_path`, `assemble_evidence_dossier`, `create_review_case` and `investigate_claim` returned text-only content.

**Consequences:** All seven tools now return structured content (verified by `scripts/smoke_mcp.py`). Schemas are generic objects/arrays, not field-level models.

**Implementation:** [MCP adapter](../src/pehchan/mcp_server.py), [smoke check](../scripts/smoke_mcp.py).

## ADR-045 — Widen through shared entities and frames when no direct match exists

**Status:** Implemented 18 October 2026. **Flows:** F-25, F-28, F-32, F-35. Extends ADR-033/ADR-042.

**Decision:** After Scout and Evidence & Response, if no `SAME_PROPOSITION` citation exists, Graph Detective calls a new permitted tool, `expand_shared_context`. It tags the submission with the same keyword rules used for the collection ([rules.py](../src/pehchan/rules.py)) and runs the fixed `SHARED_CONTEXT` Cypher: fact-checked claims connected to those Entity/NarrativeFrame nodes, scored by the sum of `1/degree` of shared nodes. Hits below 0.05 (only hub nodes such as `5G`, used by 111 claims, shared) are dropped. The step runs in deterministic, Gemma and recall modes. The same widening is exposed read-only as MCP tool `expand_narrative_context`.

**Why:** Without it, a new wording of a known narrative ended as `INSUFFICIENT_EVIDENCE` even when the graph held reviews of closely related claims. Track 1 asks for agents that choose their next step from what the graph returned.

**Consequences:** Widened results are reported under `widening.related` with every shared node's relation, basis and reviewer. They are never added to `citations` or `CITES` edges. Rule tags are partial for non-Latin scripts (for example a Devanagari "Putin" is not tagged). The 0.05 cut-off is a fixed engineering threshold, not a tuned value.

**Implementation:** [Graph Detective / Orchestrator](../src/pehchan/investigation.py), [store method](../src/pehchan/graph.py), [query](../src/pehchan/queries.py), [service](../src/pehchan/service.py), [MCP tool](../src/pehchan/mcp_server.py), [tests](../tests/test_investigation.py).

## ADR-046 — Classify findings, draft cited replies and write submissions back to the graph

**Status:** Implemented 18 October 2026. **Flows:** F-25, F-26, F-29, F-35, F-36. Extends ADR-034/ADR-035; the three action statuses remain authoritative.

**Decision:** Every report gains a `finding`: `KNOWN_RECYCLED_CLAIM` (a direct publisher review exists), `KNOWN_NARRATIVE_VARIANT` (widening hits, or semantic context at least 0.6 similar) or `NEW_CLAIM`. A narrative variant that would otherwise be `INSUFFICIENT_EVIDENCE` becomes `NEEDS_HUMAN_REVIEW` / `RELATED_NARRATIVE_CONTEXT_FOUND`. New claims and review cases are marked `review_queue.queued` with HIGH priority. A template `draft_reply` cites only graph records (direct reviews, then closest recorded wordings with their similarity and relevance label, then widened claims) and is labelled `DRAFT_REQUIRES_HUMAN_APPROVAL`. On persistence, the wording is written as a `Submission` node (own FalkorDB vector index) linked `(Investigation)-[:SUBMITTED]->`, `-[:MATCHES]->` its direct matches with the Scout assessment, and `-[:MENTIONS]->`/`-[:USES_FRAME]->` its rule tags. Before investigating, the orchestrator queries that index. A submission at least 0.95 similar to one with a direct match is answered by following its MATCHES edges (`inference.mode = graph_recall`) without rerunning retrieval, NLI or Gemma.

**Why:** Track 1 rewards actions taken from graph findings and agents that change the graph. Repeated forwards are the common case for fact-checkers, and an LLM-written reply could invent sources.

**Consequences:** A recalled answer reuses an earlier relevance assessment for a near-identical wording; this is disclosed in the Scout uncertainty, and `force_review` bypasses recall. Read-only dossiers recall but never write. Submissions add `Submission`, `SUBMITTED` and `MATCHES` to the schema; graph validation still passes. Recall depends on the scout exposing `embed`; test stubs without it skip memory. Old case snapshots lack the new fields, and the UI tolerates that. The reply is a template, not generated prose.

**Implementation:** [decide/draft_reply/recall/link_submission](../src/pehchan/investigation.py), [SubmissionIndex](../src/pehchan/semantic.py), [queries](../src/pehchan/queries.py), [UI](../src/pehchan/ui.py), [tests](../tests/test_investigation.py), [schema](graph-schema.md#submission-write-back-and-recall).

## ADR-047 — Report a held-out retrieval comparison without tuning

**Status:** Implemented 18 October 2026. **Flows:** F-30, F-37.

**Decision:** Add 30 author-written held-out queries (24 paraphrases, 6 translations) and [evaluate_retrieval.py](../scripts/evaluate_retrieval.py), which compares word overlap, the FalkorDB vector index, and vector index plus shared-context re-ranking (pool 20, weight 0.1, both fixed before running) by hit@1/hit@5 against accepted recorded wordings.

**Why:** A reviewer asked for evidence that the graph does real work in retrieval.

**Consequences:** Measured on 18 October 2026: word overlap 25/30, embeddings 30/30, embeddings plus graph 30/30 at both k. Embeddings saturate this set, so graph re-ranking shows no retrieval gain; that result is reported as is. The graph's demonstrated role is widening, recall and explanation, not top-5 retrieval. Queries were written with Claude Code assistance and are a smoke-scale check.

**Implementation:** [cases](../data/evaluation/heldout_cases.json), [script](../scripts/evaluate_retrieval.py), [report](retrieval-evaluation.json).

## ADR-048 — Serve a static web app from the API

**Status:** Implemented 18 October 2026. **Flows:** F-38. Complements ADR-038; Streamlit remains for case follow-up.

**Decision:** Serve a single static page ([index.html](../src/pehchan/web/index.html), [site.css](../src/pehchan/web/assets/site.css), [app.js](../src/pehchan/web/assets/app.js)) at `/` from FastAPI. Light poster-style design (cream paper, Anton display type, marquee band, numbered steps), inspired by the reference site the user chose. Vanilla JS calls the existing API; vis-network (pinned 9.1.9 from unpkg) draws the graph; Google Fonts supplies Anton, Inter and Noto Sans Devanagari. `color-scheme: only light` keeps it light even where browsers force dark rendering.

**Why:** One origin for the page, API and MCP makes a single public URL possible, and the user asked for this look.

**Consequences:** Investigations from the page are read-only dossiers. "Save as case" calls the write route and prompts for the write token when tokens are set; the token stays in session storage. All record and user text is inserted with `textContent`. Tool steps appear after the request completes; they are not streamed. `/?claim=…` runs a claim on load for shareable demo links. External CDN and font requests are made by the visitor's browser.

**Implementation:** [web files](../src/pehchan/web/), [routes](../src/pehchan/api.py), [package data](../pyproject.toml).

## ADR-049 — Public read-only MCP endpoint and quick-tunnel hosting

**Status:** Implemented and verified on a live quick tunnel 18 October 2026. **Flows:** F-27, F-28, F-39. Extends ADR-036/ADR-037.

**Decision:** Mount a second MCP server at `/public/mcp/` built with `include_write=False` (six read tools; no `investigate_claim`/`create_review_case`). With `PEHCHAN_PUBLIC_READ=1`, the page, `/health`, `/api/config`, read-only graph/evidence/path routes, `/api/scout`, `/api/dossier` and `/public/mcp/` need no credentials; compute calls are limited per visitor (`CF-Connecting-IP`/`X-Forwarded-For`, default 30 per 10 minutes). Case history, writes and `/mcp/` keep token checks. `scripts/run_public.py` publishes this through a Cloudflare quick tunnel.

**Why:** claude.ai and ChatGPT custom connectors accept URLs with no auth or OAuth, not static bearer tokens, and Gemini CLI takes a plain `httpUrl`. A read-only public endpoint makes "paste one URL" work in all three without exposing write actions or case history. The SDK's Host check matches exact names only, so the launcher learns the tunnel hostname before starting the API.

**Consequences:** Anyone with the URL can run dossiers (CPU time and, if configured, Gemma quota) within the rate limit. Rate limits are per process and in memory. The quick-tunnel URL is ephemeral and depends on the laptop. Client-app connection was not tested from claude.ai, ChatGPT or Gemini themselves; the official MCP client over the public URL was. OAuth remains unimplemented.

**Implementation:** [API](../src/pehchan/api.py), [MCP](../src/pehchan/mcp_server.py), [launcher](../scripts/run_public.py), [tests](../tests/test_api.py), [deployment](Deployment.md#quick-public-demo-through-a-cloudflare-tunnel).

## ADR-050 — Chain hosted Gemma providers and disclose the offline fallback

**Status:** Implemented and live-tested 18 October 2026. **Flows:** F-25, F-32, F-33. Amends ADR-041 (no automatic fallback) and ADR-043 (auto selection).

**Decision:** Add an OpenRouter provider (OpenAI-compatible chat completions with tools) behind the same content format, so every loop validation applies unchanged. `auto` builds a chain of providers with keys, cheapest first: AI Studio (free tier) then OpenRouter, both on Gemma 4 31B by default (`PEHCHAN_GEMINI_MODEL`, `PEHCHAN_OPENROUTER_MODEL`). A failed or rate-limited provider hands the rest of the investigation to the next. If all fail, the orchestrator answers with the offline specialists and reports `deterministic_fallback` with the error and a trace step (`PEHCHAN_HOSTED_FALLBACK=0` restores fail-closed). In the loop, `find_similar_claims` takes no arguments; out-of-scope reads and premature finishes are refused back to the model with what is still required instead of aborting; references outside validated citations are dropped and listed in warnings and `inference.dropped_references`.

**Why:** The user wanted an open model with minimal credit use. Live runs showed AI Studio's 31B returning HTTP 500/503 and then 429, Gemma degenerating while retyping a Hindi claim, and models asking for out-of-scope records or citing narrative-only IDs. Aborting the whole investigation on any of these made the hosted path unusable in a demo.

**Consequences:** ADR-041's statement that no fallback hides provider failure is superseded: the fallback is automatic but always disclosed in the report, trace and UI. Citations and status still come only from application code; refusing a read reads nothing; dropping a reference never adds one. Mixed-provider runs are possible within one investigation and are recorded. OpenRouter use costs money per token; the free tier is intermittent.

**Implementation:** [providers, chain and loop](../src/pehchan/inference.py), [disclosed fallback](../src/pehchan/investigation.py), [tests](../tests/test_inference.py), [setup](../README.md#configure-gemma-inference).

## ADR-051 — Graph explorer and save flow driven by user feedback

**Status:** Implemented 18 October 2026. **Flows:** F-38. Extends ADR-048.

**Decision:** The web graph settles once and then freezes, shows labels for frames, entities and the focused claim, keeps labels readable when zoomed out, and has Fit / Whole collection / Back to your match controls and a click-for-details panel (connections with their basis, publisher reviews, focus here). After an investigation it focuses on the closest claim, or states that nothing in the graph connects to a new claim. On write-protected servers, saving shows an inline team-only panel instead of a browser prompt. The page declares `color-scheme: only light` and `darkreader-lock` because it is designed light.

**Why:** A tester found the graph impressive but hard to use, read the token prompt as an error, and thought the graph ignored new claims when it silently stayed on the overview.

**Consequences:** Public visitors still cannot save; the panel explains why. Browser extensions that respect neither signal may still restyle the page.

**Implementation:** [app.js](../src/pehchan/web/assets/app.js), [site.css](../src/pehchan/web/assets/site.css), [index.html](../src/pehchan/web/index.html).

## ADR-052 — Cover the 2026 events and stop places from bridging narratives

**Status:** Implemented 18 October 2026. **Flows:** F-04, F-09, F-23, F-34, F-35. Extends ADR-042/ADR-045.

**Decision:** Import every LPG and CJP review and the first 150 Iran and Ukraine reviews from the existing feed snapshot (395 unique reviews), with keyword rules for four new frames (fuel prices and shortages, recycled or fabricated war footage, protest crackdown and smear, leaders reported killed or disgraced), four topics and sixteen entities. A widened hit now needs a shared narrative frame or a shared non-place entity; shared places alone (India, China, Iran) no longer qualify. The reply for a claim with nothing related advises treating it as unverified and not forwarding it until confirmed.

**Why:** The landing page names these events, and a tester's LPG claim was matched to unrelated 5G fact-checks only because both mentioned India.

**Consequences:** The graph grows to 645 reviews, 641 variants, 69 entities and 14 frames; both datasets validate. Iran and Ukraine are sampled, not complete. The held-out retrieval evaluation (ADR-047) was measured on the earlier 248-variant graph and was not rerun. Rules are keyword inferences and miss some languages.

**Implementation:** [rules](../src/pehchan/rules.py), [widening filter and reply](../src/pehchan/investigation.py), [query](../src/pehchan/queries.py), [event annotations](../data/annotations/events.json), [README import steps](../README.md#import-the-larger-feed).

## ADR-053 — Default OpenRouter to GPT-OSS 120B and label the engine in plain words

**Status:** Implemented 18 October 2026. **Flows:** F-32, F-33, F-38. Amends ADR-050's OpenRouter default.

**Decision:** OpenRouter's default model is `openai/gpt-oss-120b` (open weights). Both the local and public instances run OpenRouter only, because AI Studio's Gemma 4 31B kept returning HTTP 500. The web page names the engine in plain words ("AI agent: GPT-OSS 120B via OpenRouter", "Answered from graph memory", "Offline agents (AI model busy)") instead of internal mode names, and shows the model's note in a box labelled as not verified.

**Why:** The user asked for the least credit use on OpenRouter. GPT-OSS 120B costs $0.15/$0.60 per million tokens versus $0.20/$0.40 for Gemma 4 31B, and in live runs finished in 3-5 tool calls on the LPG, Hindi Putin-5G and vaccine-microchip claims.

**Consequences:** Public dossier calls now spend OpenRouter credits, bounded by the per-visitor rate limit. The model's analyst note can still be wrong; citations and status remain application decisions.

**Implementation:** [default](../src/pehchan/inference.py), [labels and note](../src/pehchan/web/assets/app.js), [setup](../README.md#configure-gemma-inference).

## ADR-054 — Host on a Hugging Face Space with FalkorDB Cloud, deployed by CI/CD

**Status:** Implemented as code 18 October 2026; accounts and first deployment are operator steps. **Flows:** F-40, F-41. Complements ADR-049 (tunnel) as the permanent option.

**Decision:** A Docker Space ([Dockerfile](../deploy/huggingface/Dockerfile)) clones the public GitHub repository at a pinned ref, installs CPU PyTorch and the server extras, downloads both local models at build time, and runs one uvicorn worker on port 7860 behind the Spaces proxy. The graph lives in FalkorDB Cloud, reached through the existing `FALKORDB_*` variables (TLS included). [load_graph.py](../scripts/load_graph.py) fills any FalkorDB from the prepared datasets through the validated ingest path, then embeds. A GitHub Actions workflow lints and tests against a real FalkorDB service container on every push and pull request, and on `main` uploads the Space files with `PEHCHAN_REF` set to the tested commit.

**Why:** A permanent HTTPS address that works with the laptop off, at no cost, without server administration; a managed FalkorDB keeps the graph central and durable; CI/CD makes every deploy a tested commit.

**Consequences:** Cold starts after sleep are slow; real-model tests (1 GB download) stay local, so CI does not exercise NLI quality; deployment is skipped with a warning until `HF_TOKEN` and `HF_SPACE` exist. The image build was tested locally on 18 October 2026; the Space and FalkorDB Cloud have not been created from here.

**Implementation:** [Space files](../deploy/huggingface/), [loader](../scripts/load_graph.py), [workflow](../.github/workflows/ci-cd.yml), [operator guide](Deployment.md#hugging-face-space--falkordb-cloud-recommended-permanent-hosting).

## ADR-055 — Make AWS EC2 the permanent host with scripted setup and SSH deploys

**Status:** Implemented as code 18 October 2026; the instance, secrets and first run are operator steps. **Flows:** F-41, F-42. Supersedes ADR-054's choice of host; the Space files remain as an alternative.

**Decision:** [setup.sh](../deploy/ec2/setup.sh) provisions a fresh Ubuntu 24.04 instance in one command: packages, swap on small instances, the app and models, FalkorDB in Docker with the graph restored from a backup archive, `/etc/pehchan.env` with generated tokens, a systemd service, and Caddy for automatic HTTPS. The CI/CD workflow gains a `deploy-ec2` job that runs [update.sh](../deploy/ec2/update.sh) over SSH after tests pass on `main`: exact-commit checkout, dependency install, restart and health check.

**Why:** The user found Hugging Face Spaces not free for this use and has AWS credits. Free tiers elsewhere cap memory at 512 MB, below what the local models need.

**Consequences:** Hosting draws on AWS credits (roughly $25-35/month for a medium instance; check current prices). The server keeps its own FalkorDB, so saved cases persist across deploys; back it up with the archive command. `ssh-keyscan` trusts the host key on first use. Both deploy jobs skip with a warning until their secrets exist.

**Implementation:** [EC2 scripts](../deploy/ec2/), [workflow](../.github/workflows/ci-cd.yml), [operator steps](Deployment.md#aws-ec2-with-one-command-setup-and-cicd-recommended-permanent-hosting).

## ADR-056 — Use native algo.SPpaths for connection paths; graph loaded into FalkorDB Cloud

**Status:** Implemented and verified 18 October 2026. **Flows:** F-13, F-40. Supersedes ADR-020's bounded variable-length match.

**Decision:** `find_evidence_path` calls FalkorDB's `algo.SPpaths` with `relDirection: 'both'`, the same three relationship types, `maxLen: 8` and `pathCount: 1`, instead of enumerating every variable-length path and sorting by length. FalkorDB's `shortestPath()` was not usable because it does not support undirected traversals. The full graph (645 reviews, 641 embedded variants) was loaded into a FalkorDB Cloud instance in ap-south-1 with `scripts/load_graph.py`.

**Why:** After the 2026 event import, hub entities linked up to 150 claims and the enumerating query took 2.1 s locally and 4.4 s on FalkorDB Cloud, and timed out (10 s limit) during cloud validation. The algorithm returns the same path in 0.01 s locally and 0.05 s on the cloud.

**Consequences:** Both datasets validate on the cloud graph with `--require-narrative`; LPG and Hindi Putin-5G dossiers match local results. The cloud instance currently has TLS disabled (`FALKORDB_SSL=false`), so credentials travel unencrypted; enable TLS in the FalkorDB Cloud console when available and rotate the password that was shared in chat. Running services keep the local database until they are restarted with the cloud settings.

**Implementation:** [query](../src/pehchan/queries.py), [loader](../scripts/load_graph.py), [README Cypher](../README.md#core-cypher).

## ADR-057 — A live graph status badge and a flow diagram on the landing page

**Status:** Implemented 18 October 2026. **Flows:** F-38. Extends ADR-048/ADR-051.

**Decision:** Keep the page's own content, palette and Anton display type, and add two components of our own: a compact top bar with a live graph badge ("Graph live · 641 wordings") whose panel shows graph, engine, size, agent chain and access from `/health` and `/api/config`; and an isometric "point at any part" diagram of Pehchan's inputs, agents, graph and outputs with captions written for Pehchan. Smaller touches: the headline lines rise in on load, labels use Geist Mono, buttons are pills. The README keeps its content and gains a header (mark, badges, screenshot) and one overview table; the mark and screenshots live under `Docs/media/`.

**Why:** The user wanted the page to show, at a glance, that the graph is live and how a message flows through it, in the style of polished hackathon landing pages, without changing the page's story. An earlier version on 18 October 2026 (commits 179fde8..4deeb5f) rewrote the hero and the README in another project's voice; the user rejected it, the content was restored, and only components designed for Pehchan were kept.

**Consequences:** No new API routes; the badge degrades to "API unreachable". Diagram captions are authored in the page's own markup and inserted as text.

**Implementation:** [index.html](../src/pehchan/web/index.html), [site.css](../src/pehchan/web/assets/site.css), [app.js](../src/pehchan/web/assets/app.js), [README](../README.md), [media](media/).

## Blueprint status after the local MVP

This table preserves the original intention IDs while making their current boundary explicit.

| ID | Proposed choice and why | Current boundary / affected proposed flows |
| --- | --- | --- |
| P-001 | Sentence Transformers embeddings with separate relevance assessment | Implemented by ADR-030/ADR-031/ADR-032; local NLI provides an explicitly limited relevance assessment |
| P-002 | Three specialists and lightweight orchestration | ADR-033 retains the offline specialist baseline; ADR-041 adds a default Gemma tool-calling investigator using local retrieval and the authoritative response policy |
| P-003 | Explicit no-match and uncertainty branches | Implemented by ADR-034/ADR-035; ADR-045/ADR-046 add widening, the recycled/narrative/new finding, drafted replies and submission write-back; decisions are workflow actions, not new truth verdicts |
| P-004 | Official SDK, Streamable HTTP, focused tools and top-level investigation | Seven tools implemented/tested locally by ADR-036/ADR-037; public HTTPS deployment and cloud connector verification remain external deployment work |
| P-005 | Persistent Investigation, EXAMINES/CITES and case follow-up | Implemented by ADR-035; priority is rule-based and no case notification service exists |
| P-006 | FastAPI, Streamlit and interactive graph exploration | Implemented by ADR-036/ADR-038; Pehchan is on 8501, the separate DB browser remains on 3000 |
| P-007 | A generative LLM provider and optional online enrichment | Gemma/AI Studio integration implemented by ADR-041; live verification needs a key. Online enrichment remains deferred |
| P-008 | Keep real-time social monitoring, unrestricted crawling, deepfake analysis and model training outside MVP scope | No implementation of these capabilities; revisit only by explicit scope change |
