"""Switch one visible recent-chat row using HWND messages and no OCR."""
from __future__ import annotations

import ctypes
import json

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.config import SessionConfig, WeChatConfig
from wechat_auto.core.application import Application
from wechat_auto.primitives import vision


def main() -> int:
    calls = 0

    def forbidden_ocr():
        nonlocal calls
        calls += 1
        raise AssertionError("OCR entered visible-row switch path")

    original = vision._get_ocr_engine
    vision._get_ocr_engine = forbidden_ocr
    config = WeChatConfig(ocr_verify_enabled=False, ocr_fallback_enabled=False)
    app = Application(config)
    try:
        app.connect()
        foreground_before = int(ctypes.windll.user32.GetForegroundWindow())
        skill = BasicSkill(app, config, SessionConfig(auto_activate=False))
        result = skill.open_visible_chat_row(0)
        foreground_after = int(ctypes.windll.user32.GetForegroundWindow())
        print(json.dumps({
            "ok": True,
            "transport": result["transport"],
            "verified_by": result["verified_by"],
            "ocr_calls": calls,
            "foreground_unchanged": foreground_before == foreground_after,
            "identity_redacted": True,
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__,
                          "ocr_calls": calls, "identity_redacted": True}))
        return 1
    finally:
        vision._get_ocr_engine = original
        app.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
