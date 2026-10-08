import json
import re
from pathlib import Path
from urllib.parse import unquote

import pytest

from wechat_auto.memory import MemoryStore
from wechat_auto.memory.dashboard import DashboardBuilder
from wechat_auto.memory.markdown import MarkdownMemory


def dashboard_data(path):
    html = Path(path).read_text(encoding="utf-8")
    return json.loads(re.search(r'<script id="memory-data" type="application/json">(.*?)</script>',
                               html, re.DOTALL).group(1))


def test_dashboard_exports_offline_html_mermaid_and_png(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        person = store.ensure_person("wxid_test_friend")
        claim = store.add_claim("发生了一件重要事情。", claim_type="event",
                                subject_person_id=person, status="observed", confidence=.9)
        store.add_event("重要事情", started_at="2026-09-01", status="observed",
                        confidence=.9, people=[person], claims=[claim])
        dashboard = DashboardBuilder(store, tmp_path / "dashboard")
        html = Path(dashboard.build(person_id=person))
        mermaid = Path(dashboard.export_mermaid(person_id=person))
        png = Path(dashboard.export_png(person_id=person))
        assert html.is_file() and "https://" not in html.read_text(encoding="utf-8")
        assert mermaid.is_file() and "重要事情" in mermaid.read_text(encoding="utf-8")
        assert png.is_file() and png.stat().st_size > 100


def test_scope_pages_do_not_overwrite_or_embed_unrelated_people(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        left = store.ensure_person("local_left", display_name="左侧对象")
        right = store.ensure_person("local_right", display_name="无关对象")
        store.add_claim("左侧记录", claim_type="preference", subject_person_id=left)
        store.add_claim("无关记录", claim_type="fact", subject_person_id=right)
        builder = DashboardBuilder(store, tmp_path / "memory" / "dashboard")
        left_page = Path(builder.build(person_id=left))
        left_bytes = left_page.read_bytes()
        right_page = Path(builder.build(person_id=right))
        assert left_page != right_page
        assert left_page == tmp_path / "memory" / "dashboard" / "people" / left / "index.html"
        assert left_page.read_bytes() == left_bytes
        payload = dashboard_data(left_page)
        assert payload["scope"]["title"] == "左侧对象"
        assert right not in payload["people"]
        assert "无关记录" not in left_page.read_text(encoding="utf-8")
        assert Path(builder.export_mermaid(person_id=left)).parent == left_page.parent
        assert Path(builder.export_png(person_id=left)).parent == left_page.parent


def test_versions_coverage_and_safe_formal_markdown_links(tmp_path):
    memory_root = tmp_path / "正式 memory"
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        person = store.ensure_person("local_person", display_name="测试对象")
        other = store.ensure_person("other_person", display_name="其他对象")
        conversation = store.ensure_conversation("local_chat", conversation_type="direct", title="测试会话")
        unrelated = store.ensure_conversation("other_chat", conversation_type="direct", title="其他会话")
        store.link_conversation_person(conversation, person)
        store.link_conversation_person(unrelated, other)
        memory = MarkdownMemory(memory_root, store)
        memory.write("conversation", conversation, "# 正式月度\n详细正文", period="2026-09", input_fingerprint="month-input")
        memory.write("person", person, "# 正式人物\n详细正文", input_fingerprint="person-input")
        memory.write("conversation", unrelated, "# 不相关正文", input_fingerprint="other-input")
        store.update_coverage("conversation", conversation, "2026-09", message_watermark="known-message",
                              evidence_count=6, input_fingerprint="month-input")
        store.mark_dirty("conversation_month", conversation + ":2026-09", "new_message")
        builder = DashboardBuilder(store, memory_root / "dashboard")
        page = Path(builder.build(person_id=person))
        payload = dashboard_data(page)
        assert len(payload["metadata"]["source_versions"]) == 2
        assert {row["scope_id"] for row in payload["metadata"]["source_versions"]} == {person, conversation}
        assert payload["metadata"]["freshness"] == "stale"
        assert payload["metadata"]["semantic_quality"] == "not_certified"
        assert payload["metadata"]["media_content_coverage"] == "unknown"
        assert payload["coverage"][0]["message_watermark"] == "known-message"
        for version in payload["metadata"]["source_versions"]:
            assert version["report"]["status"] == "verified"
            target = (page.parent / unquote(version["report"]["href"])).resolve()
            assert target.is_relative_to(memory_root)
            assert target.is_file() and target.suffix == ".md"
        combined = dashboard_data(builder.build(person_id=person, conversation_id=conversation))
        assert {row["scope_id"] for row in combined["metadata"]["source_versions"]} == {conversation}
        with pytest.raises(ValueError, match="not linked"):
            builder.build(person_id=person, conversation_id=unrelated)


@pytest.mark.parametrize("failure", ["outside", "changed", "missing"])
def test_unverified_version_never_becomes_a_clickable_report(tmp_path, failure):
    memory_root = tmp_path / "memory"
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        person = store.ensure_person("local_person")
        memory = MarkdownMemory(memory_root, store)
        result = memory.write("person", person, "# 正式正文", input_fingerprint="input")
        if failure == "outside":
            with store.transaction() as connection:
                connection.execute("UPDATE analysis_versions SET markdown_path=?", (str(tmp_path / "outside.md"),))
        elif failure == "changed":
            Path(result["version_path"]).write_text("被修改的正文", encoding="utf-8")
        else:
            Path(result["version_path"]).unlink()
        payload = dashboard_data(DashboardBuilder(store, memory_root / "dashboard").build(person_id=person))
        report = payload["metadata"]["source_versions"][0]["report"]
        assert "href" not in report
        assert report["status"] == {"outside": "unsafe_path", "changed": "content_mismatch", "missing": "missing"}[failure]


def test_html_keeps_untrusted_text_inside_json_and_uses_local_templates(tmp_path):
    dangerous = '</script><img src=x onerror="alert(1)"> & \u2028 end'
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        person = store.ensure_person("local_person", display_name=dangerous)
        store.add_claim(dangerous, claim_type="fact", subject_person_id=person, status="unknown")
        page = Path(DashboardBuilder(store, tmp_path / "dashboard").build(person_id=person))
        html = page.read_text(encoding="utf-8")
        assert dangerous not in html
        assert '\\u003c/script\\u003e' in html
        assert html.count("<script") == 2
        assert "Content-Security-Policy" in html and "connect-src 'none'" in html
        payload = dashboard_data(page)
        assert payload["claims"][0]["canonical_text"] == dangerous
        assert payload["scope"]["title"] == dangerous
        assert "尚不确定" in html and "MCP" not in html
        assert "<style>" in html and "<script src=" not in html
        assert payload["metadata"]["template_version"] == "dashboard-ui-v2"


def test_empty_page_is_honest_and_scope_ids_are_checked(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        person = store.ensure_person("local_person")
        builder = DashboardBuilder(store, tmp_path / "dashboard")
        payload = dashboard_data(builder.build(person_id=person))
        assert payload["claims"] == [] and payload["events"] == []
        assert payload["metadata"]["source_versions"] == []
        assert payload["metadata"]["freshness"] == "unknown"
        with pytest.raises(ValueError, match="unsafe"):
            builder.build(person_id="../escape")
        with pytest.raises(ValueError, match="not found"):
            builder.build(person_id="missing")
