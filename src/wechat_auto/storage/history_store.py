"""SQLite archive for imported local-database history.

Nothing is written unless the caller explicitly creates a store and calls
``save_snapshot``.  The database contains only the messages supplied by the
caller; it does not read WeChat databases or private process memory.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


def make_message_id(chat: str, local_id: object, sort_seq: object = "",
                    server_id: object = "", message_type: object = "") -> str:
    """Build an ID that survives WeChat's per-shard local_id reuse."""
    return ":".join(str(value or "") for value in
                     (chat, local_id, sort_seq, server_id, message_type))


def make_message_fingerprint(chat: object, message_time: object, content: object,
                             sender: object = "", message_type: object = "",
                             sort_seq: object = "") -> str:
    """Return a source-independent identity for cross-export de-duplication.

    WeChat's local_id is only local to a shard and is therefore deliberately
    not used here.  The fingerprint is stable across the current DB export
    and a re-export of the same message.
    """
    # Sender names can be decoded differently by different WeChat exports;
    # omit it so a re-export of the same message remains mergeable.
    payload = "\x1f".join(str(value or "") for value in
                           (chat, message_time, content, message_type, sort_seq))
    return hashlib.sha256(payload.encode("utf-8", "surrogatepass")).hexdigest()


class HistoryStore:
    def __init__(self, path: str | Path, *, voice_model_path: str | Path | None = None,
                 voice_device: str = "auto"):
        self.voice_model_path = Path(voice_model_path).resolve() if voice_model_path else None
        self.voice_device = voice_device
        self.last_voice_processing = []
        if self.voice_model_path and not self.voice_model_path.is_dir():
            raise ValueError("local voice model directory does not exist")
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        try:
            self._initialize_schema()
        except BaseException:
            self._connection.close()
            raise

    def _initialize_schema(self) -> None:
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY, chat TEXT NOT NULL, sender TEXT,
                content TEXT NOT NULL, message_time TEXT, direction TEXT,
                source TEXT, raw_json TEXT NOT NULL, fingerprint TEXT
            )
        """)
        self._connection.execute("CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat)")
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(messages)")}
        if "fingerprint" not in columns:
            self._connection.execute("ALTER TABLE messages ADD COLUMN fingerprint TEXT")
        self._backfill_fingerprints()
        self._connection.execute("CREATE INDEX IF NOT EXISTS idx_messages_fingerprint ON messages(fingerprint)")
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS message_media (
                id TEXT PRIMARY KEY, message_id TEXT NOT NULL, chat TEXT NOT NULL,
                kind TEXT NOT NULL, mime_type TEXT NOT NULL DEFAULT '',
                original_ref TEXT NOT NULL DEFAULT '', local_name TEXT NOT NULL DEFAULT '',
                size INTEGER NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL,
                FOREIGN KEY(message_id) REFERENCES messages(id)
            )
        """)
        self._connection.execute("CREATE INDEX IF NOT EXISTS idx_message_media_message ON message_media(message_id)")
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

    def _backfill_fingerprints(self) -> None:
        rows = self._connection.execute(
            "SELECT id,chat,sender,content,message_time,raw_json FROM messages WHERE fingerprint IS NULL"
        ).fetchall()
        if not rows:
            return
        values = []
        for message_id, chat, sender, content, message_time, raw_json in rows:
            try:
                raw = json.loads(raw_json)
            except (TypeError, ValueError):
                raw = {}
            values.append((make_message_fingerprint(
                chat, message_time, content, sender, raw.get("type", ""), raw.get("sort_seq", "")
            ), message_id))
        self._connection.executemany("UPDATE messages SET fingerprint=? WHERE id=?", values)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def save_messages(self, messages: Iterable[dict]) -> int:
        self.last_voice_processing = []
        rows = []
        media_rows = []
        fingerprints = []
        for message in messages:
            if not message.get("id") or not message.get("chat"):
                raise ValueError("Each stored message requires id and chat")
            fingerprint = str(message.get("fingerprint") or make_message_fingerprint(
                message["chat"], message.get("time", ""), message.get("content", ""),
                message.get("sender", ""), message.get("raw", {}).get("type", ""),
                message.get("raw", {}).get("sort_seq", "")
            ))
            fingerprints.append(fingerprint)
            rows.append((message["id"], message["chat"], message.get("sender", ""),
                         message.get("content", ""), message.get("time", ""),
                         message.get("direction", "unknown"), message.get("source", "unknown"),
                         json.dumps(message.get("raw", {}), ensure_ascii=False, sort_keys=True), fingerprint))
            for index, media in enumerate(message.get("media", ())):
                payload = media.get("data", b"")
                if isinstance(payload, memoryview):
                    payload = payload.tobytes()
                if not isinstance(payload, bytes):
                    raise TypeError("media data must be bytes")
                digest = hashlib.sha256(payload).hexdigest()
                media_id = str(media.get("id") or f"{message['id']}:{index}:{digest}")
                media_rows.append((media_id, message["id"], message["chat"],
                                   str(media.get("kind", "file")), str(media.get("mime_type", "")),
                                   str(media.get("original_ref", "")), str(media.get("local_name", "")),
                                   len(payload), digest, sqlite3.Binary(payload)))
        if not rows:
            return 0
        supplied_ids = {}
        for row in rows:
            previous = supplied_ids.setdefault(row[0], (row[1], row[-1]))
            if previous != (row[1], row[-1]):
                raise ValueError('Message ID collision has conflicting conversation or fingerprint')
        with self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            for message_id, chat, fingerprint in self._connection.execute(
                "SELECT id,chat,fingerprint FROM messages WHERE id IN ({})".format(
                    ','.join('?' for _ in supplied_ids)), tuple(supplied_ids)
            ):
                if supplied_ids[message_id] != (chat, fingerprint):
                    raise ValueError('Message ID collision has conflicting conversation or fingerprint')
            existing_rows = list(self._connection.execute(
                "SELECT fingerprint FROM messages WHERE fingerprint IN ({})".format(",".join("?" for _ in set(fingerprints))), tuple(set(fingerprints))
            ))
            existing = {row[0] for row in existing_rows}
            existing_ids = {row[0]: row[1] for row in self._connection.execute(
                "SELECT fingerprint,id FROM messages WHERE fingerprint IN ({})".format(",".join("?" for _ in set(fingerprints))), tuple(set(fingerprints))
            )}
            filtered_rows = []
            seen = set(existing)
            message_id_map = {}
            canonical_ids = dict(existing_ids)
            for row in rows:
                message_id_map[row[0]] = canonical_ids.setdefault(row[-1], row[0])
                if row[-1] in seen:
                    continue
                seen.add(row[-1])
                filtered_rows.append(row)
            media_rows = [
                (media_id, message_id_map.get(message_id, message_id), chat, kind, mime_type,
                 original_ref, local_name, size, digest, data)
                for media_id, message_id, chat, kind, mime_type, original_ref, local_name,
                size, digest, data in media_rows
            ]
            if not filtered_rows and not media_rows and self.voice_model_path is None:
                return 0
            before = self._connection.total_changes
            self._connection.executemany("""
                INSERT INTO messages(id,chat,sender,content,message_time,direction,source,raw_json,fingerprint)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING
            """, filtered_rows)
            self._connection.executemany("""
                INSERT INTO message_media(id,message_id,chat,kind,mime_type,original_ref,local_name,size,sha256,data)
                VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING
            """, media_rows)
        added = self._connection.total_changes - before
        if self.voice_model_path:
            by_chat = {}
            for row in rows:
                if str(json.loads(row[7]).get("type")) in {"语音", "34"}:
                    by_chat.setdefault(row[1], set()).add(message_id_map.get(row[0], row[0]))
            if by_chat:
                from wechat_auto.storage.voice_transcription import VoiceTranscriptions
                processor = VoiceTranscriptions(self)
                for chat, ids in by_chat.items():
                    result = processor.transcribe_local(chat, self.voice_model_path,
                        device=self.voice_device, message_ids=ids, limit=max(len(ids), 1))
                    self.last_voice_processing.append({"chat": chat, **result})
        return added

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
        result = []
        for row in cursor:
            item = {"id": row[0], "chat": row[1], "sender": row[2], "content": row[3],
                    "time": row[4], "direction": row[5], "source": row[6],
                    "raw": json.loads(row[7])}
            item["media"] = self.fetch_media(row[0])
            result.append(item)
        return self.with_transcriptions(result)

    def get_message(self, message_id: str) -> dict | None:
        """Fetch one explicitly requested evidence message by stable ID."""
        row = self._connection.execute("""
            SELECT id,chat,sender,content,message_time,direction,source,raw_json
            FROM messages WHERE id=?
        """, (message_id,)).fetchone()
        if row is None:
            return None
        return self.with_transcriptions([{ "id": row[0], "chat": row[1], "sender": row[2], "content": row[3],
                "time": row[4], "direction": row[5], "source": row[6],
                "raw": json.loads(row[7]), "media": self.fetch_media(row[0])}])[0]

    @staticmethod
    def _month_bounds(period: str) -> tuple[int, int, str]:
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            raise ValueError("period must use YYYY-MM")
        china = timezone(timedelta(hours=8))
        start = datetime.strptime(period + "-01", "%Y-%m-%d").replace(tzinfo=china)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return int(start.timestamp()), int(end.timestamp()), period

    _MONTH_FILTER = ("chat=? AND ((length(trim(message_time)) IN (10,13) "
                     "AND trim(message_time) NOT GLOB '*[^0-9]*' "
                     "AND CAST(substr(trim(message_time),1,10) AS INTEGER)>=? "
                     "AND CAST(substr(trim(message_time),1,10) AS INTEGER)<?) "
                     "OR substr(trim(message_time),1,7)=?)")
    _TRANSCRIPT_FIELDS = ("version", "text", "engine", "status", "source_ref", "audio_sha256")

    @staticmethod
    def _has_transcriptions(connection: sqlite3.Connection) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='voice_transcriptions'"
        ).fetchone() is not None

    def month_message_snapshot(self, chat: str, period: str) -> str:
        """Fingerprint archived messages and the latest transcriptions exposed to analysis."""
        return self._month_message_snapshot(self._connection, chat, period)

    @classmethod
    def read_month_message_snapshot(cls, path: str | Path, chat: str, period: str) -> str:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("BEGIN")
            return cls._month_message_snapshot(connection, chat, period)

    @classmethod
    def _month_message_snapshot(cls, connection: sqlite3.Connection, chat: str, period: str) -> str:
        bounds = cls._month_bounds(period)
        digest = hashlib.sha256(json.dumps([chat, period]).encode("utf-8"))
        for row in connection.execute(
            "SELECT id,sender,content,message_time,direction,source,raw_json "
            f"FROM messages WHERE {cls._MONTH_FILTER} ORDER BY rowid", (chat, *bounds)
        ):
            digest.update(json.dumps(row).encode("utf-8") + b"\n")
        if cls._has_transcriptions(connection):
            fields = ",".join(f"t.{field}" for field in cls._TRANSCRIPT_FIELDS)
            for row in connection.execute(
                f"SELECT m.id,{fields} FROM messages m "
                "JOIN voice_transcriptions t ON t.rowid=("
                "SELECT rowid FROM voice_transcriptions WHERE message_id=m.id ORDER BY version DESC LIMIT 1) "
                f"WHERE {cls._MONTH_FILTER} ORDER BY m.rowid", (chat, *bounds)
            ):
                digest.update(json.dumps(["transcription", *row]).encode("utf-8") + b"\n")
        return digest.hexdigest()

    @contextmanager
    def protect_archive_snapshot(self) -> Iterator[None]:
        """Keep archive writers out while verified analysis is published."""
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        finally:
            self._connection.rollback()

    @contextmanager
    def protect_month_snapshot(self, chat: str, period: str) -> Iterator[str]:
        with self.protect_archive_snapshot():
            yield self.month_message_snapshot(chat, period)

    def fetch_month(self, chat: str, period: str, *, after_id: str = "",
                    limit: int = 5000) -> list[dict]:
        """Read one calendar month for incremental analysis without media BLOBs."""
        if limit <= 0 or limit > 100_000:
            raise ValueError("limit must be from 1 through 100000")
        start_epoch, end_epoch, period = self._month_bounds(period)
        clauses = [self._MONTH_FILTER]
        params: list[object] = [chat, start_epoch, end_epoch, period]
        if after_id:
            clauses.append("rowid>(SELECT rowid FROM messages WHERE id=?)")
            params.append(after_id)
        params.append(limit)
        rows = self._connection.execute("""
            SELECT id,chat,sender,content,message_time,direction,source,raw_json
            FROM messages WHERE {} ORDER BY rowid LIMIT ?
        """.format(" AND ".join(clauses)), params).fetchall()
        return self.with_transcriptions([{"id": row[0], "chat": row[1], "sender": row[2], "content": row[3],
                 "time": row[4], "direction": row[5], "source": row[6],
                 "raw": json.loads(row[7])} for row in rows])

    def fetch_media(self, message_id: str) -> list[dict]:
        rows = self._connection.execute("""
            SELECT id,message_id,chat,kind,mime_type,original_ref,local_name,size,sha256,data
            FROM message_media WHERE message_id=? ORDER BY rowid
        """, (message_id,))
        return [{"id": r[0], "message_id": r[1], "chat": r[2], "kind": r[3],
                 "mime_type": r[4], "original_ref": r[5], "local_name": r[6],
                 "size": r[7], "sha256": r[8], "data": bytes(r[9])} for r in rows]

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
        return self.with_transcriptions([{"id": row[1], "chat": row[2], "sender": row[3], "content": row[4],
                 "time": row[5], "direction": row[6], "source": row[7],
                 "raw": json.loads(row[8])} for row in selected])

    def with_transcriptions(self, items: list[dict]) -> list[dict]:
        """Attach derived text without overwriting original XML or loading audio."""
        if self._has_transcriptions(self._connection):
            fields = ",".join(self._TRANSCRIPT_FIELDS)
            for item in items:
                row = self._connection.execute(
                    f"SELECT {fields} FROM voice_transcriptions WHERE message_id=? ORDER BY version DESC LIMIT 1",
                    (item["id"],),
                ).fetchone()
                if row:
                    item["transcription"] = dict(zip(self._TRANSCRIPT_FIELDS, row))
        return items

    def get_cursor(self, source: str, chat: str) -> int:
        row = self._connection.execute(
            "SELECT sort_seq FROM sync_cursors WHERE source=? AND chat=?", (source, chat)
        ).fetchone()
        return int(row[0]) if row else 0

    def set_cursor(self, source: str, chat: str, sort_seq: int) -> None:
        if int(sort_seq) < 0:
            raise ValueError('sort_seq must not be negative')
        self._connection.execute("""
            INSERT INTO sync_cursors(source,chat,sort_seq) VALUES(?,?,?)
            ON CONFLICT(source,chat) DO UPDATE SET sort_seq=MAX(sync_cursors.sort_seq,excluded.sort_seq),
                updated_at=CURRENT_TIMESTAMP
        """, (source, chat, int(sort_seq)))
        self._connection.commit()
