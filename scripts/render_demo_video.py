"""Render the animated Pehchan demo: an HTML/CSS scene timeline seeked frame by frame, real app excerpts
as the only screenshots, the narration track from narrate_demo_video.py for audio. Every visual beat is
placed at the word it illustrates, using the word timestamps in artifacts/video/cues.json.
Output artifacts/pehchan-demo.mp4."""

import asyncio
import base64
import json
import subprocess
import time
import urllib.request
from pathlib import Path

import imageio_ffmpeg
import websockets

ROOT = Path(__file__).resolve().parents[1]
V = ROOT / "artifacts" / "video"
FR = V / "anim"
FR.mkdir(parents=True, exist_ok=True)
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
W, H = 1280, 720
# scene lengths and word timestamps come from the narration track (narrate_demo_video.py)
_CUES = json.loads((V / "cues.json").read_text(encoding="utf-8"))
LENGTHS = _CUES["lengths"]
STARTS = [round(sum(LENGTHS[:i]), 2) for i in range(len(LENGTHS))]
TOTAL = round(sum(LENGTHS), 2)
FPS = 16


def C(scene, word, default, nth=1, lead=0.15):
    """Seconds into the scene when the narration reaches `word` (nth occurrence), a little early."""
    key = "".join(ch for ch in word.lower() if ch.isalnum())
    hits = [
        t
        for t, w in _CUES["words"][scene]
        if "".join(ch for ch in w.lower() if ch.isalnum()).startswith(key)
    ]
    if len(hits) >= nth:
        return max(0.0, hits[nth - 1] - lead)
    print("cue missing", scene, word)
    return default


