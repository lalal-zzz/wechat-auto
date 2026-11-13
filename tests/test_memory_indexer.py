import sqlite3

import pytest

from wechat_auto.memory import AnalysisService, MarkdownMemory, MemoryStore
from wechat_auto.memory.indexer import ArchiveIndexer, _readonly, message_period
from wechat_auto.storage import HistoryStore, MomentStore, ProfileStore


@pytest.mark.parametrize("fail", [False, True])
def test_readonly_source_special_path_closes_on_all_exits(tmp_path, fail):
    path = tmp_path / "history #1.sqlite3"
    with sqlite3.connect(path) as setup:
        setup.execute("CREATE TABLE sample(value TEXT)")
    try:
        with _readonly(path) as source:
            assert source.execute("SELECT count(*) FROM sample").fetchone()[0] == 0
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                source.execute("INSERT INTO sample VALUES ('blocked')")
            if fail:
                raise ValueError("simulated read failure")
    except ValueError:
        assert fail
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        source.execute("SELECT 1")


def test_archive_indexer_references_raw_archives_and_queues_months(tmp_path):
    history_path = tmp_path / "history.sqlite3"
    with HistoryStore(history_path) as history:
        history.save_messages([
            {"id": "m1", "chat": "wxid_test_friend", "content": "a", "time": "2026-08-01 10:00:00"},
            {"id": "m2", "chat": "wxid_test_friend", "content": "b", "time": "2026-09-01 10:00:00"},
            {"id": "m3", "chat": "room@chatroom", "content": "c", "time": "2026-09-02 10:00:00"},
        ])
    with MemoryStore(tmp_path / "memory.sqlite3") as memory:
        indexer = ArchiveIndexer(memory)
        first = indexer.index_history(history_path)
        second = indexer.index_history(history_path)
        service = AnalysisService(memory, MarkdownMemory(tmp_path / "memory", memory))
        queued = indexer.queue_initial_top(history_path, service, direct_count=1, group_count=1)
        assert first["messages_seen"] == 3
        assert second["messages_seen"] == 0
        assert first["conversations_seen"] == 2
        assert queued["jobs_queued"] == 3
        assert len(memory.next_jobs()) == 3


def test_message_period_accepts_epoch_and_iso_text():
    assert message_period("1731664346") == "2024-11"
    assert message_period("2026-09-01 10:00:00") == "2026-09"
    assert message_period("bad") == ""


def test_history_index_rolls_back_cursor_and_jobs_together(tmp_path, monkeypatch):
    history_path = tmp_path / "history.sqlite3"
    with HistoryStore(history_path) as history, MemoryStore(tmp_path / "memory.sqlite3") as memory:
        indexer = ArchiveIndexer(memory)
        history.save_messages([{"id": "baseline", "chat": "wxid_test_one", "time": "2026-10-01"}])
        baseline = indexer.index_history(history_path)["cursor"]
        history.save_messages([{"id": "backfill", "chat": "wxid_test_two", "time": "2026-09-01"}])
        set_cursor = memory.set_sync_cursor

        def fail_after_cursor(*args):
            set_cursor(*args)
            raise RuntimeError("simulated index failure")

        with monkeypatch.context() as patch:
            patch.setattr(memory, "set_sync_cursor", fail_after_cursor)
            with pytest.raises(RuntimeError, match="simulated index failure"):
                indexer.index_history(history_path, batch_size=1)
        assert memory.get_sync_cursor("history_index", str(history_path)) == str(baseline)
        assert memory.next_jobs() == []
        assert memory._connection.execute("SELECT count(*) FROM dirty_nodes WHERE source_id='backfill'").fetchone()[0] == 0
        assert memory._connection.execute("SELECT count(*) FROM conversations").fetchone()[0] == 1

        recovered = indexer.index_history(history_path, batch_size=1)
        assert recovered["messages_seen"] == recovered["months_dirtied"] == 1
        assert [job["period"] for job in memory.next_jobs()] == ["2026-09"]
        assert indexer.index_history(history_path, batch_size=1)["messages_seen"] == 0


