"""Synthesize the demo narration and record when each word is spoken.

Writes `artifacts/video/narration.wav` (one track, each scene padded to its length) and
`artifacts/video/cues.json` with the scene lengths and per-word timestamps. The renderer
(`render_demo_video.py`) places every visual beat at the word it belongs to, so picture and
voice stay in step however the voice paces a sentence.

    python scripts/narrate_demo_video.py
"""

import asyncio
import json
import subprocess
import wave
from pathlib import Path

import edge_tts
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "video"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
VOICE, RATE = "en-IN-NeerjaNeural", "+12%"
TAIL = 0.6  # silence after each scene's last word

SCENES = [
    "It starts with a forward. A message about LPG prices lands in a family group at seven in the morning. By noon it has been reworded, translated, and attached to the week's news. Has anyone checked this before, and what is it connected to? We built Pehchan AI to answer that from recorded sources, and nothing else.",
    "So let's paste that message in. Pehchan searches the wordings fact-checkers have already reviewed and checks how closely each one matches. Nobody has reviewed this exact sentence. So the Graph Detective widens the search through what the message shares with the graph: the LPG entity, and the fuel-price narrative. That reaches related reviews from The Quint and Fact Crescendo. Those reviews are context, not a verdict, so Pehchan drafts a reply with the sources and sends the case to a human.",
    "Behind that answer are three specialists. Claim Scout finds candidates by meaning, in any language, and checks relevance both ways. Graph Detective follows the connections recorded in FalkorDB. Evidence and Response re-reads the sources and chooses the next step. A hosted open model decides which tool to call next, but only from its list; the application decides every citation and every case status.",
    "This is where the graph earns its place. A vaccine-microchip claim and a climate claim have nothing in common as text. In the graph they meet at one entity, Bill Gates, four hops apart. FalkorDB returns that path with its native pathfinding algorithm, and Pehchan shows every edge behind it. A shared entity explains why two claims are connected; it never claims they agree.",
    "Now the part I like most. A researcher saves an investigation as a case. That writes the message itself into the graph, linked to what it matched. Tomorrow the same forward arrives with one word changed. Pehchan recognises it, follows the saved relationship, and answers from the graph's own memory, without rerunning the models. The agent did not just read the graph. It changed it.",
    "None of this is locked inside one web page. The same eight tools are served over MCP. Here an MCP client calls Pehchan's dossier tool on the live server and gets back structured results, with sources and uncertainty. Six tools are open to anyone; two write to the graph and stay with the team. Claude, ChatGPT or Gemini can use the same graph, under the same evidence policy.",
    "And this is a beginning. Next, we want relevance checks in Hindi, Tamil and Telugu, so cross-language matches are confirmed, not just surfaced. We want the graph to grow itself: when nothing matches, look the claim up in the public Fact Check Tools index, write what it finds into FalkorDB, and investigate again. And a WhatsApp tipline in front of it, with fact-checking newsrooms as partners.",
    "So that is Pehchan. A forwarded message becomes an investigation you can inspect: published sources, visible connections, a drafted reply, and a clear next step. When the evidence is not there, it says so. Built on FalkorDB for Graph Hacks, Track One. Pehchan AI. Beyond the claim, into the connections.",
]


async def synthesize(index, text):
    """One scene: MP3 from the voice service with word boundaries, converted to 22.05 kHz mono WAV."""
    mp3 = OUT / f"narration{index}.mp3"
    words = []
    speech = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary")
    with mp3.open("wb") as f:
        async for chunk in speech.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append((round(chunk["offset"] / 1e7, 2), chunk["text"]))
    wav = OUT / f"narration{index}.wav"
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "22050", "-ac", "1", str(wav)],
        check=True,
    )
    with wave.open(str(wav)) as w:
        spoken = w.getnframes() / w.getframerate()
    return wav, spoken, words


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    parts = [await synthesize(i, text) for i, text in enumerate(SCENES)]
    lengths = [round(spoken + TAIL, 2) for _, spoken, _ in parts]
    with wave.open(str(parts[0][0])) as first:
        params = first.getparams()
    with wave.open(str(OUT / "narration.wav"), "wb") as track:
        track.setparams(params)
        for (wav, _, _), length in zip(parts, lengths):
            with wave.open(str(wav)) as w:
                track.writeframes(w.readframes(w.getnframes()))
                pad = int(length * params.framerate) - w.getnframes()
            if pad > 0:
                track.writeframes(b"\x00" * pad * params.sampwidth * params.nchannels)
    cues = {"lengths": lengths, "words": [words for _, _, words in parts]}
    (OUT / "cues.json").write_text(json.dumps(cues), encoding="utf-8")
    for i, (length, (_, _, words)) in enumerate(zip(lengths, cues["words"])):
        print(f"scene {i + 1}: {length:5.1f} s, {len(words)} words")
    print("total", round(sum(lengths), 1), "s ->", OUT / "narration.wav", "and", OUT / "cues.json")


if __name__ == "__main__":
    asyncio.run(main())
