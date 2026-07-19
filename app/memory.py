"""
Persistent memory layer for MemoryAgent.

Design goals (per hackathon Track 1 requirements):
  - Efficient storage & retrieval of user preference / fact memories.
  - Timely forgetting of outdated information (recency + confidence decay,
    plus explicit overwrite when a newer fact contradicts an older one).
  - Recall of only the most *critical* memories within a limited context
    window (top-k relevance+recency scoring instead of dumping everything).

Storage: SQLite (file-based, zero external deps -> fast to deploy).
Retrieval: lightweight TF-IDF-ish keyword overlap + recency/confidence
score. Swappable for a real embedding store later without changing the
public interface (add_memory / recall / forget).
"""

import sqlite3
import time
import math
import re
import os
from dataclasses import dataclass
from typing import List, Optional

DB_PATH = os.environ.get("MEMORY_DB_PATH", "memory.db")

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "i", "you", "he", "she",
    "it", "we", "they", "to", "of", "in", "on", "for", "and", "or", "my",
    "me", "at", "with", "that", "this", "be", "have", "has", "do", "does",
}


def _tokenize(text: str) -> set:
    words = re.findall(r"[a-zA-Z0-9']+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


@dataclass
class Memory:
    id: int
    user_id: str
    content: str
    category: str
    confidence: float
    created_at: float
    last_accessed: float
    access_count: int


class MemoryStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                confidence REAL DEFAULT 1.0,
                created_at REAL NOT NULL,
                last_accessed REAL NOT NULL,
                access_count INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()
        conn.close()

    # ---------- write path ----------

    def add_memory(self, user_id: str, content: str, category: str = "general",
                    confidence: float = 1.0) -> int:
        """
        Store a new memory. If a highly similar memory already exists for
        this user (token overlap > 0.6), treat the new one as an UPDATE
        (overwrite) rather than a duplicate -- this is the "timely
        forgetting of outdated information" behavior: newer facts replace
        stale ones instead of piling up.
        """
        existing = self._all_for_user(user_id)
        new_tokens = _tokenize(content)
        for m in existing:
            old_tokens = _tokenize(m.content)
            if not old_tokens or not new_tokens:
                continue
            overlap = len(old_tokens & new_tokens) / len(old_tokens | new_tokens)
            if overlap > 0.6:
                self._update_memory(m.id, content, confidence)
                return m.id

        conn = self._conn()
        now = time.time()
        cur = conn.execute(
            "INSERT INTO memories (user_id, content, category, confidence, "
            "created_at, last_accessed, access_count) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (user_id, content, category, confidence, now, now),
        )
        conn.commit()
        mem_id = cur.lastrowid
        conn.close()
        return mem_id

    def _update_memory(self, mem_id: int, content: str, confidence: float):
        conn = self._conn()
        conn.execute(
            "UPDATE memories SET content = ?, confidence = ?, created_at = ?, "
            "last_accessed = ? WHERE id = ?",
            (content, confidence, time.time(), time.time(), mem_id),
        )
        conn.commit()
        conn.close()

    # ---------- read path ----------

    def _all_for_user(self, user_id: str) -> List[Memory]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM memories WHERE user_id = ?", (user_id,)
        ).fetchall()
        conn.close()
        return [Memory(**dict(r)) for r in rows]

    def recall(self, user_id: str, query: str, top_k: int = 5,
               half_life_days: float = 30.0) -> List[Memory]:
        """
        Return the top_k most CRITICAL memories for this query, scored by:
          relevance (token overlap with query) * confidence * recency_decay
        This keeps what fits in the agent's limited context window instead
        of dumping the full memory table into the prompt.
        """
        memories = self._all_for_user(user_id)
        if not memories:
            return []

        query_tokens = _tokenize(query)
        now = time.time()
        scored = []
        for m in memories:
            mem_tokens = _tokenize(m.content)
            overlap = len(query_tokens & mem_tokens)
            relevance = overlap / max(len(query_tokens), 1)
            # exponential recency decay
            age_days = (now - m.last_accessed) / 86400.0
            recency = math.exp(-age_days / half_life_days)
            # always give preference-type memories a baseline relevance so
            # core facts ("likes X") surface even on loosely related queries
            baseline = 0.15 if m.category == "preference" else 0.0
            score = (relevance + baseline) * m.confidence * (0.5 + 0.5 * recency)
            scored.append((score, m))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [m for score, m in scored[:top_k] if score > 0]

        # touch access stats for retrieved memories (reinforces useful ones)
        if top:
            conn = self._conn()
            for m in top:
                conn.execute(
                    "UPDATE memories SET last_accessed = ?, access_count = access_count + 1 "
                    "WHERE id = ?",
                    (now, m.id),
                )
            conn.commit()
            conn.close()
        return top

    def all_memories(self, user_id: str) -> List[Memory]:
        return sorted(self._all_for_user(user_id), key=lambda m: m.last_accessed, reverse=True)

    # ---------- forgetting path ----------

    def decay_and_forget(self, user_id: Optional[str] = None,
                          confidence_floor: float = 0.05,
                          half_life_days: float = 45.0) -> int:
        """
        Apply confidence decay based on age/disuse and hard-delete memories
        that fall below the confidence floor. Call periodically (e.g. once
        per session start) to keep the store from growing unbounded with
        stale info.
        """
        conn = self._conn()
        query = "SELECT * FROM memories"
        params = ()
        if user_id:
            query += " WHERE user_id = ?"
            params = (user_id,)
        rows = conn.execute(query, params).fetchall()

        now = time.time()
        deleted = 0
        for r in rows:
            age_days = (now - r["last_accessed"]) / 86400.0
            decay = math.exp(-age_days / half_life_days)
            new_conf = r["confidence"] * decay
            if new_conf < confidence_floor:
                conn.execute("DELETE FROM memories WHERE id = ?", (r["id"],))
                deleted += 1
            else:
                conn.execute(
                    "UPDATE memories SET confidence = ? WHERE id = ?",
                    (new_conf, r["id"]),
                )
        conn.commit()
        conn.close()
        return deleted

    def forget(self, mem_id: int):
        conn = self._conn()
        conn.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
        conn.commit()
        conn.close()
