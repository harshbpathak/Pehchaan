"""Build the 3-minute Pehchan demo: real browser footage, title cards, captions, synthesized narration.

Footage comes from the local server (same code and data as the live site). Waits longer than a few
seconds are cut and labelled "Processing time shortened". Output: artifacts/pehchan-demo.mp4
"""

import asyncio
import json
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

import imageio_ffmpeg
import websockets
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(r"C:\Pehchaan")
OUT = ROOT / "artifacts" / "video"
OUT.mkdir(parents=True, exist_ok=True)
FRAMES = OUT / "frames"
FRAMES.mkdir(exist_ok=True)
W, H = 1280, 720
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
BASE = "http://localhost:8000"
LIVE = "https://16-192-177-240.sslip.io"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

INK, PAPER, EMBER, MUTED, MINT = (
    (35, 40, 66),
    (252, 249, 243),
    (239, 91, 63),
    (91, 96, 117),
    (31, 107, 75),
)


def font(size, bold=False, mono=False):
    name = "consola.ttf" if mono else ("seguisb.ttf" if bold else "segoeui.ttf")
    return ImageFont.truetype(rf"C:\Windows\Fonts\{name}", size)


def wrap(draw, text, fnt, width):
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = (line + " " + w).strip()
        if draw.textlength(trial, font=fnt) <= width:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


# ---------- frames ----------
frames: list[tuple[Path, float]] = []  # (png, seconds)
counter = 0


def add(img: Image.Image, seconds: float, caption: str = "", label: str = ""):
    global counter
    img = img.convert("RGB").resize((W, H))
    d = ImageDraw.Draw(img, "RGBA")
    if caption:
        f = font(26)
        lines = wrap(d, caption, f, W - 120)
        band = 28 + 36 * len(lines)
        d.rectangle([0, H - band - 24, W, H], fill=(20, 22, 35, 215))
        y = H - band - 8
        for ln in lines:
            d.text((60, y), ln, font=f, fill=(255, 255, 255))
            y += 36
    if label:
        f = font(20, bold=True)
        tw = d.textlength(label, font=f)
        d.rectangle([W - tw - 56, 20, W - 20, 58], fill=(239, 91, 63, 235))
        d.text((W - tw - 38, 27), label, font=f, fill=(255, 255, 255))
    counter += 1
    p = FRAMES / f"f{counter:05d}.png"
    img.save(p)
    frames.append((p, seconds))


def card(title, lines=(), kicker="", mono_lines=(), bg=PAPER, fg=INK):
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    y = 90
    if kicker:
        d.text((80, y), kicker.upper(), font=font(18, mono=True), fill=EMBER)
        y += 44
    for ln in wrap(d, title, font(60, bold=True), W - 160):
        d.text((80, y), ln, font=font(60, bold=True), fill=fg)
        y += 70
    y += 18
    for ln in lines:
        for sub in wrap(d, ln, font(30), W - 160):
            d.text((80, y), sub, font=font(30), fill=MUTED)
            y += 42
        y += 8
    for ln in mono_lines:
        d.text((80, y), ln, font=font(22, mono=True), fill=fg)
        y += 32
    return img


def message_cards():
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.text((80, 70), "THE SAME CLAIM, THREE WAYS", font=font(18, mono=True), fill=EMBER)
    msgs = [
        ("English", "Putin bans 5G across Russia and destroys all the towers."),
        ("Reworded", "Putin has outlawed 5G in Russia and ordered every tower torn down."),
        ("Hindi forward", "पुतिन ने रूस में 5G पर प्रतिबंध लगा दिया और सभी टावर नष्ट करवा दिए।"),
    ]
    for i, (tag, text) in enumerate(msgs):
        x, y = 80 + i * 380, 140
        d.rounded_rectangle(
            [x, y, x + 350, y + 300], radius=24, fill=(255, 255, 255), outline=(220, 215, 205)
        )
        d.text((x + 24, y + 22), tag.upper(), font=font(16, mono=True), fill=MUTED)
        f = ImageFont.truetype(r"C:\Windows\Fonts\Nirmala.ttf", 26) if i == 2 else font(26)
        yy = y + 64
        for ln in wrap(d, text, f, 300):
            d.text((x + 24, yy), ln, font=f, fill=INK)
            yy += 36
    d.text(
        (80, 500),
        "Has it been reviewed before?  What connects it to earlier claims?",
        font=font(30),
        fill=INK,
    )
    d.text(
        (80, 560),
        "Pehchan AI investigates the connections and answers only from recorded sources.",
        font=font(24),
        fill=MUTED,
    )
    return img


