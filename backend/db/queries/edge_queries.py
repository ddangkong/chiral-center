"""Cypher queries for Neo4j edge/relationship operations."""

CREATE_RELATION = """
MATCH (a {entity_id: $source_id}), (b {entity_id: $target_id})
MERGE (a)-[r:{rel_type}]->(b)
SET r.relation_id = $relation_id,
    r.weight = $weight,
    r.description = $description,
    r.ontology_id = $ontology_id
RETURN r
"""

GET_ALL_EDGES = """
MATCH (a)-[r]->(b)
WHERE r.ontology_id = $ontology_id
RETURN r.relation_id as id, a.entity_id as source_id, b.entity_id as target_id,
       type(r) as relation_type, r.weight as weight, r.description as description,
       a.name as source_name, b.name as target_name
"""

GET_EDGES_FOR_NODE = """
MATCH (n {entity_id: $entity_id})-[r]-(m)
RETURN r.relation_id as id,
       CASE WHEN startNode(r) = n THEN n.entity_id ELSE m.entity_id END as source_id,
       CASE WHEN endNode(r) = n THEN n.entity_id ELSE m.entity_id END as target_id,
       type(r) as relation_type, r.weight as weight, r.description as description,
       m.name as connected_name, m.type as connected_type
"""

DELETE_ONTOLOGY_EDGES = """
MATCH ()-[r]->()
WHERE r.ontology_id = $ontology_id
DELETE r
"""
