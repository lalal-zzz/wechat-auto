"""Offline SQLite storage for normalized WeChat profile snapshots and history."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


class ProfileStore:
    """Store profile text and media references without downloading media."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                profile_type TEXT NOT NULL, wechat_id TEXT NOT NULL,
                name TEXT, nickname TEXT, remark TEXT, signature TEXT,
                alias TEXT, original_name TEXT, display_name TEXT,
                nickname_prefix TEXT, nickname_core TEXT, nickname_suffix TEXT,
                group_id TEXT, group_display_name TEXT, avatar_ref TEXT,
                avatar_md5 TEXT, background_image_ref TEXT,
                raw_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(profile_type, wechat_id)
            )
        """)
        self._ensure_columns("profiles", {
            "alias": "TEXT", "original_name": "TEXT", "display_name": "TEXT",
            "nickname_prefix": "TEXT", "nickname_core": "TEXT", "nickname_suffix": "TEXT",
            "group_id": "TEXT", "group_display_name": "TEXT", "avatar_md5": "TEXT",
        })
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS profile_snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_type TEXT NOT NULL, wechat_id TEXT NOT NULL,
                captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                profile_json TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'unknown'
            )
        """)
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS profile_changes (
                change_id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_type TEXT NOT NULL, wechat_id TEXT NOT NULL,
                field_name TEXT NOT NULL, old_value TEXT, new_value TEXT,
                detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                source TEXT NOT NULL DEFAULT 'unknown', snapshot_id INTEGER
            )
        """)
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_profile_snapshots_person "
            "ON profile_snapshots(profile_type, wechat_id, captured_at)"
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_profile_changes_person "
            "ON profile_changes(profile_type, wechat_id, detected_at)"
        )
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS profile_media (
                profile_type TEXT NOT NULL, wechat_id TEXT NOT NULL,
                media_kind TEXT NOT NULL, content BLOB NOT NULL,
                sha256 TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'unknown',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(profile_type, wechat_id, media_kind)
            )
        """)
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS profile_watchlist (
                wechat_id TEXT PRIMARY KEY, contact_query TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_observed_at TEXT, last_observation_status TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._connection.commit()

    def _ensure_columns(self, table: str, columns: dict[str, str]) -> None:
        existing = {row[1] for row in self._connection.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                self._connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def save(self, profile: dict, *, profile_type: str) -> dict:
        if profile_type not in {"self", "contact", "group_member"}:
            raise ValueError("profile_type must be 'self', 'contact' or 'group_member'")
        wechat_id = str(profile.get("wechat_id", "")).strip()
        if not wechat_id:
            raise ValueError("profile requires wechat_id")
        fields = (
            "name", "nickname", "remark", "signature", "alias", "original_name",
            "display_name", "nickname_prefix", "nickname_core", "nickname_suffix",
            "group_id", "group_display_name", "avatar", "avatar_md5", "background_image",
        )
        current = self.get(wechat_id, profile_type=profile_type)
        changed = []
        for field in fields:
            old = "" if current is None else str(current.get(field, "") or "")
            new = str(profile.get(field, "") or "")
            if old != new:
                changed.append((field, old, new))
        payload = dict(profile)
        payload["profile_type"] = profile_type
        payload["wechat_id"] = wechat_id
        source = str(profile.get("source", "unknown"))
        cursor = self._connection.execute("""
            INSERT INTO profile_snapshots(profile_type,wechat_id,profile_json,source)
            VALUES(?,?,?,?)
        """, (profile_type, wechat_id,
               json.dumps(payload, ensure_ascii=False, sort_keys=True), source))
        snapshot_id = int(cursor.lastrowid)
        self._connection.execute("""
            INSERT INTO profiles(profile_type,wechat_id,name,nickname,remark,signature,
                                 alias,original_name,display_name,nickname_prefix,nickname_core,
                                 nickname_suffix,group_id,group_display_name,avatar_ref,avatar_md5,
                                 background_image_ref,raw_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(profile_type,wechat_id) DO UPDATE SET
              name=excluded.name, nickname=excluded.nickname, remark=excluded.remark,
              signature=excluded.signature, alias=excluded.alias, original_name=excluded.original_name,
              display_name=excluded.display_name, nickname_prefix=excluded.nickname_prefix,
              nickname_core=excluded.nickname_core, nickname_suffix=excluded.nickname_suffix,
              group_id=excluded.group_id, group_display_name=excluded.group_display_name,
              avatar_ref=excluded.avatar_ref, avatar_md5=excluded.avatar_md5,
              background_image_ref=excluded.background_image_ref,
              raw_json=excluded.raw_json, updated_at=CURRENT_TIMESTAMP
        """, (profile_type, wechat_id, profile.get("name", ""), profile.get("nickname", ""),
               profile.get("remark", ""), profile.get("signature", ""), profile.get("alias", ""),
               profile.get("original_name", ""), profile.get("display_name", ""),
               profile.get("nickname_prefix", ""), profile.get("nickname_core", ""),
               profile.get("nickname_suffix", ""), profile.get("group_id", ""),
               profile.get("group_display_name", ""), profile.get("avatar", ""),
               profile.get("avatar_md5", ""), profile.get("background_image", ""),
               json.dumps(profile.get("raw", {}), ensure_ascii=False, sort_keys=True)))
        self._connection.executemany("""
            INSERT INTO profile_changes(profile_type,wechat_id,field_name,old_value,new_value,source,snapshot_id)
            VALUES(?,?,?,?,?,?,?)
        """, [(profile_type, wechat_id, field, old, new, source, snapshot_id)
               for field, old, new in changed])
        self._connection.commit()
        return {"profile_type": profile_type, "wechat_id": wechat_id,
                "snapshot_id": snapshot_id, "changed_fields": [item[0] for item in changed]}

    def get(self, wechat_id: str, *, profile_type: str = "contact") -> dict | None:
        row = self._connection.execute("""
            SELECT profile_type,wechat_id,name,nickname,remark,signature,alias,original_name,
                   display_name,nickname_prefix,nickname_core,nickname_suffix,group_id,
                   group_display_name,avatar_ref,avatar_md5,background_image_ref,raw_json,updated_at
            FROM profiles WHERE profile_type=? AND wechat_id=?
        """, (profile_type, wechat_id)).fetchone()
        if row is None:
            return None
        keys = ("profile_type", "wechat_id", "name", "nickname", "remark", "signature",
                "alias", "original_name", "display_name", "nickname_prefix", "nickname_core",
                "nickname_suffix", "group_id", "group_display_name", "avatar", "avatar_md5",
                "background_image", "raw", "updated_at")
        result = dict(zip(keys, row))
        result["raw"] = json.loads(result["raw"])
        return result

    def history(self, wechat_id: str, *, profile_type: str = "contact", limit: int = 100) -> list[dict]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        rows = self._connection.execute("""
            SELECT snapshot_id,captured_at,profile_json,source
            FROM profile_snapshots
            WHERE profile_type=? AND wechat_id=?
            ORDER BY snapshot_id DESC LIMIT ?
        """, (profile_type, wechat_id, limit)).fetchall()
        return [{"snapshot_id": row[0], "captured_at": row[1],
                 "profile": json.loads(row[2]), "source": row[3]} for row in rows]

    def snapshot_by_id(self, snapshot_id: str | int) -> dict | None:
        row = self._connection.execute("""
            SELECT snapshot_id,profile_type,wechat_id,captured_at,profile_json,source
            FROM profile_snapshots WHERE snapshot_id=?
        """, (snapshot_id,)).fetchone()
        if row is None:
            return None
        return {"snapshot_id": row[0], "profile_type": row[1], "wechat_id": row[2],
                "captured_at": row[3], "profile": json.loads(row[4]), "source": row[5]}

    def changes(self, wechat_id: str, *, profile_type: str = "contact", limit: int = 100) -> list[dict]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        rows = self._connection.execute("""
            SELECT change_id,field_name,old_value,new_value,detected_at,source,snapshot_id
            FROM profile_changes
            WHERE profile_type=? AND wechat_id=?
            ORDER BY change_id DESC LIMIT ?
        """, (profile_type, wechat_id, limit)).fetchall()
        return [{"change_id": row[0], "field": row[1], "old": row[2], "new": row[3],
                 "detected_at": row[4], "source": row[5], "snapshot_id": row[6]}
                for row in rows]

    def save_media(self, wechat_id: str, data: bytes, *, media_kind: str = "avatar",
                   profile_type: str = "contact", source: str = "unknown") -> dict:
        """Save local-only profile media without network retrieval."""
        if profile_type not in {"self", "contact", "group_member"}:
            raise ValueError("unsupported profile type")
        if media_kind != "avatar":
            raise ValueError("unsupported profile media kind")
        if not wechat_id.strip() or not data:
            raise ValueError("profile media requires an id and nonempty data")
        digest = hashlib.sha256(data).hexdigest()
        previous = self._connection.execute("""
            SELECT sha256 FROM profile_media
            WHERE profile_type=? AND wechat_id=? AND media_kind=?
        """, (profile_type, wechat_id, media_kind)).fetchone()
        self._connection.execute("""
            INSERT INTO profile_media(profile_type,wechat_id,media_kind,content,sha256,source)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(profile_type,wechat_id,media_kind) DO UPDATE SET
              content=excluded.content, sha256=excluded.sha256,
              source=excluded.source, updated_at=CURRENT_TIMESTAMP
        """, (profile_type, wechat_id, media_kind, sqlite3.Binary(data), digest, source))
        self._connection.commit()
        return {"updated": previous is None or previous[0] != digest,
                "sha256": digest, "bytes": len(data)}

    def get_media(self, wechat_id: str, *, media_kind: str = "avatar",
                  profile_type: str = "contact") -> dict | None:
        """Read one locally archived profile blob; never fetch from network."""
        row = self._connection.execute("""
            SELECT content,sha256,source,updated_at FROM profile_media
            WHERE profile_type=? AND wechat_id=? AND media_kind=?
        """, (profile_type, wechat_id, media_kind)).fetchone()
        if row is None:
            return None
        return {"content": bytes(row[0]), "sha256": row[1],
                "source": row[2], "updated_at": row[3]}

    def watch_contact(self, wechat_id: str, contact_query: str) -> None:
        """Add/update one stable contact for profile-card observation."""
        if not wechat_id.strip() or not contact_query.strip():
            raise ValueError("watch entries require a WeChat id and contact query")
        self._connection.execute("""
            INSERT INTO profile_watchlist(wechat_id,contact_query,enabled)
            VALUES(?,?,1)
            ON CONFLICT(wechat_id) DO UPDATE SET
              contact_query=excluded.contact_query, enabled=1,
              updated_at=CURRENT_TIMESTAMP
        """, (wechat_id.strip(), contact_query.strip()))
        self._connection.commit()

    def disable_watched_contact(self, wechat_id: str, *, status: str = "disabled") -> bool:
        """Stop scheduled UI observations without deleting profile history."""
        if not wechat_id.strip():
            raise ValueError("watch entry requires a WeChat id")
        cursor = self._connection.execute("""
            UPDATE profile_watchlist
            SET enabled=0, last_observation_status=?, updated_at=CURRENT_TIMESTAMP
            WHERE wechat_id=? AND enabled=1
        """, (status, wechat_id.strip()))
        self._connection.commit()
        return cursor.rowcount == 1

    def watch_contact_by_display_name(self, query: str) -> None:
        """Add one uniquely resolved archived direct contact to the watchlist."""
        if not query.strip():
            raise ValueError("contact query must not be empty")
        rows = self._connection.execute("""
            SELECT wechat_id,display_name FROM profiles
            WHERE profile_type='contact'
              AND (wechat_id=? OR nickname=? OR remark=? OR alias=? OR display_name=?)
        """, (query, query, query, query, query)).fetchall()
        if len(rows) != 1:
            raise ValueError(f"Expected exactly one archived contact match; found {len(rows)}")
        self.watch_contact(str(rows[0][0]), str(rows[0][1] or query))

    def watched_contacts(self) -> list[dict]:
        rows = self._connection.execute("""
            SELECT wechat_id,contact_query,last_observed_at,last_observation_status
            FROM profile_watchlist WHERE enabled=1 ORDER BY wechat_id
        """).fetchall()
        return [{"wechat_id": row[0], "contact_query": row[1],
                 "last_observed_at": row[2], "last_observation_status": row[3]}
                for row in rows]

    def record_signature_observation(self, wechat_id: str, signature: str | None, *,
                                     source: str = "wechat_profile_card_ocr") -> dict:
        """Persist an OCR-observed signature without overwriting on a miss.

        ``None`` means that the label/value was not visible and records no
        profile mutation.  An empty string is a confirmed observation that the
        profile card has no signature, so it is recorded as a genuine change.
        """
        current = self.get(wechat_id, profile_type="contact")
        if current is None:
            raise ValueError("observe a contact only after its base profile is archived")
        if signature is None:
            status = "signature_not_visible"
            self._connection.execute("""
                UPDATE profile_watchlist
                SET last_observed_at=CURRENT_TIMESTAMP, last_observation_status=?,
                    updated_at=CURRENT_TIMESTAMP WHERE wechat_id=?
            """, (status, wechat_id))
            self._connection.commit()
            return {"observed": False, "status": status, "changed_fields": []}
        profile = {key: value for key, value in current.items()
                   if key not in {"profile_type", "updated_at"}}
        profile["signature"] = signature
        profile["source"] = source
        raw = dict(profile.get("raw", {}))
        raw["signature_observation"] = {"source": source, "value_observed": True}
        profile["raw"] = raw
        result = self.save(profile, profile_type="contact")
        status = "signature_observed"
        self._connection.execute("""
            UPDATE profile_watchlist
            SET last_observed_at=CURRENT_TIMESTAMP, last_observation_status=?,
                updated_at=CURRENT_TIMESTAMP WHERE wechat_id=?
        """, (status, wechat_id))
        self._connection.commit()
        return {"observed": True, "status": status, **result}
