"""Database-planned no-OCR chat navigation."""
from __future__ import annotations


class SearchRouter:
    """Reject ambiguous UI searches before asking BasicSkill to navigate."""

    def __init__(self, backend, basic_skill):
        self.backend = backend
        self.basic = basic_skill

    def open_chat(self, query: str, *, expected_username: str,
                  target_kind: str, scene: str | None = None,
                  ui_query: str | None = None) -> dict:
        if getattr(self.basic._config, "ocr_verify_enabled", False):
            raise RuntimeError("SearchRouter hot path requires OCR disabled")
        if scene is None:
            scene = {"contact": "contacts", "group": "groups"}.get(target_kind)
        if scene is None:
            raise ValueError("target_kind must be contact or group")
        actual_query = (ui_query or query).strip()
        plan = self.backend.plan_search(
            actual_query, target_kind=target_kind, scene=scene,
            expected_username=expected_username,
            allow_partial=ui_query is not None,
        )
        if not plan["safe_without_ocr"]:
            raise ValueError("Search is ambiguous in the requested Weixin scene")
        navigation = self.basic.open_chat(
            query, target_kind=target_kind, scene=scene, ui_query=actual_query,
        )
        if navigation.get("ocr_used"):
            raise RuntimeError("OCR unexpectedly entered the search hot path")
        if not navigation.get("opened", False):
            raise RuntimeError("Unverified search was prepared but not selected")
        return {"plan": plan, "navigation": navigation, "ocr_used": False}

    def try_open_chat(self, query: str, *, expected_username: str,
                      target_kind: str, scene: str | None = None,
                      ui_query: str | None = None, verifier=None,
                      fallback=None) -> dict:
        """Return an explicit stale/unavailable result instead of blind success."""
        try:
            result = self.open_chat(
                query, expected_username=expected_username,
                target_kind=target_kind, scene=scene, ui_query=ui_query,
            )
        except (ValueError, RuntimeError) as exc:
            return {
                "ok": False, "status": "ambiguous_or_unavailable",
                "error": type(exc).__name__, "possible_reasons": [
                    "deleted_or_removed", "blocked", "renamed",
                    "left_group", "local_profile_stale",
                ],
            }
        verified = True if verifier is None else bool(verifier(query))
        fallback_used = False
        if not verified and fallback is not None:
            fallback_used = True
            verified = bool(fallback(query, expected_username, target_kind))
        if not verified:
            return {
                "ok": False, "status": "ui_target_not_verified",
                "fallback_used": fallback_used, "possible_reasons": [
                    "deleted_or_removed", "blocked", "renamed",
                    "left_group", "local_profile_stale",
                ],
            }
        return {"ok": True, "status": "opened", "fallback_used": fallback_used,
                **result}
