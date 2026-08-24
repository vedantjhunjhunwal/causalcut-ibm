"""Agent episodic memory for CAUSALCUT."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.core.logging import get_logger
from app.db.session import Database

log = get_logger(__name__)


class Episode(BaseModel):
    id: str
    agent_name: str
    timestamp: datetime
    observation: dict
    thought: str
    action: str
    outcome: dict | None = None
    reward: float | None = None


class AgentMemory:
    def __init__(self, agent_name: str, db: Database, max_episodes: int = 1000) -> None:
        self.agent_name = agent_name
        self.db = db
        self.max_episodes = max_episodes
        # Note: In a production system, ensure the `agent_episodes` table is created in SQLite.

    async def _ensure_table(self) -> None:
        # For simplicity, we ensure table exists here, though ideally it goes in schema.sql
        sql = """
        CREATE TABLE IF NOT EXISTS agent_episodes (
            id TEXT PRIMARY KEY,
            agent_name TEXT,
            timestamp TEXT,
            observation TEXT,
            thought TEXT,
            action TEXT,
            outcome TEXT,
            reward REAL
        )
        """
        try:
            await self.db.execute(sql)
        except Exception as e:
            log.error(f"Failed to create agent_episodes table: {e}")

    async def store_episode(self, episode: Episode) -> None:
        await self._ensure_table()
        sql = """
        INSERT INTO agent_episodes (id, agent_name, timestamp, observation, thought, action, outcome, reward)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            await self.db.execute(
                sql,
                (
                    episode.id,
                    episode.agent_name,
                    episode.timestamp.isoformat(),
                    json.dumps(episode.observation),
                    episode.thought,
                    episode.action,
                    json.dumps(episode.outcome) if episode.outcome else None,
                    episode.reward,
                )
            )
        except Exception as e:
            log.error(f"Failed to store episode: {e}")

    async def recall_recent(self, n: int = 5) -> list[Episode]:
        await self._ensure_table()
        sql = """
        SELECT * FROM agent_episodes
        WHERE agent_name = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """
        rows = await self.db.fetch_all(sql, (self.agent_name, n))
        episodes = []
        for row in rows:
            try:
                episodes.append(
                    Episode(
                        id=row["id"],
                        agent_name=row["agent_name"],
                        timestamp=datetime.fromisoformat(row["timestamp"]).replace(tzinfo=timezone.utc),
                        observation=json.loads(row["observation"]),
                        thought=row["thought"],
                        action=row["action"],
                        outcome=json.loads(row["outcome"]) if row["outcome"] else None,
                        reward=row["reward"],
                    )
                )
            except Exception as e:
                row_id = row.get("id", "unknown") if isinstance(row, dict) else "unknown"
                log.error(f"Failed to parse episode row {row_id}: {e}")
        return episodes

    async def recall_by_query(self, query: str, n: int = 3) -> list[Episode]:
        await self._ensure_table()
        # Basic LIKE search for sqlite.
        sql = """
        SELECT * FROM agent_episodes
        WHERE agent_name = ? AND (thought LIKE ? OR action LIKE ?)
        ORDER BY timestamp DESC
        LIMIT ?
        """
        like_query = f"%{query}%"
        rows = await self.db.fetch_all(sql, (self.agent_name, like_query, like_query, n))
        
        episodes = []
        for row in rows:
            try:
                episodes.append(
                    Episode(
                        id=row["id"],
                        agent_name=row["agent_name"],
                        timestamp=datetime.fromisoformat(row["timestamp"]).replace(tzinfo=timezone.utc),
                        observation=json.loads(row["observation"]),
                        thought=row["thought"],
                        action=row["action"],
                        outcome=json.loads(row["outcome"]) if row["outcome"] else None,
                        reward=row["reward"],
                    )
                )
            except Exception:
                pass
        return episodes

    async def get_context_summary(self) -> str:
        recent = await self.recall_recent(n=5)
        if not recent:
            return "No recent memory."
        
        summary = "Recent events:\n"
        for ep in recent:
            summary += f"- [{ep.timestamp.isoformat()}] Action: {ep.action} | Thought: {ep.thought}\n"
        return summary
