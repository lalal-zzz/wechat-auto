"""Offline SQLite storage for locally read WeChat Moments metadata."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

MOMENT_COLUMNS = ('id', 'username', 'nickname', 'create_time', 'text', 'images_json',
                  'videos_json', 'likes_json', 'comments_json', 'raw_json')


class MomentStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        try:
            self._initialize()
        except BaseException:
            try:
                self._connection.rollback()
            finally:
                self._connection.close()
            raise

    def _initialize(self):
        self._connection.execute('BEGIN IMMEDIATE')
        self._connection.execute("""
            CREATE TABLE IF NOT EXISTS moments (
                id TEXT PRIMARY KEY, username TEXT NOT NULL, nickname TEXT,
                create_time INTEGER, text TEXT, images_json TEXT NOT NULL,
                videos_json TEXT NOT NULL, likes_json TEXT NOT NULL,
                comments_json TEXT NOT NULL, raw_json TEXT NOT NULL
            )
        """)
        self._connection.execute("CREATE INDEX IF NOT EXISTS idx_moments_user_time ON moments(username, create_time)")
        self._connection.execute('''CREATE TABLE IF NOT EXISTS message_media (
            media_id TEXT PRIMARY KEY, moment_id TEXT NOT NULL, kind TEXT NOT NULL,
            content BLOB NOT NULL, sha256 TEXT NOT NULL, source TEXT NOT NULL,
            archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        self._initialize_versions()
        self._connection.commit()

    def _initialize_versions(self):
        self._connection.execute("""CREATE TABLE IF NOT EXISTS moment_versions (
            version_id INTEGER PRIMARY KEY AUTOINCREMENT,
            observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            verification_status TEXT NOT NULL DEFAULT 'observed',
            id TEXT NOT NULL, username TEXT NOT NULL, nickname TEXT, create_time INTEGER,
            text TEXT, images_json TEXT NOT NULL, videos_json TEXT NOT NULL,
            likes_json TEXT NOT NULL, comments_json TEXT NOT NULL, raw_json TEXT NOT NULL
        )""")
        self._connection.execute('CREATE INDEX IF NOT EXISTS idx_moment_versions_id ON moment_versions(id,version_id)')
        self._connection.execute('CREATE TABLE IF NOT EXISTS moment_store_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        columns = ','.join(MOMENT_COLUMNS)
        if not self._connection.execute("SELECT 1 FROM moment_store_meta WHERE key='versions_v1'").fetchone():
            self._connection.execute(f"""INSERT INTO moment_versions({columns},verification_status)
                SELECT {columns},'legacy_baseline' FROM moments ORDER BY rowid""")
            self._connection.execute("INSERT INTO moment_store_meta VALUES('versions_v1','complete')")
        new_columns = ','.join('NEW.'+column for column in MOMENT_COLUMNS)
        self._connection.execute(f"""CREATE TRIGGER IF NOT EXISTS moment_capture_insert AFTER INSERT ON moments
            BEGIN INSERT INTO moment_versions({columns}) VALUES({new_columns}); END""")
        different = ' OR '.join('OLD.'+column+' IS NOT NEW.'+column for column in MOMENT_COLUMNS)
        self._connection.execute(f"""CREATE TRIGGER IF NOT EXISTS moment_capture_update AFTER UPDATE ON moments
            WHEN {different} BEGIN INSERT INTO moment_versions({columns}) VALUES({new_columns}); END""")
        self._connection.execute("""CREATE TRIGGER IF NOT EXISTS moment_identity_guard BEFORE UPDATE ON moments
            WHEN OLD.id IS NOT NEW.id OR OLD.username IS NOT NEW.username
                OR (OLD.create_time>0 AND NEW.create_time IS NOT OLD.create_time)
            BEGIN SELECT RAISE(ABORT,'Moment identity or creation time cannot change'); END""")
        for operation in ('UPDATE', 'DELETE'):
            self._connection.execute(f"""CREATE TRIGGER IF NOT EXISTS moment_versions_no_{operation.lower()}
                BEFORE {operation} ON moment_versions
                BEGIN SELECT RAISE(ABORT,'Moment versions are append-only'); END""")


    def save_media(self, media_id: str, moment_id: str, kind: str, content: bytes, *, source: str = 'exact_local_cache') -> None:
        import hashlib

        if not content or kind not in {'image', 'video'} or self.get(moment_id) is None:
            raise ValueError('Known Moment and nonempty image/video content required')
        changed = self._connection.execute('''INSERT INTO message_media(media_id,moment_id,kind,content,sha256,source)
            VALUES(?,?,?,?,?,?) ON CONFLICT(media_id) DO UPDATE SET
            content=excluded.content,sha256=excluded.sha256,source=excluded.source
            WHERE message_media.moment_id=excluded.moment_id AND message_media.kind=excluded.kind''',
            (media_id, moment_id, kind, content, hashlib.sha256(content).hexdigest(), source))
        self._connection.commit()
        if changed.rowcount != 1:
            raise ValueError('Media ID already belongs to a different Moment or media kind')

    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def save(self, feeds: Iterable[dict]) -> int:
        return self.save_with_new_ids(feeds)[0]

    def save_with_new_ids(self, feeds: Iterable[dict]) -> tuple[int, set[str]]:
        """Return changed rows and IDs inserted by this committed batch only."""
        rows = []
        for feed in feeds:
            if not isinstance(feed, dict):
                raise TypeError('Moment input must be a dictionary')
            value = feed.get('id') or feed.get('tid')
            username = feed.get('username')
            if (isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip()
                    or isinstance(value, int) and value <= 0
                    or not isinstance(username, str) or not username.strip()
                    or username.strip().endswith('@chatroom')):
                raise ValueError('Each Moment requires a stable id and author username')
            ident, username = str(value).strip(), username.strip()
            creation = feed.get('create_time', 0)
            if isinstance(creation, bool):
                raise TypeError('Moment creation time must not be a boolean')
            created = int(creation or 0)
            if isinstance(creation, float) and creation != created:
                raise ValueError('Moment creation time must not lose fractional precision')
            if created < 0:
                raise ValueError('Moment creation time must not be negative')
            rows.append((ident, username, str(feed.get('nickname', '')), created,
                         str(feed.get('text', '')), json.dumps(feed.get('images', []), ensure_ascii=False, sort_keys=True),
                         json.dumps(feed.get('videos', []), ensure_ascii=False, sort_keys=True),
                         json.dumps(feed.get('likes', []), ensure_ascii=False, sort_keys=True),
                         json.dumps(feed.get('comments', []), ensure_ascii=False, sort_keys=True),
                         json.dumps(feed, ensure_ascii=False, sort_keys=True, default=str)))
        if not rows:
            return 0, set()
        if self._connection.in_transaction:
            raise RuntimeError('Moment batch requires an idle connection')
        changed = 0
        inserted = set()
        with self._connection:
            self._connection.execute('BEGIN IMMEDIATE')
            for row in rows:
                previous = self._connection.execute('SELECT username,create_time FROM moments WHERE id=?',
                                                    (row[0],)).fetchone()
                if previous:
                    if previous[0] != row[1]:
                        raise ValueError('Moment ID already belongs to a different author')
                    if previous[1] and row[3] and previous[1] != row[3]:
                        raise ValueError('Moment ID has conflicting creation time')
                else:
                    inserted.add(row[0])
                write = self._connection.execute("""
                    INSERT INTO moments(id,username,nickname,create_time,text,images_json,videos_json,likes_json,comments_json,raw_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                      nickname=excluded.nickname,
                      create_time=CASE WHEN moments.create_time IS NULL OR moments.create_time=0
                                       THEN excluded.create_time ELSE moments.create_time END,
                      text=excluded.text, images_json=excluded.images_json,
                      videos_json=excluded.videos_json, likes_json=excluded.likes_json,
                      comments_json=excluded.comments_json, raw_json=excluded.raw_json
                    WHERE moments.nickname IS NOT excluded.nickname OR moments.text IS NOT excluded.text
                      OR moments.images_json IS NOT excluded.images_json OR moments.videos_json IS NOT excluded.videos_json
                      OR moments.likes_json IS NOT excluded.likes_json OR moments.comments_json IS NOT excluded.comments_json
                      OR moments.raw_json IS NOT excluded.raw_json
                      OR ((moments.create_time IS NULL OR moments.create_time=0) AND excluded.create_time>0)
                """, row)
                changed += write.rowcount
        return changed, inserted

    def fetch(self, username: str, limit: int = 20) -> list[dict]:
        rows = self._connection.execute("""
            SELECT id,username,nickname,create_time,text,images_json,videos_json,likes_json,comments_json
            FROM moments WHERE username=? ORDER BY create_time DESC LIMIT ?
        """, (username, limit))
        return [{"id": r[0], "username": r[1], "nickname": r[2], "create_time": r[3], "text": r[4],
                 "images": json.loads(r[5]), "videos": json.loads(r[6]), "likes": json.loads(r[7]),
                 "comments": json.loads(r[8])} for r in rows]

    def get(self, moment_id: str) -> dict | None:
        row = self._connection.execute("""
            SELECT id,username,nickname,create_time,text,images_json,videos_json,likes_json,comments_json
            FROM moments WHERE id=?
        """, (moment_id,)).fetchone()
        if row is None:
            return None
        return {"id": row[0], "username": row[1], "nickname": row[2],
                "create_time": row[3], "text": row[4], "images": json.loads(row[5]),
                "videos": json.loads(row[6]), "likes": json.loads(row[7]),
                "comments": json.loads(row[8])}

    def get_version(self, version_id: int) -> dict | None:
        from wechat_auto.utils.moment_reference import (
            VERSION_COLUMNS,
            moment_version_hash,
            validate_moment_subject,
        )

        values = self._connection.execute('SELECT * FROM moment_versions WHERE version_id=?', (version_id,)).fetchone()
        if values is None:
            return None
        row = dict(zip(VERSION_COLUMNS, values, strict=True))
        validate_moment_subject(row)
        item = {key: row[key] for key in ('version_id', 'observed_at', 'verification_status',
                                         'id', 'username', 'nickname', 'create_time', 'text')}
        for key in ('images', 'videos', 'likes', 'comments'):
            item[key] = json.loads(row[key+'_json'])
        item['content_hash'] = moment_version_hash(row)
        return item

    def existing_ids(self, ids: Iterable[str]) -> set[str]:
        values = [str(item) for item in ids if item]
        if not values:
            return set()
        marks = ",".join("?" for _ in values)
        rows = self._connection.execute(f"SELECT id FROM moments WHERE id IN ({marks})", values)
        return {str(row[0]) for row in rows}
