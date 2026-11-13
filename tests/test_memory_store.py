import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from wechat_auto.memory import MemoryStore


def test_analysis_scope_status_reports_recorded_upstream_work(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        store.add_dependency("conversation_month", "chat:2026-09", "conversation", "chat")
        store.add_dependency("conversation", "chat", "person", "person")
        store.add_dependency("person", "person", "conversation", "chat")
        store.record_version("conversation", "chat", "2026-09", content_hash="hash",
                             markdown_path="test.md", input_fingerprint="input")
        store.update_coverage("conversation", "chat", "2026-09", message_watermark="old")
        store.mark_dirty("conversation_month", "chat:2026-09", "new_message", "new")
        job = store.enqueue_job("monthly_analysis", "conversation", "chat", period="2026-09")
        store.complete_job(job, success=False)
        store.enqueue_job("monthly_analysis", "conversation", "chat", period="2026-10")

        nodes = {item["node_id"]: item for item in store.analysis_scope_status("person", "person")}

        assert set(nodes) == {"person", "chat", "chat:2026-09"}
        assert nodes["person"]["version"] is None
        month = nodes["chat:2026-09"]
        assert month["version"] == 1
        assert month["message_watermark"] == "old"
        assert month["dirty"][0]["source_id"] == "new"
        assert [(item["job_id"], item["status"]) for item in month["jobs"]] == [(job, "failed")]


def test_memory_store_rejects_incompatible_schema(tmp_path):
    path = tmp_path / "memory.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO schema_meta VALUES('schema_version', '999')")
    with pytest.raises(RuntimeError, match="Unsupported Memory schema 999"):
        MemoryStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("schema_meta",)
        ]
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_locked_memory_initialization_closes_connection_and_recovers(tmp_path):
    path = tmp_path / 'memory.sqlite3'
    with MemoryStore(path) as owner:
        owner.ensure_person('wxid_test_existing')
        owner._connection.execute('BEGIN EXCLUSIVE')
        original_connect = sqlite3.connect
        attempted = []

        def connect(*args, **kwargs):
            kwargs['timeout'] = 0
            connection = original_connect(*args, **kwargs)
            attempted.append(connection)
            return connection

        try:
            with patch('wechat_auto.memory.store.sqlite3.connect', side_effect=connect), pytest.raises(
                sqlite3.OperationalError, match='locked'
            ):
                MemoryStore(path)
        finally:
            owner._connection.rollback()
        assert len(attempted) == 1
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            attempted[0].execute('SELECT 1')
    with MemoryStore(path) as recovered:
        assert recovered.database_summary()['people'] == 1


@pytest.mark.parametrize('old_version', [1, 2])
def test_memory_store_migrates_to_v3_without_losing_existing_rows(tmp_path, old_version):
    path = tmp_path / "memory.sqlite3"
    with MemoryStore(path) as store:
        person = store.ensure_person("wxid_test_friend")
        store._connection.execute("UPDATE schema_meta SET value=? WHERE key='schema_version'", (str(old_version),))
        store._connection.commit()
    with MemoryStore(path) as migrated:
        assert migrated.schema_version == 3
        assert migrated.database_summary()["people"] == 1
        assert migrated._connection.execute(
            "SELECT person_id FROM people WHERE person_id=?", (person,)
        ).fetchone()[0] == person


