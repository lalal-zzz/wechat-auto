from pathlib import Path

from wechat_auto.memory import MemoryStore
from wechat_auto.memory.dashboard import DashboardBuilder


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
