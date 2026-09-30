"""Verify one real visible contact switch by local avatar, with zero hot-path OCR."""
from __future__ import annotations

import json

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.config import SessionConfig, WeChatConfig
from wechat_auto.core.application import Application
from wechat_auto.primitives import vision
from wechat_auto.storage import ProfileStore


def main() -> int:
    with ProfileStore("data/wechat_contact_profiles.sqlite3") as store:
        candidates = []
        for watched in store.watched_contacts():
            media = store.get_media(watched["wechat_id"])
            if media:
                candidates.append((watched, media["content"]))
    original_ocr = vision._get_ocr_engine
    hot_ocr_calls = 0

    def forbidden_ocr():
        nonlocal hot_ocr_calls
        hot_ocr_calls += 1
        raise AssertionError("OCR entered the avatar navigation path")

    config = WeChatConfig(ocr_verify_enabled=False, ocr_fallback_enabled=False)
    app = Application(config)
    try:
        vision._get_ocr_engine = forbidden_ocr
        app.connect()
        skill = BasicSkill(app, config, SessionConfig(auto_activate=False))
        skill.open_navigation("chats")
        chosen = None
        diagnostic_scores = []
        for watched, avatar in candidates:
            match = skill.vision.find_avatar(avatar)
            diagnostic = skill.vision.find_avatar(
                avatar, min_score=0.0, min_margin=-1.0
            )
            if diagnostic:
                diagnostic_scores.append({
                    "score": round(diagnostic["score"], 4),
                    "margin": round(diagnostic["margin"], 4),
                })
            selected = bool(match and skill.vision.is_green_at(
                .20, match["y"], radius=.012, min_pixels=8
            ))
            if match and not selected:
                chosen = (watched, avatar, match, selected)
                break
        if chosen is None:
            print(json.dumps({"ok": False, "error": "NoUniqueVisibleArchivedAvatar",
                              "avatars_checked": len(candidates),
                              "diagnostic_scores": diagnostic_scores,
                              "hot_path_ocr_calls": hot_ocr_calls}))
            return 2
        watched, avatar, match, selected_before = chosen
        navigation = skill.open_chat_by_avatar(avatar, verified_match=match)

        vision._get_ocr_engine = original_ocr
        audit_config = WeChatConfig(ocr_verify_enabled=True, ocr_fallback_enabled=False)
        audit = BasicSkill(app, audit_config, SessionConfig(
            auto_activate=False, screenshot_dir="data/no_ocr_avatar_diagnostics"
        ))
        verified = audit.verify_open_chat(watched["contact_query"])["verified"]
        print(json.dumps({
            "ok": bool(verified),
            "avatars_checked": len(candidates),
            "route": "local_avatar_template",
            "match_score": round(navigation["match_score"], 4),
            "match_margin": round(navigation["match_margin"], 4),
            "match_point": [round(match["x"], 4), round(match["y"], 4)],
            "selected_before": selected_before,
            "hot_path_ocr_calls": hot_ocr_calls,
            "acceptance_audit": "ocr_once",
            "acceptance_verified": bool(verified),
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
