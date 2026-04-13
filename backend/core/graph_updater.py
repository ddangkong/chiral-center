"""Update knowledge graph with simulation events."""
import json
from typing import Optional

from db.neo4j_client import neo4j_client
from models.simulation import SimEvent
from utils.logger import log


class GraphUpdater:
    """Updates Neo4j graph with events from simulation."""

    def __init__(self):
        self.client = neo4j_client

    async def process_event(self, event: SimEvent, ontology_id: str):
        """Process a simulation event and update the graph."""
        if event.action_type in ("skip", "injection"):
            return

        event_id = f"evt_{event.round_num}_{event.persona_id[:8]}"

        # Create an activity node for the post/reply
        await self.client.run_query(
            """
            CREATE (a:Activity {
                event_id: $event_id,
                persona_id: $persona_id,
                persona_name: $persona_name,
                action_type: $action_type,
                content: $content,
                round_num: $round_num,
                timestamp: $timestamp,
                ontology_id: $ontology_id
            })
            """,
            {
                "event_id": event_id,
                "persona_id": event.persona_id,
                "persona_name": event.persona_name,
                "action_type": event.action_type,
                "content": event.content,
                "round_num": event.round_num,
                "timestamp": event.timestamp,
                "ontology_id": ontology_id,
            },
        )

        # Link activity to persona's entity node if exists
        await self.client.run_query(
            """
            MATCH (p {name: $persona_name, ontology_id: $ontology_id})
            MATCH (a:Activity {event_id: $event_id})
            MERGE (p)-[:PERFORMED]->(a)
            """,
            {
                "persona_name": event.persona_name,
                "ontology_id": ontology_id,
                "event_id": event_id,
            },
        )

        # If it's a reply, link to the target post's activity
        if event.action_type == "reply" and event.target_id:
            await self.client.run_query(
                """
                MATCH (a:Activity {event_id: $event_id})
                MATCH (target:Activity)
                WHERE target.round_num <= $round_num AND target.ontology_id = $ontology_id
                WITH a, target ORDER BY target.round_num DESC LIMIT 1
                MERGE (a)-[:REPLIES_TO]->(target)
                """,
                {
                    "event_id": event_id,
                    "round_num": event.round_num,
                    "ontology_id": ontology_id,
                },
            )

    async def get_interaction_summary(self, ontology_id: str) -> dict:
        """Get summary of simulation interactions in the graph."""
        # Count activities per persona
        records = await self.client.run_query(
            """
            MATCH (a:Activity {ontology_id: $ontology_id})
            RETURN a.persona_name as name, a.action_type as action, count(*) as count
            ORDER BY count DESC
            """,
            {"ontology_id": ontology_id},
        )

        summary: dict[str, dict] = {}
        for r in records:
            name = r["name"]
            if name not in summary:
                summary[name] = {"total": 0, "posts": 0, "replies": 0, "reposts": 0}
            summary[name]["total"] += r["count"]
            action = r["action"]
            if action in summary[name]:
                summary[name][action] = r["count"]

        return summary


# Singleton
graph_updater = GraphUpdater()
