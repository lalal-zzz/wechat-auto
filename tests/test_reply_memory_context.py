from pathlib import Path
import sqlite3
import pytest
from wechat_auto.memory.store import MemoryStore
from wechat_auto.memory.markdown import MarkdownMemory
from wechat_auto.memory.context import ContextBuilder


def setup_context(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    memory = MarkdownMemory(tmp_path / "memory", store)
    cv = store.ensure_conversation("friend", conversation_type="direct")
    a, b = store.ensure_person("self", person_type="self"), store.ensure_person("friend")
    for person in (a, b):
        if person == b:
            store.link_conversation_person(cv, person)
        memory.write("person", person, "# Person background", input_fingerprint="p")
    rel = store.ensure_relationship(a, b)
    memory.write("relationship", rel, "# Shared expression", input_fingerprint="r")
    memory.write("conversation", cv,
                 "---\nsource_range: 2026-09-01/2026-09-12\n---\n# Communication background", input_fingerprint="c")
    history = tmp_path / "history.sqlite3"
    with sqlite3.connect(history) as db:
        db.execute("CREATE TABLE messages(id TEXT,chat TEXT,sender TEXT,content TEXT,message_time TEXT,direction TEXT)")
        db.executemany("INSERT INTO messages VALUES(?,?,?,?,?,?)", [
            ("old", "friend", "A", "old", "2026-09-11 23:59:59", "in"),
            ("boundary", "friend", "A", "same day change", "2026-09-12 23:00:00", "in"),
            ("new", "friend", "A", "cancelled plan", "2026-09-14T10:00:00+08:00", "in"),
            ("other", "another", "A", "unrelated", "2026-09-15", "in"),
        ])
    return store, memory, cv, ContextBuilder(store, memory, history)


def test_formal_memory_and_pending_pages_include_last_day(tmp_path):
    store, memory, cv, builder = setup_context(tmp_path)
    try:
        result = builder.reply_context(cv, [{"content": "latest"}], pending_limit=1)
        assert len(result["memory_sources"]) == 4
        assert "Communication background" in result["text"]
        assert "Shared expression" in result["text"]
        assert result["pending_messages"][0]["id"] == "boundary"
        assert result["pending_coverage"]["remaining_count"] == 1
        assert result["requires_more_data"]
        second = builder.reply_context(cv, [], pending_after_id=result["pending_coverage"]["next_after_id"])
        assert [m["id"] for m in second["pending_messages"]] == ["new"]
        assert not second["requires_more_data"]
        assert result["fingerprint"] != second["fingerprint"]
    finally:
        store.close()


def test_tampered_memory_and_foreign_person_fail(tmp_path):
    store, memory, cv, builder = setup_context(tmp_path)
    try:
        outsider = store.ensure_person("outsider")
        with pytest.raises(ValueError, match="active member"):
            builder.reply_context(cv, [], person_id=outsider)
        version = store.current_version("conversation", cv)
        Path(version["markdown_path"]).write_text("tampered", encoding="utf-8")
        with pytest.raises(ValueError, match="hash mismatch"):
            builder.reply_context(cv, [])
    finally:
        store.close()


def test_without_boundary_reports_unknown_and_keeps_all_current_messages(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        builder = ContextBuilder(store)
        result = builder.reply_context("unknown", [{"content": str(i)} for i in range(30)])
        assert result["requires_more_data"]
        assert result["pending_coverage"]["boundary"] is None
        assert "[]: 0" in result["text"]
        assert result["message_count"] == 30
