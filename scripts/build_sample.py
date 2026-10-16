"""Extract the exact reviewed sample from a prepared feed; never generate publisher records."""

import argparse
import json
from pathlib import Path

from pehchan.ingestion import load_prepared

# Explicitly inspected claim texts, not keyword classifications of the entire dataset.
SELECTION = {
    "variant_c33c5ad75f0189bd1179dcf3": (
        "Biomedical technology as covert control",
        "Vaccines",
        "microchips",
    ),
    "variant_b798bbbaab3675372ee8c4c3": (
        "Vaccination as microchip implantation",
        "Vaccines",
        "microchip",
    ),
    "variant_894e450e8e7f3219fffbd7a8": (
        "Vaccination as microchip implantation",
        "Vaccines",
        "microchip",
    ),
    "variant_700ff916add10df61b609425": (
        "Biomedical technology as covert control",
        "Vaccines",
        "5G",
    ),
    "variant_9e4e7b29e161704389906809": ("5G as a cause of coronavirus illness", "5G", "5G"),
    "variant_906b5343dde8cfb4588d3456": ("5G as a cause of coronavirus illness", "5G", "5G"),
    "variant_e08e47e302b6bbca771ac442": ("5G as a cause of coronavirus illness", "5G", "5G"),
    "variant_eb55739fc76852783c3006c9": ("Moon landing as a staged event", "Space", None),
    "variant_3f38d289f8363246f70c8c4b": ("Moon landing as a staged event", "Space", None),
    "variant_03a7205f8986150abe18ca81": (
        "Climate change as a fabricated deception",
        "Climate",
        None,
    ),
    "variant_1a8529389b2b0d2708b9250d": (
        "Climate change as a fabricated deception",
        "Climate",
        None,
    ),
    "variant_afb743cbbf7de77afdb268a2": (
        "Climate change as a fabricated deception",
        "Climate",
        None,
    ),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prepared_feed", type=Path)
    args = parser.parse_args()
    records = {r["variant_id"]: r for r in load_prepared(args.prepared_feed)}
    missing = set(SELECTION) - records.keys()
    if missing:
        raise ValueError(f"Selected records absent from this feed snapshot: {sorted(missing)}")
    selected, annotations, manifest_rows = [], [], []
    for variant_id, (frame, topic, entity_span) in SELECTION.items():
        record = records[variant_id]
        selected.append(record["raw"])
        row = {
            "variant_id": variant_id,
            "reviewed_by": "Codex (AI-assisted text inspection; human review pending)",
            "rationale": "The recorded claim text expresses this broad frame. This annotation is an "
            "inference, not publisher markup, proof of claim equivalence, or coordination.",
            "frames": [
                {
                    "name": frame,
                    "description": "Curated thematic connection; propositions may differ.",
                }
            ],
            "topics": [{"name": topic}],
            "entities": [],
        }
        if entity_span:
            row["entities"] = [
                {
                    "name": "5G" if entity_span == "5G" else "Microchip",
                    "type": "Technology",
                    "evidence_span": entity_span,
                }
            ]
        annotations.append(row)
        manifest_rows.append(
            {
                k: record[k]
                for k in ("variant_id", "url_original", "source_record_index", "publisher_name")
            }
        )
    destination = Path("data/samples")
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {
        "dataset": "Google Data Commons ClaimReview Markup Tool feed",
        "downloaded_at": "2026-10-18 (Asia/Calcutta)",
        "feed_url": next(iter(records.values()))["source"],
        "feed_sha256": next(iter(records.values()))["source_sha256"],
        "attribution": "Data Commons / Google Fact Check Tools and the publishers named per record",
        "compilation_license": "https://creativecommons.org/licenses/by/4.0/",
        "license_notes": "Individual markup licenses are preserved when present. Publisher article "
        "content is not included. See publisher terms for article content.",
        "transformations": "12 ClaimReview objects selected without editing their source fields. "
        "Narrative, topic and entity annotations are separate AI-assisted inferences.",
        "records": manifest_rows,
    }
    for filename, payload in (
        ("claimreviews.json", selected),
        ("annotations.json", annotations),
        ("manifest.json", manifest),
    ):
        (destination / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        f"Wrote {len(selected)} genuine source records and {len(annotations)} separate annotations."
    )


if __name__ == "__main__":
    main()
