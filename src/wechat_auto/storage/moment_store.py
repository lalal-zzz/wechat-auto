"""Offline SQLite storage for locally read WeChat Moments metadata."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path


class MomentStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
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
        self._connection.commit()

    def save_media(self, media_id: str, moment_id: str, kind: str, content: bytes, *, source: str = 'exact_local_cache') -> None:
        import hashlib

        if not content or kind not in {'image', 'video'} or self.get(moment_id) is None:
            raise ValueError('Known Moment and nonempty image/video content required')
        self._connection.execute('''INSERT INTO message_media(media_id,moment_id,kind,content,sha256,source)
            VALUES(?,?,?,?,?,?) ON CONFLICT(media_id) DO UPDATE SET
            content=excluded.content,sha256=excluded.sha256,source=excluded.source''',
            (media_id, moment_id, kind, content, hashlib.sha256(content).hexdigest(), source))
        self._connection.commit()

    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def save(self, feeds: Iterable[dict]) -> int:
        rows = []
        for feed in feeds:
            ident = str(feed.get("id") or feed.get("tid") or "")
            username = str(feed.get("username") or "")
            if not ident or not username:
                raise ValueError("Each moment requires id/tid and username")
            rows.append((ident, username, str(feed.get("nickname", "")), int(feed.get("create_time", 0) or 0),
                         str(feed.get("text", "")), json.dumps(feed.get("images", []), ensure_ascii=False),
                         json.dumps(feed.get("videos", []), ensure_ascii=False),
                         json.dumps(feed.get("likes", []), ensure_ascii=False),
                         json.dumps(feed.get("comments", []), ensure_ascii=False),
                         json.dumps(feed, ensure_ascii=False, default=str)))
        before = self._connection.total_changes
        self._connection.executemany("""
            INSERT INTO moments(id,username,nickname,create_time,text,images_json,videos_json,likes_json,comments_json,raw_json)
            VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
              nickname=excluded.nickname, text=excluded.text, images_json=excluded.images_json,
              videos_json=excluded.videos_json, likes_json=excluded.likes_json,
              comments_json=excluded.comments_json, raw_json=excluded.raw_json
        """, rows)
        self._connection.commit()
        return self._connection.total_changes - before

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

    def existing_ids(self, ids: Iterable[str]) -> set[str]:
        values = [str(item) for item in ids if item]
        if not values:
            return set()
        marks = ",".join("?" for _ in values)
        rows = self._connection.execute(f"SELECT id FROM moments WHERE id IN ({marks})", values)
        return {str(row[0]) for row in rows}
