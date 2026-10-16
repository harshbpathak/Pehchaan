"""Normalize source markup without inventing publisher verdicts or claim equivalence."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class RecordError(ValueError):
    pass


class ConflictingReviewError(RecordError):
    pass


def stable_id(kind: str, *values: str) -> str:
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"{kind}_{hashlib.sha256(encoded).hexdigest()[:24]}"


def normalize_text(value: str) -> str:
    # Retain punctuation, numbers and negation: similarity is not proposition equivalence.
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def canonical_url(value: object) -> str:
    value = text(value)
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ValueError("URL must be absolute HTTP(S)")
        if parts.username or parts.password:
            raise ValueError("credential-bearing URLs are unsupported")
        port = parts.port
        host = parts.hostname.lower().encode("idna").decode("ascii")
        if ":" in host:
            host = f"[{host}]"
        if port and (parts.scheme.lower(), port) not in {("https", 443), ("http", 80)}:
            host += f":{port}"
        query = urlencode(
            sorted(
                (k, v)
                for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
            )
        )
        return urlunsplit((parts.scheme.lower(), host, parts.path or "/", query, ""))
    except (ValueError, UnicodeError) as exc:
        raise RecordError(f"invalid source URL: {exc}") from exc


def parsed_date(value: object, field: str, warnings: list[str]) -> str:
    raw = text(value)
    if not raw:
        return ""
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return date.fromisoformat(raw).isoformat()
        return datetime.fromisoformat(raw).date().isoformat()
    except ValueError:
        warnings.append(f"INVALID_{field.upper()}")
        return ""


def organization(value: object) -> dict:
    values = value if isinstance(value, list) else [value]
    for item in values:
        if not isinstance(item, dict):
            continue
        types = item.get("@type", [])
        types = [types] if isinstance(types, str) else types
        if "Person" not in types and text(item.get("name")):
            return item
    return {}


def normalize_review(raw: dict, source: str, source_sha256: str, index: int) -> dict:
    claim_text = text(raw.get("claimReviewed"))
    if not claim_text:
        raise RecordError("missing claimReviewed text")
    source_url = text(raw.get("url"))
    url = canonical_url(source_url)
    rating = raw.get("reviewRating")
    if not isinstance(rating, dict):
        raise RecordError("missing reviewRating object")
    verdict = text(rating.get("alternateName")) or text(rating.get("ratingValue"))
    # Numeric ratings require their original scale; do not synthesize a textual verdict.
    if not verdict and isinstance(rating.get("ratingValue"), (int, float)):
        verdict = str(rating["ratingValue"])
    if not verdict:
        raise RecordError("missing publisher rating (alternateName or ratingValue)")
    publisher = organization(raw.get("publisher")) or organization(raw.get("author"))
    publisher_basis = "source_organization" if publisher else "source_url_domain"
    publisher_domain = urlsplit(url).hostname.removeprefix("www.")
    if text(publisher.get("url")):
        try:
            publisher_domain = urlsplit(canonical_url(publisher["url"])).hostname.removeprefix(
                "www."
            )
        except RecordError:
            pass
    publisher_name = text(publisher.get("name")) or publisher_domain
    normalized = normalize_text(claim_text)
    language = text(raw.get("inLanguage")) or "und"
    warnings: list[str] = []
    reviewed_item = raw.get("itemReviewed")
    reviewed_item = reviewed_item if isinstance(reviewed_item, dict) else {}
    review_date = parsed_date(raw.get("datePublished"), "review_date", warnings)
    claim_date = parsed_date(reviewed_item.get("datePublished"), "claim_date", warnings)
    if not review_date:
        warnings.append("MISSING_REVIEW_DATE")
    if publisher_basis == "source_url_domain":
        warnings.append("PUBLISHER_NAME_UNAVAILABLE")
    return {
        "schema_version": 1,
        "variant_id": stable_id("variant", unicodedata.normalize("NFC", claim_text), language),
        "claim_id": stable_id("claim", normalized, language),
        "factcheck_id": stable_id("factcheck", url, normalized, language),
        "publisher_id": stable_id("publisher", publisher_domain),
        "text": claim_text,
        "normalized_text": normalized,
        "language": language,
        "canonical_text": normalized,
        "claim_date": claim_date,
        "review_date": review_date,
        "url": url,
        "url_original": source_url,
        "verdict_original": verdict,
        "rating_original": rating,
        "title": text(raw.get("headline")) or text(raw.get("name")),
        "publisher_name": publisher_name,
        "publisher_domain": publisher_domain,
        "publisher_basis": publisher_basis,
        "source": source,
        "source_sha256": source_sha256,
        "source_record_index": index,
        "license_original": raw.get("sdLicense", raw.get("license", "")),
        "raw": raw,
        "warnings": warnings,
    }