# ---------- browser ----------
class Browser:
    def __init__(self):
        self.proc = subprocess.Popen(
            [
                EDGE,
                "--headless=new",
                "--disable-gpu",
                "--remote-debugging-port=9444",
                f"--user-data-dir={OUT / 'profile'}",
                f"--window-size={W},{H}",
                "about:blank",
            ]
        )
        for _ in range(50):
            try:
                targets = json.load(urllib.request.urlopen("http://127.0.0.1:9444/json"))
                self.page = next(t for t in targets if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        self.n = 0

    async def __aenter__(self):
        self.ws = await websockets.connect(self.page["webSocketDebuggerUrl"], max_size=None)
        await self.call("Runtime.enable")
        await self.call("Page.enable")
        await self.call(
            "Emulation.setDeviceMetricsOverride",
            width=W,
            height=H,
            deviceScaleFactor=1,
            mobile=False,
        )
        await self.call(
            "Emulation.setEmulatedMedia",
            features=[{"name": "prefers-reduced-motion", "value": "reduce"}],
        )
        return self

    async def __aexit__(self, *a):
        await self.ws.close()
        self.proc.terminate()

    async def call(self, method, **params):
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self.n:
                return msg.get("result", {})

    async def js(self, expr):
        r = await self.call(
            "Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True
        )
        return r.get("result", {}).get("value")

    async def shot(self):
        r = await self.call("Page.captureScreenshot", format="png")
        import base64
        import io

        return Image.open(io.BytesIO(base64.b64decode(r["data"])))

    async def goto(self, url):
        await self.call("Page.navigate", url=url)
        await asyncio.sleep(2.5)

    async def scroll_to(self, selector, offset=70):
        await self.js(
            f"window.scrollTo({{top: document.querySelector('{selector}').getBoundingClientRect().top + scrollY - {offset}, behavior: 'instant'}})"
        )
        await asyncio.sleep(0.4)

    async def hold(self, seconds, caption, label="", step=0.5):
        """Capture frames for a static view: one frame held for the whole time."""
        add(await self.shot(), seconds, caption, label)

    async def run_claim(self, claim, caption, shorten_label=True, max_wait=120):
        await self.js(
            f"document.querySelector('#claim').value = {json.dumps(claim)}; document.querySelector('#claim').scrollIntoView({{block: 'center', behavior: 'instant'}});"
        )
        add(await self.shot(), 1.6, caption)
        await self.js("document.querySelector('#claim-form').requestSubmit()")
        started = time.time()
        waiting = []
        while time.time() - started < max_wait:
            await asyncio.sleep(0.5)
            waiting.append(await self.shot())
            if not await self.js("document.querySelector('#result').hidden"):
                break
        actual = round(time.time() - started)
        # keep the first and last seconds of the wait, cut the middle and say so
        keep = waiting[:4] + waiting[-3:] if len(waiting) > 7 else waiting
        label = (
            f"Processing time shortened (actual: {actual} s)"
            if shorten_label and len(waiting) > 7
            else ""
        )
        for img in keep:
            add(img, 0.5, caption, label)
        return actual


# ---------- narration ----------
VOICE = (
    "en-IN-NeerjaNeural"  # a neural voice; replace the track with a human recording if you prefer
)


def tts(text, path: Path, rate=1):
    """Synthesize to 22.05 kHz mono WAV. Neural voice via edge-tts; classic Windows voice if that fails."""
    mp3 = path.with_suffix(".mp3")
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "edge_tts",
                "--voice",
                VOICE,
                "--rate=+12%",
                "--text",
                text,
                "--write-media",
                str(mp3),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        subprocess.run(
            [
                FFMPEG,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(mp3),
                "-ar",
                "22050",
                "-ac",
                "1",
                str(path),
            ],
            check=True,
        )
    except Exception as error:  # network or service trouble: keep going with the local voice
        print("neural voice unavailable, using Zira:", str(error)[:80])
        ps = f'''Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer;
$s.SelectVoice("Microsoft Zira Desktop"); $s.Rate = {rate}; $s.SetOutputToWaveFile("{path}"); $s.Speak({json.dumps(text)}); $s.Dispose()'''
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True
        )
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


