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
import json
import logging
import hashlib
import secrets
from dataclasses import dataclass
from typing import List, Optional
from openai import OpenAI

logger = logging.getLogger("memoryagent.memory")

DB_PATH = os.environ.get("MEMORY_DB_PATH", "memory.db")
DEFAULT_OPENROUTER_KEY = ""
DEFAULT_QWEN_KEY = ""


def hash_password(password: str) -> str:
    """Hashes a plain-text password securely using PBKDF2-HMAC-SHA256 with a random salt."""
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100_000)
    return f"{salt.hex()}:{key.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verifies a plain-text password against a stored PBKDF2 hash."""
    if not stored_hash or ":" not in stored_hash:
        return False
    try:
        salt_hex, key_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100_000)
        return secrets.compare_digest(key, new_key)
    except Exception:
        return False

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "i", "you", "he", "she",
    "it", "we", "they", "to", "of", "in", "on", "for", "and", "or", "my",
    "me", "at", "with", "that", "this", "be", "have", "has", "do", "does",
}


def _tokenize(text: str) -> set:
    words = re.findall(r"[a-zA-Z0-9']+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def get_embedding(text: str) -> Optional[List[float]]:
    """
    Generates a vector embedding for the given text.
    Tries OpenRouter (text-embedding-3-small) first, falls back to Qwen Cloud (text-embedding-v3).
    Returns None if generation fails or API keys are unavailable.
    """
    if not text or not text.strip():
        return None

    # Try OpenRouter
    or_key = os.environ.get("OPENROUTER_API_KEY") or DEFAULT_OPENROUTER_KEY
    if or_key:
        try:
            client = OpenAI(api_key=or_key, base_url="https://openrouter.ai/api/v1")
            res = client.embeddings.create(model="text-embedding-3-small", input=text)
            if res and res.data and len(res.data) > 0:
                return res.data[0].embedding
        except Exception as e:
            logger.warning(f"OpenRouter embedding call failed: {e}")

    # Try Qwen
    qwen_key = os.environ.get("QWEN_API_KEY") or DEFAULT_QWEN_KEY
    if qwen_key:
        try:
            client = OpenAI(api_key=qwen_key, base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
            res = client.embeddings.create(model="text-embedding-v3", input=text)
            if res and res.data and len(res.data) > 0:
                return res.data[0].embedding
        except Exception as e:
            logger.warning(f"Qwen embedding call failed: {e}")

    logger.warning("Embedding generation failed; falling back to token overlap.")
    return None


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


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
    embedding: Optional[str] = None


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
                access_count INTEGER DEFAULT 0,
                embedding TEXT
            )
            """
        )
        try:
            conn.execute("ALTER TABLE memories ADD COLUMN embedding TEXT")
        except Exception:
            pass  # Column already exists

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                title TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                password_hash TEXT,
                created_at REAL NOT NULL,
                last_seen_at REAL NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )

        u_cols = [c[1] for c in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "password_hash" not in u_cols:
            conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS team_members (
                team_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                joined_at REAL NOT NULL,
                PRIMARY KEY (team_id, user_id),
                FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS team_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                invited_user_id TEXT NOT NULL,
                invited_by TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL,
                responded_at REAL,
                FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS team_conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                user_id TEXT NOT NULL DEFAULT '',
                title TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
            )
            """
        )
        tc_cols = [c[1] for c in conn.execute("PRAGMA table_info(team_conversations)").fetchall()]
        if "user_id" not in tc_cols:
            conn.execute("ALTER TABLE team_conversations ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS team_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_conversation_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                derived_constraints TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (team_conversation_id) REFERENCES team_conversations(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS team_shared_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (team_id) REFERENCES teams(id) ON DELETE CASCADE
            )
            """
        )
        conn.commit()
        conn.close()

    # ---------- user profile & team management ----------

    def create_session(self, user_id: str, expires_in_seconds: int = 7 * 86400) -> str:
        token = secrets.token_hex(32)
        now = time.time()
        expires_at = now + expires_in_seconds
        conn = self._conn()
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now, expires_at)
        )
        conn.commit()
        conn.close()
        return token

    def get_session(self, token: str) -> Optional[dict]:
        if not token or not token.strip():
            return None
        conn = self._conn()
        cur = conn.execute("SELECT token, user_id, created_at, expires_at FROM sessions WHERE token = ?", (token.strip(),))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        if row["expires_at"] < time.time():
            self.delete_session(token)
            return None
        return {"token": row["token"], "user_id": row["user_id"], "created_at": row["created_at"], "expires_at": row["expires_at"]}

    def delete_session(self, token: str):
        if not token:
            return
        conn = self._conn()
        conn.execute("DELETE FROM sessions WHERE token = ?", (token.strip(),))
        conn.commit()
        conn.close()

    def signup_user(self, user_id: str, password: str, display_name: Optional[str] = None) -> dict:
        clean_id = user_id.strip()
        if not clean_id:
            raise ValueError("Username cannot be empty")
        if not password or len(password) < 4:
            raise ValueError("Password must be at least 4 characters long")

        disp = (display_name or clean_id).strip()
        pwd_hash = hash_password(password)
        now = time.time()

        conn = self._conn()
        cur = conn.execute("SELECT id, password_hash, display_name FROM users WHERE id = ?", (clean_id,))
        existing = cur.fetchone()

        if existing:
            ex_hash = existing["password_hash"]
            if ex_hash and str(ex_hash).strip():
                conn.close()
                raise ValueError(f"User account '{clean_id}' already exists. Please log in.")
            # Pre-auth account password setup
            conn.execute(
                "UPDATE users SET password_hash = ?, display_name = ?, last_seen_at = ? WHERE id = ?",
                (pwd_hash, disp, now, clean_id)
            )
        else:
            conn.execute(
                "INSERT INTO users (id, display_name, password_hash, created_at, last_seen_at) VALUES (?, ?, ?, ?, ?)",
                (clean_id, disp, pwd_hash, now, now)
            )
        conn.commit()
        conn.close()

        token = self.create_session(clean_id)
        return {"token": token, "user_id": clean_id, "display_name": disp}

    def login_user(self, user_id: str, password: str) -> dict:
        clean_id = user_id.strip()
        if not clean_id or not password:
            raise ValueError("Username and password are required")

        conn = self._conn()
        cur = conn.execute("SELECT id, password_hash, display_name FROM users WHERE id = ?", (clean_id,))
        row = cur.fetchone()

        if not row:
            conn.close()
            raise ValueError("Invalid username or password.")

        pwd_hash = row["password_hash"]
        disp = row["display_name"]
        if not pwd_hash or not verify_password(password, pwd_hash):
            conn.close()
            raise ValueError("Invalid username or password.")

        conn.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (time.time(), clean_id))
        conn.commit()
        conn.close()

        token = self.create_session(clean_id)
        return {"token": token, "user_id": clean_id, "display_name": disp}

    def upsert_user(self, user_id: str, display_name: Optional[str] = None) -> dict:
        conn = self._conn()
        now = time.time()
        clean_id = user_id.strip()
        name = display_name.strip() if (display_name and display_name.strip()) else clean_id
        row = conn.execute("SELECT id, display_name, created_at FROM users WHERE id = ?", (clean_id,)).fetchone()
        if row:
            conn.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (now, clean_id))
            conn.commit()
            res = {"id": row["id"], "display_name": row["display_name"], "created_at": row["created_at"], "last_seen_at": now}
        else:
            conn.execute(
                "INSERT INTO users (id, display_name, created_at, last_seen_at) VALUES (?, ?, ?, ?)",
                (clean_id, name, now, now),
            )
            conn.commit()
            res = {"id": clean_id, "display_name": name, "created_at": now, "last_seen_at": now}
        conn.close()
        return res

    def get_user(self, user_id: str) -> Optional[dict]:
        conn = self._conn()
        row = conn.execute("SELECT id, display_name, created_at, last_seen_at FROM users WHERE id = ?", (user_id.strip(),)).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_team(self, name: str, created_by: str) -> dict:
        conn = self._conn()
        now = time.time()
        clean_creator = created_by.strip()
        self.upsert_user(clean_creator)
        cur = conn.execute(
            "INSERT INTO teams (name, created_by, created_at) VALUES (?, ?, ?)",
            (name.strip(), clean_creator, now),
        )
        team_id = cur.lastrowid
        conn.execute(
            "INSERT OR IGNORE INTO team_members (team_id, user_id, joined_at) VALUES (?, ?, ?)",
            (team_id, clean_creator, now),
        )
        conn.commit()
        conn.close()
        return {"id": team_id, "name": name.strip(), "created_by": clean_creator, "created_at": now}

    def invite_user_to_team(self, team_id: int, invited_user_id: str, invited_by: str) -> dict:
        conn = self._conn()
        now = time.time()
        target_user = invited_user_id.strip()
        inviter = invited_by.strip()

        # Validate team exists
        team_row = conn.execute("SELECT id, name FROM teams WHERE id = ?", (team_id,)).fetchone()
        if not team_row:
            conn.close()
            raise ValueError(f"Team ID {team_id} does not exist.")

        # Validate invited user exists
        user_row = conn.execute("SELECT id FROM users WHERE id = ?", (target_user,)).fetchone()
        if not user_row:
            conn.close()
            raise ValueError(f"User '{target_user}' does not exist.")

        # Validate invited user isn't already a member
        member_row = conn.execute(
            "SELECT team_id FROM team_members WHERE team_id = ? AND user_id = ?",
            (team_id, target_user),
        ).fetchone()
        if member_row:
            conn.close()
            raise ValueError(f"User '{target_user}' is already a member of this team.")

        # Check existing pending invite
        pending_row = conn.execute(
            "SELECT id FROM team_invites WHERE team_id = ? AND invited_user_id = ? AND status = 'pending'",
            (team_id, target_user),
        ).fetchone()
        if pending_row:
            conn.close()
            return {"id": pending_row["id"], "team_id": team_id, "invited_user_id": target_user, "invited_by": inviter, "status": "pending", "created_at": now}

        cur = conn.execute(
            "INSERT INTO team_invites (team_id, invited_user_id, invited_by, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (team_id, target_user, inviter, now),
        )
        conn.commit()
        invite_id = cur.lastrowid
        conn.close()
        return {"id": invite_id, "team_id": team_id, "invited_user_id": target_user, "invited_by": inviter, "status": "pending", "created_at": now}

    def get_user_invites(self, user_id: str) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT ti.id, ti.team_id, ti.invited_user_id, ti.invited_by, ti.status, ti.created_at,
                   t.name as team_name
            FROM team_invites ti
            JOIN teams t ON ti.team_id = t.id
            WHERE ti.invited_user_id = ? AND ti.status = 'pending'
            ORDER BY ti.created_at DESC
            """,
            (user_id.strip(),),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def respond_to_invite(self, invite_id: int, accept: bool) -> dict:
        conn = self._conn()
        now = time.time()
        invite = conn.execute("SELECT id, team_id, invited_user_id, status FROM team_invites WHERE id = ?", (invite_id,)).fetchone()
        if not invite:
            conn.close()
            raise ValueError("Invite not found.")

        new_status = "accepted" if accept else "declined"
        conn.execute(
            "UPDATE team_invites SET status = ?, responded_at = ? WHERE id = ?",
            (new_status, now, invite_id),
        )
        if accept:
            conn.execute(
                "INSERT OR IGNORE INTO team_members (team_id, user_id, joined_at) VALUES (?, ?, ?)",
                (invite["team_id"], invite["invited_user_id"], now),
            )
        conn.commit()
        conn.close()
        return {"id": invite_id, "team_id": invite["team_id"], "user_id": invite["invited_user_id"], "status": new_status}

    def get_user_teams(self, user_id: str) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT t.id, t.name, t.created_by, t.created_at, tm.joined_at
            FROM team_members tm
            JOIN teams t ON tm.team_id = t.id
            WHERE tm.user_id = ?
            ORDER BY tm.joined_at DESC
            """,
            (user_id.strip(),),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_team_members(self, team_id: int) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT u.id as user_id, u.display_name, tm.joined_at
            FROM team_members tm
            JOIN users u ON tm.user_id = u.id
            WHERE tm.team_id = ?
            ORDER BY tm.joined_at ASC
            """,
            (team_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ---------- team chat & shared facts management ----------

    def get_or_create_team_conversation(self, team_id: int, user_id: str) -> dict:
        conn = self._conn()
        now = time.time()
        uid = user_id.strip()
        row = conn.execute(
            "SELECT id, team_id, user_id, title, created_at, updated_at FROM team_conversations WHERE team_id = ? AND user_id = ? ORDER BY id ASC LIMIT 1",
            (team_id, uid),
        ).fetchone()
        if row:
            conn.close()
            return dict(row)

        cur = conn.execute(
            "INSERT INTO team_conversations (team_id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (team_id, uid, "Team Negotiator Chat", now, now),
        )
        conn.commit()
        conv_id = cur.lastrowid
        conn.close()
        return {"id": conv_id, "team_id": team_id, "user_id": uid, "title": "Team Negotiator Chat", "created_at": now, "updated_at": now}

    def save_team_message(
        self,
        team_conversation_id: int,
        user_id: str,
        role: str,
        content: str,
        derived_constraints: Optional[dict] = None,
    ) -> dict:
        conn = self._conn()
        now = time.time()
        dc_json = json.dumps(derived_constraints) if derived_constraints is not None else None
        cur = conn.execute(
            """
            INSERT INTO team_messages (team_conversation_id, user_id, role, content, derived_constraints, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (team_conversation_id, user_id, role, content, dc_json, now),
        )
        conn.execute(
            "UPDATE team_conversations SET updated_at = ? WHERE id = ?",
            (now, team_conversation_id),
        )
        conn.commit()
        msg_id = cur.lastrowid
        conn.close()
        return {
            "id": msg_id,
            "team_conversation_id": team_conversation_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "derived_constraints": derived_constraints,
            "created_at": now,
        }

    def get_team_conversation_messages(self, team_conversation_id: int) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT id, team_conversation_id, user_id, role, content, derived_constraints, created_at
            FROM team_messages
            WHERE team_conversation_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (team_conversation_id,),
        ).fetchall()
        conn.close()
        res = []
        for r in rows:
            d = dict(r)
            if d.get("derived_constraints"):
                try:
                    d["derived_constraints"] = json.loads(d["derived_constraints"])
                except Exception:
                    pass
            res.append(d)
        return res

    def add_team_shared_fact(self, team_id: int, user_id: str, content: str) -> dict:
        conn = self._conn()
        now = time.time()
        cur = conn.execute(
            "INSERT INTO team_shared_facts (team_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
            (team_id, user_id.strip(), content.strip(), now),
        )
        conn.commit()
        fact_id = cur.lastrowid
        conn.close()
        return {"id": fact_id, "team_id": team_id, "user_id": user_id.strip(), "content": content.strip(), "created_at": now}

    def get_user_team_shared_facts(self, team_id: int, user_id: str) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, team_id, user_id, content, created_at FROM team_shared_facts WHERE team_id = ? AND user_id = ? ORDER BY created_at ASC",
            (team_id, user_id.strip()),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_all_team_shared_facts(self, team_id: int) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, team_id, user_id, content, created_at FROM team_shared_facts WHERE team_id = ? ORDER BY created_at ASC",
            (team_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def delete_team_shared_fact(self, fact_id: int, user_id: str):
        conn = self._conn()
        conn.execute("DELETE FROM team_shared_facts WHERE id = ? AND user_id = ?", (fact_id, user_id.strip()))
        conn.commit()
        conn.close()

    def delete_team_member(self, team_id: int, user_id: str):
        conn = self._conn()
        conn.execute("DELETE FROM team_members WHERE team_id = ? AND user_id = ?", (team_id, user_id.strip()))
        conn.commit()
        conn.close()

    def delete_team(self, team_id: int, caller_id: str) -> dict:
        conn = self._conn()
        row = conn.execute("SELECT id, name, created_by FROM teams WHERE id = ?", (team_id,)).fetchone()
        if not row:
            conn.close()
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Team not found.")

        team_dict = dict(row)
        if team_dict["created_by"] != caller_id.strip():
            conn.close()
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Only team creator can delete this team.")

        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))
        conn.commit()
        conn.close()
        return {"status": "deleted", "team_id": team_id}

    def get_team_pending_invites(self, team_id: int) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, team_id, invited_user_id, invited_by, status, created_at FROM team_invites WHERE team_id = ? AND status = 'pending' ORDER BY created_at DESC",
            (team_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ---------- conversation management ----------

    def create_conversation(self, user_id: str, title: Optional[str] = None) -> dict:
        conn = self._conn()
        now = time.time()
        cur = conn.execute(
            "INSERT INTO conversations (user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, title, now, now),
        )
        conn.commit()
        conv_id = cur.lastrowid
        conn.close()
        return {
            "id": conv_id,
            "user_id": user_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
        }

    def list_conversations(self, user_id: str) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, user_id, title, created_at, updated_at FROM conversations "
            "WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_conversation_messages(self, conversation_id: int) -> List[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, conversation_id, role, content, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY created_at ASC, id ASC",
            (conversation_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def delete_conversation(self, conversation_id: int):
        conn = self._conn()
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        conn.commit()
        conn.close()

    def save_chat_message(self, conversation_id: int, role: str, content: str):
        conn = self._conn()
        now = time.time()
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, now),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        conn.commit()

        # Check if conversation needs an auto-generated title
        row = conn.execute(
            "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if row and (not row["title"] or not str(row["title"]).strip()):
            if role == "user":
                clean_title = content.strip().replace("\n", " ")
                if len(clean_title) > 40:
                    clean_title = clean_title[:40].strip() + "..."
                conn.execute(
                    "UPDATE conversations SET title = ? WHERE id = ?",
                    (clean_title, conversation_id),
                )
                conn.commit()
        conn.close()

    # ---------- write path ----------

    def add_memory(self, user_id: str, content: str, category: str = "general",
                    confidence: float = 1.0) -> int:
        """
        Store a new memory. If a highly similar memory already exists for
        this user (cosine similarity > 0.85 or token overlap > 0.6 fallback),
        treat the new one as an UPDATE (overwrite) rather than a duplicate.
        """
        existing = self._all_for_user(user_id)
        new_emb = get_embedding(content)
        new_tokens = _tokenize(content)

        for m in existing:
            # Check embedding similarity if available for both
            if new_emb and m.embedding:
                try:
                    old_emb = json.loads(m.embedding)
                    if isinstance(old_emb, list) and len(old_emb) > 0:
                        sim = cosine_similarity(new_emb, old_emb)
                        if sim > 0.85:
                            self._update_memory(m.id, content, confidence, new_emb)
                            return m.id
                except Exception:
                    pass

            # Fallback token overlap check
            old_tokens = _tokenize(m.content)
            if old_tokens and new_tokens:
                overlap = len(old_tokens & new_tokens) / len(old_tokens | new_tokens)
                if overlap > 0.6:
                    self._update_memory(m.id, content, confidence, new_emb)
                    return m.id

        conn = self._conn()
        now = time.time()
        emb_json = json.dumps(new_emb) if new_emb else None
        cur = conn.execute(
            "INSERT INTO memories (user_id, content, category, confidence, "
            "created_at, last_accessed, access_count, embedding) VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (user_id, content, category, confidence, now, now, emb_json),
        )
        conn.commit()
        mem_id = cur.lastrowid
        conn.close()
        return mem_id

    def _update_memory(self, mem_id: int, content: str, confidence: float, new_emb: Optional[List[float]] = None):
        conn = self._conn()
        emb_json = json.dumps(new_emb) if new_emb else None
        if emb_json:
            conn.execute(
                "UPDATE memories SET content = ?, confidence = ?, created_at = ?, "
                "last_accessed = ?, embedding = ? WHERE id = ?",
                (content, confidence, time.time(), time.time(), emb_json, mem_id),
            )
        else:
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
          relevance (embedding cosine similarity or token overlap fallback) * confidence * recency_decay
        This keeps what fits in the agent's limited context window instead
        of dumping the full memory table into the prompt.
        """
        memories = self._all_for_user(user_id)
        if not memories:
            return []

        query_emb = get_embedding(query)
        query_tokens = _tokenize(query)
        now = time.time()
        scored = []

        for m in memories:
            relevance = 0.0
            used_embedding = False

            if query_emb and m.embedding:
                try:
                    m_emb = json.loads(m.embedding)
                    if isinstance(m_emb, list) and len(m_emb) > 0:
                        relevance = cosine_similarity(query_emb, m_emb)
                        used_embedding = True
                except Exception:
                    used_embedding = False

            if not used_embedding:
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
