"""Import the bundled/exported message SQLite into HistoryStore."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wechat_auto.storage import HistoryStore, make_message_fingerprint, make_message_id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="?", default="data/wechat_history_full.sqlite3")
    parser.add_argument("--store", default="data/wechat_history.sqlite3")
    parser.add_argument("--source-name", default=None)
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()
    source = sqlite3.connect(args.source)
    source.row_factory = sqlite3.Row
    total = added = 0
    with HistoryStore(args.store) as store:
        columns = {row[1] for row in source.execute("PRAGMA table_info(messages)")}
        server_column = "server_id" if "server_id" in columns else "NULL AS server_id"
        cursor = source.execute(
            f"SELECT username,local_id,type,sender_id,sender_name,create_time,content,sort_seq,{server_column} FROM messages"
        )
        while True:
            rows = cursor.fetchmany(args.batch_size)
            if not rows:
                break
            records = [{
                "id": make_message_id(r["username"], r["local_id"], r["sort_seq"],
                                       r.get("server_id", ""), r["type"]),
                "chat": r["username"],
                "sender": r["sender_name"] or str(r["sender_id"] or ""),
                "content": r["content"] or "", "time": str(r["create_time"] or ""),
                "direction": "outgoing" if str(r["sender_id"]) == "2" else "incoming",
                "source": args.source_name or f"wechat_db_export:{Path(args.source).name}",
                "raw": {"local_id": r["local_id"], "sort_seq": r["sort_seq"],
                        "server_id": r["server_id"], "type": r["type"]},
                "fingerprint": make_message_fingerprint(
                    r["username"], r["create_time"], r["content"] or "",
                    r["sender_name"] or str(r["sender_id"] or ""), r["type"], r["sort_seq"]
                ),
            } for r in rows]
            added += store.save_messages(records)
            total += len(records)
    source.close()
    print({"messages_read": total, "rows_added": added, "database": str(Path(args.store).resolve())})


if __name__ == "__main__":
    main()
