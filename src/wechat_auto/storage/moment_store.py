"""Offline SQLite storage for locally read WeChat Moments metadata."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from collections.abc import Iterable


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

    def existing_ids(self, ids: Iterable[str]) -> set[str]:
        values = [str(item) for item in ids if item]
        if not values:
            return set()
        marks = ",".join("?" for _ in values)
        rows = self._connection.execute(f"SELECT id FROM moments WHERE id IN ({marks})", values)
        return {str(row[0]) for row in rows}
