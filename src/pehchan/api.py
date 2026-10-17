"""FastAPI + Streamable HTTP MCP with localhost defaults and separate write credentials."""

from __future__ import annotations

import hmac
import os
import time
from collections import defaultdict, deque
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from redis.exceptions import RedisError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .mcp_server import create_mcp
from .service import ApplicationService


class ClaimRequest(BaseModel):
    claim: str = Field(min_length=1, max_length=4000)
    request_id: str | None = Field(default=None, max_length=128)


class ReviewRequest(BaseModel):
    state: str = Field(pattern="^(OPEN|IN_PROGRESS|RESOLVED)$")
    note: str = Field(default="", max_length=4000)


WEB_ROOT = Path(__file__).parent / "web"
# Routes anyone may call in public read mode: read-only, no case lists or claim history.
PUBLIC_READ_PREFIXES = (
    "/api/config",
    "/api/graph",
    "/api/evidence/",
    "/api/narratives/",
    "/api/path",
)
PUBLIC_COMPUTE_PATHS = ("/api/scout", "/api/dossier", "/public/mcp")


class RateLimiter:
    """In-memory sliding window per visitor for model-heavy public requests."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit, self.window = limit, window_seconds
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self.hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


def visitor(request: Request) -> str:
    # Behind a tunnel every request arrives from loopback; use the forwarded client address.
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def create_app(
    service=None,
    read_token: str | None = None,
    write_token: str | None = None,
    public_read: bool | None = None,
):
    service = service or ApplicationService()
    if public_read is None:
        public_read = os.getenv("PEHCHAN_PUBLIC_READ", "") == "1"
    limiter = RateLimiter(int(os.getenv("PEHCHAN_PUBLIC_RATE_LIMIT", "30")), 600)
    read_token = read_token if read_token is not None else os.getenv("PEHCHAN_API_TOKEN", "")
    write_token = write_token if write_token is not None else os.getenv("PEHCHAN_WRITE_TOKEN", "")
    public_hosts = [
        h.strip() for h in os.getenv("PEHCHAN_PUBLIC_HOSTS", "").split(",") if h.strip()
    ]
    if public_hosts and (not read_token or not write_token or read_token == write_token):
        raise RuntimeError("Public hosting requires distinct read and write tokens.")
    mcp = create_mcp(service, public_hosts)
    mcp_app = mcp.streamable_http_app()
    public_mcp = create_mcp(service, public_hosts, include_write=False)
    public_mcp_app = public_mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp.session_manager.run())
            await stack.enter_async_context(public_mcp.session_manager.run())
            yield
        service.close()

    app = FastAPI(
        title="Pehchan AI",
        version="0.2.0",
        lifespan=lifespan,
        description="Graph-native investigation; source ratings are not new claim verdicts.",
    )
    app.state.service, app.state.mcp, app.state.public_mcp = service, mcp, public_mcp
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver", *public_hosts]
    )

    @app.middleware("http")
    async def authorize(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).hostname not in {"localhost", "127.0.0.1", *public_hosts}:
            return JSONResponse({"detail": "Origin not permitted"}, status_code=403)
        path = request.url.path
        if path == "/health" or path == "/" or path.startswith("/assets/"):
            return await call_next(request)  # static page and readiness carry no case data
        if public_read and (
            path.startswith(PUBLIC_COMPUTE_PATHS)
            or (request.method in {"GET", "HEAD"} and path.startswith(PUBLIC_READ_PREFIXES))
        ):
            heavy = request.method == "POST" and path.startswith(PUBLIC_COMPUTE_PATHS)
            if heavy and not limiter.allow(visitor(request)):
                return JSONResponse(
                    {"detail": "Public rate limit reached; try again in a few minutes."},
                    status_code=429,
                )
            return await call_next(request)
        if path.startswith("/public/mcp"):
            return JSONResponse({"detail": "Public read mode is not enabled."}, status_code=404)
        write = path.startswith("/mcp") or (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and path not in {"/api/scout", "/api/dossier"}
        )
        credential = request.headers.get("authorization", "").removeprefix("Bearer ")
        configured = bool(read_token or write_token)
        permitted = bool(write_token and hmac.compare_digest(credential, write_token))
        if not write:
            permitted |= bool(read_token and hmac.compare_digest(credential, read_token))
        local = request.client and request.client.host in {"127.0.0.1", "::1", "testclient"}
        if (configured and not permitted) or (not configured and not local):
            return JSONResponse(
                {"detail": "Write credential required" if write else "Authentication required"},
                status_code=403 if credential else 401,
            )
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def input_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(RuntimeError)
    async def setup_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(RedisError)
    async def database_error(request, exc):
        return JSONResponse({"detail": "Database unavailable; check local setup."}, status_code=503)

    @app.get("/health")
    def health():
        state = service.call("health")
        # Public health response deliberately omits case data, claim text and file paths.
        return {
            "status": state["status"],
            "graph": state["graph"],
            "claims": state["embeddings"]["total"],
            "embedded": state["embeddings"]["ready"],
            "inference": state.get("inference", {"mode": "deterministic"}),
        }

    @app.get("/api/status")
    def status():
        return service.call("health")

    @app.post("/api/scout")
    def scout(body: ClaimRequest):
        return service.call("find_similar_claims", body.claim)

    @app.post("/api/dossier")
    def dossier(body: ClaimRequest):
        return service.call("assemble_evidence_dossier", body.claim)

    @app.post("/api/investigations")
    def investigate(body: ClaimRequest):
        return service.call("investigate_claim", body.claim, body.request_id)

    @app.post("/api/review-cases")
    def create_review(body: ClaimRequest):
        return service.call("create_review_case", body.claim, body.request_id)

    @app.get("/api/investigations")
    def cases():
        return service.call("cases")

    @app.get("/api/investigations/{investigation_id}")
    def case(investigation_id: str):
        result = service.call("case", investigation_id)
        if result is None:
            raise HTTPException(404, "Investigation not found")
        return result

    @app.patch("/api/investigations/{investigation_id}")
    def review(investigation_id: str, body: ReviewRequest):
        return service.call("review", investigation_id, body.state, body.note)

    @app.get("/api/evidence/{variant_id}")
    def evidence(variant_id: str):
        return service.call("get_claim_evidence", variant_id)

    @app.get("/api/narratives/{variant_id}")
    def narratives(variant_id: str):
        return service.call("explore_narrative_graph", variant_id)

    @app.get("/api/path")
    def path(from_id: str, to_id: str):
        return service.call("find_evidence_path", from_id, to_id)

    @app.get("/api/graph")
    def graph(variant_id: str | None = None, limit: int = 80):
        return service.call("graph", variant_id, limit)

    @app.get("/api/config")
    def config():
        return {"public_read": public_read, "write_protected": bool(write_token or read_token)}

    app.mount("/public/mcp", public_mcp_app)
    app.mount("/mcp", mcp_app)
    if WEB_ROOT.is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_ROOT / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def index():
            from fastapi.responses import FileResponse

            return FileResponse(WEB_ROOT / "index.html")

    return app


app = create_app()