CSS = """
@import url('https://fonts.googleapis.com/css2?family=Anton&family=Inter:wght@400;500;600;700&family=Geist+Mono:wght@400;500&family=Noto+Sans+Devanagari:wght@400;700&display=swap');
:root{--paper:#FCF9F3;--paper2:#F5EFE4;--ink:#232842;--muted:#5B6075;--ember:#EF5B3F;--ember2:#B8402A;--sun:#FFE27A;--sunsoft:#FFF5CF;--mint:#DDF3E8;--mintink:#1F6B4B;--sky:#E3ECFF;--skyink:#2F4FA6;--lilac:#EEE7FB;--violet:#A57BE0;--line:rgba(35,40,66,.14)}
*{box-sizing:border-box;margin:0}
html,body{width:1280px;height:720px;overflow:hidden;background:var(--paper);font-family:Inter,'Noto Sans Devanagari',sans-serif;color:var(--ink)}
.scene>.a{position:absolute}
.scene{position:absolute;inset:0;opacity:0;animation:scene linear both;animation-duration:var(--l);animation-delay:var(--d)}
@keyframes scene{0%{opacity:0}2.5%{opacity:1}97.5%{opacity:1}100%{opacity:0}}
.a{animation-fill-mode:both;animation-timing-function:cubic-bezier(.22,1,.36,1);animation-duration:var(--l,.8s);animation-delay:var(--d,0s)}
.fade-up{animation-name:fadeUp;opacity:0}@keyframes fadeUp{from{opacity:0;transform:translateY(26px)}to{opacity:1;transform:none}}
.fade{animation-name:fade;opacity:0}
.fade-out{animation-name:fadeOut}@keyframes fadeOut{to{opacity:0}}
.scene>.wrap{position:absolute;inset:0}@keyframes fade{to{opacity:1}}
.pop{animation-name:pop;opacity:0}@keyframes pop{from{opacity:0;transform:scale(.6)}to{opacity:1;transform:scale(1)}}
.slide-l{animation-name:slideL;opacity:0}@keyframes slideL{from{opacity:0;transform:translateX(60px)}to{opacity:1;transform:none}}
.slide-r{animation-name:slideR;opacity:0}@keyframes slideR{from{opacity:0;transform:translateX(-60px)}to{opacity:1;transform:none}}
.draw{stroke-dasharray:var(--len);stroke-dashoffset:var(--len);animation-name:draw;animation-timing-function:linear}@keyframes draw{to{stroke-dashoffset:0}}
.pulse{animation-name:pulse;animation-iteration-count:infinite;animation-duration:1.6s;animation-timing-function:ease-in-out}@keyframes pulse{0%,100%{filter:drop-shadow(0 0 0 rgba(239,91,63,0))}50%{filter:drop-shadow(0 0 14px rgba(239,91,63,.9))}}
.kb{animation-name:kb;animation-timing-function:linear}@keyframes kb{from{transform:scale(1)}to{transform:scale(1.07)}}
.type{overflow:hidden;white-space:nowrap;width:0;animation-name:type;animation-timing-function:steps(40,end)}@keyframes type{to{width:100%}}
.display{font-family:Anton,Impact,sans-serif;text-transform:uppercase;letter-spacing:.005em;line-height:.92}
.mono{font-family:'Geist Mono',Consolas,monospace;letter-spacing:.12em;text-transform:uppercase;font-size:12px;color:var(--muted)}
.eyebrow{position:absolute;left:70px;top:48px;font-family:'Geist Mono',monospace;font-size:13px;letter-spacing:.2em;text-transform:uppercase;color:var(--ember2)}
.shot{position:absolute;border-radius:18px;overflow:hidden;box-shadow:0 30px 70px -30px rgba(35,40,66,.45);border:1px solid var(--line);background:#fff}
.shot img{display:block;width:100%;transform-origin:50% 0}
.ring{position:absolute;border:3px solid var(--ember);border-radius:14px;box-shadow:0 0 0 6px rgba(239,91,63,.18)}
.chip{display:inline-flex;align-items:center;gap:8px;border-radius:999px;padding:9px 16px;font-weight:600;font-size:16px;background:#fff;border:1.5px solid var(--ink)}
.chip.on{background:var(--ink);color:var(--paper)}
.bubble{position:absolute;background:#fff;border-radius:22px 22px 22px 6px;padding:18px 22px;font-size:20px;line-height:1.4;box-shadow:0 18px 40px -24px rgba(35,40,66,.4);border:1px solid var(--line);max-width:430px}
.bubble small{display:block;margin-top:8px;font-family:'Geist Mono',monospace;font-size:11px;letter-spacing:.14em;color:var(--muted)}
.card{position:absolute;background:#fff;border:1px solid var(--line);border-radius:22px;padding:22px 24px;box-shadow:0 18px 40px -26px rgba(35,40,66,.35)}
.card h3{font-size:22px;font-weight:700;margin-bottom:6px}
.card p{color:var(--muted);font-size:15px;line-height:1.5}
.tag{display:inline-block;font-family:'Geist Mono',monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;padding:4px 10px;border-radius:8px;background:var(--sunsoft);color:var(--ember2)}
.node{position:absolute;border-radius:50%;display:grid;place-items:center;font-weight:700;color:#fff;font-size:13px;text-align:center}
.lbl{position:absolute;font-size:15px;font-weight:600;color:var(--ink)}
.lbl small{display:block;font-family:'Geist Mono',monospace;font-size:11px;letter-spacing:.12em;color:var(--muted);font-weight:500;text-transform:uppercase;margin-top:2px}
.term{position:absolute;background:#141626;color:#E6E6EB;border-radius:18px;padding:22px 26px;font-family:'Geist Mono',monospace;font-size:14px;line-height:1.75;box-shadow:0 30px 60px -30px rgba(0,0,0,.6)}
.term .ln{display:block}
.term .ok{color:#7FE0B5}.term .k{color:#F7B267}
.band{position:absolute;left:0;right:0;bottom:0;height:64px;background:var(--sun);border-top:1px solid var(--ink);display:flex;align-items:center;gap:36px;padding:0 70px;font-family:Anton;font-size:26px;text-transform:uppercase;color:#2A2410;white-space:nowrap;overflow:hidden}
.band i{color:var(--ember);font-style:normal}
.counter{position:absolute;font-family:Anton;font-size:88px;line-height:1;color:var(--ink)}
.counter small{display:block;font-family:'Geist Mono',monospace;font-size:12px;letter-spacing:.18em;color:var(--muted);text-transform:uppercase;margin-top:8px}
.roadmap{position:absolute;left:120px;top:150px;width:1040px}
.step{position:relative;padding:0 0 30px 56px;font-size:21px;line-height:1.35}
.step::before{content:"";position:absolute;left:14px;top:4px;width:16px;height:16px;border-radius:50%;background:var(--ember);box-shadow:0 0 0 6px var(--sunsoft)}
.step small{display:block;font-family:'Geist Mono',monospace;font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin-bottom:4px}
"""


def el(tag, cls="", style="", d=0.0, l=0.8, inner="", **attrs):
    extra = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
    cls = ("a " + cls).strip() if cls and cls != "scene" else cls
    return f'<{tag} class="{cls}" style="--d:{d:.2f}s;--l:{l:.2f}s;{style}" {extra}>{inner}</{tag}>'


def shot(name, left, top, width, d, l=0.9, kb=20, cls="slide-l"):
    return el(
        "div",
        f"shot {cls}",
        f"left:{left}px;top:{top}px;width:{width}px",
        d,
        l,
        f'<img class="a kb" style="--d:{d:.2f}s;--l:{kb}s" src="assets/{name}.png">',
    )


def svg_path(dpath, d, l, color="#232842", width=2, dashed=True, length=900):
    dash = f' stroke-dasharray="{length}"'
    return (
        f'<path class="a draw" style="--d:{d:.2f}s;--l:{l:.2f}s;--len:{length}" d="{dpath}" fill="none" '
        f'stroke="{color}" stroke-width="{width}" stroke-linecap="round"{dash}/>'
    )


