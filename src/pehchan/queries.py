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
    "Submission",
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

# Widening: fact-checked claims sharing frames/entities with a submission. Rarer shared nodes
# weigh more (1/degree), so "5G" alone ranks below "Bill Gates" plus a specific frame.
SHARED_CONTEXT = """
MATCH (n)
WHERE (n:Entity AND n.name IN $entities) OR (n:NarrativeFrame AND n.name IN $frames)
MATCH (n)<-[:MENTIONS|USES_FRAME]-(:Claim)
WITH n, count(*) AS degree
MATCH (n)<-[r:MENTIONS|USES_FRAME]-(c:Claim)<-[:EXPRESSES]-(v:ClaimVariant)
WHERE NOT v.id IN $exclude
WITH v, c, collect({label: labels(n)[0], name: n.name, relation: type(r), basis: r.basis,
                    reviewed_by: r.reviewed_by, evidence_span: r.evidence_span,
                    degree: degree}) AS shared,
     sum(1.0 / degree) AS score
MATCH (fc:FactCheck)-[:CHECKS]->(v)
MATCH (fc)-[:PUBLISHED_BY]->(pub:Publisher)
RETURN v.id, v.text, c.id, shared, score, fc.id, fc.url, fc.verdict_original, fc.review_date,
       pub.name
ORDER BY score DESC, v.id, fc.id
LIMIT $limit
"""

SUBMISSION_SEARCH = """
CALL db.idx.vector.queryNodes('Submission', 'embedding', $limit, vecf32($vector))
YIELD node, score
OPTIONAL MATCH (i:Investigation)-[:SUBMITTED]->(node)
OPTIONAL MATCH (node)-[m:MATCHES]->(v:ClaimVariant)
RETURN node.id, node.text, score, i.id, i.status, i.finding,
       collect(DISTINCT {variant_id: v.id, text: v.text, relation: m.relation,
                         similarity: m.similarity, assessment_json: m.assessment_json})
ORDER BY score ASC, node.id
"""

# Write-back: the submitted wording joins the graph, linked to what the agent established.
LINK_SUBMISSION = """
MATCH (i:Investigation {id: $investigation_id})
MERGE (s:Submission {id: $id})
SET s.text = $text, s.normalized_text = $normalized_text, s.embedding = vecf32($vector),
    s.embedding_model = $model, s.embedding_revision = $revision,
    s.first_seen = coalesce(s.first_seen, $created_at), s.last_seen = $created_at,
    s.times_seen = coalesce(s.times_seen, 0) + 1
MERGE (i)-[:SUBMITTED]->(s)
WITH s
UNWIND $matches AS match
MATCH (v:ClaimVariant {id: match.variant_id})
MERGE (s)-[m:MATCHES]->(v)
SET m.relation = match.relation, m.similarity = match.similarity,
    m.assessment_json = match.assessment_json, m.basis = 'model_assessment',
    m.investigation_id = $investigation_id
RETURN count(m)
"""

LINK_SUBMISSION_CONTEXT = """
MATCH (s:Submission {id: $id})
UNWIND $items AS item
MATCH (n {id: item.node_id})
WHERE n:Entity OR n:NarrativeFrame
FOREACH (_ IN CASE WHEN n:Entity THEN [1] ELSE [] END |
  MERGE (s)-[r:MENTIONS]->(n)
  SET r.basis = 'rule_inference', r.evidence_span = item.evidence_span)
FOREACH (_ IN CASE WHEN n:NarrativeFrame THEN [1] ELSE [] END |
  MERGE (s)-[r:USES_FRAME]->(n) SET r.basis = 'rule_inference')
RETURN count(n)
"""
