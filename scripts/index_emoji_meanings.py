"""Build a local semantic index for type-47 emoji messages."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wechat_auto.storage.emoji_metadata import parse_emoji_metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "database", nargs="?", default="data/wechat_history_full.sqlite3"
    )
    args = parser.parse_args()
    path = Path(args.database).resolve(strict=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS emoji_semantics(
                username TEXT NOT NULL,
                local_id INTEGER NOT NULL,
                direction TEXT NOT NULL,
                hint TEXT NOT NULL,
                hint_source TEXT NOT NULL,
                md5 TEXT NOT NULL,
                product_id TEXT NOT NULL,
                width TEXT NOT NULL,
                height TEXT NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY(username, local_id)
            )
        """)
        rows = connection.execute("""
            SELECT username,local_id,sender_id,content FROM messages
            WHERE (type_code % 256)=47
        """).fetchall()
        records = []
        for username, local_id, sender_id, content in rows:
            item = parse_emoji_metadata(content)
            records.append((
                username, local_id,
                "sent" if str(sender_id) == "2" else "received",
                item["hint"], item["hint_source"], item["md5"],
                item["product_id"], item.get("width", ""), item.get("height", ""),
                "metadata_hint" if item["hint"] else "unknown",
            ))
        connection.executemany("""
            INSERT INTO emoji_semantics VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(username,local_id) DO UPDATE SET
                direction=excluded.direction, hint=excluded.hint,
                hint_source=excluded.hint_source, md5=excluded.md5,
                product_id=excluded.product_id, width=excluded.width,
                height=excluded.height, status=excluded.status
        """, records)
        connection.commit()
        status = Counter(row[-1] for row in records)
        sent_known = sum(1 for row in records if row[2] == "sent" and row[-1] == "metadata_hint")
        sent_total = sum(1 for row in records if row[2] == "sent")
        print({"database": str(path), "indexed": len(records),
               "status": dict(status), "sent_known": sent_known,
               "sent_total": sent_total})
    finally:
        connection.close()


if __name__ == "__main__":
    main()
