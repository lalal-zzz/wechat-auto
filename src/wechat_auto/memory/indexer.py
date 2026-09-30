"""Build lightweight entity and analysis indexes over existing archives."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wechat_auto.memory.analysis import AnalysisService
from wechat_auto.memory.store import MemoryStore


def _readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


_CHINA_TZ = timezone(timedelta(hours=8))


def message_period(value: object) -> str:
    """Normalize Unix seconds/milliseconds or ISO-like text to YYYY-MM."""
    text = str(value or "").strip()
    if re.fullmatch(r"\d{10}|\d{13}", text):
        stamp = int(text) / (1000 if len(text) == 13 else 1)
        return datetime.fromtimestamp(stamp, _CHINA_TZ).strftime("%Y-%m")
    if re.match(r"^\d{4}-\d{2}", text):
        return text[:7]
    return ""


class ArchiveIndexer:
    """Index archive IDs and dates without copying message or media content."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def index_profiles(self, profile_path: str | Path) -> dict:
        path = Path(profile_path).expanduser().resolve()
        if not path.is_file():
            return {"profiles_seen": 0, "people_created_or_seen": 0}
        seen = 0
        current_people: set[str] = set()
        with _readonly(path) as source:
            rows = source.execute("""
                SELECT profile_type,wechat_id,nickname,remark,original_name,display_name,updated_at
                FROM profiles ORDER BY wechat_id
            """)
            for row in rows:
                person_id = self.store.ensure_person(
                    str(row["wechat_id"]), person_type=str(row["profile_type"]),
                    display_name=str(row["display_name"] or row["remark"] or row["nickname"] or ""),
                    source="profile_archive", seen_at=str(row["updated_at"] or "") or None,
                )
                for alias_type in ("nickname", "remark", "original_name"):
                    value = str(row[alias_type] or "")
                    self.store.add_alias(person_id, alias_type, value, source="profile_archive")
                seen += 1
                current_people.add(person_id)
        baseline = {str(row[0]) for row in self.store._connection.execute(
            "SELECT person_id FROM people WHERE person_type IN ('contact','self')"
        )}
        snapshot = self.store.reconcile_snapshot(
            "person", current_people, source="profile_archive", complete=True,
            baseline_ids=baseline,
        )
        return {"profiles_seen": seen, "people_created_or_seen": seen,
                "presence_snapshot": {"seen": snapshot["seen"], "missing": snapshot["missing"]}}

    def index_history(self, history_path: str | Path, *, batch_size: int = 10_000) -> dict:
        path = Path(history_path).expanduser().resolve()
        if not path.is_file():
            return {"messages_seen": 0, "months_dirtied": 0, "conversations_seen": 0}
        cursor_row = self.store._connection.execute(
            "SELECT cursor FROM sync_cursors WHERE source='history_index' AND stream_id=?",
            (str(path),),
        ).fetchone()
        cursor = int(cursor_row[0]) if cursor_row else 0
        is_incremental = cursor > 0
        messages = 0
        dirty: dict[tuple[str, str], str] = {}
        conversations: set[str] = set()
        conversation_cache: dict[str, tuple[str, str]] = {}
        with _readonly(path) as source:
            while True:
                rows = source.execute("""
                    SELECT rowid,id,chat,message_time FROM messages
                    WHERE rowid>? ORDER BY rowid LIMIT ?
                """, (cursor, batch_size)).fetchall()
                if not rows:
                    break
                for row in rows:
                    source_chat_id = str(row["chat"])
                    cached = conversation_cache.get(source_chat_id)
                    if cached is None:
                        kind = "group" if source_chat_id.endswith("@chatroom") else "direct"
                        conversation_id = self.store.ensure_conversation(
                            source_chat_id, conversation_type=kind,
                            seen_at=str(row["message_time"] or "") or None,
                            mark_active=False,
                        )
                        conversation_cache[source_chat_id] = (conversation_id, kind)
                        if kind == "direct":
                            person_id = self.store.ensure_person(
                                source_chat_id, seen_at=str(row["message_time"] or "") or None,
                                mark_active=False,
                            )
                            self.store.link_conversation_person(conversation_id, person_id, role="other")
                            self.store.add_dependency("conversation", conversation_id,
                                                      "person", person_id, "contributes_to")
                    else:
                        conversation_id, kind = cached
                    conversations.add(conversation_id)
                    period = message_period(row["message_time"])
                    if period:
                        dirty[(conversation_id, period)] = str(row["id"])
                    cursor = int(row["rowid"])
                    messages += 1
                self.store._connection.execute("""
                    INSERT INTO sync_cursors(source,stream_id,cursor,updated_at)
                    VALUES('history_index',?,?,CURRENT_TIMESTAMP)
                    ON CONFLICT(source,stream_id) DO UPDATE SET
                      cursor=excluded.cursor,updated_at=excluded.updated_at
                """, (str(path), str(cursor)))
                self.store._connection.commit()
        for (conversation_id, period), message_id in dirty.items():
            node_id = f"{conversation_id}:{period}"
            self.store.mark_dirty("conversation_month", node_id, "new_message", message_id)
            self.store.add_dependency("conversation_month", node_id,
                                      "conversation", conversation_id, "rolls_up_to")
            if is_incremental:
                self.store.enqueue_job("monthly_analysis", "conversation", conversation_id,
                                       period=period, priority=50)
        return {"messages_seen": messages, "months_dirtied": len(dirty),
                "conversations_seen": len(conversations), "cursor": cursor}

    def index_profile_snapshots(self, profile_path: str | Path) -> dict:
        path = Path(profile_path).expanduser().resolve()
        if not path.is_file():
            return {"snapshots_seen": 0, "people_dirtied": 0}
        cursor_row = self.store._connection.execute(
            "SELECT cursor FROM sync_cursors WHERE source='profile_snapshot_index' AND stream_id=?",
            (str(path),),
        ).fetchone()
        cursor = int(cursor_row[0]) if cursor_row else 0
        is_incremental = cursor > 0
        seen, people = 0, set()
        with _readonly(path) as source, self.store.transaction():
            rows = source.execute("""
                SELECT snapshot_id,profile_type,wechat_id,captured_at,profile_json,source
                FROM profile_snapshots WHERE snapshot_id>? ORDER BY snapshot_id
            """, (cursor,)).fetchall()
            for row in rows:
                person_id = self.store.ensure_person(
                    str(row["wechat_id"]), person_type=str(row["profile_type"]),
                    source=str(row["source"] or "profile_archive"), seen_at=str(row["captured_at"]),
                )
                ref = str(row["snapshot_id"])
                digest = hashlib.sha256(str(row["profile_json"]).encode("utf-8", "surrogatepass")).hexdigest()
                self.store._connection.execute(
                    "INSERT OR IGNORE INTO profile_snapshot_refs VALUES(?,?,?,?,?)",
                    (ref, person_id, str(row["captured_at"]), str(row["source"]), digest),
                )
                self.store.mark_dirty("person", person_id, "profile_snapshot", ref)
                if is_incremental:
                    self.store.enqueue_job("person_analysis", "person", person_id, priority=30)
                people.add(person_id)
                cursor = int(row["snapshot_id"])
                seen += 1
            self.store._connection.execute("""
                INSERT INTO sync_cursors(source,stream_id,cursor,updated_at)
                VALUES('profile_snapshot_index',?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(source,stream_id) DO UPDATE SET cursor=excluded.cursor,updated_at=excluded.updated_at
            """, (str(path), str(cursor)))
        return {"snapshots_seen": seen, "people_dirtied": len(people), "cursor": cursor}

    def index_moments(self, moments_path: str | Path) -> dict:
        path = Path(moments_path).expanduser().resolve()
        if not path.is_file():
            return {"moments_seen": 0, "people_dirtied": 0}
        cursor_row = self.store._connection.execute(
            "SELECT cursor FROM sync_cursors WHERE source='moment_index' AND stream_id=?",
            (str(path),),
        ).fetchone()
        cursor = int(cursor_row[0]) if cursor_row else 0
        is_incremental = cursor > 0
        seen, people = 0, set()
        with _readonly(path) as source:
            rows = source.execute("""
                SELECT rowid,id,username,nickname,create_time FROM moments
                WHERE rowid>? ORDER BY rowid
            """, (cursor,)).fetchall()
            for row in rows:
                person_id = self.store.ensure_person(
                    str(row["username"]), display_name=str(row["nickname"] or ""),
                    source="moments_archive", seen_at=str(row["create_time"] or "") or None,
                    mark_active=False,
                )
                evidence_id = str(row["id"])
                self.store.mark_dirty("person", person_id, "new_moment", evidence_id)
                if is_incremental:
                    self.store.enqueue_job("person_analysis", "person", person_id, priority=40)
                people.add(person_id)
                cursor = int(row["rowid"])
                seen += 1
            self.store._connection.execute("""
                INSERT INTO sync_cursors(source,stream_id,cursor,updated_at)
                VALUES('moment_index',?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(source,stream_id) DO UPDATE SET cursor=excluded.cursor,updated_at=excluded.updated_at
            """, (str(path), str(cursor)))
            self.store._connection.commit()
        return {"moments_seen": seen, "people_dirtied": len(people), "cursor": cursor}

    def queue_initial_top(self, history_path: str | Path, analysis: AnalysisService, *,
                          direct_count: int = 5, group_count: int = 5) -> dict:
        path = Path(history_path).expanduser().resolve()
        selected: list[tuple[str, str, int]] = []
        with _readonly(path) as source:
            for is_group, count in ((False, direct_count), (True, group_count)):
                operator = "LIKE" if is_group else "NOT LIKE"
                rows = source.execute(f"""
                    SELECT chat,COUNT(*) AS total FROM messages
                    WHERE chat {operator} '%@chatroom'
                    GROUP BY chat ORDER BY total DESC LIMIT ?
                """, (count,)).fetchall()
                selected.extend((str(row["chat"]), "group" if is_group else "direct", int(row["total"]))
                                for row in rows)
            jobs = 0
            result = []
            for chat, kind, total in selected:
                conversation_id = self.store.ensure_conversation(chat, conversation_type=kind,
                                                                 mark_active=False)
                current = self.store._connection.execute(
                    "SELECT status FROM conversations WHERE conversation_id=?", (conversation_id,)
                ).fetchone()
                if current and str(current[0]) in {"inferred_removed", "confirmed_removed"}:
                    continue
                if kind == "direct":
                    removed = self.store._connection.execute("""
                        SELECT 1 FROM conversation_members cm JOIN people p ON p.person_id=cm.person_id
                        WHERE cm.conversation_id=? AND p.status IN ('inferred_removed','confirmed_removed')
                        LIMIT 1
                    """, (conversation_id,)).fetchone()
                    if removed:
                        continue
                periods = sorted({message_period(row[0]) for row in source.execute(
                    "SELECT message_time FROM messages WHERE chat=?", (chat,)
                ) if message_period(row[0])})
                for period in periods:
                    analysis.queue_month(conversation_id, period, priority=100)
                    jobs += 1
                result.append({"conversation_id": conversation_id, "type": kind,
                               "message_count": total, "months": len(periods)})
        return {"selected": result, "jobs_queued": jobs}
