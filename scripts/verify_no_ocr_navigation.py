"""Real-Weixin check proving hot-path navigation does not initialize OCR."""
from __future__ import annotations

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
        raise AssertionError("OCR entered a no-OCR navigation path")

    vision._get_ocr_engine = forbidden_ocr
    config = WeChatConfig(ocr_verify_enabled=False, ocr_fallback_enabled=False)
    app = Application(config)
    try:
        app.connect()
        skill = BasicSkill(app, config, SessionConfig(auto_activate=False))
        contacts = skill.open_navigation("contacts")
        chats = skill.open_navigation("chats")
        print(json.dumps({
            "ok": True,
            "contacts_verified_by": contacts["verified_by"],
            "chats_verified_by": chats["verified_by"],
            "ocr_calls": calls,
            "transport": "hwnd",
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__,
                          "ocr_calls": calls}, ensure_ascii=False))
        return 1
    finally:
        app.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
