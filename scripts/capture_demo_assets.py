"""Capture clean excerpts of the running app (no captions) for the animated video."""

import asyncio
import base64
import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

import websockets

OUT = Path(r"C:\Pehchaan\artifacts\video\assets")
OUT.mkdir(parents=True, exist_ok=True)
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE = "http://localhost:8000"
W, H = 1400, 900


async def main():
    proc = subprocess.Popen(
        [
            EDGE,
            "--headless=new",
            "--disable-gpu",
            "--remote-debugging-port=9455",
            f"--user-data-dir={OUT / 'profile'}",
            f"--window-size={W},{H}",
            "about:blank",
        ]
    )
    for _ in range(50):
        try:
            page = next(
                t
                for t in json.load(urllib.request.urlopen("http://127.0.0.1:9455/json"))
                if t["type"] == "page"
            )
            break
        except Exception:
            time.sleep(0.2)
    n = 0
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:

        async def call(method, **params):
            nonlocal n
            n += 1
            await ws.send(json.dumps({"id": n, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == n:
                    return msg.get("result", {})

        async def js(expr):
            r = await call(
                "Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True
            )
            return r.get("result", {}).get("value")

        async def clip(selector, name, pad=0, index=0):
            rect = await js(
                f"(() => {{ const e = document.querySelectorAll({json.dumps(selector)})[{index}]; e.scrollIntoView({{block: 'start', behavior: 'instant'}}); scrollBy(0, -20); const r = e.getBoundingClientRect(); return [r.x + scrollX, r.y + scrollY, r.width, r.height]; }})()"
            )
            x, y, w, h = rect
            r = await call(
                "Page.captureScreenshot",
                format="png",
                captureBeyondViewport=True,
                clip={
                    "x": max(0, x - pad),
                    "y": max(0, y - pad),
                    "width": min(W, w + 2 * pad),
                    "height": h + 2 * pad,
                    "scale": 1,
                },
            )
            (OUT / f"{name}.png").write_bytes(base64.b64decode(r["data"]))
            print("captured", name, [round(v) for v in rect])

        await call("Runtime.enable")
        await call("Page.enable")
        await call(
            "Emulation.setDeviceMetricsOverride",
            width=W,
            height=H,
            deviceScaleFactor=1,
            mobile=False,
        )
        await call(
            "Emulation.setEmulatedMedia",
            features=[{"name": "prefers-reduced-motion", "value": "reduce"}],
        )

        claim = "The LPG crisis in India hikes the prices by 100%."
        await call("Page.navigate", url=BASE + "/?claim=" + urllib.parse.quote(claim))
        for _ in range(240):
            await asyncio.sleep(0.5)
            if await js("!document.querySelector('#result').hidden"):
                break
        await asyncio.sleep(1.5)
        await js("document.querySelector('.nav').style.display = 'none'")
        await js(
            "document.querySelectorAll('.timeline li').forEach(li => { li.style.animation = 'none'; li.style.opacity = 1; li.style.transform = 'none'; })"
        )
        await clip(".finding", "lpg_finding", pad=4)
        await clip(".reply-card", "lpg_reply", pad=4)
        await clip(".sources", "lpg_sources", pad=4, index=0)
        await clip(".result .card", "lpg_timeline", pad=4, index=2)
        await js(
            "document.querySelector('.graph-toolbar') && document.querySelector('#graph-overview').click()"
        )
        await asyncio.sleep(3.5)
        await clip(".graph-card", "graph_card", pad=0)
        await clip(".diagram", "diagram", pad=0)
        await clip(".tools", "tools", pad=0)
        await clip("#connect .endpoint", "endpoint", pad=0)
        await clip(".claim-form", "claim_form", pad=0)
        await call(
            "Page.navigate",
            url=BASE
            + "/?claim="
            + urllib.parse.quote(
                "Bill Gates wants to put microchips into people through the covid vaccine!"
            ),
        )
        for _ in range(120):
            await asyncio.sleep(0.5)
            if await js("!document.querySelector('#result').hidden"):
                break
        await asyncio.sleep(1)
        await js("document.querySelector('.nav').style.display = 'none'")
        await clip(".finding", "memory_finding", pad=4)
        await clip(".reply-card", "memory_reply", pad=4)
    proc.terminate()


asyncio.run(main())
