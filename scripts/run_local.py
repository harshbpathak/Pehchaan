"""Launch the local API and UI without changing shell execution policies."""

import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def available(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False


def occupied(port):
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def main():
    root = Path(__file__).resolve().parents[1]
    artifacts = root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    services = [
        (
            "api",
            8000,
            "http://127.0.0.1:8000/health",
            [
                "-m",
                "uvicorn",
                "pehchan.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--workers",
                "1",
            ],
        ),
        (
            "ui",
            8501,
            "http://127.0.0.1:8501/_stcore/health",
            [
                "-m",
                "streamlit",
                "run",
                str(root / "src/pehchan/ui.py"),
                "--server.address",
                "127.0.0.1",
                "--server.port",
                "8501",
                "--server.headless",
                "true",
                "--browser.gatherUsageStats",
                "false",
            ],
        ),
    ]
    processes = []
    for name, port, url, args in services:
        if available(url):
            print(f"{name}: already running")
            continue
        if occupied(port):
            raise SystemExit(
                f"Port {port} is occupied but {name} health check failed. Check service logs."
            )
        with (
            (artifacts / f"{name}.stdout.log").open("w", encoding="utf-8") as out,
            (artifacts / f"{name}.stderr.log").open("w", encoding="utf-8") as err,
        ):
            process = subprocess.Popen(
                [sys.executable, *args],
                cwd=root,
                stdout=out,
                stderr=err,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
        processes.append({"service": name, "pid": process.pid})
        print(f"{name}: started process {process.pid}")
    (artifacts / "local-processes.json").write_text(
        json.dumps(processes, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "Pehchan UI: http://localhost:8501\nAPI docs: http://localhost:8000/docs\nMCP: http://localhost:8000/mcp/"
    )


if __name__ == "__main__":
    main()
