"""Async Neo4j client with graceful degradation when Neo4j is unavailable."""
from neo4j import AsyncGraphDatabase
from config import settings
from utils.logger import log


class Neo4jClient:
    def __init__(self):
        self._driver = None
        self._connected = False

    async def connect(self):
        try:
            self._driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            await self._driver.verify_connectivity()
            self._connected = True
            log.info("neo4j_connected", uri=settings.neo4j_uri)
        except Exception as exc:
            self._connected = False
            log.info("neo4j_unavailable", reason=str(exc)[:120])

    async def close(self):
        if self._driver:
            try:
                await self._driver.close()
            except Exception:
                pass

    async def ping(self) -> bool:
        if not self._driver:
            return False
        try:
            await self._driver.verify_connectivity()
            self._connected = True
            return True
        except Exception:
            self._connected = False
            return False

    async def execute(self, cypher: str, params: dict = None) -> list[dict]:
        """Execute a Cypher query and return list of result dicts.
        Raises an exception if Neo4j is not connected (caller should catch).
        """
        if not self._driver or not self._connected:
            raise RuntimeError("Neo4j not connected")
        async with self._driver.session() as session:
            result = await session.run(cypher, params or {})
            records = await result.data()
            return records

    # Legacy alias
    async def run_query(self, cypher: str, params: dict = None) -> list[dict]:
        return await self.execute(cypher, params)


neo4j_client = Neo4jClient()
