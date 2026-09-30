from wechat_auto.storage import HistoryStore


def test_history_store_deduplicates_and_reads(tmp_path):
    path = tmp_path / "history.sqlite3"
    message = {"id": "m1", "chat": "文件传输助手", "content": "hello", "direction": "incoming", "raw": {"x": 1}}
    with HistoryStore(path) as store:
        assert store.save_messages([message]) == 1
        assert store.save_messages([message]) == 0
        assert store.fetch_messages("文件传输助手")[0]["content"] == "hello"


def test_history_store_context_and_export_metadata(tmp_path):
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        store.save_messages([
            {"id": "a", "chat": "群", "content": "one"},
            {"id": "b", "chat": "群", "content": "two"},
            {"id": "c", "chat": "群", "content": "three"},
        ])
        assert [m["id"] for m in store.fetch_context("群", "b", 1, 1)] == ["a", "b", "c"]
        export_id = store.record_export("群", {"pages_scanned": 2, "complete": False,
                                                 "stopped_reason": "page_limit", "source": "ocr"}, 3)
        assert export_id > 0


def test_history_store_cursor_persists(tmp_path):
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        assert store.get_cursor("wechat_db", "room") == 0
        store.set_cursor("wechat_db", "room", 99)
        assert store.get_cursor("wechat_db", "room") == 99


def test_history_store_archives_binary_media_with_message(tmp_path):
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        assert store.save_messages([{
            "id": "m-media", "chat": "群", "content": "图片和语音",
            "media": [
                {"kind": "image", "mime_type": "image/png", "original_ref": "x.png", "data": b"png"},
                {"kind": "voice", "mime_type": "audio/amr", "data": b"voice"},
            ],
        }]) == 3
        media = store.fetch_media("m-media")
        assert [item["kind"] for item in media] == ["image", "voice"]
        assert [item["data"] for item in media] == [b"png", b"voice"]
        assert store.fetch_messages("群")[0]["media"][0]["sha256"] == media[0]["sha256"]


def test_fetch_month_supports_unix_timestamp_archive(tmp_path):
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        store.save_messages([
            {"id": "m1", "chat": "c", "content": "a", "time": "1731664346"},
            {"id": "m2", "chat": "c", "content": "b", "time": "2026-09-01 10:00:00"},
        ])
        assert [item["id"] for item in store.fetch_month("c", "2024-11")] == ["m1"]
        assert [item["id"] for item in store.fetch_month("c", "2026-09")] == ["m2"]
