"""SQLite archive for imported local-database history.

Nothing is written unless the caller explicitly creates a store and calls
``save_snapshot``.  The database contains only the messages supplied by the
caller; it does not read WeChat databases or private process memory.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable


class HistoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY, chat TEXT NOT NULL, sender TEXT,
                content TEXT NOT NULL, message_time TEXT, direction TEXT,
                source TEXT, raw_json TEXT NOT NULL
            )
        """)
        self._connection.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat)")
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS history_exports (
                id INTEGER PRIMARY KEY, chat TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                pages_scanned INTEGER NOT NULL, complete INTEGER NOT NULL,
                stopped_reason TEXT NOT NULL, source TEXT NOT NULL, rows_added INTEGER NOT NULL
            )
        """)
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS sync_cursors (
                source TEXT NOT NULL, chat TEXT NOT NULL, sort_seq INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(source, chat)
            )
        """)
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def save_messages(self, messages: Iterable[dict]) -> int:
        rows = []
        for message in messages:
            if not message.get("id") or not message.get("chat"):
                raise ValueError("Each stored message requires id and chat")
            rows.append((message["id"], message["chat"], message.get("sender", ""),
                         message.get("content", ""), message.get("time", ""),
                         message.get("direction", "unknown"), message.get("source", "unknown"),
                         json.dumps(message.get("raw", {}), ensure_ascii=False, sort_keys=True)))
        before = self._connection.total_changes
        self._connection.executemany("""
            INSERT INTO messages(id,chat,sender,content,message_time,direction,source,raw_json)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING
        """, rows)
        self._connection.commit()
        return self._connection.total_changes - before

    def save_snapshot(self, snapshot: dict) -> int:
        return self.save_messages(snapshot.get("messages", []))

    def record_export(self, chat: str, snapshot: dict, rows_added: int) -> int:
        """Persist export evidence, including whether the history was complete."""
        cursor = self._connection.execute("""
            INSERT INTO history_exports(chat,pages_scanned,complete,stopped_reason,source,rows_added)
            VALUES(?,?,?,?,?,?)
        """, (chat, int(snapshot.get("pages_scanned", 0)), int(bool(snapshot.get("complete"))),
              str(snapshot.get("stopped_reason", "unknown")), str(snapshot.get("source", "unknown")),
              int(rows_added)))
        self._connection.commit()
        return int(cursor.lastrowid)

    def fetch_messages(self, chat: str, limit: int = 100) -> list[dict]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        cursor = self._connection.execute("""
            SELECT id,chat,sender,content,message_time,direction,source,raw_json
            FROM messages WHERE chat=? ORDER BY rowid DESC LIMIT ?
        """, (chat, limit))
        return [{"id": row[0], "chat": row[1], "sender": row[2], "content": row[3],
                 "time": row[4], "direction": row[5], "source": row[6],
                 "raw": json.loads(row[7])} for row in cursor]

    def fetch_context(self, chat: str, message_id: str, before: int = 5, after: int = 5) -> list[dict]:
        """Return stored chronological neighbours for group/conversation analysis."""
        if before < 0 or after < 0:
            raise ValueError("before and after must be non-negative")
        rows = list(self._connection.execute("""
            SELECT rowid,id,chat,sender,content,message_time,direction,source,raw_json
            FROM messages WHERE chat=? ORDER BY rowid ASC
        """, (chat,)))
        index = next((i for i, row in enumerate(rows) if row[1] == message_id), None)
        if index is None:
            return []
        selected = rows[max(0, index - before):index + after + 1]
        return [{"id": row[1], "chat": row[2], "sender": row[3], "content": row[4],
                 "time": row[5], "direction": row[6], "source": row[7],
                 "raw": json.loads(row[8])} for row in selected]

    def get_cursor(self, source: str, chat: str) -> int:
        row = self._connection.execute(
            "SELECT sort_seq FROM sync_cursors WHERE source=? AND chat=?", (source, chat)
        ).fetchone()
        return int(row[0]) if row else 0

    def set_cursor(self, source: str, chat: str, sort_seq: int) -> None:
        self._connection.execute("""
            INSERT INTO sync_cursors(source,chat,sort_seq) VALUES(?,?,?)
            ON CONFLICT(source,chat) DO UPDATE SET sort_seq=excluded.sort_seq,
                updated_at=CURRENT_TIMESTAMP
        """, (source, chat, int(sort_seq)))
        self._connection.commit()
