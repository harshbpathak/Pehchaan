"""Publish Pehchan through a Cloudflare quick tunnel: web page plus a read-only public MCP endpoint.

Runs a separate API process on port 8100 (the local one on 8000 is left alone) with public read
mode on, distinct generated read/write tokens, and the tunnel hostname as the only public host.
Writes stay protected by the write token. Stop everything with Ctrl+C.
"""

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CLOUDFLARED_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-windows-amd64.exe"
)
TUNNEL_HOST = re.compile(r"https://([a-z0-9-]+\.trycloudflare\.com)")


def cloudflared(root: Path) -> str:
    for candidate in ("cloudflared", "cloudflared.exe"):
        try:
            subprocess.run([candidate, "--version"], capture_output=True, check=True)
            return candidate
        except (OSError, subprocess.CalledProcessError):
            pass
    local = root / ".tools" / "cloudflared.exe"
    if not local.exists():
        if os.name != "nt":
            raise SystemExit(
                "Install cloudflared: https://developers.cloudflare.com/cloudflare-one/"
            )
        print("Downloading cloudflared from Cloudflare's GitHub releases…")
        local.parent.mkdir(exist_ok=True)
        urllib.request.urlretrieve(CLOUDFLARED_URL, local)
    return str(local)


def tokens(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    created = {"read": secrets.token_urlsafe(24), "write": secrets.token_urlsafe(24)}
    path.write_text(json.dumps(created, indent=2) + "\n", encoding="utf-8")
    return created


def wait_for(url: str, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(1)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    artifacts = root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    tunnel_log = artifacts / "tunnel.log"
    tunnel = subprocess.Popen(
        [cloudflared(root), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{args.port}"],
        stdout=subprocess.DEVNULL,
        stderr=tunnel_log.open("w", encoding="utf-8"),
        creationflags=flags,
    )
    host = None
    for _ in range(60):
        match = TUNNEL_HOST.search(tunnel_log.read_text(encoding="utf-8", errors="ignore"))
        if match:
            host = match.group(1)
            break
        time.sleep(1)
    if not host:
        tunnel.terminate()
        raise SystemExit(f"Tunnel did not report a hostname; see {tunnel_log}")

    secret = tokens(artifacts / "public-tokens.json")
    env = {
        **os.environ,
        "PEHCHAN_PUBLIC_HOSTS": host,
        "PEHCHAN_PUBLIC_READ": "1",
        "PEHCHAN_API_TOKEN": secret["read"],
        "PEHCHAN_WRITE_TOKEN": secret["write"],
    }
    with (
        (artifacts / "public-api.stdout.log").open("w", encoding="utf-8") as out,
        (artifacts / "public-api.stderr.log").open("w", encoding="utf-8") as err,
    ):
        api = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "pehchan.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
                "--workers",
                "1",
                "--proxy-headers",
            ],
            cwd=root,
            env=env,
            stdout=out,
            stderr=err,
            creationflags=flags,
        )
    try:
        if not wait_for(f"http://127.0.0.1:{args.port}/health", 90):
            raise SystemExit(
                "Public API did not become healthy; see artifacts/public-api.stderr.log"
            )
        if not wait_for(f"https://{host}/health", 60):
            print("Warning: the tunnel is not answering yet; it can take a minute to propagate.")
        base = f"https://{host}"
        endpoint = {
            "web": base + "/",
            "public_mcp": base + "/public/mcp/",
            "full_mcp_requires_write_token": base + "/mcp/",
            "token_file": str(artifacts / "public-tokens.json"),
        }
        (artifacts / "public-endpoint.json").write_text(
            json.dumps(endpoint, indent=2) + "\n", "utf-8"
        )
        print(f"""
Pehchan is public (this laptop must stay on):

  Web page        {endpoint["web"]}
  Public MCP      {endpoint["public_mcp"]}   (read-only, no auth)
  Full MCP        {endpoint["full_mcp_requires_write_token"]}   (Bearer write token)
  Write token     saved in {endpoint["token_file"]} (never share it)

  Claude (claude.ai / Desktop): Settings > Connectors > Add custom connector > paste the public MCP URL
  Claude Code:  claude mcp add --transport http pehchan {endpoint["public_mcp"]}
  ChatGPT:      Settings > Apps & Connectors > Developer mode > Create > paste the public MCP URL, no auth
  Gemini CLI:   ~/.gemini/settings.json -> {{"mcpServers": {{"pehchan": {{"httpUrl": "{endpoint["public_mcp"]}"}}}}}}

Press Ctrl+C to stop the tunnel and the public API.""")
        while api.poll() is None and tunnel.poll() is None:
            time.sleep(2)
        print("A process exited; shutting down.")
    except KeyboardInterrupt:
        pass
    finally:
        for process in (api, tunnel):
            process.terminate()


if __name__ == "__main__":
    main()
