from pathlib import Path

import pytest

from wechat_auto.memory import MarkdownMemory, MemoryStore
from wechat_auto.memory.report import FullReportBuilder, render_markdown


def test_full_report_embeds_all_formal_text_and_excludes_candidates(tmp_path):
    root = tmp_path / "memory"
    with MemoryStore(tmp_path / "memory.sqlite3") as store:
        cid = store.ensure_conversation("test_chat", conversation_type="direct", title="测试会话")
        memory = MarkdownMemory(root, store)
        text = "# 全面月度\n\n" + "\n\n".join(f"具体偏好与关系 {i}" for i in range(601))
        memory.write("conversation", cid, text, period="2025-01", input_fingerprint="a")
        memory.write("conversation", cid, "# 未复核旧版", period="2025-02", input_fingerprint="b")
        (tmp_path / "candidate.md").write_text("不得发布的候选", encoding="utf-8")
        path = FullReportBuilder(store, root / "dashboard", memory_root=root).build(
            conversation_id=cid, accepted_versions={("conversation", cid, "2025-01"): 1},
            source_months=["2025-01", "2025-02", "2025-03"])
        html = Path(path).read_text(encoding="utf-8")
        assert "具体偏好与关系 600" in html
        assert "未复核旧版" not in html and "不得发布的候选" not in html
        assert "待完成月份：2025-02、2025-03" in html
        version = store.current_version("conversation", cid, "2025-01")
        Path(version["markdown_path"]).write_text("tampered", encoding="utf-8")
        previous_html = Path(path).read_bytes()
        with pytest.raises(ValueError, match="path/hash"):
            FullReportBuilder(store, root / "dashboard", memory_root=root).build(
                conversation_id=cid, accepted_versions={("conversation", cid, "2025-01"): 1})
        assert Path(path).read_bytes() == previous_html
        html = Path(FullReportBuilder(store, root / "dashboard", memory_root=root).build(
            conversation_id=cid)).read_text(encoding="utf-8")
        assert "tampered" not in html and "具体偏好与关系 600" not in html


def test_markdown_escapes_active_html_and_preserves_structured_content():
    text = "---\ntype: month\n---\n# 喜好\n\n<script>alert(1)</script>\n\n| 人 | 喜好 |\n|---|---|\n| 我 | 茶 |\n\n- **事实**\n\n```\n遗漏也保留\n"
    html = render_markdown(text)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<table>" in html and "<td>茶</td>" in html
    assert "<strong>事实</strong>" in html and "遗漏也保留" in html