def node(x, y, r, color, text, d, cls="pop", l=0.6, fs=13):
    return el(
        "div",
        f"node {cls}",
        f"left:{x - r}px;top:{y - r}px;width:{2 * r}px;height:{2 * r}px;background:{color};font-size:{fs}px",
        d,
        l,
        text,
    )


def label(x, y, text, sub, d, w=220):
    return el(
        "div",
        "lbl fade-up",
        f"left:{x}px;top:{y}px;width:{w}px",
        d,
        0.7,
        f"{text}<small>{sub}</small>",
    )


def scene(i, inner):
    return f'<div class="scene" style="--d:{STARTS[i]:.2f}s;--l:{LENGTHS[i]:.2f}s;z-index:{i + 1}">{inner}</div>'


def band():
    items = [
        "COVID-19",
        "USA–Iran war",
        "LPG crisis",
        "Russia–Ukraine war",
        "CJP protest",
        "One forward is all it takes",
    ] * 2
    return '<div class="band">' + "".join(f"<span>{t}</span><i>✺</i>" for t in items) + "</div>"


def s1():
    t = STARTS[0]
    msgs = [
        (
            "07:02 · family group",
            "The LPG crisis in India hikes the prices by 100%.",
            70,
            120,
            C(0, "message", 0.6),
        ),
        (
            "09:40 · reworded",
            "LPG rates doubled overnight because of the crisis, share before they hide it!",
            120,
            300,
            C(0, "reworded", 4.0),
        ),
        (
            "12:15 · hindi forward",
            "एलपीजी संकट से भारत में दाम 100% बढ़ गए।",
            70,
            480,
            C(0, "translated", 7.5),
        ),
    ]
    out = ""
    for sub, text, x, y, d in msgs:
        out += el(
            "div",
            "bubble fade-up",
            f"left:{x}px;top:{y}px",
            t + d,
            0.9,
            f"{text}<small>{sub}</small>",
        )
    # three dotted lines converge on a graph hub
    svg = '<svg style="position:absolute;inset:0" width="1280" height="720" viewBox="0 0 1280 720">'
    k = C(0, "connected", 12)
    for (x1, y1), d in (((470, 190), k), ((560, 360), k + 0.6), ((430, 540), k + 1.2)):
        svg += svg_path(
            f"M{x1} {y1} C 700 {y1}, 760 380, 905 380", t + d, 1.6, "#EF5B3F", 2.5, length=700
        )
    svg += "</svg>"
    out += svg
    hub = ""
    pts = [
        (905, 380, 16, "#EF5B3F"),
        (980, 320, 10, "#A57BE0"),
        (1000, 430, 10, "#6C8EEA"),
        (860, 300, 9, "#3FA57A"),
        (1060, 370, 9, "#E9B949"),
        (940, 470, 8, "#3FA57A"),
        (830, 450, 8, "#A57BE0"),
    ]
    for x, y, r, c in pts:
        hub += node(x, y, r, c, "", t + k + 1.4 + (x % 7) * 0.08, "pop", 0.5)
    gsvg = '<svg style="position:absolute;inset:0" width="1280" height="720">'
    for x, y, *_r in pts[1:]:
        gsvg += svg_path(f"M905 380 L{x} {y}", t + k + 1.6, 0.8, "#232842", 1.5, length=200)
    out += gsvg + hub
    out += el(
        "div",
        "mono fade",
        "left:860px;top:520px",
        t + k + 2.5,
        0.6,
        "FalkorDB claim graph · 11,758 fact-checks",
    )
    out += el(
        "div",
        "display fade-up",
        "left:70px;top:600px;font-size:64px",
        t + C(0, "Pehchan", 17),
        0.9,
        "Pehchan <span style='color:var(--ember)'>AI</span>",
    )
    out += el(
        "div",
        "fade-up",
        "left:380px;top:628px;font-size:22px;color:var(--muted)",
        t + C(0, "recorded", 17.8),
        0.9,
        "Answers only from recorded sources. Nothing else.",
    )
    return scene(0, out)


