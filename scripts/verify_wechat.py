"""Run a safe, real-device WeChat 4.x smoke check.

This script only attaches to an already logged-in WeChat client, opens the
named conversation, and verifies its title via OCR.  It never sends a message,
changes WeChat data, or prints captured chat/profile content.
"""
from __future__ import annotations

import argparse
import json
import sys

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.config import SessionConfig, WeChatConfig
from wechat_auto.core.application import Application


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe real-WeChat smoke verification")
    parser.add_argument("--contact", default="文件传输助手", help="conversation to open; no message is sent")
    parser.add_argument("--screenshot-dir", default=None, help="optional local directory for verification screenshots")
    args = parser.parse_args()

    config = WeChatConfig(ocr_verify_enabled=True, ocr_fallback_enabled=False)
    session = SessionConfig(auto_activate=True, screenshot_dir=args.screenshot_dir)
    app = Application(config)
    try:
        app.connect()
        skill = BasicSkill(app, config, session)
        result = skill.open_chat(args.contact)
        verification = skill.verify_open_chat(args.contact)
        print(json.dumps({
            "ok": bool(verification["verified"]),
            "action": result["action"],
            "transport": result["transport"],
            "verified_by": result.get("verified_by"),
            "reason": verification["reason"],
        }, ensure_ascii=False))
        return 0 if verification["verified"] else 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__}, ensure_ascii=False))
        return 1
    finally:
        app.disconnect()


if __name__ == "__main__":
    sys.exit(main())
