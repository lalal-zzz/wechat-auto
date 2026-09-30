from wechat_auto.memory import AnalysisService, MarkdownMemory, MemoryStore
from wechat_auto.memory.indexer import ArchiveIndexer, message_period
from wechat_auto.storage import HistoryStore, MomentStore, ProfileStore


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