def s2():
    t = STARTS[1]
    out = el("div", "eyebrow fade", "", t, 0.5, "01 / Investigate")
    h2 = C(1, "human", 25.5)
    out += el(
        "div",
        "wrap fade-out",
        "",
        t + h2 - 0.3,
        0.6,
        shot("claim_form", 70, 90, 620, t + 0.3, cls="slide-r", kb=30)
        + el("div", "ring fade", "left:94px;top:140px;width:572px;height:84px", t + 1.2, 0.5),
    )
    # pipeline chips
    chips = [
        ("vector index", C(1, "searches", 3.5)),
        ("relevance check · both ways", C(1, "checks", 4.6)),
        ("no direct review", C(1, "Nobody", 6.0)),
    ]
    x = 70
    for text, d in chips:
        on = " on" if "no direct" not in text else ""
        style = f"left:{x}px;top:250px" + (
            ""
            if on
            else ";background:var(--sunsoft);border-color:var(--ember2);color:var(--ember2)"
        )
        out += el("div", f"chip{on} pop", "position:absolute;" + style, t + d, 0.5, text)
        x += 70 + 10 * len(text)
    # widening path: message → LPG entity → fuel-price frame → reviews
    svg = '<svg style="position:absolute;inset:0" width="1280" height="720">'
    w2, l2, f2, q2, c2 = (
        C(1, "widens", 8),
        C(1, "LPG", 9),
        C(1, "fuel", 10),
        C(1, "Quint", 11),
        C(1, "Crescendo", 11.6),
    )
    svg += svg_path("M150 420 C 230 420, 250 420, 330 420", t + w2, 0.8, "#A57BE0", 2.5, length=200)
    svg += svg_path("M330 420 C 410 420, 430 420, 510 420", t + l2, 0.8, "#A57BE0", 2.5, length=200)
    svg += svg_path("M510 420 C 580 420, 600 490, 660 510", t + f2, 0.8, "#3FA57A", 2.5, length=220)
    svg += svg_path(
        "M510 420 C 580 420, 600 350, 660 330", t + f2 + 0.3, 0.8, "#3FA57A", 2.5, length=220
    )
    svg += "</svg>"
    out += svg
    out += node(150, 420, 22, "#232842", "msg", t + w2 - 0.4, fs=12)
    out += node(330, 420, 24, "#6C8EEA", "LPG", t + l2 - 0.2)
    out += node(510, 420, 24, "#E9B949", "frame", t + f2 - 0.2, fs=11)
    out += node(660, 330, 16, "#3FA57A", "", t + q2)
    out += node(660, 510, 16, "#3FA57A", "", t + c2)
    out += label(96, 455, "Your message", "no recorded wording matches", t + w2 - 0.2)
    out += label(276, 455, "Entity: LPG", "shared · 1/degree weighted", t + l2)
    out += label(446, 455, "Fuel prices as weapons", "narrative frame", t + f2, 240)
    out += label(686, 300, "The Quint · FALSE", "related review", t + q2 + 0.2, 240)
    out += label(686, 530, "Fact Crescendo · False", "related review", t + c2 + 0.2, 240)
    out += shot("lpg_sources", 800, 60, 410, t + c2 + 0.9, kb=18)
    out += el(
        "div",
        "card fade-up",
        "left:70px;top:560px;width:620px",
        t + C(1, "context", 20),
        0.8,
        "<h3>Context, not a verdict</h3><p>Related reviews explain the narrative. They do not settle this exact message, so Pehchan drafts a reply with the sources and queues the case for a human.</p>",
    )
    out += shot("lpg_finding", 70, 90, 660, t + h2, kb=10, cls="fade-up")
    out += el("div", "ring fade", "left:92px;top:118px;width:300px;height:58px", t + h2 + 1.0, 0.5)
    out += shot("lpg_reply", 760, 290, 450, t + C(1, "drafts", 28), kb=10)
    return scene(1, out)


def s3():
    t = STARTS[2]
    out = el("div", "eyebrow fade", "", t, 0.5, "02 / Three specialists")
    roles = [
        (
            "Claim Scout",
            "finds candidates by meaning, in any language; checks relevance both ways",
            ["find_similar_claims"],
            70,
        ),
        (
            "Graph Detective",
            "follows the connections recorded in FalkorDB; widens when nothing matches",
            [
                "explore_narrative_graph",
                "find_evidence_path",
                "expand_shared_context",
                "breadth_first_search",
            ],
            330,
        ),
        (
            "Evidence &amp; Response",
            "re-reads the publisher records; chooses the next step; drafts the reply",
            ["get_claim_evidence"],
            590,
        ),
    ]
    for i, (name, desc, tools, x) in enumerate(roles):
        chips = "".join(
            f'<span class="tag" style="margin:4px 4px 0 0;display:inline-block">{c}</span>'
            for c in tools
        )
        out += el(
            "div",
            "card fade-up",
            f"left:{x}px;top:110px;width:240px;height:250px",
            t + [C(2, "Claim", 0.6), C(2, "Graph", 3.0), C(2, "Evidence", 6.0)][i],
            0.8,
            f"<h3>{name}</h3><p>{desc}</p><div style='margin-top:10px'>{chips}</div>",
        )
    # arrows down into FalkorDB
    svg = '<svg style="position:absolute;inset:0" width="1280" height="720">'
    for i, x in enumerate((190, 450, 710)):
        svg += svg_path(
            f"M{x} 365 L{x} 440", t + C(2, "FalkorDB", 5) + i * 0.3, 0.6, "#232842", 2, length=80
        )
    svg += svg_path(
        "M960 290 C 960 330, 960 360, 930 420",
        t + C(2, "hosted", 9.5) + 1,
        0.8,
        "#EF5B3F",
        2.5,
        length=200,
    )
    svg += "</svg>"
    out += svg
    out += el(
        "div",
        "card pop",
        "left:70px;top:445px;width:760px;height:110px;background:var(--ink);color:var(--paper);border:0",
        t + C(2, "FalkorDB", 5) + 0.6,
        0.8,
        '<h3 style="color:var(--paper)">FalkorDB claim graph</h3><p style="color:#C9CAD6">vector index · narrative paths · algo.SPpaths · algo.BFS · MERGE writes. The only store; remove it and nothing answers.</p>',
    )
    out += el(
        "div",
        "card fade-up",
        "left:860px;top:110px;width:350px;height:170px;background:var(--sunsoft)",
        t + C(2, "hosted", 9.5),
        0.8,
        '<span class="tag">hosted open model</span><h3 style="margin-top:8px">GPT-OSS 20B · OpenRouter</h3><p>Chooses the next tool, only from its list. The application decides every citation and every case status.</p>',
    )
    out += el(
        "div",
        "mono fade",
        "left:860px;top:300px",
        t + C(2, "list", 11),
        0.6,
        "allow-list · required reads · refused calls recorded",
    )
    a3 = C(2, "application", 14)
    out += shot("lpg_timeline", 860, 340, 350, t + a3, kb=14)
    for i, y in enumerate((392, 440, 488, 536, 600)):
        out += el(
            "div",
            "ring fade",
            f"left:874px;top:{y}px;width:322px;height:40px;border-radius:10px",
            t + a3 + 1.5 + i * 1.4,
            0.4,
        )
    return scene(2, out)


