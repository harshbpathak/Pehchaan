"""Fixed, parameterized Cypher. No user input becomes a label or query fragment."""

LABELS = (
    "ClaimVariant",
    "Claim",
    "FactCheck",
    "Publisher",
    "Entity",
    "NarrativeFrame",
    "Topic",
    "Investigation",
)

UPSERT_REVIEW = """
MERGE (v:ClaimVariant {id: $variant_id})
SET v.text = $text, v.normalized_text = $normalized_text,
    v.language = $language, v.date = $claim_date
MERGE (c:Claim {id: $claim_id})
SET c.canonical_text = $canonical_text, c.language = $language,
    c.equivalence_basis = 'exact_normalized_text_only'
MERGE (fc:FactCheck {id: $factcheck_id})
SET fc.url = $url, fc.url_original = $url_original,
    fc.verdict_original = $verdict_original, fc.review_date = $review_date,
    fc.title = $title, fc.rating_original_json = $rating_original_json,
    fc.source_record_json = $source_record_json, fc.source = $source,
    fc.source_sha256 = $source_sha256, fc.source_record_index = $source_record_index,
    fc.license_original_json = $license_original_json
MERGE (pub:Publisher {id: $publisher_id})
SET pub.name = $publisher_name, pub.domain = $publisher_domain,
    pub.identity_basis = $publisher_basis
MERGE (v)-[:EXPRESSES {basis: 'exact_normalized_text_only'}]->(c)
MERGE (fc)-[:CHECKS]->(v)
MERGE (fc)-[:PUBLISHED_BY]->(pub)
RETURN fc.id
"""

EVIDENCE = """
MATCH (v:ClaimVariant {id: $variant_id})<-[:CHECKS]-(fc:FactCheck)
      -[:PUBLISHED_BY]->(pub:Publisher)
RETURN fc.id, fc.url, fc.verdict_original, fc.review_date,
       pub.name, fc.source, fc.source_sha256, fc.source_record_index,
       fc.rating_original_json, fc.source_record_json
ORDER BY fc.id
"""

NARRATIVE_PATHS = """
MATCH p = (v:ClaimVariant {id: $variant_id})-[:EXPRESSES]->(:Claim)
          -[:USES_FRAME]->(frame:NarrativeFrame)<-[:USES_FRAME]-(:Claim)
          <-[:EXPRESSES]-(related:ClaimVariant)
WHERE related.id <> v.id
MATCH (fc:FactCheck)-[:CHECKS]->(related)
MATCH (fc)-[:PUBLISHED_BY]->(pub:Publisher)
RETURN related.id, related.text, frame.name,
       [n IN nodes(p) | n.id], [e IN relationships(p) | type(e)],
       fc.url, fc.verdict_original, pub.name,
       [e IN relationships(p) | {type: type(e), basis: e.basis,
          reviewed_by: e.reviewed_by, rationale: e.rationale,
          source_variant_id: e.source_variant_id}], fc.id, pub.id
ORDER BY related.id, fc.id
LIMIT $limit
"""

SHORTEST_PATH = """
MATCH (a:ClaimVariant {id: $from_id}), (b:ClaimVariant {id: $to_id})
MATCH p = (a)-[:EXPRESSES|USES_FRAME|MENTIONS*1..8]-(b)
WITH p, length(p) AS hops ORDER BY hops LIMIT 1
RETURN [n IN nodes(p) | n.id], [e IN relationships(p) | type(e)]
"""

BFS = """
MATCH (v:ClaimVariant {id: $variant_id})
CALL algo.BFS(v, $depth, null) YIELD nodes, edges
RETURN [n IN nodes | n.id], [e IN edges | type(e)]
"""

VARIANTS = "MATCH (v:ClaimVariant) RETURN v.id, v.text, v.normalized_text ORDER BY v.id"
