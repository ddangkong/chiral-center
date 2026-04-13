"""Cypher queries for Neo4j node operations."""

CREATE_ENTITY_NODE = """
MERGE (n:{label} {{entity_id: $entity_id}})
SET n.name = $name,
    n.type = $type,
    n.description = $description,
    n.attributes = $attributes,
    n.ontology_id = $ontology_id
RETURN n
"""

GET_ALL_NODES = """
MATCH (n)
WHERE n.ontology_id = $ontology_id
RETURN n.entity_id as id, n.name as name, n.type as type,
       n.description as description, n.attributes as attributes,
       labels(n) as labels
"""

GET_NODE_BY_ID = """
MATCH (n {entity_id: $entity_id})
RETURN n
"""

DELETE_ONTOLOGY_NODES = """
MATCH (n {ontology_id: $ontology_id})
DETACH DELETE n
"""

SEARCH_NODES = """
MATCH (n)
WHERE n.ontology_id = $ontology_id AND (
    toLower(n.name) CONTAINS toLower($query) OR
    toLower(n.description) CONTAINS toLower($query)
)
RETURN n.entity_id as id, n.name as name, n.type as type,
       n.description as description
LIMIT $limit
"""