def s4():
    t = STARTS[3]
    out = el("div", "eyebrow fade", "", t, 0.5, "03 / Why the graph")
    # faint background graph
    import random

    rnd = random.Random(3)
    svg = '<svg style="position:absolute;inset:0" width="1280" height="720">'
    pts = [(rnd.randint(80, 1200), rnd.randint(110, 640)) for _ in range(28)]
    for i, (x, y) in enumerate(pts):
        x2, y2 = pts[(i * 7 + 3) % len(pts)]
        svg += (
            f'<line x1="{x}" y1="{y}" x2="{x2}" y2="{y2}" stroke="#232842" stroke-opacity=".08"/>'
        )
    path = [(170, 520), (390, 400), (640, 300), (890, 400), (1110, 520)]
    m4 = C(3, "meet", 2.2)
    for (x1, y1), (x2, y2), d in zip(path, path[1:], (m4, m4 + 1.2, m4 + 2.4, m4 + 3.6)):
        svg += svg_path(f"M{x1} {y1} L{x2} {y2}", t + d, 1.0, "#3FA57A", 4, length=300)
    svg += "</svg>"
    out += svg
    for x, y in pts:
        out += node(x, y, 4, "rgba(35,40,66,.25)", "", t + 0.3 + (x % 5) * 0.1, "fade", 0.6)
    b4 = max(C(3, "Bill", 4.1), m4 + 2.2)
    names = [
        ("vaccine-microchip wording", "#EF5B3F", C(3, "vaccine", 1.6), "CLAIM WORDING"),
        ("claim", "#F59E7E", m4 + 1.0, "CLAIM"),
        ("Bill Gates", "#6C8EEA", b4, "ENTITY · SHARED"),
        ("claim", "#F59E7E", m4 + 3.4, "CLAIM"),
        ("climate wording", "#EF5B3F", C(3, "climate", 6.5), "CLAIM WORDING"),
    ]
    for (x, y), (nm, c, d, kind) in zip(path, names):
        r = 34 if nm == "Bill Gates" else 22
        out += node(x, y, r, c, "", t + d, "pop", 0.6)
        out += label(x - 110, y + r + 10, nm, kind, t + d + 0.2)
    out += el(
        "div",
        "node pulse",
        f"left:{640 - 34}px;top:{300 - 34}px;width:68px;height:68px;background:transparent;border:3px solid #6C8EEA",
        t + b4 + 0.8,
        1.6,
    )
    for (x, y), rel in zip(
        ((280, 455), (515, 345), (765, 345), (1000, 455)),
        ("EXPRESSES", "MENTIONS", "MENTIONS", "EXPRESSES"),
    ):
        out += el(
            "div",
            "mono fade",
            f"left:{x - 40}px;top:{y}px;color:var(--mintink)",
            t + C(3, "edge", 7.5),
            0.5,
            rel,
        )
    out += el(
        "div",
        "counter fade-up",
        "left:70px;top:110px",
        t + C(3, "four", 8.5),
        0.9,
        "4 hops<small>algo.SPpaths · 0.01 s on this graph · the path as returned</small>",
    )
    out += el(
        "div",
        "card fade-up",
        "left:70px;top:600px;width:560px",
        t + C(3, "shared", 11),
        0.8,
        "<p>A shared entity explains <b>why</b> two claims are connected. It never says they agree, or that anyone coordinated them.</p>",
    )
    out += shot("graph_card", 850, 100, 360, t + C(3, "pathfinding", 14), kb=12)
    return scene(3, out)


