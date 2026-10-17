"""Load the prepared datasets, their annotations and embeddings into any FalkorDB.

Point FALKORDB_HOST/PORT/USERNAME/PASSWORD/SSL at the target (for example FalkorDB Cloud),
then run from the repository root. Reuses the validated ingest path, so source checks,
annotation span checks and idempotent MERGE writes apply. Saved cases are not copied.
"""

import argparse
import json
from pathlib import Path

from pehchan.annotations import load_annotations
from pehchan.graph import GraphStore
from pehchan.ingestion import load_prepared
from pehchan.models import Embedder
from pehchan.semantic import VectorIndex

DATASETS = (
    ("data/processed/claims.jsonl", "data/annotations/collection.json"),
    ("data/processed/events.jsonl", "data/annotations/events.json"),
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", default="pehchan")
    args = parser.parse_args()
    # Validate every input before the first write.
    loaded = []
    for records_path, annotations_path in DATASETS:
        records = load_prepared(Path(records_path))
        loaded.append((records_path, records, load_annotations(Path(annotations_path), records)))
    store = GraphStore(args.graph)
    try:
        store.init_schema()
        for name, records, annotations in loaded:
            store.ingest(records, annotations)
            print(f"ingested {len(records)} reviews and {len(annotations)} annotations from {name}")
        status = VectorIndex(store).build(Embedder())
        print(
            json.dumps(
                {
                    "stats": store.stats(),
                    "embeddings": {
                        k: status[k] for k in ("total", "ready", "written", "index_operational")
                    },
                },
                indent=2,
            )
        )
    finally:
        store.close()


if __name__ == "__main__":
    main()
