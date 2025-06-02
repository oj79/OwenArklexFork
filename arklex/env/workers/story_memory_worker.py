import sqlite3
import os
import logging
from datetime import datetime
from typing import Any, Dict, List

from arklex.env.workers.worker import BaseWorker, register_worker
from arklex.utils.graph_state import MessageState, ResourceRecord

logger = logging.getLogger(__name__)


@register_worker
class StoryMemoryWorker(BaseWorker):
    """Worker that stores conversation stories in an SQLite database."""

    description: str = "Persist and retrieve key conversation stories"

    def __init__(self, db_path: str = "stories.sqlite") -> None:
        super().__init__()
        self.db_path = os.path.join(os.environ.get("DATA_DIR", ""), db_path)
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._ensure_table()

    def _ensure_table(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS stories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                summary TEXT,
                details TEXT
            )
            """
        )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    def add_story(self, msg_state: MessageState) -> None:
        """Persist a conversation turn."""
        user_msg = msg_state.user_message.message if msg_state.user_message else ""
        assistant_msg = msg_state.response
        summary = user_msg[:100]
        details = f"User: {user_msg}\nAssistant: {assistant_msg}"
        timestamp = datetime.utcnow().isoformat()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO stories(timestamp, summary, details) VALUES (?, ?, ?)",
            (timestamp, summary, details),
        )
        conn.commit()
        conn.close()

    def retrieve_stories(self, query: str, top_k: int = 5) -> List[ResourceRecord]:
        like = f"%{query}%"
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, timestamp, summary, details FROM stories
            WHERE summary LIKE ? OR details LIKE ?
            ORDER BY id DESC LIMIT ?
            """,
            (like, like, top_k),
        )
        rows = cursor.fetchall()
        conn.close()
        records: List[ResourceRecord] = []
        for story_id, ts, summary, details in rows:
            records.append(
                ResourceRecord(
                    info={"story_id": story_id, "timestamp": ts, "summary": summary},
                    output=details,
                    intent="story_memory",
                )
            )
        return records

    # ------------------------------------------------------------------
    def _execute(self, msg_state: MessageState, **kwargs: Any) -> Dict[str, Any]:
        action = kwargs.get("action", "add")
        if action == "retrieve":
            query = kwargs.get("query", "")
            top_k = kwargs.get("top_k", 5)
            records = self.retrieve_stories(query, top_k)
            msg_state.relevant_records = records
            return msg_state.model_dump()
        else:
            self.add_story(msg_state)
            return msg_state.model_dump()