def test_history_index_keeps_new_input_queued_while_month_is_running(tmp_path):
    history_path = tmp_path / "history.sqlite3"
    memory_path = tmp_path / "memory.sqlite3"
    with HistoryStore(history_path) as history, MemoryStore(memory_path) as memory, MemoryStore(memory_path) as worker:
        indexer = ArchiveIndexer(memory)
        base = {"chat": "wxid_test_one", "time": "2026-09-01"}
        history.save_messages([{**base, "id": "baseline", "content": "baseline"}])
        indexer.index_history(history_path)
        history.save_messages([{**base, "id": "first", "content": "first"}])
        indexer.index_history(history_path)
        running = worker.claim_next_job()
        assert running["input_fingerprint"].startswith("message-batch:")

        history.save_messages([{**base, "id": "second", "content": "second"}])
        indexer.index_history(history_path)
        pending, = memory.next_jobs()
        assert pending["input_fingerprint"] != running["input_fingerprint"]
        assert worker.claim_next_job(job_id=pending["job_id"]) is None
        worker.complete_job(running["job_id"], success=True)
        assert worker.claim_next_job()["job_id"] == pending["job_id"]


def test_profile_and_moment_updates_dirty_people_without_copying_body(tmp_path):
    profile_path = tmp_path / "profiles.sqlite3"
    moment_path = tmp_path / "moments.sqlite3"
    with ProfileStore(profile_path) as profiles:
        profiles.save({"wechat_id": "wxid_test_friend", "nickname": "朋友",
                       "source": "test", "raw": {}}, profile_type="contact")
    with MomentStore(moment_path) as moments:
        moments.save([{"id": "mmt1", "username": "wxid_test_friend", "nickname": "朋友",
                       "create_time": 1, "text": "private body", "images": [],
                       "videos": [], "likes": [], "comments": []}])
    with MemoryStore(tmp_path / "memory.sqlite3") as memory:
        indexer = ArchiveIndexer(memory)
        assert indexer.index_profiles(profile_path)["profiles_seen"] == 1
        assert indexer.index_profile_snapshots(profile_path)["snapshots_seen"] == 1
        assert indexer.index_moments(moment_path)["moments_seen"] == 1
        rows = memory._connection.execute("SELECT reason,source_id FROM dirty_nodes").fetchall()
        assert {row[0] for row in rows} == {"profile_snapshot", "new_moment"}
        database_text = (tmp_path / "memory.sqlite3").read_bytes()
        assert b"private body" not in database_text


def test_profile_archive_neither_marks_absence_nor_restores_presence(tmp_path):
    profile_path = tmp_path / 'profiles.sqlite3'
    with ProfileStore(profile_path) as profiles:
        profiles.save({'wechat_id': 'wxid_test_missing', 'nickname': 'old', 'raw': {}},
                      profile_type='contact')
        profiles.save({'wechat_id': 'wxid_test_new', 'nickname': 'new', 'raw': {}},
                      profile_type='contact')
    with MemoryStore(tmp_path / 'memory.sqlite3') as memory:
        absent = memory.ensure_person('wxid_test_absent')
        missing = memory.ensure_person('wxid_test_missing')
        memory.observe_presence('person', missing, present=False, snapshot_key='baseline')
        result = ArchiveIndexer(memory).index_profiles(profile_path)
        assert result['presence_snapshot'] == {'seen': 2, 'missing': 0, 'complete': False}
        assert memory._connection.execute('SELECT status FROM people WHERE person_id=?',
                                          (absent,)).fetchone()[0] == 'active'
        assert memory._connection.execute('SELECT status FROM people WHERE person_id=?',
                                          (missing,)).fetchone()[0] == 'missing'
        assert memory._connection.execute('SELECT count(*) FROM entity_status_events').fetchone()[0] == 1
        assert memory._connection.execute(
            "SELECT p.status FROM people p JOIN person_identities i USING(person_id) "
            "WHERE i.identity_value='wxid_test_new'").fetchone()[0] == 'unknown'
