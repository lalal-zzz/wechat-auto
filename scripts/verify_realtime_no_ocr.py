"""Verify the real local-message hot path without waiting for user traffic."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from wechat_auto.backends.dpapi_db import open_dpapi_wechat_db
from wechat_auto.backends.watcher import WindowsDirectoryWatcher
from wechat_auto.backends.wechatauto_db import DatabaseConversationBackend
from wechat_auto.primitives import vision
from wechat_auto.storage import ProfileStore


def main() -> int:
    with ProfileStore("data/wechat_contact_profiles.sqlite3") as store:
        watched = store.watched_contacts()
    if not watched:
        print(json.dumps({"ok": False, "error": "EmptyWatchlist"}))
        return 1
    original_ocr = vision._get_ocr_engine
    calls = 0

    def forbidden_ocr():
        nonlocal calls
        calls += 1
        raise AssertionError("OCR entered the realtime DB path")

    watcher = None
    try:
        vision._get_ocr_engine = forbidden_ocr
        with open_dpapi_wechat_db(
            "data/.secrets", database_names=("contact.db",), include_message_family=True
        ) as db:
            backend = DatabaseConversationBackend(db)
            username = watched[0]["wechat_id"]
            latest = db.get_messages(username, limit=1)
            watermark = int(latest[0].get("sort_seq", 0)) if latest else 0
            delta = backend.poll(username, watermark, limit=20)
            paths = [Path(item[1]) for item in db._db_files
                     if "message" in {part.casefold() for part in Path(item[1]).parts}]
            watcher = WindowsDirectoryWatcher(paths[0].parent, recursive=True)
            watcher.start()
            event_during_snapshot = watcher.wait(timeout_ms=100)
            print(json.dumps({
                "ok": True,
                "real_contact_db": True,
                "real_message_db": True,
                "message_partitions": len(paths),
                "incremental_rows_after_latest": len(delta["all_messages"]),
                "directory_watcher_started": True,
                "event_during_snapshot": bool(event_during_snapshot),
                "ocr_calls": calls,
                "rapidocr_loaded": "rapidocr_onnxruntime" in sys.modules,
                "identity_redacted": True,
            }))
            return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "ocr_calls": calls}))
        return 1
    finally:
        if watcher is not None:
            watcher.close()
        vision._get_ocr_engine = original_ocr


if __name__ == "__main__":
    raise SystemExit(main())