def s5():
    t = STARTS[4]
    out = el("div", "eyebrow fade", "", t, 0.5, "04 / Act, and remember")
    out += el(
        "div",
        "chip on pop",
        "position:absolute;left:70px;top:110px",
        t + C(4, "saves", 0.5) - 0.3,
        0.5,
        "Save as case and remember it",
    )
    chain = [
        ("Investigation", "#232842", 160, 260),
        ("Submission", "#A57BE0", 420, 260),
        ("ClaimVariant", "#EF5B3F", 680, 260),
    ]
    rels = [("SUBMITTED", 290), ("MATCHES", 550)]
    svg = '<svg style="position:absolute;inset:0" width="1280" height="720">'
    w5, l5, m5 = C(4, "writes", 3.2), C(4, "linked", 5.0), C(4, "matched", 6.2)
    svg += svg_path("M200 260 L380 260", t + w5, 0.8, "#232842", 3, length=200)
    svg += svg_path("M460 260 L640 260", t + l5, 0.8, "#A57BE0", 3, length=200)
    svg += svg_path("M420 300 L420 420", t + m5, 0.7, "#A57BE0", 2, length=140)
    svg += svg_path(
        "M560 440 C 520 440, 480 440, 452 300",
        t + C(4, "follows", 14.5),
        1.0,
        "#A57BE0",
        2.5,
        length=220,
    )
    svg += "</svg>"
    out += svg
    for (nm, c, x, y), d in zip(chain, (C(4, "case", 2.2), w5 + 0.8, l5 + 0.8)):
        out += node(x, y, 40, c, nm, t + d, "pop", 0.6, fs=12)
    for (rel, x), d in zip(rels, (w5 + 0.4, l5 + 0.4)):
        out += el(
            "div", "mono fade", f"left:{x - 30}px;top:228px;color:var(--ink)", t + d, 0.5, rel
        )
    out += label(360, 430, "MENTIONS · USES_FRAME", "its tags, written back too", t + m5 + 0.4, 260)
    out += el(
        "div",
        "card fade-up",
        "left:70px;top:520px;width:560px",
        t + C(4, "changed", 24, nth=2),
        0.8,
        "<h3>The agent changed the graph</h3><p>The message itself is now a node, linked to what it matched and to the entities and frames it carries.</p>",
    )
    out += el(
        "div",
        "bubble fade-up",
        "left:560px;top:400px;max-width:380px;font-size:18px",
        t + C(4, "Tomorrow", 12.5),
        0.9,
        "Bill Gates wants to put microchips <b>into</b> people through the covid vaccine<b>!</b><small>the next day · one word changed</small>",
    )
    out += el(
        "div",
        "mono fade",
        "left:470px;top:330px;color:var(--violet)",
        t + C(4, "recognises", 15.2),
        0.5,
        "similarity 0.96 · recalled",
    )
    m5a = C(4, "answers", 17)
    out += shot("memory_finding", 680, 90, 530, t + m5a, kb=10)
    out += el(
        "div",
        "ring fade",
        "left:910px;top:170px;width:150px;height:30px;border-radius:999px",
        t + m5a + 1,
        0.5,
    )
    out += el(
        "div",
        "counter fade-up",
        "left:700px;top:560px;font-size:64px",
        t + C(4, "without", 21),
        0.9,
        "3.8 s<small>answered from graph memory · no models rerun · a cold run took 32 s</small>",
    )
    return scene(4, out)