SCENES = []  # (narration_text, start_frame_index, end_frame_index)


def scene(text):
    """Mark the frames added inside the block as one narrated scene."""

    class _S:
        def __enter__(self):
            self.start = len(frames)

        def __exit__(self, *a):
            SCENES.append((text, self.start, len(frames)))

    return _S()


async def main():
    # real outputs for the text cards
    path_out = subprocess.run(
        [
            sys.executable,
            "-m",
            "pehchan.cli",
            "--graph",
            "pehchan",
            "path",
            "variant_d5c3859c252aebe9af62a470",
            "variant_c9ce10f79c7b3a3a9a738cf3",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    ).stdout
    path_json = json.loads(path_out)
    mcp_out = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("check_public_endpoint.py")), LIVE],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    ).stdout

    async with Browser() as b:
        # 1 · the problem
        with scene(
            "It starts with a forward. A message about LPG prices lands in a family group at seven in the morning. "
            "By noon it has been reworded, translated, and attached to the week's news. "
            "Has anyone checked this before, and what is it connected to? "
            "We built Pehchan AI to answer that from recorded sources, and nothing else."
        ):
            add(message_cards(), 6, "")
            await b.goto(BASE + "/")
            await b.hold(
                4,
                "Pehchan AI · the investigation desk, the graph, and eight tools over MCP, all on one FalkorDB graph",
            )
            await b.scroll_to("#spark", 60)
            await b.hold(
                3.5,
                "Five 2026 events are in the graph, with 11,758 fact-checks from 184 publishers",
            )

        # 2 · a real investigation
        with scene(
            "So let's paste that message in. Pehchan searches the wordings fact-checkers have already reviewed and checks how closely each one matches. "
            "Nobody has reviewed this exact sentence. So the Graph Detective widens the search through what the message shares with the graph: "
            "the LPG entity, and the fuel-price narrative. That reaches related reviews from The Quint and Fact Crescendo. "
            "Those reviews are context, not a verdict, so Pehchan drafts a reply with the sources and sends the case to a human."
        ):
            await b.scroll_to("#investigate", 60)
            lpg = "The LPG crisis in India hikes the prices by 100%."
            await b.run_claim(
                lpg, "Investigating: “The LPG crisis in India hikes the prices by 100%.”"
            )
            await b.scroll_to("#result", 70)
            await b.hold(
                5, "Finding: variant of a known narrative · human review needed · nothing invented"
            )
            await b.js(
                "document.querySelector('.reply-card').scrollIntoView({block: 'start', behavior: 'instant'}); scrollBy(0, -70)"
            )
            await b.hold(
                6,
                "The drafted reply cites only graph records: The Quint and Fact Crescendo on related LPG-price claims",
            )
            await b.js(
                "[...document.querySelectorAll('.result h3')].find(h => h.textContent.startsWith('Widened')).scrollIntoView({block: 'start', behavior: 'instant'}); scrollBy(0, -70)"
            )
            await b.hold(
                6,
                "Widened context: each hit lists the entity or frame it shares and who inferred that edge",
            )

        # 3 · the agents
        with scene(
            "Behind that answer are three specialists. Claim Scout finds candidates by meaning, in any language, and checks relevance both ways. "
            "Graph Detective follows the connections recorded in FalkorDB. Evidence and Response re-reads the sources and chooses the next step. "
            "A hosted open model decides which tool to call next, but only from its list; the application decides every citation and every case status."
        ):
            await b.js(
                "[...document.querySelectorAll('.result h3')].find(h => h.textContent.startsWith('How the agents')).scrollIntoView({block: 'start', behavior: 'instant'}); scrollBy(0, -70)"
            )
            await b.hold(9, "How the agents decided: every step names its tool and its reason")
            await b.scroll_to("#how", 60)
            await b.hold(5, "Agents propose. The graph decides.")
            await b.js(
                "document.querySelector('.diagram').scrollIntoView({block: 'center', behavior: 'instant'}); document.querySelectorAll('.diagram .part')[5].dispatchEvent(new Event('mouseenter'))"
            )
            await b.hold(
                6,
                "Inputs → agents → the FalkorDB claim graph → a cited reply, a review queue, a written-back submission, MCP tools",
            )

        # 4 · why the graph matters
        with scene(
            "This is where the graph earns its place. A vaccine-microchip claim and a climate claim have nothing in common as text. "
            "In the graph they meet at one entity, Bill Gates, four hops apart. FalkorDB returns that path with its native pathfinding algorithm, "
            "and Pehchan shows every edge behind it. A shared entity explains why two claims are connected; it never claims they agree."
        ):
            nodes = path_json[0][0] if path_json else []
            rels = path_json[0][1] if path_json else []
            add(
                card(
                    "A four-hop connection, returned by FalkorDB",
                    ["python -m pehchan.cli path <vaccine-microchip wording> <climate wording>"],
                    kicker="algo.SPpaths · real output",
                    mono_lines=[
                        f"{n}" + (f"   -[{rels[i]}]->" if i < len(rels) else "")
                        for i, n in enumerate(nodes)
                    ]
                    + ["", "variant → claim → Entity(Bill Gates) ← claim ← variant"],
                ),
                9,
                "The path as node ids and relationship types: nothing is drawn that the query did not return",
            )
            await b.scroll_to("#graph", 60)
            await b.js("document.querySelector('#graph-overview').click()")
            await asyncio.sleep(3)
            await b.js(
                "document.querySelector('.graph-card').scrollIntoView({block: 'start', behavior: 'instant'}); scrollBy(0, -70)"
            )
            await b.hold(
                8,
                "The graph explorer: dashed edges are inferences, solid edges come from source records; click a node for its evidence",
            )

        # 5 · act and remember
        with scene(
            "Now the part I like most. A researcher saves an investigation as a case. That writes the message itself into the graph, "
            "linked to what it matched. Tomorrow the same forward arrives with one word changed. "
            "Pehchan recognises it, follows the saved relationship, and answers from the graph's own memory, "
            "without rerunning the models. The agent did not just read the graph. It changed it."
        ):
            await b.scroll_to("#investigate", 60)
            gates = "Bill Gates wants to put microchips in people through the covid vaccine."
            await b.run_claim(
                gates,
                "Investigating: “Bill Gates wants to put microchips in people through the covid vaccine.”",
            )
            await b.scroll_to("#result", 70)
            await b.hold(3, "Known recycled claim: BBC Reality Check reviewed this wording")
            await b.js(
                "document.querySelector('.result-actions').scrollIntoView({block: 'center', behavior: 'instant'}); document.querySelector('.result-actions button').click()"
            )
            for _ in range(30):
                await asyncio.sleep(0.5)
                if (await b.js("document.querySelector('#status').textContent")).startswith(
                    "Saved"
                ):
                    break
            await b.hold(
                4, "Saved: Investigation → SUBMITTED → Submission → MATCHES → the recorded wording"
            )
            await b.scroll_to("#investigate", 60)
            await b.run_claim(
                "Bill Gates wants to put microchips into people through the covid vaccine!",
                "A reworded forward of the same message",
                shorten_label=True,
            )
            await b.scroll_to("#result", 70)
            await b.hold(
                7,
                "Answered from graph memory: the saved MATCHES edge, not a model, found the record",
            )

        # 6 · MCP
        with scene(
            "None of this is locked inside one web page. The same eight tools are served over MCP. "
            "Here an MCP client calls Pehchan's dossier tool on the live server and gets back structured results, with sources and uncertainty. "
            "Six tools are open to anyone; two write to the graph and stay with the team. "
            "Claude, ChatGPT or Gemini can use the same graph, under the same evidence policy."
        ):
            lines = [ln for ln in mcp_out.strip().splitlines() if ln.strip()]
            add(
                card(
                    "An MCP client against the live endpoint",
                    [LIVE + "/public/mcp/"],
                    kicker="official MCP Python client · Streamable HTTP · real output",
                    mono_lines=[ln[:92] for ln in lines][:12],
                    bg=(20, 22, 35),
                    fg=(230, 230, 235),
                ),
                12,
                "assemble_evidence_dossier returns the finding, status, citations and uncertainty as structured content",
            )
            await b.scroll_to("#tools", 60)
            await b.hold(
                6, "Eight tools, one graph: six open to everyone, two reserved for the team"
            )
            await b.goto(LIVE + "/")
            await b.scroll_to("#connect", 60)
            await b.hold(
                5, "Paste the URL into Claude, ChatGPT or Gemini; the page has copy-ready snippets"
            )

        # 7 · what comes next
        with scene(
            "And this is a beginning. Next, we want relevance checks in Hindi, Tamil and Telugu, so cross-language matches are confirmed, not just surfaced. "
            "We want the graph to grow itself: when nothing matches, look the claim up in the public Fact Check Tools index, "
            "write what it finds into FalkorDB, and investigate again. And a WhatsApp tipline in front of it, with fact-checking newsrooms as partners."
        ):
            add(
                card(
                    "What comes next",
                    [
                        "Relevance models for Hindi, Tamil and Telugu: confirm cross-language matches, not only surface them.",
                        "A graph that grows itself: on no match, query the public Fact Check Tools index, ingest the reviews, investigate again.",
                        "A WhatsApp or Telegram tipline in front of the investigation desk.",
                        "Fact-checker partnerships: labelled forwards, reviewed tags, shared cases with owners and history.",
                        "Entity linking to Wikidata ids, so the same person or place is one node across languages.",
                    ],
                    kicker="future scope",
                ),
                22,
                "",
            )

        # 8 · close
        with scene(
            "So that is Pehchan. A forwarded message becomes an investigation you can inspect: published sources, visible connections, "
            "a drafted reply, and a clear next step. When the evidence is not there, it says so. "
            "Built on FalkorDB for Graph Hacks, Track One. Pehchan AI. Beyond the claim, into the connections."
        ):
            await b.scroll_to("#proof", 60)
            await b.hold(
                6,
                "Measured: the FalkorDB vector index finds 30 of 30 held-out queries; word overlap finds 25",
            )
            add(
                card(
                    "Pehchan AI",
                    [
                        "Beyond the claim. Into the connections.",
                        "",
                        "Graph Hacks · Track 1 · Agents That Act on Connected Data",
                        "github.com/harshbpathak/Pehchaan · 16-192-177-240.sslip.io",
                    ],
                    kicker="◈ pehchan",
                ),
                9,
                "",
            )

    # ---------- narration and timing ----------
    audio_parts = []
    frame_durations = [d for _, d in frames]
    for i, (text, start, end) in enumerate(SCENES):
        wav = OUT / f"narration{i}.wav"
        spoken = tts(text, wav)
        footage = sum(frame_durations[start:end])
        if spoken + 0.6 > footage:  # hold the scene's last frame until the narration ends
            frame_durations[end - 1] += spoken + 0.6 - footage
            footage = spoken + 0.6
        audio_parts.append((wav, footage))
        print(f"scene {i + 1}: narration {spoken:5.1f} s, footage {footage:5.1f} s")
    # one narration track, each scene padded with silence to its footage length
    out_wav = OUT / "narration.wav"
    with wave.open(str(audio_parts[0][0])) as w0:
        params = w0.getparams()
    with wave.open(str(out_wav), "wb") as out:
        out.setparams(params)
        for wav, length in audio_parts:
            with wave.open(str(wav)) as w:
                data = w.readframes(w.getnframes())
            out.writeframes(data)
            pad = int((length * params.framerate) - w.getnframes())
            if pad > 0:
                out.writeframes(b"\x00" * pad * params.sampwidth * params.nchannels)
    total = sum(frame_durations)
    print(f"total {total:.1f} s")

    concat = OUT / "frames.txt"
    with concat.open("w", encoding="utf-8") as f:
        for (p, _), d in zip(frames, frame_durations):
            f.write(f"file '{p.as_posix()}'\nduration {d:.3f}\n")
        f.write(f"file '{frames[-1][0].as_posix()}'\n")
    mp4 = ROOT / "artifacts" / "pehchan-demo.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-i",
            str(out_wav),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "24",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(mp4),
        ],
        check=True,
    )
    print("written", mp4, round(mp4.stat().st_size / 1e6, 1), "MB")


asyncio.run(main())
