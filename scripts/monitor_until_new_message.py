"""Wait for the first new local WeChat message, then exit.

This is event-driven: it blocks on ReadDirectoryChangesW and only queries the
read-only database after a message-directory change. It never sends a reply.
"""
from __future__ import annotations

import json
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wechatauto import WeChatDB
from wechat_auto.backends.wechatauto_db import DatabaseConversationBackend
from wechat_auto.backends.watcher import WindowsDirectoryWatcher
from wechat_auto.storage.history_store import HistoryStore


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wait for a new message in one explicitly selected chat"
    )
    parser.add_argument("contact", help="exact contact/group name or local username")
    parser.add_argument("--store", default="data/wechat_history.sqlite3")
    args = parser.parse_args()

    db = WeChatDB()
    backend = DatabaseConversationBackend(db)
    match = backend.resolve_chat(args.contact)
    username = str(match["username"])
    store_path = str(Path(args.store).resolve())
    with HistoryStore(store_path) as store:
        watermark = store.get_cursor("wechat_db", username)
        if watermark == 0:
            latest = db.get_messages(username, limit=1)
            watermark = int(latest[0].get("sort_seq", 0)) if latest else 0
            store.set_cursor("wechat_db", username, watermark)

    message_paths = [Path(p) for p in getattr(db, "_db_files", [])
                     if "message" in str(p).lower() and Path(p).parent.name == "message"]
    if not message_paths:
        raise RuntimeError("Cannot locate the WeChat message database directory")
    watcher = WindowsDirectoryWatcher(message_paths[0].parent, recursive=True)
    watcher.start()
    print(json.dumps({"watching": True, "contact": args.contact,
                      "username": username, "watermark": watermark,
                      "event_source": "WindowsDirectoryWatcher", "stop_on": "first_new_message"}), flush=True)
    try:
        while True:
            watcher.wait(timeout_ms=60_000)
            time.sleep(0.35)  # let SQLite/WAL commit settle
            update = backend.sync_when_notified(username, store_path, limit=100)
            if update["new_inbound"]:
                print(json.dumps({"new_message": True,
                                  "message_count": update["new_inbound"],
                                  "rows_added": update["rows_added"],
                                  "watermark": update["watermark"]},
                                 ensure_ascii=True), flush=True)
                return
    finally:
        watcher.close()


if __name__ == "__main__":
    main()
