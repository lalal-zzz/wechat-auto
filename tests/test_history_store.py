import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from wechat_auto.storage import HistoryStore


def test_concurrent_history_deduplication_reads_inside_writer_transaction(tmp_path):
    path = tmp_path / "history.sqlite3"
    with HistoryStore(path):
        pass
    ready = Barrier(2, timeout=5)

    def write(message_id):
        with HistoryStore(path) as history:
            observed = []

            def trace(statement):
                if "SELECT fingerprint,id FROM messages" in statement:
                    observed.append(history._connection.in_transaction)

            history._connection.set_trace_callback(trace)
            ready.wait()
            added = history.save_messages([{"id": message_id, "chat": "test-chat", "content": "same",
                                            "time": "2026-09-01", "fingerprint": "shared-fingerprint"}])
            assert observed == [True]
            return added

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, ("source-one", "source-two"))) == [0, 1]
    with HistoryStore(path) as history:
        assert len(history.fetch_messages("test-chat")) == 1


def test_month_input_includes_millisecond_timestamps(tmp_path):
    with HistoryStore(tmp_path / "history.sqlite3") as history:
        before = history.month_message_snapshot("test-chat", "2024-11")
        history.save_messages([{"id": "milliseconds", "chat": "test-chat", "time": "1731664346000"}])
        assert [item["id"] for item in history.fetch_month("test-chat", "2024-11")] == ["milliseconds"]
        assert history.month_message_snapshot("test-chat", "2024-11") != before


def test_corrupt_history_store_releases_file_on_init_failure(tmp_path):
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"invalid SQLite header" + bytes(4096))

    with pytest.raises(sqlite3.DatabaseError, match="not a database") as error:
        HistoryStore(path)
    path.unlink()
    assert error.value.sqlite_errorcode == sqlite3.SQLITE_NOTADB


def test_protected_month_snapshot_releases_wal_writer_after_failure(tmp_path):
    path = tmp_path / "history.sqlite3"
    with HistoryStore(path) as reader, HistoryStore(path) as writer:
        assert reader._connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer._connection.execute("PRAGMA busy_timeout=0")
        month = ("test-chat", "2026-09")
        message = {"id": "backfill", "chat": month[0], "time": "2026-09-01", "content": "synthetic"}
        with pytest.raises(RuntimeError, match="publication failed"), reader.protect_month_snapshot(*month) as snapshot:
            with pytest.raises(sqlite3.OperationalError, match="database is locked"):
                writer.save_messages([message])
            assert reader.month_message_snapshot(*month) == snapshot
            raise RuntimeError("publication failed")

        assert writer.save_messages([message]) == 1
        assert reader.month_message_snapshot(*month) != snapshot


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
        store.set_cursor("wechat_db", "room", 10)
        assert store.get_cursor("wechat_db", "room") == 99
        with pytest.raises(ValueError, match='negative'):
            store.set_cursor("wechat_db", "room", -1)
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


def test_same_batch_duplicate_fingerprint_attaches_media_to_saved_message(tmp_path):
    with HistoryStore(tmp_path / 'history.sqlite3') as store:
        store.save_messages([
            {'id': 'source-a', 'chat': 'wxid_test_one', 'content': 'same', 'time': '2026-09-01'},
            {'id': 'source-b', 'chat': 'wxid_test_one', 'content': 'same', 'time': '2026-09-01',
             'media': [{'kind': 'image', 'data': b'synthetic'}]},
        ])
        assert store.get_message('source-b') is None
        assert store.fetch_media('source-a')[0]['data'] == b'synthetic'
        assert store._connection.execute(
            'SELECT count(*) FROM message_media mm LEFT JOIN messages m ON m.id=mm.message_id WHERE m.id IS NULL'
        ).fetchone()[0] == 0


@pytest.mark.parametrize('same_batch', [True, False])
def test_conflicting_message_id_does_not_mix_conversations(tmp_path, same_batch):
    first = {'id': 'reused-local-id', 'chat': 'wxid_test_one', 'content': 'first'}
    other = {'id': 'reused-local-id', 'chat': 'wxid_test_two', 'content': 'other',
             'media': [{'kind': 'image', 'data': b'synthetic'}]}
    with HistoryStore(tmp_path / 'history.sqlite3') as store:
        if not same_batch:
            store.save_messages([first])
        with pytest.raises(ValueError, match='ID collision'):
            store.save_messages([first, other] if same_batch else [other])
        assert store.fetch_media('reused-local-id') == []
        assert store.fetch_messages('wxid_test_two') == []
