"""Conversation-specific sticker preferences and verified HWND locations."""
from __future__ import annotations

import math
import sqlite3
import time
from pathlib import Path


class StickerPreferenceAnalyzer:
    """Rank stickers the user historically sent in one conversation."""

    def __init__(self, history_database: str | Path):
        self.path = Path(history_database).expanduser().resolve(strict=True)

    def recommend(self, username: str, *, intent: str = "", limit: int = 5,
                  now: int | None = None) -> list[dict]:
        if not username or limit <= 0:
            raise ValueError("username must be set and limit must be positive")
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute("""
                SELECT e.md5,e.product_id,e.hint,COUNT(*) AS uses,
                       MAX(CAST(m.create_time AS INTEGER)) AS last_used
                FROM emoji_semantics e
                JOIN messages m ON m.username=e.username AND m.local_id=e.local_id
                WHERE e.username=? AND e.direction='sent'
                  AND (e.md5<>'' OR e.product_id<>'')
                GROUP BY e.md5,e.product_id,e.hint
            """, (username,)).fetchall()
        if not rows:
            return []
        maximum = max(int(row[3]) for row in rows)
        current = int(now if now is not None else time.time())
        wanted = intent.strip().casefold()
        candidates = []
        for md5, product_id, hint, uses, last_used in rows:
            normalized_hint = (hint or "").strip()
            semantic = 0.0
            if wanted and normalized_hint:
                got = normalized_hint.casefold()
                semantic = 1.0 if got == wanted else (0.7 if wanted in got or got in wanted else 0.0)
            age_days = max(0.0, (current - int(last_used or 0)) / 86400)
            recency = math.exp(-age_days / 180.0)
            frequency = math.log1p(int(uses)) / math.log1p(maximum)
            score = .60 * frequency + .25 * recency + .15 * semantic
            candidates.append({
                "sticker_id": md5 or f"product:{product_id}",
                "md5": md5 or "", "product_id": product_id or "",
                "hint": normalized_hint, "uses": int(uses),
                "last_used": int(last_used or 0), "score": round(score, 6),
                "semantic_match": semantic,
            })
        candidates.sort(key=lambda item: (-item["score"], -item["uses"], item["sticker_id"]))
        return candidates[:limit]


class StickerCatalog:
    """Persist verified sticker-panel coordinates, separate from preferences."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS sticker_catalog(
                sticker_id TEXT PRIMARY KEY,
                hint TEXT NOT NULL,
                x REAL NOT NULL,
                y REAL NOT NULL,
                page_steps INTEGER NOT NULL DEFAULT 0,
                layout_width INTEGER NOT NULL,
                layout_height INTEGER NOT NULL,
                image_hash TEXT NOT NULL DEFAULT '',
                verified INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def register(self, sticker_id: str, *, hint: str, cell: tuple[float, float],
                 layout_size: tuple[int, int], page_steps: int = 0,
                 image_hash: str = "", verified: bool = False) -> None:
        x, y = cell
        width, height = layout_size
        if not sticker_id or not 0 <= x <= 1 or not 0 <= y <= 1:
            raise ValueError("sticker_id and normalized cell coordinates are required")
        if width <= 0 or height <= 0:
            raise ValueError("layout_size must be positive")
        self.connection.execute("""
            INSERT INTO sticker_catalog
                (sticker_id,hint,x,y,page_steps,layout_width,layout_height,image_hash,verified)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(sticker_id) DO UPDATE SET
                hint=excluded.hint,x=excluded.x,y=excluded.y,
                page_steps=excluded.page_steps,layout_width=excluded.layout_width,
                layout_height=excluded.layout_height,image_hash=excluded.image_hash,
                verified=excluded.verified,updated_at=CURRENT_TIMESTAMP
        """, (sticker_id, hint, x, y, int(page_steps), width, height,
              image_hash, int(verified)))
        self.connection.commit()

    def resolve(self, sticker_id: str, *, require_verified: bool = True) -> dict | None:
        row = self.connection.execute("""
            SELECT sticker_id,hint,x,y,page_steps,layout_width,layout_height,
                   image_hash,verified FROM sticker_catalog WHERE sticker_id=?
        """, (sticker_id,)).fetchone()
        if row is None or (require_verified and not row[8]):
            return None
        return {"sticker_id": row[0], "hint": row[1], "cell": (row[2], row[3]),
                "page_steps": row[4], "layout_size": (row[5], row[6]),
                "image_hash": row[7], "verified": bool(row[8])}
