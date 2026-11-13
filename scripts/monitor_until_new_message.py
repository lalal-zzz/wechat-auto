"""Wait for one new local WeChat message using DB events and zero OCR."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from wechat_auto.backends.dpapi_db import open_dpapi_wechat_db
from wechat_auto.backends.watcher import WindowsDirectoryWatcher
from wechat_auto.backends.wechatauto_db import DatabaseConversationBackend
from wechat_auto.storage.history_store import HistoryStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Wait for a new message in one selected chat")
    parser.add_argument("contact", help="exact contact/group name or local username")
    parser.add_argument("--store", default="data/wechat_history.sqlite3")
    parser.add_argument("--secret-dir", default="data/.secrets")
    args = parser.parse_args()

    with open_dpapi_wechat_db(
        args.secret_dir, database_names=("contact.db",), include_message_family=True
    ) as db:
        backend = DatabaseConversationBackend(db)
        username = str(backend.resolve_chat(args.contact)["username"])
        store_path = str(Path(args.store).resolve())
        message_paths = [Path(item[1]) for item in getattr(db, "_db_files", [])
                         if "message" in {part.casefold() for part in Path(item[1]).parts}]
        if not message_paths:
            raise RuntimeError("Cannot locate the WeChat message database directory")
        watcher = WindowsDirectoryWatcher(message_paths[0].parent, recursive=True)
        watcher.start()
        try:
            with HistoryStore(store_path) as store:
                watermark = store.get_cursor("wechat_db", username)
                if watermark == 0:
                    latest = db.get_messages(username, limit=1)
                    watermark = int(latest[0].get("sort_seq", 0)) if latest else 0
                    store.set_cursor("wechat_db", username, watermark)
            print(json.dumps({"watching": True, "identity_redacted": True,
                              "event_source": "WindowsDirectoryWatcher",
                              "ocr_used": False, "stop_on": "first_new_message"}), flush=True)
            batch_size = 100
            while True:
                if not watcher.wait(timeout_ms=60_000):
                    continue
                time.sleep(0.35)
                while True:
                    update = backend.sync_when_notified(username, store_path, limit=batch_size)
                    if update["new_inbound"]:
                        print(json.dumps({"new_message": True,
                                          "message_count": update["new_inbound"],
                                          "rows_added": update["rows_added"],
                                          "ocr_used": False}), flush=True)
                        return
                    previous, watermark = watermark, update["watermark"]
                    if update["messages_read"] < batch_size or watermark <= previous:
                        break
        finally:
            watcher.close()


if __name__ == "__main__":
    main()
