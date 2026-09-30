"""Anonymized real-Weixin verification of database-planned no-OCR search."""
from __future__ import annotations

import argparse
import ctypes
import json

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.backends.dpapi_db import open_dpapi_wechat_db
from wechat_auto.backends.wechatauto_db import DatabaseConversationBackend
from wechat_auto.config import SessionConfig, WeChatConfig
from wechat_auto.core.application import Application
from wechat_auto.primitives import vision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--kind", choices=("contact", "group"), default="contact")
    parser.add_argument("--ui-query")
    args = parser.parse_args()
    query = args.query.strip()
    if not query:
        parser.error("--query must not be empty")

    with open_dpapi_wechat_db("data/.secrets", database_names=("contact.db",)) as db:
        backend = DatabaseConversationBackend(db)
        resolved = backend.resolve_chat(query)
        ui_query = (args.ui_query or query).strip()
        plan = backend.plan_search(
            ui_query, target_kind=args.kind, scene="main",
            expected_username=resolved["username"],
            allow_partial=args.ui_query is not None,
        )
    if not plan["safe_without_ocr"]:
        print(json.dumps({"ok": False, "error": "UnsafeSearchPlan",
                          "plan": plan}, ensure_ascii=False))
        return 2

    original_ocr = vision._get_ocr_engine
    hot_ocr_calls = 0

    def forbidden_ocr():
        nonlocal hot_ocr_calls
        hot_ocr_calls += 1
        raise AssertionError("OCR entered the no-OCR search path")

    config = WeChatConfig(
        ocr_verify_enabled=False, ocr_fallback_enabled=False,
        keyboard_input_mode="wmchar", keyboard_search_mode="click",
    )
    app = Application(config)
    try:
        vision._get_ocr_engine = forbidden_ocr
        app.connect()
        foreground_before = int(ctypes.windll.user32.GetForegroundWindow())
        skill = BasicSkill(app, config, SessionConfig(auto_activate=False))
        skill.open_navigation("chats")
        navigation = skill.open_chat(ui_query)
        foreground_after = int(ctypes.windll.user32.GetForegroundWindow())

        # Acceptance OCR is deliberately outside the hot path and counted
        # separately. It is used only by this verification script.
        vision._get_ocr_engine = original_ocr
        audit_config = WeChatConfig(ocr_verify_enabled=True, ocr_fallback_enabled=False)
        audit = BasicSkill(app, audit_config, SessionConfig(
            auto_activate=False, screenshot_dir="data/no_ocr_search_diagnostics"
        ))
        verified = audit.verify_open_chat(query)["verified"]
        print(json.dumps({
            "ok": bool(verified),
            "target_kind": plan["target_kind"],
            "search_scene": plan["scene"],
            "safe_without_ocr": plan["safe_without_ocr"],
            "hot_path_ocr_calls": hot_ocr_calls,
            "navigation_ocr_used": navigation["ocr_used"],
            "acceptance_audit": "ocr_once",
            "acceptance_verified": bool(verified),
            "foreground_unchanged": foreground_before == foreground_after,
        }, ensure_ascii=False))
        return 0 if verified else 3
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__,
                          "hot_path_ocr_calls": hot_ocr_calls}, ensure_ascii=False))
        return 1
    finally:
        vision._get_ocr_engine = original_ocr
        app.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
