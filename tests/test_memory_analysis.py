from wechat_auto.memory import (
    AnalysisService,
    ContextBuilder,
    MarkdownMemory,
    MemoryStore,
)


def test_analysis_versions_are_full_and_unchanged_input_is_idempotent(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        memory = MarkdownMemory(tmp_path / "memory", store)
        service = AnalysisService(store, memory)
        conversation = store.ensure_conversation("wxid_test_friend", conversation_type="direct")
        first = service.submit(
            scope_type="conversation", scope_id=conversation, period="2026-09",
            markdown="# 2026-09\n\n## 本月概览\n第一次。",
            evidence_ids=["m1"], template_version="1",
        )
        same = service.submit(
            scope_type="conversation", scope_id=conversation, period="2026-09",
            markdown="# ignored", evidence_ids=["m1"], template_version="1",
        )
        second = service.submit(
            scope_type="conversation", scope_id=conversation, period="2026-09",
            markdown="# 2026-09\n\n## 本月概览\n第一次。新增变化。",
            evidence_ids=["m1", "m2"], template_version="1",
            expected_parent=1,
        )
        assert first["version"] == 1
        assert same == {"changed": False, "version": 1,
                        "input_fingerprint": first["input_fingerprint"],
                        "reason": "input_unchanged"}
        assert second["version"] == 2
        assert "第一次。" in memory.read_version("conversation", conversation, 1, "2026-09")
        assert "新增变化" in memory.read_current("conversation", conversation, "2026-09")
        assert "新增变化" in memory.compare("conversation", conversation, 1, 2, "2026-09")


def test_compact_context_omits_evidence_ids(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        person = store.ensure_person("wxid_test_friend")
        claim = store.add_claim(
            "工作群表达更正式。", claim_type="communication",
            subject_person_id=person, status="inferred", confidence=.7,
            evidence=[{"evidence_id": "secret-message-id"}],
        )
        result = ContextBuilder(store).compact_claims(person_id=person)
        assert f"[{claim}]" in result["text"]
        assert "secret-message-id" not in result["text"]


def test_month_update_queues_conversation_and_person_rollups(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        person = store.ensure_person("wxid_test_friend")
        conversation = store.ensure_conversation("wxid_test_friend", conversation_type="direct")
        store.add_dependency("conversation_month", f"{conversation}:2026-09",
                             "conversation", conversation)
        store.add_dependency("conversation", conversation, "person", person)
        service = AnalysisService(store, MarkdownMemory(tmp_path / "memory", store))
        service.submit(scope_type="conversation", scope_id=conversation, period="2026-09",
                       markdown="# 2026-09\n\n完成。", evidence_ids=["m1"], template_version="1")
        assert {(job["job_type"], job["scope_id"]) for job in store.next_jobs()} == {
            ("conversation_summary", conversation), ("person_analysis", person)
        }
