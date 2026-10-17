"""Explicit live Google AI Studio check; requires a locally configured API key."""

import argparse
import json
from pathlib import Path

from pehchan.inference import configuration
from pehchan.service import ApplicationService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claim", default="Coronavirus is being spread by 5G technology.")
    args = parser.parse_args()
    config = configuration()
    if config["mode"] not in {"gemini", "openrouter"} or not config["configured"]:
        parser.exit(2, "Set OPENROUTER_API_KEY or GEMINI_API_KEY before this live check.\n")
    service = ApplicationService()
    try:
        report = service.assemble_evidence_dossier(args.claim)
        assert report["inference"]["mode"] == config["mode"]
        assert report["inference"]["tool_calls"] >= 2
        assert set(report["inference"]["factcheck_ids"]) <= {
            c["factcheck_id"] for c in report["citations"]
        }
        path = Path(__file__).resolve().parents[1] / "artifacts" / "gemma-live-verification.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": True,
                    "model": config["model"],
                    "status": report["status"],
                    "tool_calls": report["inference"]["tool_calls"],
                    "report": str(path),
                }
            )
        )
    except (RuntimeError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")
    finally:
        service.close()


if __name__ == "__main__":
    main()
