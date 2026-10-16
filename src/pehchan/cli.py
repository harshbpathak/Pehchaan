from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import ijson
from redis.exceptions import RedisError

from .annotations import load_annotations
from .graph import GraphStore
from .ingestion import load_prepared, prepare


def main() -> int:
    parser = argparse.ArgumentParser(description="Pehchan ingestion and FalkorDB validation")
    parser.add_argument("--graph", help="graph name (default: FALKORDB_GRAPH or pehchan)")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="normalize ClaimReview markup into audited JSONL")
    prep.add_argument("input", type=Path)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--report", type=Path, required=True)
    prep.add_argument("--source", required=True, help="dataset origin URL or attribution label")
    prep.add_argument(
        "--contains", action="append", help="case-insensitive claim substring; OR matching"
    )
    prep.add_argument("--limit", type=int)
    ingest = sub.add_parser("ingest", help="idempotently merge prepared records into FalkorDB")
    ingest.add_argument("input", type=Path)
    ingest.add_argument("--annotations", type=Path)
    valid = sub.add_parser("validate", help="verify provenance, graph integrity and algorithms")
    valid.add_argument("input", type=Path)
    valid.add_argument("--require-narrative", action="store_true")
    valid.add_argument("--output", type=Path)
    search = sub.add_parser("search", help="lexical candidate matching; not a verdict")
    search.add_argument("claim")
    for name in ("evidence", "narratives", "bfs"):
        command = sub.add_parser(name)
        command.add_argument("variant_id")
    path = sub.add_parser("path")
    path.add_argument("from_id")
    path.add_argument("to_id")
    sub.add_parser("stats")
    args = parser.parse_args()
    store = None
    try:
        if args.command == "prepare":
            result = prepare(
                args.input,
                args.output,
                args.report,
                source=args.source,
                contains=args.contains,
                limit=args.limit,
            )
        else:
            # Validate all input before creating schema or writing any graph nodes.
            if args.command in {"ingest", "validate"}:
                records = load_prepared(args.input)
            if args.command == "ingest":
                annotations = load_annotations(args.annotations, records)
            store = GraphStore(args.graph)
            if args.command == "ingest":
                store.init_schema()
                result = store.ingest(records, annotations)
            elif args.command == "validate":
                result = store.validate(records, require_narrative=args.require_narrative)
            elif args.command == "search":
                result = store.candidates(args.claim)
            elif args.command == "evidence":
                result = store.evidence(args.variant_id)
            elif args.command == "narratives":
                result = store.narrative_paths(args.variant_id)
            elif args.command == "bfs":
                result = store.bfs(args.variant_id)
            elif args.command == "path":
                result = store.shortest_path(args.from_id, args.to_id)
            else:
                result = store.stats()
        if args.command == "prepare":
            result = {
                **result,
                "rejected": len(result["rejected"]),
                "warnings": len(result["warnings"]),
                "report": str(args.report),
            }
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        print(rendered)
        if args.command == "validate" and args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        return 1 if isinstance(result, dict) and result.get("ok") is False else 0
    except (ValueError, KeyError, OSError, RedisError, ijson.JSONError) as exc:
        # Never echo connection strings, passwords or the raw exception from a network client.
        if isinstance(exc, (ValueError, KeyError, FileNotFoundError)):
            print(f"Input error: {exc}", file=sys.stderr)
        else:
            print(
                f"Operation failed ({type(exc).__name__}). Check input and FalkorDB availability.",
                file=sys.stderr,
            )
        return 2
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
