import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from threading import Lock

from app.config import settings
from app.models.schemas import FragmentData, TurnData


class SessionStore:
    """Multi-turn Session Store with In-Memory Cache and SQLite Persistence."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.db_path
        self._lock = Lock()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        workspace_paths TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS fragments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT,
                        fragment_id TEXT,
                        type TEXT,
                        content TEXT,
                        tool_name TEXT,
                        args_json TEXT,
                        step_idx INTEGER,
                        output_preview TEXT,
                        timestamp TEXT,
                        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS turns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT,
                        turn_id TEXT,
                        user_prompt TEXT,
                        current_action TEXT,
                        final_response TEXT,
                        fragments_json TEXT,
                        timestamp TEXT,
                        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                    )
                """)
                conn.commit()

    def create_session(self, session_id: Optional[str] = None, workspace_paths: Optional[List[str]] = None) -> str:
        session_id = session_id or f"session-{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow().isoformat()
        paths_str = json.dumps(workspace_paths or [])

        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO sessions (session_id, workspace_paths, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (session_id, paths_str, now, now)
                )
                conn.commit()

            self._cache[session_id] = {
                "workspace_paths": workspace_paths or [],
                "created_at": now,
                "updated_at": now,
                "fragments": [],
                "turns": []
            }

        return session_id

    def add_fragment(self, session_id: str, fragment: FragmentData) -> str:
        if not fragment.fragment_id:
            fragment.fragment_id = f"frag-{uuid.uuid4().hex[:8]}"

        now = fragment.timestamp or datetime.utcnow().isoformat()
        args_json = json.dumps(fragment.args) if fragment.args else None

        with self._lock:
            if session_id not in self._cache:
                self.create_session(session_id)

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO fragments 
                       (session_id, fragment_id, type, content, tool_name, args_json, step_idx, output_preview, timestamp)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        fragment.fragment_id,
                        fragment.type,
                        fragment.content,
                        fragment.tool_name,
                        args_json,
                        fragment.step_idx,
                        fragment.output_preview,
                        now
                    )
                )
                cursor.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))
                conn.commit()

            if session_id in self._cache:
                self._cache[session_id]["fragments"].append(fragment)

        return fragment.fragment_id

    def add_turn_batch(self, session_id: str, turns: List[TurnData]) -> int:
        now = datetime.utcnow().isoformat()

        with self._lock:
            if session_id not in self._cache:
                self.create_session(session_id)

            processed_count = 0
            with self._get_connection() as conn:
                cursor = conn.cursor()
                for turn in turns:
                    if not turn.turn_id:
                        turn.turn_id = f"turn-{uuid.uuid4().hex[:8]}"

                    turn_ts = turn.timestamp or datetime.utcnow().isoformat()
                    fragments_json = json.dumps([f.to_dict() for f in turn.fragments])

                    cursor.execute(
                        """INSERT INTO turns
                           (session_id, turn_id, user_prompt, current_action, final_response, fragments_json, timestamp)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            session_id,
                            turn.turn_id,
                            turn.user_prompt,
                            turn.current_action,
                            turn.final_response,
                            fragments_json,
                            turn_ts
                        )
                    )
                    processed_count += 1

                cursor.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))
                conn.commit()

            if session_id in self._cache:
                self._cache[session_id]["turns"].extend(turns)

        return processed_count

    def get_fragments(self, session_id: str) -> List[FragmentData]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT fragment_id, type, content, tool_name, args_json, step_idx, output_preview, timestamp FROM fragments WHERE session_id = ? ORDER BY id ASC",
                    (session_id,)
                )
                rows = cursor.fetchall()
                fragments = []
                for row in rows:
                    args = json.loads(row["args_json"]) if row["args_json"] else None
                    fragments.append(
                        FragmentData(
                            fragment_id=row["fragment_id"],
                            type=row["type"],
                            content=row["content"],
                            tool_name=row["tool_name"],
                            args=args,
                            step_idx=row["step_idx"],
                            output_preview=row["output_preview"],
                            timestamp=row["timestamp"]
                        )
                    )
                return fragments

    def get_turns(self, session_id: str) -> List[TurnData]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT turn_id, user_prompt, current_action, final_response, fragments_json, timestamp FROM turns WHERE session_id = ? ORDER BY id ASC",
                    (session_id,)
                )
                rows = cursor.fetchall()
                turns = []
                for row in rows:
                    raw_frags = json.loads(row["fragments_json"]) if row["fragments_json"] else []
                    fragments = [FragmentData.from_dict(f) for f in raw_frags]
                    turns.append(
                        TurnData(
                            turn_id=row["turn_id"],
                            user_prompt=row["user_prompt"],
                            fragments=fragments,
                            current_action=row["current_action"],
                            final_response=row["final_response"],
                            timestamp=row["timestamp"]
                        )
                    )
                return turns

    def clear_all(self):
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM fragments")
                cursor.execute("DELETE FROM turns")
                cursor.execute("DELETE FROM sessions")
                conn.commit()
            self._cache.clear()


_global_session_store: Optional[SessionStore] = None


def get_session_store(db_path: Optional[str] = None) -> SessionStore:
    global _global_session_store
    if _global_session_store is None:
        _global_session_store = SessionStore(db_path=db_path)
    return _global_session_store
