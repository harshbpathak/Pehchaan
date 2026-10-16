"""Streaming readers, deterministic deduplication and auditable rejection reports."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import ijson

from .records import ConflictingReviewError, RecordError, normalize_review


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unwrap(value: object) -> Iterator[dict]:
    if isinstance(value, list):
        for item in value:
            yield from unwrap(item)
    elif isinstance(value, dict):
        types = value.get("@type", [])
        types = [types] if isinstance(types, str) else types
        if "ClaimReview" in types or "claimReviewed" in value:
            yield value
        else:
            for key in ("dataFeedElement", "item", "@graph"):
                if key in value:
                    yield from unwrap(value[key])


def iter_reviews(path: Path) -> Iterator[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    suffixes = path.suffixes
    if ".jsonl" in suffixes or ".ndjson" in suffixes:
        with opener(path, "rt", encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, 1):
                if line.strip():
                    try:
                        yield from unwrap(json.loads(line))
                    except json.JSONDecodeError as exc:
                        raise RecordError(f"invalid JSON at line {line_number}: {exc.msg}") from exc
        return
    with opener(path, "rb") as stream:
        # Discover the root container with the parser, rather than guessing from file size.
        prefix = ""
        for event_prefix, event, value in ijson.parse(stream):
            if event_prefix == "" and event == "start_array":
                prefix = "item"
                break
            if event_prefix == "" and event == "map_key" and value in {"dataFeedElement", "@graph"}:
                prefix = f"{value}.item"
                break
            if event_prefix == "" and event == "map_key" and value == "claimReviewed":
                break
        stream.seek(0)
        for value in ijson.items(stream, prefix, use_float=True):
            yield from unwrap(value)


def prepare(
    input_path: Path,
    output_path: Path,
    report_path: Path,
    *,
    source: str,
    contains: list[str] | None = None,
    limit: int | None = None,
) -> dict:
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    paths = [p.resolve() for p in (input_path, output_path, report_path)]
    if len(set(paths)) != 3:
        raise ValueError("input, output and report paths must differ")
    digest = file_sha256(input_path)
    report = {
        "source": source,
        "source_sha256": digest,
        "scanned": 0,
        "selected": 0,
        "duplicates": 0,
        "filtered": 0,
        "rejected": [],
        "warnings": [],
    }
    seen: dict[str, dict] = {}
    needles = [s.casefold() for s in contains or []]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        with staging.open("w", encoding="utf-8", newline="\n") as output:
            for index, raw in enumerate(iter_reviews(input_path), 1):
                report["scanned"] += 1
                if needles and not any(
                    s in str(raw.get("claimReviewed", "")).casefold() for s in needles
                ):
                    report["filtered"] += 1
                    continue
                try:
                    record = normalize_review(raw, source, digest, index)
                    key = record["factcheck_id"]
                    if key in seen:
                        previous = seen[key]
                        if previous["rating_original"] != record["rating_original"]:
                            raise ConflictingReviewError(
                                "conflicting rating for the same source URL and claim"
                            )
                        report["duplicates"] += 1
                        continue
                    seen[key] = record
                except ConflictingReviewError as exc:
                    report["aborted"] = True
                    report["rejected"].append({"index": index, "reason": str(exc)})
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                    raise
                except RecordError as exc:
                    report["rejected"].append({"index": index, "reason": str(exc)})
                    continue
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                report["selected"] += 1
                if record["warnings"]:
                    report["warnings"].append({"index": index, "warnings": record["warnings"]})
                if limit and report["selected"] >= limit:
                    break
        if not report["scanned"]:
            raise RecordError("no ClaimReview records found; check input format (HTML is not data)")
        staging.replace(output_path)
    finally:
        staging.unlink(missing_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def load_prepared(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            expected = normalize_review(
                record["raw"],
                record["source"],
                record["source_sha256"],
                record["source_record_index"],
            )
            if record != expected:
                raise RecordError(f"prepared record {index} was modified; rerun prepare")
            records.append(record)
    if not records:
        raise RecordError("prepared dataset is empty")
    if len({r["factcheck_id"] for r in records}) != len(records):
        raise RecordError("prepared dataset contains duplicate factcheck IDs")
    return records
