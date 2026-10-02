"""Read-only HWND + page inventory. No coordinates or input are executed here."""
from __future__ import annotations

import time

from wechat_auto.primitives.page_catalog import PAGES

WINDOW_OBSERVER_VERSION = 1
KNOWN_PAGES = {page.key for page in PAGES}
MENU_PAGES = {"main_menu", "contact_more", "message_menu", "moments_menu"}
EDITOR_PAGES = {"contact_remark", "contact_permissions", "contact_tags", "moments_comment",
                "moments_publish", "group_name", "group_announcement", "group_invite", "file_picker"}


def window_summary(metadata: dict, observation: dict) -> dict:
    """Keep page labels and topology; omit private OCR, titles and evidence text."""
    public_metadata = {key: metadata[key] for key in (
        'hwnd', 'pid', 'class', 'width', 'height', 'rect', 'client_rect', 'owner_hwnd',
        'dpi', 'visible', 'enabled', 'minimized', 'is_main') if key in metadata}
    result = {**public_metadata, "observer_version": WINDOW_OBSERVER_VERSION,
              "observed_at": time.time(), "surfaces": [], "action_authorized": False,
              "identity_verified": False, "role": "main_client" if metadata["is_main"] else "unknown_window"}
    if not observation.get("ok"):
        return {**result, "status": "observation_failed", "error": observation.get("error", "observation_failed")}
    state = observation["state"]
    if list(state.get("size", [])) != [metadata["width"], metadata["height"]]:
        return {**result, "status": "stale", "error": "frame_geometry_changed"}
    seen = set()
    records = [(state.get("page", "unknown"), "base", {})]
    records.extend((item["key"], layer, item) for layer, field in (
        ("overlay", "overlays"), ("panel", "panels"), ("window", "content_windows")
    ) for item in state.get(field, []))
    if metadata['is_main'] and state.get('page') != 'contacts' and state.get('contact_section', {}).get('ok'):
        records.append(('contacts', 'panel', {'presentation': 'embedded_panel',
                                             'verification': 'exact_contacts_header_and_current_chevron'}))
    explicit = {(key, layer) for key, layer, item in records if item.get('presentation')}
    # Alternative base candidates are not promoted to targets. The base page
    # chosen by the existing multi-anchor classifier remains just an observation.
    for key, layer, item in records:
        if key not in KNOWN_PAGES:
            continue
        if layer == 'panel' and not item.get('presentation') and (key, layer) in explicit:
            continue
        if metadata["is_main"]:
            presentation = item.get("presentation") or (
                "embedded_overlay" if layer == "overlay" else "embedded_panel" if layer == "panel" else "embedded_main")
        else:
            presentation = "auxiliary_popup" if layer == "overlay" else "auxiliary_window"
        if (key, presentation) in seen:
            continue
        seen.add((key, presentation))
        result["surfaces"].append({"page": key, "layer": layer, "presentation": presentation,
                                   "verification": item.get("verification", "page_classifier")})
    keys = {item["page"] for item in result["surfaces"]}
    if not metadata["is_main"] and keys:
        result["role"] = ("menu_window" if keys & MENU_PAGES else
                          "editor_window" if keys & EDITOR_PAGES else
                          "dialog_window" if any(s["layer"] == "overlay" for s in result["surfaces"]) else
                          "content_window")
    result.update(status="recognized" if keys else "unknown", page=state.get("page", "unknown"),
                  blocking=bool(state.get("overlays")) or "ToolSaveBits" in metadata.get("class", ""),
                  composer_present=state.get("composer", {}).get("state") == "present",
                  right_panel_present=state.get("right_panel", {}).get("state") == "present")
    return result


def select_surface(windows: list[dict], page: str, *, presentation: str | None = None,
                   hwnd: int | None = None) -> dict:
    """Choose exactly one live surface; never select the first matching HWND."""
    if page not in KNOWN_PAGES:
        raise ValueError("Unknown target page")
    candidates = []
    for window in windows:
        if window.get("status") != "recognized" or not window.get("visible", True) or window.get("minimized"):
            continue
        if hwnd is not None and window["hwnd"] != hwnd:
            continue
        for surface in window["surfaces"]:
            if surface["page"] == page and (presentation is None or surface["presentation"] == presentation):
                candidates.append({"hwnd": window["hwnd"], "pid": window["pid"],
                                   "role": window["role"], "enabled": window.get("enabled", True), **surface})
    if len(candidates) != 1:
        return {"ok": False, "error": "ambiguous_target_window" if candidates else "target_page_not_found",
                "page": page, "candidates": candidates, "action_authorized": False}
    if not candidates[0]["enabled"]:
        return {"ok": False, "error": "target_window_disabled", "page": page,
                "candidates": candidates, "action_authorized": False}
    return {"ok": True, "target": candidates[0], "identity_verified": False, "action_authorized": False}


class WindowObserver:
    """Recheck process/owner/rect before and after recognition of every HWND."""

    def __init__(self, application, config):
        self.application, self.config = application, config

    def inspect(self, *, include_ocr: bool = True) -> list[dict]:
        from wechat_auto.primitives.vision import VisionAutomation

        summaries = []
        for initial in self.application.list_windows():
            try:
                before = self.application.describe_window(initial["hwnd"])
                if before.get("minimized"):
                    observation = {"ok": False, "error": "window_minimized"}
                else:
                    target = self.application.for_window(before["hwnd"])
                    observation = VisionAutomation(target, self.config).observe_page(include_ocr=include_ocr)
                after = self.application.describe_window(before["hwnd"])
                if any(before[key] != after[key] for key in (
                    "pid", "class", "rect", "client_rect", "owner_hwnd", "dpi", "enabled", "visible", "minimized"
                )):
                    summaries.append({**after, "status": "stale", "error": "window_changed_during_observation",
                                      "surfaces": [], "action_authorized": False})
                else:
                    summaries.append(window_summary(after, observation))
            except (RuntimeError, PermissionError):
                summaries.append({**initial, "status": "unavailable", "error": "window_unavailable",
                                  "surfaces": [], "action_authorized": False})
        return summaries
