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
