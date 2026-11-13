"""Build lightweight entity and analysis indexes over existing archives."""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wechat_auto.memory.analysis import AnalysisService
from wechat_auto.memory.store import MemoryStore
from wechat_auto.utils.moment_reference import (
    moment_reference,
    moment_version_hash,
    validate_moment_subject,
)
from wechat_auto.utils.profile_reference import profile_content_hash, profile_reference


@contextmanager
def _readonly(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        yield connection
    finally:
        connection.close()


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

    @staticmethod
    def history_periods(history_path: str | Path, source_chat_id: str) -> set[str]:
        """Read the archive's month coverage with the same clock as indexing."""
        with _readonly(Path(history_path)) as source:
            return {message_period(row[0]) for row in source.execute(
                "SELECT DISTINCT message_time FROM messages WHERE chat=?", (source_chat_id,)
            )}

    def index_profiles(self, profile_path: str | Path) -> dict:
        path = Path(profile_path).expanduser().resolve()
        if not path.is_file():
            return {"profiles_seen": 0, "people_created_or_seen": 0}
        seen = 0
        current_people: set[str] = set()
        with _readonly(path) as source, self.store.atomic():
            rows = source.execute("""
                SELECT profile_type,wechat_id,nickname,remark,original_name,display_name,updated_at
                FROM profiles WHERE profile_type IN ('self','contact') ORDER BY wechat_id
            """)
            for row in rows:
                person_id = self.store.ensure_person(
                    str(row["wechat_id"]), person_type=str(row["profile_type"]),
                    display_name=str(row["display_name"] or row["remark"] or row["nickname"] or ""),
                    source="profile_archive", seen_at=str(row["updated_at"] or "") or None,
                    mark_active=False,
                )
                for alias_type in ("nickname", "remark", "original_name"):
                    value = str(row[alias_type] or "")
                    self.store.add_alias(person_id, alias_type, value, source="profile_archive")
                seen += 1
                current_people.add(person_id)
            scoped_seen = 0
            tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if {'group_profile_current', 'group_profile_versions'} <= tables:
                rows = source.execute("""SELECT c.group_id,c.wechat_id,s.profile_json,s.captured_at
                    FROM group_profile_current c JOIN group_profile_versions v ON v.snapshot_id=c.snapshot_id
                    JOIN profile_snapshots s ON s.snapshot_id=c.snapshot_id
                    WHERE v.scope_status IN ('scoped','scoped_baseline') ORDER BY c.group_id,c.wechat_id""").fetchall()
                for row in rows:
                    profile = json.loads(row['profile_json'])
                    if profile.get('wechat_id') != row['wechat_id'] or profile.get('group_id') != row['group_id']:
                        raise ValueError('Scoped profile index identity mismatch')
                    existing = self.store._connection.execute(
                        "SELECT person_id FROM person_identities WHERE identity_type='wxid' AND identity_value=?",
                        (row['wechat_id'],)).fetchone()
                    person_id = self.store.ensure_person(row['wechat_id'], person_type='group_member',
                        display_name='' if existing else str(profile.get('remark') or profile.get('nickname') or ''),
                        source='scoped_profile_archive', seen_at=row['captured_at'], mark_active=False)
                    for alias_type in ('nickname', 'remark', 'original_name', 'group_display_name'):
                        self.store.add_alias(person_id, alias_type, str(profile.get(alias_type) or ''),
                            context_id=row['group_id'] if alias_type == 'group_display_name' else '',
                            valid_from=row['captured_at'], source='scoped_profile_archive')
                    current_people.add(person_id)
                    seen += 1
                    scoped_seen += 1
            # An accumulated archive is neither a current friend list nor a
            # complete snapshot. It must not create absence or restore evidence.
            snapshot = self.store.reconcile_snapshot(
                "person", current_people, source="profile_archive", complete=False,
            )
        return {"profiles_seen": seen, "people_created_or_seen": len(current_people), "scoped_group_profiles_seen": scoped_seen,
                "presence_snapshot": {"seen": snapshot["seen"], "missing": snapshot["missing"],
                                      "complete": snapshot["complete"]}}

    def index_history(self, history_path: str | Path, *, batch_size: int = 10_000) -> dict:
        path = Path(history_path).expanduser().resolve()
        if not path.is_file():
            return {"messages_seen": 0, "months_dirtied": 0, "conversations_seen": 0}
        is_incremental = None
        messages = 0
        dirty: set[tuple[str, str]] = set()
        conversations: set[str] = set()
        conversation_cache: dict[str, tuple[str, str]] = {}
        with _readonly(path) as source:
            while True:
                batch_dirty: dict[tuple[str, str], list[str]] = {}
                with self.store.atomic():
                    cursor = int(self.store.get_sync_cursor("history_index", str(path)) or 0)
                    if is_incremental is None:
                        is_incremental = cursor > 0
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
                            batch_dirty.setdefault((conversation_id, period), []).append(str(row["id"]))
                        cursor = int(row["rowid"])
                        messages += 1
                    for (conversation_id, period), message_ids in batch_dirty.items():
                        if is_incremental:
                            self.store.queue_month_message_delta(conversation_id, period, message_ids)
                            continue
                        node_id = f"{conversation_id}:{period}"
                        self.store.mark_dirty("conversation_month", node_id, "new_message", message_ids[-1])
                        self.store.add_dependency("conversation_month", node_id,
                                                  "conversation", conversation_id, "rolls_up_to")
                    self.store.set_sync_cursor("history_index", str(path), cursor)
                dirty.update(batch_dirty)
        return {"messages_seen": messages, "months_dirtied": len(dirty),
                "conversations_seen": len(conversations), "cursor": cursor}

    def index_profile_snapshots(self, profile_path: str | Path) -> dict:
        path = Path(profile_path).expanduser().resolve()
        if not path.is_file():
            return {"snapshots_seen": 0, "people_dirtied": 0}
        cursor_row = self.store._connection.execute(
            "SELECT cursor FROM sync_cursors WHERE source='profile_snapshot_index_v2' AND stream_id=?",
            (str(path),),
        ).fetchone()
        cursor = int(cursor_row[0]) if cursor_row else 0
        is_incremental = cursor > 0
        seen, people = 0, set()
        skipped = 0
        with _readonly(path) as source, self.store.atomic():
            tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            rows = source.execute("""
                SELECT snapshot_id,profile_type,wechat_id,captured_at,profile_json,source
                FROM profile_snapshots WHERE snapshot_id>? ORDER BY snapshot_id
            """, (cursor,)).fetchall()
            for row in rows:
                if row['profile_type'] == 'group_member':
                    scoped = source.execute('SELECT scope_status,group_id,wechat_id FROM group_profile_versions WHERE snapshot_id=?',
                        (row['snapshot_id'],)).fetchone() if 'group_profile_versions' in tables else None
                    if scoped is None or scoped[0] not in {'scoped', 'scoped_baseline'}:
                        cursor = int(row['snapshot_id'])
                        skipped += 1
                        continue
                    profile = json.loads(row['profile_json'])
                    if (profile.get('wechat_id') != row['wechat_id'] or scoped[2] != row['wechat_id']
                            or profile.get('group_id') != scoped[1]):
                        raise ValueError('Scoped snapshot identity mismatch')
                payload = json.loads(row['profile_json'])
                if not isinstance(payload, dict) or payload.get('wechat_id') != row['wechat_id']:
                    raise ValueError('Profile snapshot subject identity mismatch')
                person_id = self.store.ensure_person(
                    str(row["wechat_id"]), person_type=str(row["profile_type"]),
                    source=str(row["source"] or "profile_archive"), seen_at=str(row["captured_at"]),
                    mark_active=False,
                )
                digest = profile_content_hash(row)
                ref = profile_reference(path, row["snapshot_id"], digest)
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
                VALUES('profile_snapshot_index_v2',?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(source,stream_id) DO UPDATE SET cursor=excluded.cursor,updated_at=excluded.updated_at
            """, (str(path), str(cursor)))
        return {"snapshots_seen": seen, "people_dirtied": len(people), "cursor": cursor,
                "legacy_group_snapshots_skipped": skipped, "reference_version": 2}

    def index_moments(self, moments_path: str | Path) -> dict:
        path = Path(moments_path).expanduser().resolve()
        if not path.is_file():
            return {"moments_seen": 0, "people_dirtied": 0}
        seen, people = 0, set()
        with _readonly(path) as source, self.store.atomic():
            versioned = bool(source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='moment_versions'").fetchone())
            cursor_source = 'moment_version_index' if versioned else 'moment_index'
            cursor_row = self.store._connection.execute(
                "SELECT cursor FROM sync_cursors WHERE source=? AND stream_id=?",
                (cursor_source, str(path)),
            ).fetchone()
            cursor = int(cursor_row[0]) if cursor_row else 0
            is_incremental = cursor > 0
            rows = source.execute("SELECT * FROM moment_versions WHERE version_id>? ORDER BY version_id", (cursor,)).fetchall() if versioned else source.execute("""
                SELECT rowid,id,username,nickname,create_time FROM moments
                WHERE rowid>? ORDER BY rowid
            """, (cursor,)).fetchall()
            for row in rows:
                if versioned:
                    validate_moment_subject(row)
                existing = self.store._connection.execute(
                    "SELECT person_id FROM person_identities WHERE identity_type='wxid' AND identity_value=?",
                    (row['username'],)).fetchone()
                person_id = self.store.ensure_person(
                    str(row["username"]), display_name='' if existing else str(row["nickname"] or ""),
                    source="moments_archive", seen_at=str(row["observed_at"] if versioned else row["create_time"] or "") or None,
                    mark_active=False,
                )
                evidence_id = moment_reference(path, row["version_id"], moment_version_hash(row)) if versioned else str(row["id"])
                self.store.add_alias(person_id, 'nickname', str(row['nickname'] or ''),
                                     context_id=evidence_id, source='moments_archive',
                                     valid_from=str(row['observed_at']) if versioned else None)
                self.store.mark_dirty("person", person_id, "new_moment", evidence_id)
                if is_incremental:
                    self.store.enqueue_job("person_analysis", "person", person_id, priority=40)
                people.add(person_id)
                cursor = int(row["version_id"] if versioned else row["rowid"])
                seen += 1
            self.store._connection.execute("""
                INSERT INTO sync_cursors(source,stream_id,cursor,updated_at)
                VALUES(?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(source,stream_id) DO UPDATE SET cursor=excluded.cursor,updated_at=excluded.updated_at
            """, (cursor_source, str(path), str(cursor)))
        return {"moments_seen": seen, "people_dirtied": len(people), "cursor": cursor,
                "cursor_source": cursor_source, "updates_supported": versioned}

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