def s6():
    t = STARTS[5]
    out = el("div", "eyebrow fade", "", t, 0.5, "05 / The same tools, over MCP")
    clients = ["Claude", "ChatGPT", "Gemini", "any MCP client"]
    for i, c in enumerate(clients):
        out += el(
            "div",
            "chip pop",
            f"position:absolute;left:70px;top:{120 + i * 52}px",
            t + 0.4 + i * 0.3,
            0.5,
            c,
        )
    svg = '<svg style="position:absolute;inset:0" width="1280" height="720">'
    for i in range(4):
        y = 140 + i * 52
        svg += svg_path(
            f"M230 {y} C 280 {y}, 290 230, 330 230",
            t + C(5, "MCP", 1.8) + i * 0.15,
            0.7,
            "#232842",
            1.5,
            length=160,
        )
    svg += svg_path("M430 230 L 500 230", t + 3.2, 0.5, "#232842", 2, length=80)
    svg += svg_path("M960 230 L 1005 230", t + (C(5, "MCP", 5) + 1.0), 0.5, "#232842", 2, length=60)
    svg += "</svg>"
    out += svg
    out += el(
        "div",
        "chip on pop",
        "position:absolute;left:330px;top:212px",
        t + C(5, "MCP", 1.8) + 0.5,
        0.5,
        "MCP · Streamable HTTP",
    )
    tools = [
        ("find_similar_claims", 1),
        ("get_claim_evidence", 1),
        ("explore_narrative_graph", 1),
        ("find_evidence_path", 1),
        ("expand_narrative_context", 1),
        ("assemble_evidence_dossier", 1),
        ("investigate_claim", 0),
        ("create_review_case", 0),
    ]
    for i, (nm, open_) in enumerate(tools):
        col, row = i % 2, i // 2
        bg = "var(--mint);color:var(--mintink)" if open_ else "var(--sky);color:var(--skyink)"
        out += el(
            "div",
            "tag pop",
            f"position:absolute;left:{530 + col * 225}px;top:{130 + row * 46}px;background:{bg};font-size:11px",
            t + C(5, "eight", 3.6) + i * 0.3,
            0.4,
            nm,
        )
    out += el(
        "div",
        "mono fade",
        "left:530px;top:320px",
        t + C(5, "Six", 6.2),
        0.5,
        "6 open to everyone · 2 reserved for the team",
    )
    out += el(
        "div",
        "card pop",
        "left:1010px;top:186px;width:200px;height:88px;background:var(--ink);color:var(--paper);border:0",
        t + (C(5, "MCP", 5) + 1.0) + 0.3,
        0.6,
        '<h3 style="color:var(--paper);font-size:18px">FalkorDB</h3><p style="color:#C9CAD6;font-size:13px">one graph · one evidence policy</p>',
    )
    lines = [
        "$ python scripts/check_public_endpoint.py https://16-192-177-240.sslip.io",
        "<span class='ok'>/health 200</span>   <span class='ok'>/api/config 200</span>   /api/investigations <span class='k'>401 (protected)</span>",
        "tools: [assemble_evidence_dossier, expand_narrative_context, explore_narrative_graph,",
        "        find_evidence_path, find_similar_claims, get_claim_evidence]",
        'call: assemble_evidence_dossier("Putin has banned 5G in Russia and destroyed all the towers.")',
        "<span class='ok'>dossier: KNOWN_RECYCLED_CLAIM · NEEDS_HUMAN_REVIEW</span>",
        '- PolitiFact rated "Putin bans 5G across Russia, destroys all towers." as "False"',
        "  https://www.politifact.com/factchecks/2023/aug/10/…",
    ]
    k6 = C(5, "client", 8.5)
    body = "".join(
        el("span", "ln fade", "", t + k6 + 0.5 + i * 1.1, 0.4, ln) for i, ln in enumerate(lines)
    )
    out += el("div", "term fade-up", "left:70px;top:380px;width:860px", t + k6, 0.8, body)
    out += el(
        "div",
        "card fade-up",
        "left:70px;top:632px;width:860px;padding:14px 22px;background:var(--sunsoft);border-color:transparent",
        t + C(5, "Claude", 21),
        0.8,
        '<span class="mono" style="color:var(--ember2)">MCP server URL</span> &nbsp; <span style="font-family:Geist Mono,monospace;font-size:16px">https://16-192-177-240.sslip.io/public/mcp/</span>',
    )
    out += el(
        "div",
        "card fade-up",
        "left:950px;top:380px;width:260px",
        t + C(5, "structured", 19),
        0.8,
        "<p>Structured results: finding, status, citations with URLs and ratings, and the uncertainty, exactly as the web page gets them.</p>",
    )
    return scene(5, out)


def s7():
    t = STARTS[6]
    out = el("div", "eyebrow fade", "", t, 0.5, "06 / What comes next")
    out += el(
        "div",
        "display fade-up",
        "left:70px;top:80px;font-size:54px",
        t + 0.3,
        0.8,
        "This is a <span style='color:var(--ember)'>beginning.</span>",
    )
    items = [
        (
            "Relevance in Hindi, Tamil and Telugu",
            "confirm cross-language matches, not just surface them",
        ),
        (
            "A graph that grows itself",
            "on no match, query the public Fact Check Tools index, ingest the reviews into FalkorDB, investigate again",
        ),
        (
            "A WhatsApp or Telegram tipline",
            "the investigation desk where the forwards actually arrive",
        ),
        (
            "Fact-checking newsrooms as partners",
            "labelled forwards, reviewed tags, shared cases with owners and history",
        ),
        ("Entity linking to Wikidata", "the same person or place is one node across languages"),
    ]
    svg = (
        '<svg style="position:absolute;inset:0" width="1280" height="720">'
        + svg_path("M142 190 L142 640", t + 1, 18, "#EF5B3F", 2, length=460)
        + "</svg>"
    )
    out += svg
    c7 = [
        C(6, "Hindi", 2),
        C(6, "grow", 6),
        C(6, "Fact", 12),
        C(6, "WhatsApp", 16),
        C(6, "newsrooms", 20),
    ]
    body = "".join(
        el(
            "div",
            "step fade-up",
            "",
            t + c7[i],
            0.8,
            f"<small>{i + 1:02d}</small>{h}<div style='font-size:16px;color:var(--muted);margin-top:2px'>{s}</div>",
        )
        for i, (h, s) in enumerate(items)
    )
    out += el("div", "roadmap", "", t, 1, body)
    return scene(6, out)