def test_identity_alias_claim_and_evidence_are_structured(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        person = store.ensure_person("wxid_test_friend", display_name="朋友")
        assert store.ensure_person("wxid_test_friend", display_name="新昵称") == person
        store.add_alias(person, "nickname", "朋友")
        store.add_alias(person, "nickname", "新昵称")
        conversation = store.ensure_conversation("wxid_test_friend", conversation_type="direct")
        claim = store.add_claim(
            "表达通常比较简短。", claim_type="communication",
            subject_person_id=person, conversation_id=conversation,
            status="observed", confidence=.9,
            evidence=[{"evidence_type": "message", "evidence_id": "m1"}],
        )
        item = store.get_claim(claim, include_evidence=True)
        assert item["canonical_text"] == "表达通常比较简短。"
        assert item["evidence"][0]["evidence_id"] == "m1"
        assert store.database_summary()["people"] == 1


def test_presence_requires_three_snapshots_and_24_hours(tmp_path):
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        assert store.observe_presence("person", "p1", present=False,
                                      observed_at=start.isoformat()) == "missing"
        assert store.observe_presence("person", "p1", present=False,
                                      observed_at=(start + timedelta(hours=12)).isoformat()) == "missing"
        assert store.observe_presence("person", "p1", present=False,
                                      observed_at=(start + timedelta(hours=25)).isoformat()) == "inferred_removed"
        assert store.observe_presence("person", "p1", present=True,
                                      observed_at=(start + timedelta(hours=26)).isoformat()) == "restored"


def test_confirmation_is_exact_and_single_use(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        draft = store.create_reply_draft("cv1", "m1", "你好", "ctx")
        confirmation = store.confirm_reply_draft(draft)
        with pytest.raises(PermissionError):
            store.consume_confirmation(confirmation, "cv1", "你好呀")
        assert store.consume_confirmation(confirmation, "cv1", "你好") == draft
        with pytest.raises(PermissionError):
            store.consume_confirmation(confirmation, "cv1", "你好")


def test_contact_action_confirmation_binds_stored_payload_and_is_single_use(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        plan = {"username": "wxid_test_friend", "action": "set_remark", "value": "新备注"}
        action_id = store.create_pending_action("set_remark", "wxid_test_friend", plan)
        confirmation_id = store.confirm_pending_action(action_id)
        assert store.consume_pending_action(action_id, confirmation_id) == plan
        with pytest.raises(PermissionError, match="unconsumed"):
            store.consume_pending_action(action_id, confirmation_id)
        store.finish_pending_action(action_id, succeeded=True)


def test_analysis_jobs_are_idempotent_for_same_input(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        first = store.enqueue_job("monthly_analysis", "conversation", "cv1",
                                  period="2026-09", input_fingerprint="abc")
        second = store.enqueue_job("monthly_analysis", "conversation", "cv1",
                                   period="2026-09", input_fingerprint="abc")
        assert first == second
        assert store.next_jobs()[0]["job_id"] == first
        claimed = store.claim_next_job(worker_id="worker-1")
        assert claimed["job_id"] == first
        assert claimed["attempts"] == 1
        assert store.claim_next_job() is None
        store.complete_job(first, success=True)
        assert store.enqueue_job("monthly_analysis", "conversation", "cv1",
                                 period="2026-09", input_fingerprint="abc") == first
        assert store.next_jobs() == []
        revised = store.enqueue_job("monthly_analysis", "conversation", "cv1",
                                    period="2026-09", input_fingerprint="def")
        assert revised != first
        assert store.claim_next_job()["job_id"] == revised
        store.complete_job(revised, success=False)
        assert store.enqueue_job("monthly_analysis", "conversation", "cv1",
                                 period="2026-09", input_fingerprint="def") == revised
        assert store.claim_next_job()["attempts"] == 2


def test_dirty_dependencies_propagate_recursively(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        store.add_dependency("conversation_month", "cv1:2026-09", "conversation", "cv1")
        store.add_dependency("conversation", "cv1", "person", "p1")
        changed = store.propagate_dirty("conversation_month", "cv1:2026-09", "updated")
        assert changed == [{"node_type": "conversation", "node_id": "cv1"},
                           {"node_type": "person", "node_id": "p1"}]


def test_incomplete_snapshot_never_marks_absent_entity_missing(tmp_path):
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        store.reconcile_snapshot("person", ["p1", "p2"], observed_at=start.isoformat())
        result = store.reconcile_snapshot("person", ["p1"], complete=False,
                                          observed_at=(start + timedelta(days=2)).isoformat())
        assert result["missing"] == 0
        row = store._connection.execute(
            "SELECT status FROM entity_presence WHERE entity_id='p2'"
        ).fetchone()
        assert row[0] == "active"


def test_identity_merge_requires_candidate_decision_and_preserves_alias(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        left = store.ensure_person("wxid_test_left")
        right = store.ensure_person("wxid_test_right")
        store.add_alias(right, "nickname", "旧昵称")
        candidate = store.propose_identity_merge(left, right, "user says same person")
        assert store.decide_identity_merge(candidate, confirm=True)["merged"] is True
        assert store.ensure_person("wxid_test_right") == left
        alias = store._connection.execute(
            "SELECT person_id FROM person_aliases WHERE alias_value='旧昵称'"
        ).fetchone()
        assert alias[0] == left


def test_scoped_job_claim_does_not_fall_back_to_another_month(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        wanted = store.enqueue_job("monthly_analysis", "conversation", "chat", period="2026-09")
        other = store.enqueue_job("monthly_analysis", "conversation", "chat", period="2026-10",
                                  priority=100)
        scope = ("conversation", "chat", "2026-09")
        assert store.claim_next_job(job_id=other, scope=scope) is None
        assert store.claim_next_job(scope=scope)["job_id"] == wanted
        assert store.claim_next_job(scope=scope) is None
        assert store.claim_next_job()["job_id"] == other


def test_exact_job_claim_does_not_take_unrelated_high_priority_job(tmp_path):
    path = tmp_path / "memory.sqlite3"
    with MemoryStore(path) as store, MemoryStore(path) as other_worker:
        unrelated = store.enqueue_job("monthly_analysis", "conversation", "other",
                                      period="2026-08", priority=100)
        selected = store.enqueue_job("monthly_analysis", "conversation", "selected",
                                     period="2024-06", priority=1)
        assert store.claim_next_job(job_id="missing") is None
        claimed = store.claim_next_job(job_id=selected, worker_id="selected-worker")
        assert claimed["job_id"] == selected and claimed["status"] == "running"
        assert other_worker.claim_next_job(job_id=selected) is None
        assert [job["job_id"] for job in store.next_jobs()] == [unrelated]
        assert other_worker.claim_next_job()["job_id"] == unrelated


def test_exact_job_claim_respects_future_availability(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        selected = store.enqueue_job("monthly_analysis", "conversation", "selected")
        with store.transaction() as connection:
            connection.execute("UPDATE analysis_jobs SET available_at=? WHERE job_id=?",
                               ("9999-01-01T00:00:00+00:00", selected))
        assert store.claim_next_job(job_id=selected) is None
