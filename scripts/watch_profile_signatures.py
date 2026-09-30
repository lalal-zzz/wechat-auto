"""Observe signature changes for an explicit fixed-contact watchlist.

Run once by default. It searches from the Contacts page, requires a unique
contact result and verifies the opened profile page before OCR.  A legacy
calibrated chat-profile entry can still be supplied explicitly. It never
sends messages or fetches remote media.
"""
from __future__ import annotations

import argparse
import json

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.config import SessionConfig, WeChatConfig
from wechat_auto.core.application import Application
from wechat_auto.storage import ProfileStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Observe fixed contacts' visible profile signatures")
    parser.add_argument("--database", default="data/wechat_contact_profiles.sqlite3")
    parser.add_argument("--profile-entry-x", type=float,
                        help="legacy calibrated chat-profile entry x fraction")
    parser.add_argument("--profile-entry-y", type=float,
                        help="legacy calibrated chat-profile entry y fraction")
    parser.add_argument("--limit", type=int, default=None,
                        help="Observe at most this many watched contacts")
    parser.add_argument("--screenshot-dir", default=None,
                        help="optional local-only diagnostic screenshot directory")
    args = parser.parse_args()
    if (args.profile_entry_x is None) != (args.profile_entry_y is None):
        parser.error("--profile-entry-x and --profile-entry-y must be supplied together")
    with ProfileStore(args.database) as store:
        watched = store.watched_contacts()
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be at least 1")
        watched = watched[:args.limit]
    # Qt's focused search field consumes the normal Ctrl+V route reliably;
    # direct WM_CHAR is not consistently forwarded by Weixin 4.x.
    app = Application(WeChatConfig(
        ocr_verify_enabled=True, ocr_fallback_enabled=False, keyboard_input_mode="winmsg",
        keyboard_search_mode="shortcut",
    ))
    try:
        app.connect()
        skill = BasicSkill(app, app.config, SessionConfig(
            auto_activate=False, screenshot_dir=args.screenshot_dir
        ))
        observed = missed = failed = 0
        failure_types: dict[str, int] = {}
        failure_stages: dict[str, int] = {}
        for item in watched:
            try:
                skill.prepare_profile_observation(
                    item["contact_query"],
                    ((args.profile_entry_x, args.profile_entry_y)
                     if args.profile_entry_x is not None else None),
                    expected_wechat_id=item["wechat_id"],
                )
                result = skill.capture_visible_signature(item["wechat_id"], args.database)
                observed += int(result["signature_observed"])
                missed += int(not result["signature_observed"])
            except Exception as exc:
                failed += 1
                name = type(exc).__name__
                failure_types[name] = failure_types.get(name, 0) + 1
                # BasicSkill emits only generic navigation stages here; do
                # not expose contact query text or OCR content in logs.
                stage = str(exc)
                failure_stages[stage] = failure_stages.get(stage, 0) + 1
        print(json.dumps({"ok": True, "watchlist": len(watched), "observed": observed,
                          "not_visible": missed, "failed": failed,
                          "failure_types": failure_types,
                          "failure_stages": failure_stages}, ensure_ascii=False))
        return 0
    finally:
        app.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
