# Running and deploying Pehchan AI

The local MVP is implemented and tested. This document separates its complete local setup from public hosting that still requires a reachable machine/domain and deployment credentials. No public HTTPS URL or cloud connector is claimed to be active.

## Service map

| Service | Local address | Purpose |
| --- | --- | --- |
| Web app | `http://127.0.0.1:8000/` | Investigation desk, graph explorer, MCP connection guide |
| Streamlit | `http://127.0.0.1:8501` | Investigation, graph explorer, dossiers and case follow-up |
| FastAPI | `http://127.0.0.1:8000` | Application API; interactive schema at `/docs` |
| MCP | `http://127.0.0.1:8000/mcp/` | Eight Streamable HTTP tools (writes need the write token when tokens are set) |
| Public MCP | `/public/mcp/` with `PEHCHAN_PUBLIC_READ=1` | Six read-only tools, no credentials |
| FalkorDB browser | `http://127.0.0.1:3000` | Direct database inspection |
| FalkorDB protocol | `127.0.0.1:16379` | Python/database clients; not an HTTP page |

Inside the database container, Redis/FalkorDB listens on 6379 and the bundled browser connects there. Outside the container, Python uses the mapped 16379 port.

## Local prerequisites and launch

Follow the [root setup instructions](../README.md#set-up-the-complete-mvp-from-a-fresh-clone). The tested pinned environment is Python 3.12; the code supports Python 3.11+, but other Python versions may need compatible dependency resolution rather than this exact constraints snapshot.

The setup order is significant:

1. Install the project and selected extras (`semantic`, `server`, `ui`, `dev`); install CPU PyTorch from its official index for the tested CPU configuration.
2. Start Docker Compose and confirm database health.
3. Ingest the stable included sample using `scripts/validate_demo.py`, or import the larger prepared feed.
4. Run `download-models` once. Model IDs/revisions are fixed in [models.py](../src/pehchan/models.py).
5. Run `embed` against the intended graph. Re-run it whenever new claims are ingested or stored wording changes.
6. Set `FALKORDB_GRAPH` consistently in the API/UI environment. Fresh sample setup uses `pehchan_demo`; the current larger workspace uses `pehchan`.
7. Configure `GEMINI_API_KEY` in the backend environment for default Gemma tool calling, following [inference setup](../README.md#configure-gemma-inference). Alternatively select `PEHCHAN_INFERENCE=deterministic` for the explicit offline baseline.
8. Run `python scripts/run_local.py` or the two foreground commands in the README.

The Python launcher does not install models/data or change shell policy. It prints startup URLs and records new process IDs in `artifacts/local-processes.json`. Re-running it leaves a healthy running service alone; it does not reload changed API code. Foreground development runs can be stopped from their terminal. For background restarts, identify the process by its executable and command line before stopping it; do not terminate unrelated processes by port alone.

## Check readiness and behavior

`GET /health` reports collection/vector readiness plus inference mode/model/key-presence configuration. `setup_required` means source data, complete compatible embeddings, local model files or the default hosted inference key need setup. Key presence does not establish valid credentials, model access or quota. A database failure returns an operational error rather than pretending the collection is ready. This check does not perform inference; real model/semantic checks are separate.

```text
python scripts/evaluate_semantic.py --graph pehchan
python scripts/verify_mvp.py
python scripts/smoke_mcp.py
python scripts/smoke_inference.py
```

The API/MCP scripts use `PEHCHAN_API_URL` (default `http://127.0.0.1:8000`) and `PEHCHAN_WRITE_TOKEN` when configured. Their action tests create tagged, retry-deduplicated demo investigations. The fixed semantic evaluation contains one known conservative false negative and reports it explicitly; see [the MVP validation snapshot](mvp-validation.json).

The Gemma smoke uses ApplicationService directly and requires an AI Studio key in its own process environment. It creates a read-only dossier and local verification artifact. Investigation smoke calls now use configured inference; old request IDs can return historical snapshots. Use a fresh request ID for actual new inference. See the separate [inference verification snapshot](inference-validation.json) for the latest tested scope and pending live provider check.

## Three demonstration scenarios

| Scenario | Submitted claim / operation | What to inspect |
| --- | --- | --- |
| Historical review and dossier | `Scientists have had to pause the Climate Change Hoax Scam` | Recorded source, original rating, dossier-ready action; the publisher's rating text may be unusually long and is preserved |
| Entity bridge | `find_evidence_path` from `variant_700ff916add10df61b609425` to `variant_9e4e7b29e161704389906809` | Existing paths through explicitly mentioned 5G entity; do not interpret this as coordination |
| Unresolved autonomous action | `Underwater quartz clocks transmit encrypted rainfall forecasts.` | No confident match, Detective skipped, `INSUFFICIENT_EVIDENCE`, saved case without fabricated citations |

The microchip-scanner paraphrase in the UI placeholder demonstrates semantic retrieval, but full-collection NLI/source-context findings can conservatively route it to human review. Model inference is disclosed; no new truth verdict is generated.

## Configure access deliberately

Without credentials, application access is accepted only from loopback peers. Default API/UI bindings are loopback. To require credentials even locally, configure distinct values:

```text
PEHCHAN_API_TOKEN=<read credential>
PEHCHAN_WRITE_TOKEN=<different write credential>
PEHCHAN_UI_TOKEN=<credential the private UI should use>
```

Requests use `Authorization: Bearer <credential>`. Read access can inspect cases and run Scout/read-only dossier operations. Case creation/follow-up needs write access. The combined MCP endpoint requires the write credential because it includes action tools. Tool annotations also identify read/write effects but are not an access-control substitute.

There are no user accounts, tenant-specific case ownership, OAuth implementation, quotas or multi-worker locking. The deployed credential grants access to the configured collection. Run one API worker; the shared local service serializes model/graph operations.

## AWS EC2 with one-command setup and CI/CD (recommended permanent hosting)

Implemented as scripts and a pipeline (ADR-055, F-41, F-42). Pehchan needs about 3-4 GB of RAM for its two local models and FalkorDB, which rules out 512 MB free tiers; a t3.medium or t4g.medium with swap runs it on AWS credits.

1. **Back up the graph on the laptop:** `docker compose stop falkordb`, then `docker run --rm -v pehchan_falkordb-data:/data -v ${PWD}:/backup alpine tar czf /backup/falkordb-data.tgz -C /data .`, then `docker compose start falkordb`.
2. **Launch EC2** (ap-south-1): Ubuntu 24.04, t3.medium or larger, 30 GB gp3, key pair, security group SSH from your IP plus HTTP/HTTPS from anywhere. Attach an Elastic IP. Hostname: your domain's A record, or `<ip-with-dashes>.sslip.io`.
3. **Copy and run setup:** `scp -i key.pem falkordb-data.tgz deploy/ec2/setup.sh ubuntu@<ip>:~` then `ssh -i key.pem ubuntu@<ip> "bash setup.sh <hostname> <openrouter-key>"`. It installs everything, restores the graph, writes `/etc/pehchan.env` with fresh tokens (prints the write token once), starts the service and obtains HTTPS.
4. **CI/CD:** add GitHub repository secrets `EC2_HOST` (the IP or hostname) and `EC2_SSH_KEY` (the private key contents). Every push to `main` that passes tests runs [update.sh](../deploy/ec2/update.sh) over SSH: checkout of the exact commit, dependency update, restart and health check.

## Hugging Face Space + FalkorDB Cloud (alternative)

Use when a free or paid Space is available to you; the Docker image was built and run locally.

Implemented as files and a pipeline (ADR-054, F-40, F-41); the accounts, secrets and first deploy are operator steps.

1. **FalkorDB Cloud:** create a free instance and note host, port, username, password and whether TLS is on.
2. **Load the graph from the laptop** (it has the prepared files and models):
   ```powershell
   $env:FALKORDB_HOST="<cloud host>"; $env:FALKORDB_PORT="<port>"
   $env:FALKORDB_USERNAME="<user>"; $env:FALKORDB_PASSWORD="<password>"; $env:FALKORDB_SSL="true"
   .\.tools\python\python.exe scripts/load_graph.py --graph pehchan
   ```
   Expect 645 FactCheck, 641 ClaimVariant, 641 embedded. Saved cases are not copied.
3. **Hugging Face:** create a Space (SDK: Docker, hardware: CPU basic). In Settings → Variables and secrets add `FALKORDB_HOST`, `FALKORDB_PORT`, `FALKORDB_USERNAME`, `FALKORDB_PASSWORD`, `FALKORDB_SSL`, `FALKORDB_GRAPH=pehchan`, `OPENROUTER_API_KEY`, `PEHCHAN_OPENROUTER_MODEL=openai/gpt-oss-120b`, `PEHCHAN_PUBLIC_READ=1`, `PEHCHAN_PUBLIC_HOSTS=<owner>-<space>.hf.space`, and two distinct random `PEHCHAN_API_TOKEN` / `PEHCHAN_WRITE_TOKEN` values.
4. **GitHub:** add repository secret `HF_TOKEN` (a Hugging Face write token) and repository variable `HF_SPACE=<owner>/<space>`. Every push to `main` that passes CI uploads [deploy/huggingface](../deploy/huggingface/) to the Space with the Dockerfile pinned to that commit; the Space rebuilds (about 10 minutes) and serves the web app and `/public/mcp/` at `https://<owner>-<space>.hf.space`.

Limits: free CPU Spaces sleep after about 48 hours without visits and take a minute or more to wake (connectors may time out on the first call); Space storage is ephemeral, which is fine because the graph lives in FalkorDB Cloud; the in-memory rate limiter resets on restart.

## Quick public demo through a Cloudflare tunnel

Implemented in [scripts/run_public.py](../scripts/run_public.py) (ADR-049, F-39). It downloads `cloudflared` into ignored `.tools/` if missing, opens a quick tunnel to `127.0.0.1:8100`, reads the generated `*.trycloudflare.com` hostname, generates distinct read/write tokens into ignored `artifacts/public-tokens.json`, and starts a separate single-worker API with `PEHCHAN_PUBLIC_HOSTS=<that host>` and `PEHCHAN_PUBLIC_READ=1`. The local API on 8000 is untouched. The web page, `/health`, read-only graph routes, `/api/dossier`, `/api/scout` and `/public/mcp/` work without credentials; case history, writes and `/mcp/` require tokens. Rate limiting applies per `CF-Connecting-IP`.

Limits: the hostname changes every run; the service stops when the laptop sleeps or the script ends; quick tunnels have no uptime guarantee; there is one in-memory rate limiter per process. For a permanent address, follow the procedure below with a named tunnel or reverse proxy.

## Public HTTPS MCP hosting — operator procedure

These are deployment instructions, not evidence that deployment has happened.

1. Provision a machine that can run the tested Python environment, local checkpoints and FalkorDB. Preserve the database volume and model cache across restarts; set `PEHCHAN_MODEL_DIR` if checkpoints live outside the checkout.
2. Configure `FALKORDB_*` connection values. Keep database protocol and its administration browser private.
3. Configure distinct read/write credentials and set `PEHCHAN_PUBLIC_HOSTS` to the exact public API hostname, for example `investigate.example.org`.
4. Run the single-worker API on loopback, under a process supervisor. Configure an HTTPS reverse proxy on the public host that forwards to `127.0.0.1:8000`, preserves Host and Authorization, and allows long investigation requests. Do not log bearer credentials.
5. Test public `/health`, authenticated API operations and `/mcp/` with the official MCP client. Unauthenticated write requests must fail. Re-run the same smoke scripts with the external URL and intended credential.
6. Connect only clients that support this endpoint's bearer authorization. If a particular cloud connector requires OAuth, add a tested OAuth layer rather than claiming the current bearer endpoint already supports that flow.

For example, the reverse-proxy routing portion of a Caddy configuration is:

```caddyfile
investigate.example.org {
    reverse_proxy 127.0.0.1:8000
}
```

Replace the example with an owned configured domain. TLS/domain provisioning and credential distribution are external operator actions. The API's own token checks still apply behind the proxy. The product UI should remain private, or receive authenticated reverse-proxy access control before remote exposure: its server-side backend credential allows its users to invoke the corresponding actions. No public UI authentication is implemented in Streamlit itself.

## Persistence, recovery and current limits

FalkorDB's named volume is mounted at `/var/lib/falkordb/data`; `REDIS_ARGS` enables AOF with one-second fsync. Ordinary container recreation retains source records, vectors and investigations. Do not remove the named volume as a restart step. AOF/volume persistence is not a separate backup strategy.

Keep backups/exports of case snapshots if case history matters. Source files can rebuild claims/relationships and embeddings can be regenerated, but that does not recreate arbitrary researcher notes or previous model-assessment snapshots. Store credentials outside version control. `.models/`, raw/processed data, local logs and artifacts are ignored by Git.

Logs are `artifacts/api.stderr.log` and `artifacts/ui.stderr.log` when using the launcher. Missing checkpoints, wrong graph selection, stale vectors, occupied ports and denied write credentials are distinct setup branches documented in [Flow.md](Flow.md).
