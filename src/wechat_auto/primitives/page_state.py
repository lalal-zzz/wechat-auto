"""Conservative, composable Weixin page observations; never performs actions."""
from __future__ import annotations

import re

from wechat_auto.actions.semantics import PageId
from wechat_auto.primitives.page_catalog import PAGE_CATALOG_VERSION, match_page_catalog
from wechat_auto.primitives.moments_observation import has_calendar_rows

REGIONS = {
    "navigation": (0, 0, .07, 1),
    "conversation_list": (.07, .08, .25, 1),
    "conversation_header": (.25, .02, .68, .14),
    "conversation_body": (.25, .14, .68, .74),
    "composer": (.25, .74, 1, 1),
    "right_content": (.68, .02, 1, .90),
}


def classify_page(boxes: list[dict], size: tuple[int, int], *,
                  minimum_score: float = .65, geometry: dict | None = None) -> dict:
    """Infer simultaneous regions from OCR anchors, retaining unknown states.

    Ratios are broad observation zones, not click coordinates. Empty OCR cannot
    prove absence of a composer or panel. No result authorizes an action.
    """
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError("Screenshot dimensions must be positive")
    zones = dict(REGIONS)
    geometry = geometry or {}
    separators = geometry.get("vertical_separators", [])
    nav_splits = [s for s in separators if .04 <= s["fraction"] <= .12]
    list_splits = [s for s in separators if .18 <= s["fraction"] <= .42]
    nav_end = float(nav_splits[0]["fraction"]) if nav_splits else .07
    chat_start = float(list_splits[-1]["fraction"]) if list_splits else .25
    zones["navigation"] = (0, 0, nav_end, 1)
    zones["conversation_list"] = (nav_end, .04, chat_start, 1)
    zones["conversation_header"] = (chat_start, .02, .68, .14)
    zones["conversation_body"] = (chat_start, .14, .68, .74)
    boundary = geometry.get("right_panel_candidate")
    if boundary:
        split = float(boundary["fraction"])
        zones["right_content"] = (split, .02, 1, .90)
        zones["conversation_header"] = (chat_start, .02, split, .14)
        zones["conversation_body"] = (chat_start, .14, split, .74)
    zones["right_panel_header"] = (zones["right_content"][0], .025, .96, .12)
    candidates = geometry.get("composer_candidates", [])
    if candidates:
        x, y, w, h = candidates[0]["window_fraction"]
        zones["composer"] = (x, y, x + w, y + h)
    regions = {}
    for name, (left, top, right, bottom) in zones.items():
        regions[name] = [
            {"text": str(b.get("text", "")), "box_index": i,
             "score": float(b.get("score", 0))}
            for i, b in enumerate(boxes)
            if float(b.get("score", 0)) >= minimum_score
            and left <= (b["x"] + b["w"] / 2) / width <= right
            and top <= (b["y"] + b["h"] / 2) / height <= bottom
        ]

    def anchors(region, words):
        return [b for b in regions[region]
                if re.sub(r"\s+", "", b["text"]) in words]

    send = anchors("composer", {"发送", "发送(S)", "发送（S）"})
    no_chat = anchors("conversation_body", {"选择一个聊天", "暂无聊天", "未选择会话"})
    panel_types = []
    panel_evidence = []
    content_tabs = []
    for item in regions["right_panel_header"]:
        label = re.sub(r"\s+", "", item["text"])
        for suffix, kind in {"搜一搜": "search", "视频号": "channels",
                             "公众号": "official_account", "小程序": "mini_program"}.items():
            if boundary and (label == suffix or label.endswith(("-" + suffix, "—" + suffix))):
                content_tabs.append({"type": kind, "evidence_box_index": item["box_index"]})
                panel_types.append(kind)
                panel_evidence.append(item)
    for kind, words in {
        "official_account": {"公众号", "公众号文章", "阅读原文", "订阅号"},
        "channels": {"视频号", "视频号直播", "直播"},
        "search": {"搜一搜", "搜索结果"},
    }.items():
        matches = anchors("right_content", words)
        # Without a panel boundary, only header markers count. A chat bubble
        # containing '公众号' or '直播' in the right half is not a content pane.
        if not boundary:
            matches = [m for m in matches
                       if (boxes[m["box_index"]]["y"] + boxes[m["box_index"]]["h"] / 2)
                       / height < .18]
        if matches:
            panel_types.append(kind)
            panel_evidence.extend(matches)
    center_content = []
    center_evidence = []
    for kind, words in {
        "official_account": {"公众号", "订阅号"},
        "channels": {"视频号", "视频号直播"},
    }.items():
        matches = anchors("conversation_header", words)
        if matches:
            center_content.append(kind)
            center_evidence.extend(matches)
    search = anchors("conversation_list", {"联系人", "群聊", "聊天记录", "搜一搜"})
    page = "chat" if send else "unknown"
    if center_content and not send:
        page = "content_view"
    if no_chat and not send:
        page = "main_without_selected_chat"
    catalog_matches = match_page_catalog(boxes, size, bounds=zones,
                                         minimum_score=minimum_score)
    # A personal album opened from a profile is an embedded right tab in
    # current 4.x. Its header says Moments, with pinned/calendar rows below.
    # Keep it separate from the central profile and from a generic feed.
    if boundary and any(m['key'] == 'contact_profile' for m in catalog_matches):
        album_items = regions['right_content']
        left = zones['right_content'][0] * width
        date_column_right = left + (width-left)*.25
        dated = [item for item in album_items if
                 boxes[item['box_index']]['x'] <= date_column_right and
                 boxes[item['box_index']]['y'] > height*.12]
        pinned = any(re.sub(r'\s+', '', item['text']) == '置顶' for item in dated)
        calendar = has_calendar_rows([re.sub(r'\s+', '', item['text']) for item in dated])
        album_header = [item for item in regions['right_panel_header']
                        if re.sub(r'\s+', '', item['text']) == '朋友圈']
        if len(album_header) == 1 and (pinned or calendar):
            tab = {'type': 'moments_person', 'evidence_box_index': album_header[0]['box_index']}
            content_tabs.append(tab)
            panel_types.append('moments_person')
            panel_evidence.extend(album_header)
    embedded_pages = {"search": (PageId.WEB_SEARCH, "web_search"),
                      "channels": (PageId.CHANNELS, "channels"),
                      "official_account": (PageId.OFFICIAL_ACCOUNTS, "official_accounts"),
                      "mini_program": (PageId.MINI_PROGRAM, "mini_program"),
                      "moments_person": (PageId.MOMENTS_PERSON, "moments_person")}
    for tab in content_tabs:
        pid, key = embedded_pages[tab["type"]]
        catalog_matches.append({"page_id": int(pid), "key": key, "label": key,
                                "layer": "panel", "parent": "contact_profile" if key == 'moments_person' else "chat", "state": "candidate",
                                "presentation": "embedded_right_tab",
                                "evidence_box_indices": [tab["evidence_box_index"]],
                                "verification": "boundary_and_tab_header",
                                "action_authorized": False})
    # A selected Discover item can have no text heading in the content area.
    # Corroborate the OCR label with its actual accent selection rectangle.
    selected_map = {"朋友圈": (PageId.MOMENTS_FEED, "moments_feed"),
                    "视频号": (PageId.CHANNELS, "channels"),
                    "搜一搜": (PageId.WEB_SEARCH, "web_search"),
                    "小程序": (PageId.MINI_PROGRAM_LIST, "mini_program_list")}
    for row in geometry.get("selected_list_rows", []):
        for item in regions["conversation_list"]:
            box = boxes[item["box_index"]]
            cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
            if (item["text"] in selected_map and row["x"] <= cx <= row["x"] + row["w"]
                    and row["y"] <= cy <= row["y"] + row["h"]):
                pid, key = selected_map[item["text"]]
                catalog_matches.append({"page_id": int(pid), "key": key,
                                        "label": item["text"], "layer": "base",
                                        "parent": "discover", "state": "candidate",
                                        "evidence_box_indices": [item["box_index"]],
                                        "verification": "selected_row_and_ocr",
                                        "action_authorized": False})
    base_candidates = [m for m in catalog_matches if m["layer"] == "base"]
    if base_candidates:
        # A selected profile is more specific than the contacts list still
        # visible beside it. Preserve both candidates, choose the child page.
        keys = {m["key"] for m in base_candidates}
        strongest = max(base_candidates, key=lambda m: (
            m["parent"] in keys, len(m["evidence_box_indices"])))
        page = strongest["key"]
    ids = {"unknown": PageId.UNKNOWN, "chat": PageId.CHAT,
           "contacts": PageId.CONTACTS, "contact_profile": PageId.CONTACT_PROFILE,
           "main_without_selected_chat": PageId.MAIN_EMPTY}
    page_id = next((m["page_id"] for m in base_candidates if m["key"] == page),
                   int(ids.get(page, PageId.UNKNOWN)))
    chat_evidence = send if page in {"chat", "group_chat", "file_transfer"} else []
    composer_role = "chat_input" if chat_evidence else "unknown"
    if any(m["key"] == "moments_comment" for m in catalog_matches):
        composer_role = "moments_comment_candidate"
    return {
        "observer_version": 5, "catalog_version": PAGE_CATALOG_VERSION,
        "page": page, "page_id": page_id, "geometry": geometry,
        "page_candidates": base_candidates,
        "overlays": [m for m in catalog_matches if m["layer"] == "overlay"],
        "panels": [m for m in catalog_matches if m["layer"] == "panel"],
        "content_windows": [m for m in catalog_matches if m["layer"] == "window"],
        "chat_area": {"state": "present" if chat_evidence else "absent" if no_chat else "unknown",
                      "evidence": chat_evidence or no_chat},
        "composer": {"state": "present" if chat_evidence else "candidate" if candidates else "unknown",
                     "role": composer_role, "evidence": chat_evidence,
                     "geometry_candidates": candidates},
        "right_panel": {"state": "present" if panel_evidence else "candidate" if boundary else "unknown",
                        "types": sorted(set(panel_types)), "evidence": panel_evidence,
                        "tabs": content_tabs, "embedded": bool(boundary),
                        "bounds": zones["right_content"]},
        "content_view": {"state": "present" if center_evidence else "unknown",
                         "types": center_content, "evidence": center_evidence},
        "search_results": {"state": "present" if search else "unknown", "evidence": search},
        "regions": regions, "region_bounds": zones, "size": [width, height],
        "action_authorized": False,
        "limitations": ["OCR anchors are observations, not verified UI controls.",
                        "Missing text does not prove that a panel or empty input is absent.",
                        "Unknown layouts require fresh visual evidence or a guarded Agent review."],
    }
