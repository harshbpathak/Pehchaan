import copy
import gzip
import json

import ijson
import pytest

from pehchan.annotations import load_annotations
from pehchan.ingestion import iter_reviews, load_prepared, prepare
from pehchan.records import RecordError, canonical_url, normalize_review, normalize_text


def test_stable_identity_preserves_negation_and_publisher_verdict(review):
    first = normalize_review(review, "test", "abc", 1)
    second = normalize_review(review, "other location", "def", 99)
    assert first["factcheck_id"] == second["factcheck_id"]
    assert first["claim_id"] == second["claim_id"]
    assert first["raw"] == review
    assert first["verdict_original"] == review["reviewRating"]["alternateName"]
    assert first["claim_date"] == ""  # Review date is not claim publication date.
    assert first["publisher_name"] == "Synthetic Test Publisher"
    opposite = copy.deepcopy(review)
    opposite["claimReviewed"] = "The town clock does not run on moonlight."
    assert normalize_review(opposite, "test", "abc", 2)["claim_id"] != first["claim_id"]


@pytest.mark.parametrize("shape", ["single", "array", "graph", "feed", "jsonl", "gzip"])
def test_source_containers(tmp_path, review, shape):
    path = tmp_path / ("source.jsonl" if shape == "jsonl" else "source.json")
    payload = review
    if shape in {"array", "gzip"}:
        payload = [review]
    elif shape == "graph":
        payload = {"@context": "https://schema.org", "@graph": [review]}
    elif shape == "feed":
        payload = {"@type": "DataFeed", "dataFeedElement": [{"item": [review]}]}
    if shape == "gzip":
        path = tmp_path / "source.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump(payload, stream)
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    assert list(iter_reviews(path)) == [review]


def test_dedup_reject_and_tamper_detection(tmp_path, review):
    broken = copy.deepcopy(review)
    del broken["reviewRating"]
    source = tmp_path / "raw.json"
    source.write_text(json.dumps([review, review, broken]), encoding="utf-8")
    output, report = tmp_path / "normalized.jsonl", tmp_path / "report.json"
    result = prepare(source, output, report, source="synthetic test")
    assert result["selected"] == 1
    assert result["duplicates"] == 1
    assert len(result["rejected"]) == 1
    record = load_prepared(output)[0]
    record["verdict_original"] = "invented verdict"
    output.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(RecordError, match="modified"):
        load_prepared(output)


def test_conflicting_rating_is_audited(tmp_path, review):
    conflicting = copy.deepcopy(review)
    conflicting["reviewRating"]["alternateName"] = "Different rating"
    source = tmp_path / "raw.json"
    source.write_text(json.dumps([review, conflicting]))
    with pytest.raises(RecordError, match="conflicting rating"):
        prepare(source, tmp_path / "out.jsonl", tmp_path / "report.json", source="test")
    result = json.loads((tmp_path / "report.json").read_text())
    assert "conflicting rating" in result["rejected"][0]["reason"]
    assert result["aborted"] is True
    assert not (tmp_path / "out.jsonl").exists()


def test_annotations_cannot_invent_entities(tmp_path, review):
    record = normalize_review(review, "test", "abc", 1)
    path = tmp_path / "annotations.json"
    row = {
        "variant_id": record["variant_id"],
        "reviewed_by": "test curator",
        "rationale": "synthetic test",
        "entities": [
            {"name": "Imaginary entity", "type": "Thing", "evidence_span": "not in claim"}
        ],
    }
    path.write_text(json.dumps([row]))
    with pytest.raises(RecordError, match="evidence_span"):
        load_annotations(path, [record])


def test_dates_urls_and_numeric_ratings(review):
    review["datePublished"] = "2024-02-30"
    review["reviewRating"] = {"ratingValue": 2, "bestRating": 4}
    record = normalize_review(review, "test", "abc", 1)
    assert record["verdict_original"] == "2"
    assert record["rating_original"]["bestRating"] == 4
    assert "INVALID_REVIEW_DATE" in record["warnings"]
    assert (
        canonical_url("https://Checks.example/a?b=2&utm_source=x&a=1#test")
        == "https://checks.example/a?a=1&b=2"
    )
    with pytest.raises(RecordError):
        canonical_url("javascript:alert(1)")
    assert normalize_text("  CAFÉ\nclock  ") == "café clock"


def test_filter_and_limit(tmp_path, review):
    source = tmp_path / "raw.json"
    source.write_text(json.dumps([review, {**review, "claimReviewed": "Different claim"}]))
    result = prepare(
        source,
        tmp_path / "out",
        tmp_path / "report",
        source="test",
        contains=["MOONLIGHT"],
        limit=1,
    )
    assert result["selected"] == 1


def test_invalid_json_does_not_replace_previous_output(tmp_path):
    source, output = tmp_path / "raw.json", tmp_path / "out.jsonl"
    source.write_text("<!DOCTYPE html>")
    output.write_text("previous valid output")
    with pytest.raises(ijson.JSONError):
        prepare(source, output, tmp_path / "report", source="test")
    assert output.read_text() == "previous valid output"


def test_conflicting_rating_can_be_skipped_and_audited(tmp_path, review):
    conflicting = copy.deepcopy(review)
    conflicting["reviewRating"]["alternateName"] = "Different rating"
    source = tmp_path / "feed.json"
    source.write_text(json.dumps([review, conflicting]))
    report = prepare(
        source, tmp_path / "out.jsonl", tmp_path / "report.json", source="test", on_conflict="skip"
    )
    assert report["selected"] == 1 and "aborted" not in report
    assert report["rejected"][0]["reason"].startswith("conflicting rating")
    with pytest.raises(ValueError, match="on_conflict"):
        prepare(source, tmp_path / "o2.jsonl", tmp_path / "r2.json", source="test", on_conflict="x")