def s8():
    t = STARTS[7]
    out = ""
    tiles = [
        ("lpg_reply", 70, 70, 330),
        ("graph_card", 430, 70, 400),
        ("memory_finding", 860, 70, 350),
        ("tools", 860, 300, 350),
    ]
    for i, (nm, x, y, w) in enumerate(tiles):
        out += shot(
            nm,
            x,
            y,
            w,
            t
            + [
                C(7, "forwarded", 1),
                C(7, "published", 3),
                C(7, "connections", 5),
                C(7, "reply", 7),
            ][i],
            kb=10,
            cls="fade-up",
        ).replace(f"width:{w}px", f"width:{w}px;height:200px")
    out += el(
        "div",
        "display fade-up",
        "left:70px;top:420px;font-size:72px",
        t + C(7, "Pehchan", 7, nth=2),
        0.9,
        "Pehchan <span style='color:var(--ember)'>AI</span>",
    )
    out += el(
        "div",
        "fade-up",
        "left:70px;top:510px;font-size:24px;color:var(--muted)",
        t + C(7, "Beyond", 8),
        0.9,
        "Beyond the claim. Into the connections.",
    )
    out += el(
        "div",
        "mono fade-up",
        "left:70px;top:560px;font-size:13px",
        t + C(7, "Graph", 9),
        0.9,
        "Graph Hacks · Track 1 · Agents That Act on Connected Data",
    )
    out += el(
        "div",
        "mono fade-up",
        "left:70px;top:590px;font-size:13px",
        t + C(7, "Graph", 9) + 0.6,
        0.9,
        "github.com/harshbpathak/Pehchaan · 16-192-177-240.sslip.io",
    )
    out += el("div", "fade", "", t + C(7, "connections", 11, nth=2), 1, band())
    return scene(7, out)


def build_html():
    html = f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"
    html += s1() + s2() + s3() + s4() + s5() + s6() + s7() + s8()
    html += "</body></html>"
    (V / "anim.html").write_text(html, encoding="utf-8")


async def render():
    proc = subprocess.Popen(
        [
            EDGE,
            "--headless=new",
            "--disable-gpu",
            "--remote-debugging-port=9466",
            f"--user-data-dir={V / 'profile2'}",
            f"--window-size={W},{H}",
            "--hide-scrollbars",
            "about:blank",
        ]
    )
    for _ in range(50):
        try:
            page = next(
                t
                for t in json.load(urllib.request.urlopen("http://127.0.0.1:9466/json"))
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

        await call("Page.enable")
        await call("Runtime.enable")
        await call(
            "Emulation.setDeviceMetricsOverride",
            width=W,
            height=H,
            deviceScaleFactor=1,
            mobile=False,
        )
        await call("Page.navigate", url=(V / "anim.html").as_uri())
        await asyncio.sleep(4)  # fonts and images
        await call(
            "Runtime.evaluate",
            expression="document.fonts.ready.then(() => true)",
            awaitPromise=True,
        )
        await call(
            "Runtime.evaluate", expression="document.getAnimations().forEach(a => a.pause())"
        )
        import os

        preview = os.environ.get("PREVIEW")
        if preview:  # a few timestamps only, for checking the design
            for sec in preview.split(","):
                await call(
                    "Runtime.evaluate",
                    expression=f"document.getAnimations().forEach(a => {{ a.currentTime = {float(sec) * 1000:.1f}; }})",
                )
                r = await call("Page.captureScreenshot", format="png")
                (V / f"preview_{float(sec):06.1f}.png").write_bytes(base64.b64decode(r["data"]))
            proc.terminate()
            return
        frames = int(TOTAL * FPS)
        started = time.time()
        for i in range(frames):
            ms = i * 1000 / FPS
            await call(
                "Runtime.evaluate",
                expression=f"document.getAnimations().forEach(a => {{ a.currentTime = {ms:.1f}; }})",
            )
            r = await call("Page.captureScreenshot", format="png")
            (FR / f"{i:05d}.png").write_bytes(base64.b64decode(r["data"]))
            if i % 240 == 0:
                print(f"frame {i}/{frames}  {time.time() - started:.0f}s", flush=True)
    proc.terminate()


def encode():
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out = ROOT / "artifacts" / "pehchan-demo.mp4"
    subprocess.run(
        [
            ff,
            "-y",
            "-loglevel",
            "error",
            "-framerate",
            str(FPS),
            "-i",
            str(FR / "%05d.png"),
            "-i",
            str(V / "narration.wav"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "medium",
            "-crf",
            "22",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out),
        ],
        check=True,
    )
    print("written", out, round(out.stat().st_size / 1e6, 1), "MB")


if __name__ == "__main__":
    import os

    build_html()
    print("scenes", STARTS, "total", TOTAL)
    asyncio.run(render())
    if not os.environ.get("PREVIEW"):
        encode()
