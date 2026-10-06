"""SQLite index for structured WeChat memory.

The store deliberately keeps long-form analysis out of SQLite.  Claims contain
one compact canonical sentence; full human/agent-readable memory is materialized
by :mod:`wechat_auto.memory.markdown`.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Self
from uuid import uuid4

from wechat_auto.version import MEMORY_SCHEMA_VERSION

CLAIM_STATUSES = {"confirmed", "observed", "inferred", "unknown", "inactive", "superseded"}
ENTITY_STATUSES = {"active", "missing", "inferred_removed", "confirmed_removed", "restored", "unknown"}
JOB_STATUSES = {"pending", "running", "complete", "failed", "superseded"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _short_id(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:12]}"


class MemoryStore:
    """Own the normalized entity, claim, dependency, and version index."""

    schema_version = MEMORY_SCHEMA_VERSION

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # MCP executes synchronous tool functions in worker threads.  The store
        # owns one process-local connection, so allow those serialized SDK calls
        # to use it outside the thread that built the server.
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection:
            yield self._connection

    def _create_schema(self) -> None:
        self._connection.executescript("""
        CREATE TABLE IF NOT EXISTS schema_meta(
            key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS people(
            person_id TEXT PRIMARY KEY, person_type TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
            first_seen_at TEXT, last_seen_at TEXT, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS person_identities(
            identity_type TEXT NOT NULL, identity_value TEXT NOT NULL,
            person_id TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'unknown',
            confirmed INTEGER NOT NULL DEFAULT 1, first_seen_at TEXT,
            last_seen_at TEXT, PRIMARY KEY(identity_type,identity_value),
            FOREIGN KEY(person_id) REFERENCES people(person_id)
        );
        CREATE TABLE IF NOT EXISTS person_aliases(
            id INTEGER PRIMARY KEY, person_id TEXT NOT NULL, alias_type TEXT NOT NULL,
            alias_value TEXT NOT NULL, context_id TEXT NOT NULL DEFAULT '',
            valid_from TEXT, valid_to TEXT, source TEXT NOT NULL DEFAULT 'unknown',
            UNIQUE(person_id,alias_type,alias_value,context_id,valid_from),
            FOREIGN KEY(person_id) REFERENCES people(person_id)
        );
        CREATE TABLE IF NOT EXISTS conversations(
            conversation_id TEXT PRIMARY KEY, source_chat_id TEXT NOT NULL UNIQUE,
            conversation_type TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active', first_seen_at TEXT,
            last_seen_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversation_members(
            conversation_id TEXT NOT NULL, person_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member', valid_from TEXT, valid_to TEXT,
            PRIMARY KEY(conversation_id,person_id,valid_from),
            FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id),
            FOREIGN KEY(person_id) REFERENCES people(person_id)
        );
        CREATE TABLE IF NOT EXISTS groups(
            group_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id)
        );
        CREATE TABLE IF NOT EXISTS group_memberships(
            group_id TEXT NOT NULL, person_id TEXT NOT NULL,
            group_display_name TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT 'member',
            valid_from TEXT, valid_to TEXT, status TEXT NOT NULL DEFAULT 'active',
            PRIMARY KEY(group_id,person_id,valid_from),
            FOREIGN KEY(group_id) REFERENCES groups(group_id),
            FOREIGN KEY(person_id) REFERENCES people(person_id)
        );
        CREATE TABLE IF NOT EXISTS relationships(
            relationship_id TEXT PRIMARY KEY, left_person_id TEXT NOT NULL,
            right_person_id TEXT NOT NULL, relationship_type TEXT NOT NULL DEFAULT 'unknown',
            status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, UNIQUE(left_person_id,right_person_id),
            FOREIGN KEY(left_person_id) REFERENCES people(person_id),
            FOREIGN KEY(right_person_id) REFERENCES people(person_id)
        );
        CREATE TABLE IF NOT EXISTS profile_snapshot_refs(
            snapshot_ref TEXT PRIMARY KEY, person_id TEXT NOT NULL,
            observed_at TEXT NOT NULL, source TEXT NOT NULL,
            content_hash TEXT NOT NULL, FOREIGN KEY(person_id) REFERENCES people(person_id)
        );
        CREATE TABLE IF NOT EXISTS entity_status_events(
            event_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
            status TEXT NOT NULL, observed_at TEXT NOT NULL, source TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1, reason TEXT NOT NULL DEFAULT '',
            snapshot_key TEXT NOT NULL DEFAULT '', UNIQUE(entity_type,entity_id,status,snapshot_key)
        );
        CREATE TABLE IF NOT EXISTS entity_presence(
            entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
            missing_count INTEGER NOT NULL DEFAULT 0, first_missing_at TEXT,
            last_checked_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            PRIMARY KEY(entity_type,entity_id)
        );
        CREATE TABLE IF NOT EXISTS entity_snapshots(
            snapshot_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL,
            observed_at TEXT NOT NULL, source TEXT NOT NULL, complete INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS entity_snapshot_members(
            snapshot_id TEXT NOT NULL, entity_id TEXT NOT NULL,
            PRIMARY KEY(snapshot_id,entity_id),
            FOREIGN KEY(snapshot_id) REFERENCES entity_snapshots(snapshot_id)
        );
        CREATE TABLE IF NOT EXISTS identity_merge_candidates(
            candidate_id TEXT PRIMARY KEY, left_person_id TEXT NOT NULL,
            right_person_id TEXT NOT NULL, reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
            decided_at TEXT, UNIQUE(left_person_id,right_person_id)
        );
        CREATE TABLE IF NOT EXISTS claims(
            claim_id TEXT PRIMARY KEY, claim_type TEXT NOT NULL,
            subject_person_id TEXT, object_person_id TEXT,
            conversation_id TEXT, group_id TEXT, canonical_text TEXT NOT NULL,
            valid_from TEXT, valid_to TEXT, status TEXT NOT NULL,
            confidence REAL NOT NULL, current_version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS claim_versions(
            claim_id TEXT NOT NULL, version INTEGER NOT NULL,
            canonical_text TEXT NOT NULL, valid_from TEXT, valid_to TEXT,
            status TEXT NOT NULL, confidence REAL NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(claim_id,version), FOREIGN KEY(claim_id) REFERENCES claims(claim_id)
        );
        CREATE TABLE IF NOT EXISTS claim_evidence(
            claim_id TEXT NOT NULL, evidence_type TEXT NOT NULL,
            evidence_id TEXT NOT NULL, relation TEXT NOT NULL DEFAULT 'supports',
            weight REAL NOT NULL DEFAULT 1, PRIMARY KEY(claim_id,evidence_type,evidence_id,relation),
            FOREIGN KEY(claim_id) REFERENCES claims(claim_id)
        );
        CREATE TABLE IF NOT EXISTS claim_counter_evidence(
            claim_id TEXT NOT NULL, evidence_type TEXT NOT NULL,
            evidence_id TEXT NOT NULL, relation TEXT NOT NULL DEFAULT 'contradicts',
            weight REAL NOT NULL DEFAULT 1, PRIMARY KEY(claim_id,evidence_type,evidence_id,relation),
            FOREIGN KEY(claim_id) REFERENCES claims(claim_id)
        );
        CREATE TABLE IF NOT EXISTS events(
            event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '', started_at TEXT, ended_at TEXT,
            status TEXT NOT NULL DEFAULT 'observed', confidence REAL NOT NULL DEFAULT 1,
            current_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS event_phases(
            phase_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, title TEXT NOT NULL,
            started_at TEXT, ended_at TEXT, ordinal INTEGER NOT NULL,
            FOREIGN KEY(event_id) REFERENCES events(event_id)
        );
        CREATE TABLE IF NOT EXISTS event_people(
            event_id TEXT NOT NULL, person_id TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'participant',
            PRIMARY KEY(event_id,person_id,role), FOREIGN KEY(event_id) REFERENCES events(event_id)
        );
        CREATE TABLE IF NOT EXISTS event_conversations(
            event_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
            PRIMARY KEY(event_id,conversation_id), FOREIGN KEY(event_id) REFERENCES events(event_id)
        );
        CREATE TABLE IF NOT EXISTS event_claims(
            event_id TEXT NOT NULL, claim_id TEXT NOT NULL,
            PRIMARY KEY(event_id,claim_id), FOREIGN KEY(event_id) REFERENCES events(event_id),
            FOREIGN KEY(claim_id) REFERENCES claims(claim_id)
        );
        CREATE TABLE IF NOT EXISTS event_versions(
            event_id TEXT NOT NULL, version INTEGER NOT NULL, title TEXT NOT NULL,
            summary TEXT NOT NULL, started_at TEXT, ended_at TEXT, status TEXT NOT NULL,
            confidence REAL NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(event_id,version), FOREIGN KEY(event_id) REFERENCES events(event_id)
        );
        CREATE TABLE IF NOT EXISTS analysis_runs(
            run_id TEXT PRIMARY KEY, scope_type TEXT NOT NULL, scope_id TEXT NOT NULL,
            period TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL,
            status TEXT NOT NULL, input_fingerprint TEXT NOT NULL,
            parent_version INTEGER, output_version INTEGER, started_at TEXT NOT NULL,
            completed_at TEXT, error TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS analysis_coverage(
            scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, period TEXT NOT NULL DEFAULT '',
            message_watermark TEXT NOT NULL DEFAULT '', moment_watermark TEXT NOT NULL DEFAULT '',
            profile_watermark TEXT NOT NULL DEFAULT '', evidence_count INTEGER NOT NULL DEFAULT 0,
            input_fingerprint TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
            PRIMARY KEY(scope_type,scope_id,period)
        );
        CREATE TABLE IF NOT EXISTS analysis_versions(
            scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, period TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL, parent_version INTEGER, content_hash TEXT NOT NULL,
            markdown_path TEXT NOT NULL, input_fingerprint TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(scope_type,scope_id,period,version)
        );
        CREATE TABLE IF NOT EXISTS input_fingerprints(
            scope_type TEXT NOT NULL, scope_id TEXT NOT NULL, period TEXT NOT NULL DEFAULT '',
            fingerprint TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(scope_type,scope_id,period,fingerprint)
        );
        CREATE TABLE IF NOT EXISTS dependency_edges(
            upstream_type TEXT NOT NULL, upstream_id TEXT NOT NULL,
            downstream_type TEXT NOT NULL, downstream_id TEXT NOT NULL,
            relation TEXT NOT NULL, PRIMARY KEY(upstream_type,upstream_id,downstream_type,downstream_id,relation)
        );
        CREATE TABLE IF NOT EXISTS dirty_nodes(
            node_type TEXT NOT NULL, node_id TEXT NOT NULL, reason TEXT NOT NULL,
            dirty_since TEXT NOT NULL, source_id TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(node_type,node_id,reason,source_id)
        );
        CREATE TABLE IF NOT EXISTS sync_cursors(
            source TEXT NOT NULL, stream_id TEXT NOT NULL, cursor TEXT NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY(source,stream_id)
        );
        CREATE TABLE IF NOT EXISTS analysis_jobs(
            job_id TEXT PRIMARY KEY, job_type TEXT NOT NULL, scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL, period TEXT NOT NULL DEFAULT '', priority INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending', input_fingerprint TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0, available_at TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(job_type,scope_type,scope_id,period,input_fingerprint)
        );
        CREATE TABLE IF NOT EXISTS user_corrections(
            correction_id TEXT PRIMARY KEY, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
            correction_text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL, superseded_at TEXT
        );
        CREATE TABLE IF NOT EXISTS reply_drafts(
            draft_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
            trigger_evidence_id TEXT NOT NULL, text TEXT NOT NULL,
            context_fingerprint TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL, expires_at TEXT, confirmed_at TEXT,
            confirmation_id TEXT UNIQUE, sent_at TEXT
        );
        CREATE TABLE IF NOT EXISTS pending_actions(
            action_id TEXT PRIMARY KEY, action_type TEXT NOT NULL, target_id TEXT NOT NULL,
            payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
            expires_at TEXT, confirmed_at TEXT, confirmation_id TEXT UNIQUE,
            finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_claim_scope ON claims(conversation_id,subject_person_id,status);
        CREATE INDEX IF NOT EXISTS idx_claim_validity ON claims(valid_from,valid_to);
        CREATE INDEX IF NOT EXISTS idx_event_time ON events(started_at,ended_at);
        CREATE INDEX IF NOT EXISTS idx_jobs_pending ON analysis_jobs(status,priority,available_at);
        CREATE INDEX IF NOT EXISTS idx_dirty_node ON dirty_nodes(node_type,node_id);
        CREATE TABLE IF NOT EXISTS contact_state_history(
            observation_key TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(person_id),
            relation TEXT NOT NULL, value TEXT NOT NULL, source TEXT NOT NULL,
            evidence_ref TEXT NOT NULL, confirmed INTEGER NOT NULL, observed_at TEXT NOT NULL,
            fingerprint TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS moments_coverage(
            observation_key TEXT PRIMARY KEY, person_id TEXT NOT NULL REFERENCES people(person_id),
            path TEXT NOT NULL, status TEXT NOT NULL, count INTEGER NOT NULL, pages INTEGER NOT NULL,
            reason TEXT NOT NULL, evidence_ref TEXT NOT NULL, oldest_at TEXT NOT NULL,
            newest_at TEXT NOT NULL, observed_at TEXT NOT NULL, fingerprint TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS moments_section_coverage(
            observation_key TEXT NOT NULL REFERENCES moments_coverage(observation_key),
            section TEXT NOT NULL, status TEXT NOT NULL,
            visibility_window TEXT NOT NULL, visibility_hint TEXT NOT NULL,
            PRIMARY KEY(observation_key,section)
        );
        CREATE TABLE IF NOT EXISTS moments_load_queue(
            person_id TEXT PRIMARY KEY REFERENCES people(person_id), status TEXT NOT NULL,
            last_error TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """)
        existing = self._connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        existing_version = int(existing[0]) if existing is not None else None
        if existing_version in {1, 2} and self.schema_version == 3:
            # v2 adds pending_actions; v3 adds directional contact observations,
            # collection coverage and a resumable loading queue. Existing rows
            # and Markdown version references are preserved.
            self._connection.execute(
                "UPDATE schema_meta SET value='3' WHERE key='schema_version'"
            )
            existing_version = 3
        if existing_version is not None and existing_version != self.schema_version:
            self._connection.close()
            raise RuntimeError(
                f"Unsupported Memory schema {existing_version}; expected {self.schema_version}. "
                "Run a compatible migration or rebuild before opening this database."
            )
        self._connection.execute(
            "INSERT OR IGNORE INTO schema_meta(key,value) VALUES('schema_version',?)",
            (str(self.schema_version),),
        )
        self._connection.commit()

    def ensure_person(self, identity_value: str, *, identity_type: str = "wxid",
                      person_type: str = "contact", display_name: str = "",
                      source: str = "wechat_db", seen_at: str | None = None,
                      mark_active: bool = True) -> str:
        if not identity_value.strip():
            raise ValueError("identity_value must not be empty")
        row = self._connection.execute(
            "SELECT person_id FROM person_identities WHERE identity_type=? AND identity_value=?",
            (identity_type, identity_value.strip()),
        ).fetchone()
        now = _now()
        observed = seen_at or now
        if row:
            person_id = str(row[0])
            with self._connection:
                self._connection.execute(
                    "UPDATE people SET display_name=CASE WHEN ?='' THEN display_name ELSE ? END, "
                    "last_seen_at=?, status=CASE WHEN ? THEN 'active' ELSE status END, "
                    "updated_at=? WHERE person_id=?",
                    (display_name, display_name, observed, int(mark_active), now, person_id),
                )
                self._connection.execute(
                    "UPDATE person_identities SET last_seen_at=? WHERE identity_type=? AND identity_value=?",
                    (observed, identity_type, identity_value.strip()),
                )
            return person_id
        person_id = _short_id("p")
        with self._connection:
            self._connection.execute(
                "INSERT INTO people VALUES(?,?,?,?,?,?,?,?)",
                (person_id, person_type, display_name, "active" if mark_active else "unknown",
                 observed, observed, now, now),
            )
            self._connection.execute(
                "INSERT INTO person_identities VALUES(?,?,?,?,?,?,?)",
                (identity_type, identity_value.strip(), person_id, source, 1, observed, observed),
            )
        return person_id

    def add_alias(self, person_id: str, alias_type: str, alias_value: str, *,
                  context_id: str = "", valid_from: str | None = None,
                  source: str = "wechat_db") -> None:
        if not alias_value.strip():
            return
        self._connection.execute(
            "INSERT OR IGNORE INTO person_aliases(person_id,alias_type,alias_value,context_id,valid_from,source) "
            "VALUES(?,?,?,?,?,?)",
            (person_id, alias_type, alias_value.strip(), context_id, valid_from, source),
        )
        self._connection.commit()

    def propose_identity_merge(self, left_person_id: str, right_person_id: str,
                               reason: str) -> str:
        if left_person_id == right_person_id:
            raise ValueError("cannot merge a person with itself")
        row = self._connection.execute("""
            SELECT candidate_id FROM identity_merge_candidates
            WHERE left_person_id=? AND right_person_id=?
        """, (left_person_id, right_person_id)).fetchone()
        if row:
            return str(row[0])
        candidate_id = _short_id("im")
        self._connection.execute(
            "INSERT INTO identity_merge_candidates(candidate_id,left_person_id,right_person_id,reason,created_at) "
            "VALUES(?,?,?,?,?)",
            (candidate_id, left_person_id, right_person_id, reason, _now()),
        )
        self._connection.commit()
        return candidate_id

    def decide_identity_merge(self, candidate_id: str, *, confirm: bool) -> dict:
        row = self._connection.execute(
            "SELECT * FROM identity_merge_candidates WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
        if row is None or row["status"] != "pending":
            raise ValueError("merge candidate is missing or already decided")
        left, right = str(row["left_person_id"]), str(row["right_person_id"])
        if not confirm:
            self._connection.execute(
                "UPDATE identity_merge_candidates SET status='rejected',decided_at=? WHERE candidate_id=?",
                (_now(), candidate_id),
            )
            self._connection.commit()
            return {"candidate_id": candidate_id, "merged": False, "status": "rejected"}
        with self._connection:
            self._connection.execute("UPDATE person_identities SET person_id=? WHERE person_id=?", (left, right))
            self._connection.execute("UPDATE OR IGNORE person_aliases SET person_id=? WHERE person_id=?", (left, right))
            self._connection.execute("DELETE FROM person_aliases WHERE person_id=?", (right,))
            self._connection.execute("UPDATE OR IGNORE conversation_members SET person_id=? WHERE person_id=?", (left, right))
            self._connection.execute("DELETE FROM conversation_members WHERE person_id=?", (right,))
            self._connection.execute("UPDATE OR IGNORE group_memberships SET person_id=? WHERE person_id=?", (left, right))
            self._connection.execute("DELETE FROM group_memberships WHERE person_id=?", (right,))
            self._connection.execute("UPDATE profile_snapshot_refs SET person_id=? WHERE person_id=?", (left, right))
            self._connection.execute("UPDATE contact_state_history SET person_id=? WHERE person_id=?", (left, right))
            self._connection.execute("UPDATE moments_coverage SET person_id=? WHERE person_id=?", (left, right))
            # Retain both queue records for audit; the merged identity cannot
            # be loaded independently after confirmation.
            self._connection.execute("UPDATE moments_load_queue SET status='merged',updated_at=? WHERE person_id=?",
                                     (_now(), right))
            self._connection.execute("UPDATE claims SET subject_person_id=? WHERE subject_person_id=?", (left, right))
            self._connection.execute("UPDATE claims SET object_person_id=? WHERE object_person_id=?", (left, right))
            self._connection.execute("UPDATE OR IGNORE event_people SET person_id=? WHERE person_id=?", (left, right))
            self._connection.execute("DELETE FROM event_people WHERE person_id=?", (right,))
            self._connection.execute("UPDATE OR IGNORE relationships SET left_person_id=? WHERE left_person_id=?", (left, right))
            self._connection.execute("UPDATE OR IGNORE relationships SET right_person_id=? WHERE right_person_id=?", (left, right))
            self._connection.execute("DELETE FROM relationships WHERE left_person_id=? OR right_person_id=? OR left_person_id=right_person_id", (right, right))
            self._connection.execute("UPDATE people SET status='merged',updated_at=? WHERE person_id=?", (_now(), right))
            self._connection.execute(
                "UPDATE identity_merge_candidates SET status='confirmed',decided_at=? WHERE candidate_id=?",
                (_now(), candidate_id),
            )
        self.mark_dirty("person", left, "identity_merge", candidate_id)
        return {"candidate_id": candidate_id, "merged": True,
                "canonical_person_id": left, "merged_person_id": right}

    def ensure_conversation(self, source_chat_id: str, *, conversation_type: str,
                            title: str = "", seen_at: str | None = None,
                            mark_active: bool = True) -> str:
        if conversation_type not in {"direct", "group"}:
            raise ValueError("conversation_type must be direct or group")
        now = _now()
        observed = seen_at or now
        row = self._connection.execute(
            "SELECT conversation_id FROM conversations WHERE source_chat_id=?", (source_chat_id,)
        ).fetchone()
        if row:
            conversation_id = str(row[0])
            self._connection.execute(
                "UPDATE conversations SET title=CASE WHEN ?='' THEN title ELSE ? END, "
                "status=CASE WHEN ? THEN 'active' ELSE status END,last_seen_at=?,updated_at=? "
                "WHERE conversation_id=?",
                (title, title, int(mark_active), observed, now, conversation_id),
            )
        else:
            conversation_id = _short_id("cv")
            self._connection.execute(
                "INSERT INTO conversations VALUES(?,?,?,?,?,?,?,?,?)",
                (conversation_id, source_chat_id, conversation_type, title,
                 "active" if mark_active else "unknown",
                 observed, observed, now, now),
            )
        if conversation_type == "group":
            self._connection.execute(
                "INSERT INTO groups(group_id,conversation_id,title,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(group_id) DO UPDATE SET "
                "title=excluded.title,status=CASE WHEN ? THEN 'active' ELSE groups.status END,"
                "updated_at=excluded.updated_at",
                (source_chat_id, conversation_id, title,
                 "active" if mark_active else "unknown", now, now, int(mark_active)),
            )
        self._connection.commit()
        return conversation_id

    def link_conversation_person(self, conversation_id: str, person_id: str,
                                 role: str = "member", valid_from: str | None = None) -> None:
        self._connection.execute(
            "INSERT OR IGNORE INTO conversation_members VALUES(?,?,?,?,?)",
            (conversation_id, person_id, role, valid_from, None),
        )
        self._connection.commit()

    def ensure_relationship(self, left_person_id: str, right_person_id: str, *,
                            relationship_type: str = "unknown") -> str:
        if left_person_id == right_person_id:
            raise ValueError("relationship participants must differ")
        left, right = sorted((left_person_id, right_person_id))
        row = self._connection.execute(
            "SELECT relationship_id FROM relationships WHERE left_person_id=? AND right_person_id=?",
            (left, right),
        ).fetchone()
        if row:
            relationship_id = str(row[0])
            self._connection.execute(
                "UPDATE relationships SET relationship_type=?,updated_at=? WHERE relationship_id=?",
                (relationship_type, _now(), relationship_id),
            )
        else:
            relationship_id = _short_id("rel")
            now = _now()
            self._connection.execute(
                "INSERT INTO relationships VALUES(?,?,?,?,?,?,?)",
                (relationship_id, left, right, relationship_type, "active", now, now),
            )
        self._connection.commit()
        return relationship_id

    def add_claim(self, canonical_text: str, *, claim_type: str,
                  subject_person_id: str | None = None, object_person_id: str | None = None,
                  conversation_id: str | None = None, group_id: str | None = None,
                  valid_from: str | None = None, valid_to: str | None = None,
                  status: str = "inferred", confidence: float = .5,
                  evidence: Iterable[dict] = (), counter_evidence: Iterable[dict] = (),
                  claim_id: str | None = None) -> str:
        text = canonical_text.strip()
        if not text or len(text) > 500:
            raise ValueError("canonical_text must contain 1-500 characters")
        if status not in CLAIM_STATUSES:
            raise ValueError(f"unsupported claim status: {status}")
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        claim_id = claim_id or _short_id("c")
        now = _now()
        current = self._connection.execute(
            "SELECT current_version FROM claims WHERE claim_id=?", (claim_id,)
        ).fetchone()
        version = int(current[0]) + 1 if current else 1
        with self._connection:
            self._connection.execute("""
                INSERT INTO claims(claim_id,claim_type,subject_person_id,object_person_id,
                  conversation_id,group_id,canonical_text,valid_from,valid_to,status,confidence,
                  current_version,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(claim_id) DO UPDATE SET
                  claim_type=excluded.claim_type,subject_person_id=excluded.subject_person_id,
                  object_person_id=excluded.object_person_id,conversation_id=excluded.conversation_id,
                  group_id=excluded.group_id,canonical_text=excluded.canonical_text,
                  valid_from=excluded.valid_from,valid_to=excluded.valid_to,status=excluded.status,
                  confidence=excluded.confidence,current_version=excluded.current_version,
                  updated_at=excluded.updated_at
            """, (claim_id, claim_type, subject_person_id, object_person_id, conversation_id,
                  group_id, text, valid_from, valid_to, status, confidence, version, now, now))
            self._connection.execute(
                "INSERT INTO claim_versions VALUES(?,?,?,?,?,?,?,?)",
                (claim_id, version, text, valid_from, valid_to, status, confidence, now),
            )
            for item in evidence:
                self._insert_evidence("claim_evidence", claim_id, item)
            for item in counter_evidence:
                self._insert_evidence("claim_counter_evidence", claim_id, item)
        return claim_id

    def invalidate_claim(self, claim_id: str, *, status: str = "inactive") -> int:
        claim = self.get_claim(claim_id)
        if claim is None:
            raise ValueError("claim not found")
        self.add_claim(
            claim_id=claim_id, canonical_text=claim["canonical_text"],
            claim_type=claim["claim_type"], subject_person_id=claim["subject_person_id"],
            object_person_id=claim["object_person_id"], conversation_id=claim["conversation_id"],
            group_id=claim["group_id"], valid_from=claim["valid_from"], valid_to=claim["valid_to"],
            status=status, confidence=float(claim["confidence"]),
        )
        return int(self.get_claim(claim_id)["current_version"])

    def _insert_evidence(self, table: str, claim_id: str, item: dict) -> None:
        evidence_type = str(item.get("evidence_type") or item.get("type") or "message")
        evidence_id = str(item.get("evidence_id") or item.get("id") or "")
        if not evidence_id:
            raise ValueError("evidence requires evidence_id")
        relation = str(item.get("relation") or ("supports" if table == "claim_evidence" else "contradicts"))
        weight = float(item.get("weight", 1))
        self._connection.execute(
            f"INSERT OR REPLACE INTO {table} VALUES(?,?,?,?,?)",
            (claim_id, evidence_type, evidence_id, relation, weight),
        )

    def get_claim(self, claim_id: str, *, include_evidence: bool = False) -> dict | None:
        row = self._connection.execute("SELECT * FROM claims WHERE claim_id=?", (claim_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        if include_evidence:
            result["evidence"] = self.evidence_for_claim(claim_id)
            result["counter_evidence"] = self.evidence_for_claim(claim_id, counter=True)
        return result

    def search_claims(self, *, query: str = "", person_id: str | None = None,
                      conversation_id: str | None = None, statuses: Iterable[str] = ("confirmed", "observed", "inferred"),
                      limit: int = 50) -> list[dict]:
        if limit <= 0 or limit > 500:
            raise ValueError("limit must be from 1 through 500")
        states = tuple(statuses)
        if not states:
            return []
        clauses = [f"status IN ({','.join('?' for _ in states)})"]
        params: list[object] = list(states)
        if query:
            clauses.append("canonical_text LIKE ?")
            params.append(f"%{query}%")
        if person_id:
            clauses.append("(subject_person_id=? OR object_person_id=?)")
            params.extend((person_id, person_id))
        if conversation_id:
            clauses.append("conversation_id=?")
            params.append(conversation_id)
        params.append(limit)
        rows = self._connection.execute(
            "SELECT * FROM claims WHERE " + " AND ".join(clauses) +
            " ORDER BY COALESCE(valid_to,valid_from,'') DESC,confidence DESC LIMIT ?", params
        ).fetchall()
        return [dict(row) for row in rows]

    def evidence_for_claim(self, claim_id: str, *, counter: bool = False) -> list[dict]:
        table = "claim_counter_evidence" if counter else "claim_evidence"
        return [dict(row) for row in self._connection.execute(
            f"SELECT evidence_type,evidence_id,relation,weight FROM {table} WHERE claim_id=? "
            "ORDER BY weight DESC,evidence_id", (claim_id,)
        )]

    def add_event(self, title: str, *, event_type: str = "life_event", summary: str = "",
                  started_at: str | None = None, ended_at: str | None = None,
                  status: str = "observed", confidence: float = .5,
                  people: Iterable[str] = (), conversations: Iterable[str] = (),
                  claims: Iterable[str] = (), phases: Iterable[dict] = (),
                  event_id: str | None = None) -> str:
        event_id = event_id or _short_id("e")
        now = _now()
        current = self._connection.execute(
            "SELECT current_version FROM events WHERE event_id=?", (event_id,)
        ).fetchone()
        version = int(current[0]) + 1 if current else 1
        with self._connection:
            self._connection.execute("""
                INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(event_id) DO UPDATE SET event_type=excluded.event_type,
                  title=excluded.title,summary=excluded.summary,started_at=excluded.started_at,
                  ended_at=excluded.ended_at,status=excluded.status,confidence=excluded.confidence,
                  current_version=excluded.current_version,updated_at=excluded.updated_at
            """, (event_id, event_type, title.strip(), summary.strip(), started_at, ended_at,
                  status, confidence, version, now, now))
            self._connection.execute(
                "INSERT INTO event_versions VALUES(?,?,?,?,?,?,?,?,?)",
                (event_id, version, title.strip(), summary.strip(), started_at, ended_at,
                 status, confidence, now),
            )
            for person_id in people:
                self._connection.execute("INSERT OR IGNORE INTO event_people VALUES(?,?,'participant')",
                                         (event_id, person_id))
            for conversation_id in conversations:
                self._connection.execute("INSERT OR IGNORE INTO event_conversations VALUES(?,?)",
                                         (event_id, conversation_id))
            for claim_id in claims:
                self._connection.execute("INSERT OR IGNORE INTO event_claims VALUES(?,?)",
                                         (event_id, claim_id))
            self._connection.execute("DELETE FROM event_phases WHERE event_id=?", (event_id,))
            for ordinal, phase in enumerate(phases):
                self._connection.execute(
                    "INSERT INTO event_phases VALUES(?,?,?,?,?,?)",
                    (str(phase.get("phase_id") or _short_id("ep")), event_id,
                     str(phase.get("title", "")), phase.get("started_at"),
                     phase.get("ended_at"), ordinal),
                )
        return event_id

    def get_event(self, event_id: str) -> dict | None:
        row = self._connection.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["phases"] = [dict(item) for item in self._connection.execute(
            "SELECT * FROM event_phases WHERE event_id=? ORDER BY ordinal", (event_id,)
        )]
        result["people"] = [item[0] for item in self._connection.execute(
            "SELECT person_id FROM event_people WHERE event_id=?", (event_id,)
        )]
        result["conversations"] = [item[0] for item in self._connection.execute(
            "SELECT conversation_id FROM event_conversations WHERE event_id=?", (event_id,)
        )]
        result["claims"] = [item[0] for item in self._connection.execute(
            "SELECT claim_id FROM event_claims WHERE event_id=?", (event_id,)
        )]
        return result

    def list_events(self, *, person_id: str | None = None,
                    conversation_id: str | None = None, limit: int = 200) -> list[dict]:
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be from 1 through 1000")
        joins, clauses, params = [], [], []
        if person_id:
            joins.append("JOIN event_people ep ON ep.event_id=e.event_id")
            clauses.append("ep.person_id=?")
            params.append(person_id)
        if conversation_id:
            joins.append("JOIN event_conversations ec ON ec.event_id=e.event_id")
            clauses.append("ec.conversation_id=?")
            params.append(conversation_id)
        sql = "SELECT DISTINCT e.* FROM events e " + " ".join(joins)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY COALESCE(e.started_at,'') DESC LIMIT ?"
        params.append(limit)
        return [dict(row) for row in self._connection.execute(sql, params)]

    def list_conversations(self, *, active_only: bool = False, limit: int = 500) -> list[dict]:
        clause = "WHERE status='active'" if active_only else ""
        return [dict(row) for row in self._connection.execute(
            f"SELECT * FROM conversations {clause} ORDER BY last_seen_at DESC LIMIT ?", (limit,)
        )]

    def get_conversation(self, conversation_id: str) -> dict | None:
        row = self._connection.execute(
            "SELECT * FROM conversations WHERE conversation_id=?", (conversation_id,)
        ).fetchone()
        return dict(row) if row else None

    def person_conversations(self, person_id: str) -> list[dict]:
        return [dict(row) for row in self._connection.execute("""
            SELECT c.*,cm.role,cm.valid_from,cm.valid_to
            FROM conversation_members cm JOIN conversations c
              ON c.conversation_id=cm.conversation_id
            WHERE cm.person_id=? ORDER BY c.last_seen_at DESC
        """, (person_id,))]

    def list_people(self, *, active_only: bool = False, limit: int = 500) -> list[dict]:
        clause = "WHERE status='active'" if active_only else ""
        return [dict(row) for row in self._connection.execute(
            f"SELECT * FROM people {clause} ORDER BY last_seen_at DESC LIMIT ?", (limit,)
        )]

    def input_fingerprint(self, scope_type: str, scope_id: str, period: str,
                          evidence_ids: Iterable[str], template_version: str,
                          correction_ids: Iterable[str] = ()) -> str:
        payload = "\x1f".join((scope_type, scope_id, period, template_version,
                                *sorted(set(map(str, evidence_ids))),
                                *sorted(set(map(str, correction_ids)))))
        return hashlib.sha256(payload.encode("utf-8", "surrogatepass")).hexdigest()

    def current_version(self, scope_type: str, scope_id: str, period: str = "") -> dict | None:
        row = self._connection.execute("""
            SELECT * FROM analysis_versions WHERE scope_type=? AND scope_id=? AND period=?
            AND status='current' ORDER BY version DESC LIMIT 1
        """, (scope_type, scope_id, period)).fetchone()
        return dict(row) if row else None

    def record_version(self, scope_type: str, scope_id: str, period: str, *,
                       content_hash: str, markdown_path: str, input_fingerprint: str,
                       expected_parent: int | None = None) -> int:
        current = self.current_version(scope_type, scope_id, period)
        parent = int(current["version"]) if current else None
        if expected_parent is not None and (parent or 0) != expected_parent:
            raise RuntimeError(f"stale parent version: expected {expected_parent}, current {parent}")
        if current and current["content_hash"] == content_hash and current["input_fingerprint"] == input_fingerprint:
            return parent or 1
        version = (parent or 0) + 1
        now = _now()
        with self._connection:
            self._connection.execute(
                "UPDATE analysis_versions SET status='superseded' WHERE scope_type=? AND scope_id=? "
                "AND period=? AND status='current'", (scope_type, scope_id, period),
            )
            self._connection.execute("""
                INSERT INTO analysis_versions VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (scope_type, scope_id, period, version, parent, content_hash,
                  markdown_path, input_fingerprint, "current", now))
            self._connection.execute(
                "INSERT OR IGNORE INTO input_fingerprints VALUES(?,?,?,?,?)",
                (scope_type, scope_id, period, input_fingerprint, now),
            )
        return version

    def start_run(self, scope_type: str, scope_id: str, period: str,
                  input_fingerprint: str, *, mode: str = "incremental") -> str:
        run_id = _short_id("r")
        current = self.current_version(scope_type, scope_id, period)
        self._connection.execute(
            "INSERT INTO analysis_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, scope_type, scope_id, period, mode, "running", input_fingerprint,
             current["version"] if current else None, None, _now(), None, ""),
        )
        self._connection.commit()
        return run_id

    def complete_run(self, run_id: str, output_version: int) -> None:
        self._connection.execute(
            "UPDATE analysis_runs SET status='complete',output_version=?,completed_at=? WHERE run_id=?",
            (output_version, _now(), run_id),
        )
        self._connection.commit()

    def fail_run(self, run_id: str, error: str) -> None:
        self._connection.execute(
            "UPDATE analysis_runs SET status='failed',error=?,completed_at=? WHERE run_id=?",
            (error[:1000], _now(), run_id),
        )
        self._connection.commit()

    def update_coverage(self, scope_type: str, scope_id: str, period: str, *,
                        message_watermark: str = "", moment_watermark: str = "",
                        profile_watermark: str = "", evidence_count: int = 0,
                        input_fingerprint: str = "") -> None:
        self._connection.execute("""
            INSERT INTO analysis_coverage VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(scope_type,scope_id,period) DO UPDATE SET
              message_watermark=excluded.message_watermark,
              moment_watermark=excluded.moment_watermark,
              profile_watermark=excluded.profile_watermark,
              evidence_count=excluded.evidence_count,
              input_fingerprint=excluded.input_fingerprint,
              updated_at=excluded.updated_at
        """, (scope_type, scope_id, period, message_watermark, moment_watermark,
              profile_watermark, evidence_count, input_fingerprint, _now()))
        self._connection.commit()

    def mark_dirty(self, node_type: str, node_id: str, reason: str,
                   source_id: str = "") -> None:
        self._connection.execute(
            "INSERT OR IGNORE INTO dirty_nodes VALUES(?,?,?,?,?)",
            (node_type, node_id, reason, _now(), source_id),
        )
        self._connection.commit()

    def add_dependency(self, upstream_type: str, upstream_id: str,
                       downstream_type: str, downstream_id: str,
                       relation: str = "invalidates") -> None:
        self._connection.execute(
            "INSERT OR IGNORE INTO dependency_edges VALUES(?,?,?,?,?)",
            (upstream_type, upstream_id, downstream_type, downstream_id, relation),
        )
        self._connection.commit()

    def get_sync_cursor(self, source: str, stream_id: str) -> str:
        row = self._connection.execute(
            "SELECT cursor FROM sync_cursors WHERE source=? AND stream_id=?",
            (source, stream_id),
        ).fetchone()
        return str(row[0]) if row else ""

    def set_sync_cursor(self, source: str, stream_id: str, cursor: str | int) -> None:
        self._connection.execute("""
            INSERT INTO sync_cursors(source,stream_id,cursor,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(source,stream_id) DO UPDATE SET
              cursor=excluded.cursor,updated_at=excluded.updated_at
        """, (source, stream_id, str(cursor), _now()))
        self._connection.commit()

    def propagate_dirty(self, upstream_type: str, upstream_id: str, reason: str) -> list[dict]:
        queue = [(upstream_type, upstream_id)]
        visited = {(upstream_type, upstream_id)}
        result = []
        while queue:
            current_type, current_id = queue.pop(0)
            rows = self._connection.execute(
                "SELECT downstream_type,downstream_id FROM dependency_edges "
                "WHERE upstream_type=? AND upstream_id=?", (current_type, current_id)
            ).fetchall()
            for row in rows:
                key = (str(row[0]), str(row[1]))
                if key in visited:
                    continue
                visited.add(key)
                self.mark_dirty(key[0], key[1], reason, f"{current_type}:{current_id}")
                result.append({"node_type": key[0], "node_id": key[1]})
                queue.append(key)
        return result

    def enqueue_job(self, job_type: str, scope_type: str, scope_id: str, *,
                    period: str = "", priority: int = 0, input_fingerprint: str = "") -> str:
        existing = self._connection.execute("""
            SELECT job_id,status FROM analysis_jobs WHERE job_type=? AND scope_type=? AND scope_id=?
              AND period=? AND input_fingerprint=?
        """, (job_type, scope_type, scope_id, period, input_fingerprint)).fetchone()
        if existing:
            if existing["status"] not in {"pending", "running"}:
                now = _now()
                self._connection.execute("""
                    UPDATE analysis_jobs SET status='pending',priority=?,available_at=?,updated_at=?
                    WHERE job_id=?
                """, (priority, now, now, existing["job_id"]))
                self._connection.commit()
            return str(existing["job_id"])
        job_id = _short_id("j")
        now = _now()
        self._connection.execute(
            "INSERT INTO analysis_jobs VALUES(?,?,?,?,?,?,?,?,0,?,?,?)",
            (job_id, job_type, scope_type, scope_id, period, priority, "pending",
             input_fingerprint, now, now, now),
        )
        self._connection.commit()
        return job_id

    def complete_job(self, job_id: str, *, success: bool, error: str = "") -> None:
        status = "complete" if success else "failed"
        self._connection.execute(
            "UPDATE analysis_jobs SET status=?,updated_at=? WHERE job_id=?",
            (status, _now(), job_id),
        )
        self._connection.commit()

    def add_user_correction(self, target_type: str, target_id: str,
                            correction_text: str) -> str:
        if not correction_text.strip():
            raise ValueError("correction_text must not be empty")
        correction_id = _short_id("uc")
        self._connection.execute(
            "INSERT INTO user_corrections(correction_id,target_type,target_id,correction_text,created_at) "
            "VALUES(?,?,?,?,?)",
            (correction_id, target_type, target_id, correction_text.strip(), _now()),
        )
        self._connection.commit()
        self.mark_dirty(target_type, target_id, "user_correction", correction_id)
        return correction_id

    def next_jobs(self, limit: int = 20) -> list[dict]:
        rows = self._connection.execute("""
            SELECT * FROM analysis_jobs WHERE status='pending' AND available_at<=?
            ORDER BY priority DESC,created_at LIMIT ?
        """, (_now(), limit)).fetchall()
        return [dict(row) for row in rows]

    def claim_next_job(self, *, worker_id: str = "agent") -> dict | None:
        now = _now()
        with self._connection:
            row = self._connection.execute("""
                SELECT * FROM analysis_jobs WHERE status='pending' AND available_at<=?
                ORDER BY priority DESC,created_at LIMIT 1
            """, (now,)).fetchone()
            if row is None:
                return None
            changed = self._connection.execute("""
                UPDATE analysis_jobs SET status='running',attempts=attempts+1,updated_at=?
                WHERE job_id=? AND status='pending'
            """, (now, row["job_id"])).rowcount
            if changed != 1:
                return None
        result = dict(row)
        result["status"] = "running"
        result["attempts"] = int(result["attempts"]) + 1
        result["worker_id"] = worker_id
        return result

    def observe_presence(self, entity_type: str, entity_id: str, *, present: bool,
                         observed_at: str | None = None, snapshot_key: str = "") -> str:
        now = observed_at or _now()
        if snapshot_key:
            existing = self._connection.execute(
                "SELECT status FROM entity_status_events WHERE entity_type=? AND entity_id=? "
                "AND snapshot_key=?", (entity_type, entity_id, snapshot_key),
            ).fetchone()
            if existing:
                return str(existing[0])
        row = self._connection.execute(
            "SELECT * FROM entity_presence WHERE entity_type=? AND entity_id=?",
            (entity_type, entity_id),
        ).fetchone()
        if present:
            old_status = str(row["status"]) if row else "unknown"
            status = "restored" if old_status in {"missing", "inferred_removed", "confirmed_removed"} else "active"
            missing_count, first_missing = 0, None
        else:
            missing_count = (int(row["missing_count"]) if row else 0) + 1
            first_missing = (row["first_missing_at"] if row else None) or now
            elapsed = 0
            try:
                elapsed = (datetime.fromisoformat(now) - datetime.fromisoformat(first_missing)).total_seconds()
            except (TypeError, ValueError):
                pass
            status = "inferred_removed" if missing_count >= 3 and elapsed >= 86400 else "missing"
        with self._connection:
            self._connection.execute("""
                INSERT INTO entity_presence VALUES(?,?,?,?,?,?)
                ON CONFLICT(entity_type,entity_id) DO UPDATE SET
                  missing_count=excluded.missing_count,first_missing_at=excluded.first_missing_at,
                  last_checked_at=excluded.last_checked_at,status=excluded.status
            """, (entity_type, entity_id, missing_count, first_missing, now, status))
            event_key = snapshot_key or f"{now}:{missing_count}"
            self._connection.execute("""
                INSERT OR IGNORE INTO entity_status_events
                VALUES(?,?,?,?,?,?,?,?,?)
            """, (_short_id("se"), entity_type, entity_id, status, now, "snapshot_diff",
                  .75 if status == "inferred_removed" else 1, "presence_snapshot", event_key))
            table = {"person": ("people", "person_id"),
                     "conversation": ("conversations", "conversation_id"),
                     "group": ("groups", "group_id")}.get(entity_type)
            if table:
                persisted = "active" if status in {"active", "restored"} else status
                self._connection.execute(
                    f"UPDATE {table[0]} SET status=?,updated_at=? WHERE {table[1]}=?",
                    (persisted, now, entity_id),
                )
        return status

    def reconcile_snapshot(self, entity_type: str, entity_ids: Iterable[str], *,
                           observed_at: str | None = None, source: str = "wechat_db",
                           complete: bool = True, snapshot_id: str | None = None,
                           baseline_ids: Iterable[str] = ()) -> dict:
        """Compare one complete entity snapshot and apply the conservative missing policy."""
        now = observed_at or _now()
        snapshot_id = snapshot_id or _short_id("ss")
        current = {str(value) for value in entity_ids if str(value)}
        duplicate = self._connection.execute(
            "SELECT * FROM entity_snapshots WHERE snapshot_id=?", (snapshot_id,),
        ).fetchone()
        if duplicate:
            saved = {str(row[0]) for row in self._connection.execute(
                "SELECT entity_id FROM entity_snapshot_members WHERE snapshot_id=?", (snapshot_id,))}
            if (saved != current or duplicate['entity_type'] != entity_type
                    or duplicate['source'] != source or bool(duplicate['complete']) != complete):
                raise ValueError('Snapshot ID reused with different content')
            statuses = {row['entity_id']: row['status'] for row in self._connection.execute(
                "SELECT entity_id,status FROM entity_status_events WHERE snapshot_key=?", (snapshot_id,))}
            return {'snapshot_id': snapshot_id, 'seen': len(current),
                    'missing': sum(s in {'missing', 'inferred_removed'} for s in statuses.values()),
                    'statuses': statuses, 'complete': complete, 'duplicate': True}
        previous_row = self._connection.execute("""
            SELECT snapshot_id FROM entity_snapshots
            WHERE entity_type=? AND complete=1 ORDER BY observed_at DESC,rowid DESC LIMIT 1
        """, (entity_type,)).fetchone()
        previous = {str(value) for value in baseline_ids if str(value)}
        if previous_row:
            previous = {str(row[0]) for row in self._connection.execute(
                "SELECT entity_id FROM entity_snapshot_members WHERE snapshot_id=?",
                (previous_row[0],),
            )}
        with self._connection:
            self._connection.execute(
                "INSERT INTO entity_snapshots VALUES(?,?,?,?,?)",
                (snapshot_id, entity_type, now, source, int(complete)),
            )
            self._connection.executemany(
                "INSERT INTO entity_snapshot_members VALUES(?,?)",
                [(snapshot_id, item) for item in sorted(current)],
            )
        statuses = {item: self.observe_presence(
            entity_type, item, present=True, observed_at=now, snapshot_key=snapshot_id
        ) for item in current} if complete else {}
        # Keep checking previously missing entities, even after they disappear
        # from the immediately previous complete snapshot.
        previous.update(str(row[0]) for row in self._connection.execute(
            "SELECT entity_id FROM entity_presence WHERE entity_type=? AND status IN "
            "('missing','inferred_removed')", (entity_type,)))
        missing = previous - current if complete else set()
        statuses.update({item: self.observe_presence(
            entity_type, item, present=False, observed_at=now, snapshot_key=snapshot_id
        ) for item in missing})
        return {"snapshot_id": snapshot_id, "seen": len(current), "missing": len(missing),
                "statuses": statuses, "complete": bool(complete)}

    def create_reply_draft(self, conversation_id: str, trigger_evidence_id: str,
                           text: str, context_fingerprint: str,
                           expires_at: str | None = None) -> str:
        if not text.strip():
            raise ValueError("draft text must not be empty")
        draft_id = _short_id("d")
        self._connection.execute(
            "INSERT INTO reply_drafts(draft_id,conversation_id,trigger_evidence_id,text,context_fingerprint,created_at,expires_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (draft_id, conversation_id, trigger_evidence_id, text, context_fingerprint, _now(), expires_at),
        )
        self._connection.commit()
        return draft_id

    def create_pending_action(self, action_type: str, target_id: str, payload: dict,
                              expires_at: str | None = None) -> str:
        if not action_type or not target_id:
            raise ValueError("action_type and target_id are required")
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        action_id = _short_id("a")
        self._connection.execute(
            "INSERT INTO pending_actions(action_id,action_type,target_id,payload_json,payload_hash,"
            "created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
            (action_id, action_type, target_id, serialized,
             hashlib.sha256(serialized.encode("utf-8")).hexdigest(), _now(), expires_at),
        )
        self._connection.commit()
        return action_id

    def confirm_pending_action(self, action_id: str) -> str:
        row = self._connection.execute(
            "SELECT status,expires_at FROM pending_actions WHERE action_id=?", (action_id,)
        ).fetchone()
        if row is None or row["status"] != "pending":
            raise ValueError("action is missing or not pending")
        if row["expires_at"] and str(row["expires_at"]) < _now():
            raise PermissionError("action confirmation has expired")
        confirmation_id = _short_id("acf")
        self._connection.execute(
            "UPDATE pending_actions SET status='confirmed',confirmation_id=?,confirmed_at=? "
            "WHERE action_id=?", (confirmation_id, _now(), action_id),
        )
        self._connection.commit()
        return confirmation_id

    def consume_pending_action(self, action_id: str, confirmation_id: str) -> dict:
        row = self._connection.execute(
            "SELECT * FROM pending_actions WHERE action_id=? AND confirmation_id=?",
            (action_id, confirmation_id),
        ).fetchone()
        if row is None or row["status"] != "confirmed":
            raise PermissionError("valid unconsumed action confirmation required")
        if row["expires_at"] and str(row["expires_at"]) < _now():
            raise PermissionError("action confirmation has expired")
        payload = json.loads(row["payload_json"])
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(serialized.encode("utf-8")).hexdigest() != row["payload_hash"]:
            raise PermissionError("stored action payload failed integrity validation")
        self._connection.execute(
            "UPDATE pending_actions SET status='dispatching' WHERE action_id=?", (action_id,)
        )
        self._connection.commit()
        return payload

    def finish_pending_action(self, action_id: str, *, succeeded: bool) -> None:
        self._connection.execute(
            "UPDATE pending_actions SET status=?,finished_at=? WHERE action_id=? AND status='dispatching'",
            ("complete" if succeeded else "failed", _now(), action_id),
        )
        self._connection.commit()

    def confirm_reply_draft(self, draft_id: str) -> str:
        row = self._connection.execute(
            "SELECT status,expires_at FROM reply_drafts WHERE draft_id=?", (draft_id,)
        ).fetchone()
        if row is None or row["status"] != "pending":
            raise ValueError("draft is missing or not pending")
        if row["expires_at"] and str(row["expires_at"]) < _now():
            raise PermissionError("draft confirmation has expired")
        confirmation_id = _short_id("cf")
        self._connection.execute(
            "UPDATE reply_drafts SET status='confirmed',confirmation_id=?,confirmed_at=? WHERE draft_id=?",
            (confirmation_id, _now(), draft_id),
        )
        self._connection.commit()
        return confirmation_id

    def consume_confirmation(self, confirmation_id: str, conversation_id: str, text: str) -> str:
        row = self._connection.execute(
            "SELECT * FROM reply_drafts WHERE confirmation_id=?", (confirmation_id,)
        ).fetchone()
        if row is None or row["status"] != "confirmed":
            raise PermissionError("valid unconsumed confirmation required")
        if row["conversation_id"] != conversation_id or row["text"] != text:
            raise PermissionError("confirmation does not match conversation and exact draft text")
        if row["expires_at"] and str(row["expires_at"]) < _now():
            raise PermissionError("confirmation has expired")
        self._connection.execute("UPDATE reply_drafts SET status='dispatching' WHERE draft_id=?",
                                 (row["draft_id"],))
        self._connection.commit()
        return str(row["draft_id"])

    def finish_reply_dispatch(self, draft_id: str, *, sent: bool) -> None:
        self._connection.execute(
            "UPDATE reply_drafts SET status=?,sent_at=? WHERE draft_id=? AND status='dispatching'",
            ("sent" if sent else "failed", _now() if sent else None, draft_id),
        )
        self._connection.commit()

    def database_summary(self) -> dict:
        names = ("people", "conversations", "claims", "events", "analysis_versions",
                 "relationships", "analysis_jobs", "dirty_nodes", "reply_drafts",
                 "pending_actions")
        return {name: int(self._connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                for name in names}
