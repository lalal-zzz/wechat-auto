"""Single low-level action skill for Weixin 4.x.

Invariant: every UI mutation is delivered through the Weixin HWND route (the
top-level window or its unique visible MMUI render child). OCR is only an
observer: it verifies a result or supplies a replacement coordinate. It never
performs the click itself.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wechat_auto.actions.base import BaseSkill
from wechat_auto.actions.contracts import ActionReceipt, LayoutProfile
from wechat_auto.exceptions import ChatNotFoundError
from wechat_auto.utils.clipboard import ClipboardHelper


@dataclass(frozen=True)
class BasicLayout:
    chats_button: tuple[float, float] = (.027, .143)
    recent_first_row_y: float = .145
    recent_row_step: float = .082
    recent_row_x: float = .170
    emoji_button: tuple[float, float] = (.372, .941)
    discover_button: tuple[float, float] = (.040, .366)
    moments_entry: tuple[float, float] = (.145, .145)
    contacts_button: tuple[float, float] = (.027, .207)


class BasicSkill(BaseSkill):
    """All primitive WeChat UI actions, with confirmation for external acts."""

    name = "basic_action"

    def __init__(self, *args, layout: BasicLayout | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if getattr(self._config, "action_driver", "hwnd") != "hwnd":
            raise ValueError("BasicSkill requires action_driver='hwnd'")
        self.layout = layout or BasicLayout()
        profile_path = getattr(self._config, "layout_profile_path", None)
        self.layout_profile = LayoutProfile.load(profile_path) if profile_path else None

    def _validate_layout(self) -> None:
        if self.layout_profile is None:
            return
        width, height = self.vision.size()
        if not self.layout_profile.matches(width, height):
            raise RuntimeError(
                f"WeChat layout mismatch: expected "
                f"{self.layout_profile.client_width}x{self.layout_profile.client_height}, "
                f"observed {width}x{height}"
            )

    def _receipt(self, action: str, *, point: tuple[float, float] | None = None,
                 verified_by: str = "not_verified", **extra) -> dict:
        result = ActionReceipt(
            action=action, point=point, verified_by=verified_by,
            layout_profile=self.layout_profile.profile_id if self.layout_profile else "default",
        ).to_dict()
        result.update(extra)
        return result

    def _run(self, **params) -> Any:
        action = params.pop("action", "")
        handlers = {
            "open_chat": self.open_chat,
            "open_visible_chat_row": self.open_visible_chat_row,
            "open_navigation": self.open_navigation,
            "open_chat_by_avatar": self.open_chat_by_avatar,
            "open_contact_profile": self.open_contact_profile,
            "execute_contact_action": self.execute_contact_action,
            "page_operation": self.page_operation,
            "prepare_search": self.prepare_search,
            "open_search_content": self.open_search_content,
            "prepare_text": self.prepare_text,
            "send_text": self.send_text,
            "prepare_mention": self.prepare_mention,
            "send_mention": self.send_mention,
            "prepare_quote": self.prepare_quote,
            "send_quote": self.send_quote,
            "copy_message": self.copy_message,
            "prepare_profile_observation": self.prepare_profile_observation,
            "capture_visible_signature": self.capture_visible_signature,
            "click": self.click,
            "right_click": self.right_click,
            "scroll": self.scroll,
            "press_key": self.press_key,
            "prepare_file": self.prepare_file,
            "send_file": self.send_file,
            "prepare_image": self.prepare_image,
            "send_image": self.send_image,
            "open_emoji": self.open_emoji,
            "send_sticker": self.send_sticker,
            "send_sticker_by_id": self.send_sticker_by_id,
            "open_moments": self.open_moments,
            "like_moment": self.like_moment,
            "comment_moment": self.comment_moment,
        }
        if action not in handlers:
            raise ValueError(f"Unknown basic action: {action}")
        result = handlers[action](**params)
        if isinstance(result, dict) and "receipt_id" not in result:
            receipt = self._receipt(
                str(result.get("action") or action),
                verified_by=str(result.get("verified_by") or "not_verified"),
            )
            receipt.update(result)
            return receipt
        return result

    def click(self, x: float, y: float) -> dict:
        self._validate_layout()
        self.keyboard_only.click_window_fraction(x, y)
        return self._receipt("click", point=(x, y))

    def observe_windows(self, *, include_ocr: bool = True) -> list[dict]:
        """Observe every visible client-process top-level window separately."""
        from wechat_auto.primitives.vision import VisionAutomation

        return [{**window, "observation": VisionAutomation(
            self._app.for_window(window["hwnd"]), self._config
        ).observe_page(include_ocr=include_ocr)} for window in self._app.list_windows()]

    def resize_window(self, width: int, height: int) -> dict:
        self._app.resize_window(width, height)
        time.sleep(self._config.action_delay + .5)
        left, top, right, bottom = self._app.get_window_rect()
        return self._receipt("resize_window", verified_by="window_rectangle",
                             requested_size=[width, height], actual_size=[right-left, bottom-top],
                             success=(right-left, bottom-top) == (width, height))

    def drag_divider(self, start: tuple[float, float], end: tuple[float, float]) -> dict:
        """Move only a separator corroborated in the current captured frame."""
        from wechat_auto.primitives.page_geometry import observe_geometry
        image = self.vision.capture()
        if image is None:
            raise RuntimeError("Divider capture unavailable")
        before = observe_geometry(image)
        px, py = start[0] * image.width, start[1] * image.height
        vertical = [s for s in before['vertical_separators']
                    if abs(s['x'] - px) <= 2 and .15 * image.height < py < .7 * image.height]
        horizontal = [c for c in before['composer_candidates']
                      if abs(c['y'] - py) <= 3 and c['x'] + 15 < px < c['x'] + c['w'] - 15]
        if len(vertical) + len(horizontal) != 1:
            raise RuntimeError("Drag start is not a unique current divider")
        self.keyboard_only.drag_window_fraction(start, end)
        after_image = self.vision.capture()
        after = observe_geometry(after_image) if after_image else {}
        if vertical:
            candidates = [s['x'] for s in after.get('vertical_separators', [])
                          if abs(s['x'] - end[0] * image.width) <= 6]
            original = vertical[0]['x']
        else:
            candidates = [c['y'] for c in after.get('composer_candidates', [])
                          if abs(c['y'] - end[1] * image.height) <= 6]
            original = horizontal[0]['y']
        verified = len(candidates) == 1 and abs(candidates[0] - original) >= 5
        return self._receipt("drag_divider", verified_by="divider_geometry" if verified else "postcondition_failed",
                             success=verified, dispatched=True, automatic_retry=False,
                             start=list(start), end=list(end))

    def prepare_search(self, query: str) -> dict:
        """Populate the main search field, verifying its focus without choosing a result."""
        from wechat_auto.primitives.page_controls import find_search_clear
        from wechat_auto.primitives.page_geometry import observe_geometry
        from wechat_auto.primitives.vision import normalize_text

        if not query.strip() or any(ord(c) < 32 for c in query):
            raise ValueError("Search query must be non-empty printable text")
        image = self.vision.capture()
        if image is None:
            raise RuntimeError("Search window capture unavailable")
        fields = observe_geometry(image).get("search_field_candidates", [])
        if len(fields) != 1:
            raise RuntimeError("Search field geometry is absent or ambiguous")
        field = fields[0]
        # Exclude the magnifier as well as the clear/microphone zone. OCR can
        # join the magnifier and placeholder into one text box ("Q 搜索").
        region = (field["x"] + int(field["w"] * .13), field["y"],
                  int(field["w"] * .75), field["h"])
        def field_text(boxes):
            # OCR can turn the microphone/clear icon into a letter. Their
            # rightmost control zone is outside the editable text span.
            return "".join(normalize_text(b.get("text", "")) for b in boxes
                           if field["x"] + field["w"] * .08 < b["x"] + b["w"] / 2
                           < field["x"] + field["w"] * .88)
        prior = self.vision.recognize_image(image.crop((region[0], region[1],
            region[0] + region[2], region[1] + region[3])), region=region, window_size=image.size)
        existing = field_text(prior)
        if not existing:
            raise RuntimeError("Search field text unavailable; typing stopped")
        driver = self.keyboard_only
        if existing and existing != "搜索":
            clear = find_search_clear(image, field)
            if len(clear) != 1:
                raise RuntimeError("Search clear control is absent or ambiguous")
            driver.click_window_fraction(clear[0][0] / image.width, clear[0][1] / image.height)
            time.sleep(self._config.action_delay)
            empty = field_text(self.vision.ocr(region))
            if empty != "搜索":
                raise RuntimeError("Search field did not clear; typing stopped")
        driver.click_window_fraction((field["x"] + field["w"] * .4) / image.width,
                                     (field["y"] + field["h"] / 2) / image.height)
        with driver.foreground_lease():
            driver._type_text(query)
            time.sleep(self._config.action_delay + .5)
        observed = self.vision.ocr(region)
        joined = field_text(observed)
        if normalize_text(query) != joined:
            raise RuntimeError("Search field text was not verified; no result selected")
        return self._receipt("prepare_search", verified_by="search_field_ocr",
                             selection_required=True, sent=False)

    def open_search_content(self, query: str) -> dict:
        """Open the exact verified main-field query in the embedded network pane."""
        from wechat_auto.primitives.vision import VisionAutomation, normalize_text

        self.prepare_search(query)
        choices = []
        for window in self._app.list_windows():
            if window["is_main"] or "ToolSaveBits" not in window["class"]:
                continue
            target = self._app.for_window(window["hwnd"])
            result = VisionAutomation(target, self._config).observe_page()
            if not result.get("ok"):
                continue
            boxes = [b for b in result["boxes"] if b.get("score", 0) >= .65
                     and normalize_text(b.get("text", "")) == "搜索网络结果"]
            for heading in boxes:
                # This heading is inert. The first suggestion below it is the
                # clickable exact query, before expanded/similar suggestions.
                entries = [b for b in result["boxes"] if b.get("score", 0) >= .65
                           and normalize_text(b.get("text", "")) == normalize_text(query)
                           and heading["y"] + heading["h"] < b["y"]
                           < heading["y"] + heading["h"] * 5]
                if entries:
                    box = min(entries, key=lambda b: b["y"])
                    choices.append((target, self._box_center_fraction(box, tuple(result["state"]["size"]))))
        if len(choices) != 1:
            raise RuntimeError("Network search entry absent or ambiguous; no result selected")
        target, point = choices[0]
        skill = BasicSkill(target, self._config, self._session)
        skill.keyboard_only.foreground_mode = "never"
        skill.keyboard_only.click_window_fraction(*point)
        time.sleep(self._config.action_delay + .8)
        result = self.vision.observe_page()
        state = result.get("state", {})
        panel = state.get("right_panel", {})
        verified = result.get("ok") and panel.get("state") == "present" and "search" in panel.get("types", [])
        if verified:
            verified = any(normalize_text(query) in normalize_text(result["boxes"][t["evidence_box_index"]]["text"])
                           for t in panel.get("tabs", []))
        return self._receipt("open_search_content", verified_by="embedded_query_tab_ocr" if verified else "postcondition_failed",
                             success=bool(verified), sent=False, automatic_retry=False)

    def page_operation(self, operation: str, *, hwnd: int | None = None,
                       expected_page: str | None = None) -> dict:
        """Execute one registered navigation transition, verifying both ends.

        Mutation operations are deliberately absent: they retain their dedicated
        confirmation APIs. Unknown pages/points and competing controls stop here.
        """
        from wechat_auto.actions.pages import page_keys, resolve_operation
        from wechat_auto.primitives.vision import VisionAutomation

        target = self._app.for_window(hwnd) if hwnd is not None else self._app
        observer = self.vision if target.handle == self._app.handle else VisionAutomation(target, self._config)
        before = observer.observe_page()
        if not before.get("ok"):
            raise RuntimeError("Page observation unavailable; action stopped")
        if expected_page and expected_page not in page_keys(before["state"]):
            raise RuntimeError("Expected page does not match current window")
        spec, source = resolve_operation(operation, before["state"])
        if operation == "close_content_tab":
            panel = before["state"]["right_panel"]
            if panel["state"] != "present" or not panel.get("embedded") or len(panel.get("tabs", [])) != 1:
                raise RuntimeError("Embedded content tab is absent or ambiguous")
            embedded = {p["key"] for p in before["state"].get("panels", [])
                        if p.get("presentation") == "embedded_right_tab" and p["key"] in spec.sources}
            if len(embedded) != 1:
                raise RuntimeError("Embedded content page is absent or ambiguous")
            source = next(iter(embedded))
        windows_before = self._app.list_windows()
        # The main PrintWindow frame does not contain independent Qt popups.
        if target.handle == self._app.handle:
            for window in windows_before:
                if not window["is_main"] and "ToolSaveBits" in window["class"]:
                    raise RuntimeError("An auxiliary popup must be handled before main navigation")
        if spec.method == "wm_close" and target.handle == self._app.handle:
            raise PermissionError("Use navigation to leave an embedded page; main client cannot be closed")
        skill = self if target.handle == self._app.handle else BasicSkill(
            target, self._config, self._session)
        # Popup activation dismisses Qt menus; preserve their current focus.
        driver = skill.keyboard_only
        old_mode = driver.foreground_mode
        if target.handle != self._app.handle:
            driver.foreground_mode = "never"
        elif operation == "open_main_menu":
            # Returning focus to another application immediately dismisses
            # this menu. Keep the client foreground until it is handled.
            driver.foreground_mode = "leave"
        point = None
        used_layout = "observed_frame"
        try:
            if spec.method in {"ocr", "ocr_cancel"}:
                boxes = [b for b in before["boxes"] if b.get("score", 0) >= .65
                         and re.sub(r"\s+", "", b.get("text", "")) in spec.anchors]
                # Discover labels must be in the navigation list, not body text.
                if source in {"discover", "moments_feed", "channels", "web_search", "mini_program_list"}:
                    bounds = before["state"]["region_bounds"]["conversation_list"]
                    width, _height = before["state"]["size"]
                    boxes = [b for b in boxes if bounds[0] <= (b["x"] + b["w"] / 2) / width <= bounds[2]]
                if len(boxes) != 1:
                    raise RuntimeError("Page control absent or ambiguous; action stopped")
                point = self._box_center_fraction(boxes[0], tuple(before["state"]["size"]))
                driver.click_window_fraction(*point)
            elif spec.method == "calibrated_point":
                metadata = target.window_metadata()
                theme = before["state"]["geometry"].get("theme", "unknown")
                filename = (f"{metadata['wechat_version']}_{metadata['width']}x{metadata['height']}_"
                            f"{metadata['dpi']}_{theme}.json")
                path = Path(getattr(self._config, "page_layout_directory", "data/layouts")) / filename
                profile = LayoutProfile.load(path)
                used_layout = profile.profile_id
                if profile.theme == "unknown" or not profile.matches(
                    metadata["width"], metadata["height"], dpi=metadata["dpi"],
                    wechat_version=metadata["wechat_version"], theme=theme,
                ):
                    raise RuntimeError("Version, size, DPI or theme does not match page layout")
                values = (profile.page_operations or {}).get(f"{source}:{operation}")
                if not values or len(values) != 2 or not all(0 <= v <= 1 for v in values):
                    raise RuntimeError("Page operation has no calibrated coordinate")
                point = tuple(values)
                driver.click_window_fraction(*point)
            elif spec.method == "tab_close":
                candidate = before["state"]["right_panel"]["tabs"][0].get("close_candidate")
                if not candidate:
                    raise RuntimeError("Tab close glyph is absent or ambiguous")
                point = tuple(candidate["window_fraction"])
                driver.click_content_fraction(*point)
            elif spec.method == "escape":
                driver.press_key("escape")
            elif spec.method == "wm_close":
                driver.close_window()
            else:
                raise RuntimeError("Page operation is not implemented")
            time.sleep(self._config.action_delay + .5)
        finally:
            driver.foreground_mode = old_mode
        windows_after = self._app.list_windows()
        visible = {w["hwnd"] for w in windows_after}
        if spec.method in {"ocr_cancel", "escape", "wm_close"}:
            verified = target.handle not in visible
            after_keys = []
            if not verified:
                after = observer.observe_page()
                after_keys = sorted(page_keys(after.get("state", {})))
                verified = bool(after.get("ok") and source not in after_keys)
        else:
            verified = False
            after_keys = []
            # Check main target plus newly created auxiliary windows. Existing
            # unrelated windows must not satisfy this operation's postcondition.
            old_handles = {w["hwnd"] for w in windows_before}
            for window in windows_after:
                if window["hwnd"] != target.handle and window["hwnd"] in old_handles:
                    continue
                post = VisionAutomation(self._app.for_window(window["hwnd"]), self._config).observe_page()
                keys = page_keys(post.get("state", {}))
                after_keys.extend(sorted(keys))
                if (post.get("ok") and keys & set(spec.targets)
                        and (not spec.require_source_exit or source not in keys)):
                    verified = True
        return self._receipt("page_operation", point=point,
                             verified_by="post_action_page_observation" if verified else "postcondition_failed",
                             operation=operation, source_page=source, after_pages=after_keys,
                             hwnd=target.handle, success=verified, automatic_retry=False,
                             layout_profile=used_layout,
                             observer_version=before["state"].get("observer_version"),
                             catalog_version=before["state"].get("catalog_version"))

    def _semantic_click(self, page: int, element: int) -> tuple[float, float]:
        if self.layout_profile is None:
            raise RuntimeError("A versioned layout profile is required for semantic UI actions")
        self._validate_layout()
        point = self.layout_profile.point_for(page, element)
        self.keyboard_only.click_window_fraction(*point)
        time.sleep(self._config.action_delay)
        return point

    @staticmethod
    def _require_contact_confirmation(username: str, action: str, *, confirm: bool,
                                      confirmation_target: str) -> None:
        if not confirm or confirmation_target != username:
            raise PermissionError(
                f"{action} requires explicit confirmation bound to {username!r}"
            )

    def execute_contact_action(self, *, username: str, contact_action: str, ui_query: str,
                               visible_wechat_id: str = "", value: str = "",
                               confirm: bool = False,
                               confirmation_target: str = "") -> dict:
        """Execute a DB-resolved contact plan through calibrated semantic IDs.

        ``username`` is the stable target. ``ui_query`` and visible ID are only
        navigation/verification attributes and never become identity keys.
        """
        from wechat_auto.actions.semantics import PageId

        action = contact_action
        if action not in {"open_contact", "set_remark", "delete_contact"}:
            raise ValueError(f"Unsupported contact action: {action}")
        if not username or username.endswith("@chatroom"):
            raise ValueError("A non-group stable username is required")
        opened = self.open_contact_profile(
            ui_query, expected_wechat_id=visible_wechat_id or None,
        )
        if action == "open_contact":
            return self._receipt(
                action, verified_by=opened["verified_by"], username=username,
                semantic_target="21", sent=False,
            )

        self._require_contact_confirmation(
            username, action, confirm=confirm, confirmation_target=confirmation_target,
        )
        if action == "set_remark":
            if not value.strip():
                raise ValueError("set_remark requires a non-empty value")
            self._semantic_click(PageId.CONTACT_PROFILE, 3)
            self._semantic_click(PageId.CONTACT_REMARK, 1)
            self.keyboard_only._select_all_clear()
            self.keyboard_only._type_text(value)
            self._semantic_click(PageId.CONTACT_REMARK, 2)
            time.sleep(self._config.action_delay + .5)
            observed = "".join(str(box.get("text", "")) for box in self.vision.ocr())
            if value not in observed:
                raise RuntimeError("Remark UI action completed but post-action OCR did not verify it")
            return self._receipt(
                action, verified_by="profile_ocr_after_write", username=username,
                semantic_target="21.03", value=value, requires_database_resync=True,
            )

        self._semantic_click(PageId.CONTACT_PROFILE, 9)
        self._semantic_click(PageId.CONTACT_MORE, 3)
        self._semantic_click(PageId.CONFIRM_DIALOG, 2)
        return self._receipt(
            action, verified_by="confirmation_dialog_action", username=username,
            semantic_target="22.03", requires_database_resync=True,
        )

    def scroll(self, x: float, y: float, notches: int) -> dict:
        self._validate_layout()
        self.keyboard_only.wheel_window_fraction(x, y, notches)
        return self._receipt("scroll", point=(x, y), notches=notches)

    def right_click(self, x: float, y: float) -> dict:
        self._validate_layout()
        self.keyboard_only.right_click_window_fraction(x, y)
        return self._receipt("right_click", point=(x, y))

    def press_key(self, key: str) -> dict:
        self._validate_layout()
        self.keyboard_only.press_key(key)
        return self._receipt("press_key", key=key.lower())

    def open_navigation(self, page: str, *, attempts: int = 3) -> dict:
        """Open Chats or Contacts and verify via a tiny green-pixel probe.

        This hot-path state check never initializes OCR.  It is suitable for
        frequent routing while OCR remains reserved for explicit recovery.
        """
        points = {"chats": self.layout.chats_button,
                  "contacts": self.layout.contacts_button}
        if page not in points:
            raise ValueError("page must be 'chats' or 'contacts'")
        if attempts < 1:
            raise ValueError("attempts must be positive")
        self._activate()
        point = points[page]
        for count in range(1, attempts + 1):
            self.keyboard_only.click_window_fraction(*point)
            time.sleep(self._config.action_delay + .25)
            if self.vision.is_green_at(*point):
                return {"action": "open_navigation", "transport": "hwnd",
                        "page": page, "verified_by": "pixel_probe",
                        "ocr_used": False, "attempts": count}
            # Pixel probes can miss dark-mode/theme/layout changes.  When
            # OCR verification is explicitly enabled, observe the page marker
            # after the HWND click.  OCR never performs the action.
            if getattr(self._config, "ocr_verify_enabled", False):
                from wechat_auto.primitives.vision import normalize_text
                markers = {"contacts": {"通讯录", "联系人"},
                           "chats": {"微信", "聊天"}}[page]
                observed = {normalize_text(box.get("text", ""))
                            for box in self.vision.ocr()}
                if observed & markers:
                    return {"action": "open_navigation", "transport": "hwnd",
                            "page": page, "verified_by": "ocr_page_marker",
                            "ocr_used": True, "attempts": count}
        raise RuntimeError(f"Navigation page {page!r} was not pixel-verified")

    def open_chat_by_avatar(self, avatar: bytes, *, verified_match: dict | None = None) -> dict:
        """Open a visible recent chat by a unique local avatar match, no OCR."""
        page = self.open_navigation("chats")
        match = verified_match or self.vision.find_avatar(avatar)
        if match is None:
            raise ChatNotFoundError("Unique visible avatar was not found")
        if (match.get("ocr_used") is not False or match.get("score", 0) < .72
                or match.get("margin", 0) < .025):
            raise ChatNotFoundError("Avatar match did not meet the verified threshold")
        # The avatar itself is drawn by MMUI and may not accept background
        # window messages; the text area in the same verified row does.
        self.keyboard_only.click_window_fraction_sync(.17, match["y"])
        time.sleep(self._config.action_delay + .5)
        return {"action": "open_chat_by_avatar", "transport": "hwnd",
                "navigation": page, "verified_by": "local_avatar_template",
                "ocr_used": False, "match_score": match["score"],
                "match_margin": match["margin"]}

    def open_visible_chat_row(self, row_index: int) -> dict:
        """Open one visible recent-chat row without OCR or text input."""
        if not isinstance(row_index, int) or not 0 <= row_index <= 9:
            raise ValueError("row_index must be an integer from 0 through 9")
        page = self.open_navigation("chats")
        y = self.layout.recent_first_row_y + self.layout.recent_row_step * row_index
        if y >= .98:
            raise ValueError("row_index is outside the visible chat-list area")
        self.keyboard_only.click_window_fraction(self.layout.recent_row_x, y)
        time.sleep(self._config.action_delay + .35)
        if not self.vision.is_green_at(.20, y, radius=.018, min_pixels=8):
            raise ChatNotFoundError("Visible chat row was not pixel-verified")
        return {"action": "open_visible_chat_row", "transport": "hwnd",
                "row_index": row_index, "navigation": page,
                "verified_by": "selection_pixel_probe", "ocr_used": False}

    def _title_matches(self, text: str) -> bool:
        from wechat_auto.primitives.vision import normalize_text
        # The optional search/detail pane occupies the right third of wide
        # Weixin windows.  The conversation title starts near x=.24.
        boxes = self.vision.ocr(self.vision.region_of(.23, .04, .66, .12))
        joined = "".join(normalize_text(b.get("text", "")) for b in sorted(boxes, key=lambda b: (b["y"], b["x"])))
        alias = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9.]", "", normalize_text(text))
        return bool(alias and alias in joined)

    def verify_open_chat(self, contact: str) -> dict:
        """Observe whether *contact* is the currently open conversation."""
        if not getattr(self._config, "ocr_verify_enabled", False):
            return {"verified": False, "reason": "ocr_verification_disabled"}
        return {
            "verified": self._title_matches(contact),
            "reason": "title_ocr",
            "screenshot": self.vision.shot("basic", "open-chat-verify"),
        }

    def _choose_context_menu_item(self, keyword: str) -> tuple[float, float]:
        """Return one OCR-observed context-menu item as a window fraction.

        OCR remains an observer; the returned coordinate is clicked only via
        ``KeyboardOnlyDriver``.  Ambiguous menus are rejected rather than
        guessed.
        """
        if not getattr(self._config, "ocr_verify_enabled", False):
            raise RuntimeError("OCR verification must be enabled for menu text location")
        from wechat_auto.primitives.vision import match_boxes

        boxes = match_boxes(self.vision.ocr(), keyword, exact=True)
        if len(boxes) != 1:
            raise RuntimeError(f"Context-menu item {keyword!r} is ambiguous or absent ({len(boxes)})")
        box = boxes[0]
        width, height = self.vision.size()
        if width <= 0 or height <= 0:
            raise RuntimeError("Cannot determine WeChat window size for menu action")
        return ((box["x"] + box["w"] / 2) / width,
                (box["y"] + box["h"] / 2) / height)

    def open_chat(self, contact: str, *, target_kind: str = "contact",
                  scene: str | None = None, ui_query: str | None = None) -> dict:
        if not contact:
            raise ValueError("contact must not be empty")
        if target_kind not in {"contact", "group"}:
            raise ValueError("target_kind must be 'contact' or 'group'")
        scene = scene or {"contact": "contacts", "group": "groups"}[target_kind]
        if scene not in {"contacts", "groups", "main"}:
            raise ValueError("scene must be contacts, groups or main")
        actual_query = (ui_query or contact).strip()
        self._activate()
        if scene in {"contacts", "groups"}:
            self.open_navigation("contacts")
        driver = self.keyboard_only
        driver.prepare_chat_search(actual_query)
        time.sleep(self._config.action_delay + .5)
        if not getattr(self._config, "ocr_verify_enabled", False):
            return {"action": "prepare_chat_search", "transport": "hwnd",
                    "opened": False, "selection_required": True,
                    "verified_by": "not_verified", "ocr_used": False}
        return self._open_chat_ocr_fallback(
            contact, target_kind=target_kind, ui_query=actual_query,
        )

    def _open_chat_ocr_fallback(self, contact: str, *, target_kind: str = "contact",
                                ui_query: str | None = None) -> dict:
        from wechat_auto.primitives.vision import normalize_text, parse_search_sections
        driver = self.keyboard_only
        alias = normalize_text(ui_query or contact)
        # Safety gate: if the query is absent from the actual search box, the
        # focused editor may be the current chat. Never press Enter or click a
        # result in that state.
        search_box = self.vision.region_of(.05, .035, .23, .11)
        search_text = "".join(normalize_text(b.get("text", ""))
                              for b in self.vision.ocr(search_box))
        if not alias or alias not in search_text:
            raise ChatNotFoundError("search_focus_not_verified")
        boxes = self.vision.ocr(self.vision.region_of(.05, .09, .42, .72))
        sections = parse_search_sections(boxes)
        candidates = [box for section in sections if section["section"] == target_kind
                      for box in section["items"]
                      if alias in normalize_text(box.get("text", ""))]
        if len(candidates) != 1:
            raise ChatNotFoundError(f"search_result_unavailable:{target_kind}:{len(candidates)}")
        box = candidates[0]
        width, height = self.vision.size()
        driver.click_window_fraction((box["x"] + box["w"] / 2) / width,
                                     (box["y"] + box["h"] / 2) / height)
        time.sleep(self._config.action_delay + .5)
        if not self._title_matches(contact):
            raise ChatNotFoundError("opened_title_not_verified")
        return {"action": "open_chat", "transport": "hwnd", "verified_by": "ocr",
                "opened": True, "ocr_used": True,
                "fallback": "verified_section_coordinate"}

    @staticmethod
    def _box_center_fraction(box: dict, size: tuple[int, int]) -> tuple[float, float]:
        width, height = size
        if width <= 0 or height <= 0:
            raise RuntimeError("Cannot determine WeChat window size")
        return ((box["x"] + box["w"] / 2) / width,
                (box["y"] + box["h"] / 2) / height)

    def _open_and_verify_contact_box(self, box: dict, expected_wechat_id: str | None) -> dict:
        """Open one OCR-confirmed Contacts-list row and verify its profile."""
        from wechat_auto.primitives.vision import normalize_text
        point = self._box_center_fraction(box, self.vision.size())
        self.keyboard_only.click_window_fraction(*point)
        time.sleep(self._config.action_delay + .7)
        profile_boxes = self.vision.ocr()
        profile_text = "".join(normalize_text(item.get("text", "")) for item in profile_boxes)
        if "微信号" not in profile_text:
            raise ChatNotFoundError("Contact profile was not verified")
        if expected_wechat_id:
            expected = normalize_text(expected_wechat_id)
            values = []
            for label in profile_boxes:
                text = normalize_text(label.get('text', ''))
                if not text.startswith('微信号'):
                    continue
                suffix = text[len('微信号'):].lstrip(':：')
                if suffix:
                    values.append(suffix)
                else:
                    values.extend(normalize_text(item.get('text', '')) for item in profile_boxes
                                  if item['x'] >= label['x'] + label['w']
                                  and abs(item['y'] + item['h']/2 - label['y'] - label['h']/2)
                                  <= max(item['h'], label['h']) * .5)
            if len(values) != 1 or values[0] != expected:
                raise ChatNotFoundError("Visible WeChat id did not match the archived contact")
        return {"action": "open_contact_profile", "transport": "hwnd",
                "verified_by": "contacts_page_and_profile_ocr", "ocr_used": True,
                "result_point": list(point), "sent": False}

    def open_contact_profile(self, contact: str, expected_wechat_id: str | None = None,
                             *, max_contact_scroll_pages: int = 12) -> dict:
        """Open one exact contact from the Contacts page, never global content.

        OCR observes the Contacts marker and supplies the exact result
        coordinate.  The resulting click is still dispatched exclusively by
        the HWND driver.  Ambiguous or unverified results are rejected.
        """
        if not contact:
            raise ValueError("contact must not be empty")
        if not getattr(self._config, "ocr_verify_enabled", False):
            raise RuntimeError("OCR verification is required for contact-profile navigation")
        from wechat_auto.primitives.vision import normalize_text, scoped_search_matches

        self._activate()
        driver = self.keyboard_only
        driver.press_key("escape")
        page_boxes: list[dict] = []
        for _ in range(3):
            driver.click_window_fraction(*self.layout.contacts_button)
            time.sleep(self._config.action_delay + .5)
            page_boxes = self.vision.ocr()
            if any("通讯录" in normalize_text(box.get("text", "")) for box in page_boxes):
                break
        else:
            self.vision.shot("profile", "contacts-page-not-verified")
            raise ChatNotFoundError("Contacts page was not verified")

        # A visible exact row is safer than driving a search box and avoids
        # crossing into chat, article or service-account result categories.
        width, _ = self.vision.size()
        query = normalize_text(contact)
        def visible_matches(items: list[dict]) -> list[dict]:
            return [box for box in items
                    if box["x"] < width * .24 and box["y"] > 100
                    and normalize_text(box.get("text", "")) == query]

        visible = visible_matches(page_boxes)
        if len(visible) == 1:
            return self._open_and_verify_contact_box(visible[0], expected_wechat_id)
        if len(visible) > 1:
            raise ChatNotFoundError("Visible Contacts-list result is ambiguous")
        if max_contact_scroll_pages < 0:
            raise ValueError("max_contact_scroll_pages must not be negative")
        for _ in range(max_contact_scroll_pages):
            driver.wheel_window_fraction(.14, .72, 6)
            time.sleep(self._config.scroll_delay)
            visible = visible_matches(self.vision.ocr())
            if len(visible) == 1:
                return self._open_and_verify_contact_box(visible[0], expected_wechat_id)
            if len(visible) > 1:
                raise ChatNotFoundError("Visible Contacts-list result is ambiguous")

        driver.focus_search()
        driver._select_all_clear()
        driver._type_text(contact)
        time.sleep(max(1.2, self._config.action_delay))
        boxes = self.vision.ocr(self.vision.region_of(.04, .05, .40, .70))
        headers = [box for box in boxes
                   if normalize_text(box.get("text", "")) in {"联系人", "通讯录"}]
        if not headers:
            self.vision.shot("profile", "contacts-search-section-not-verified")
            raise ChatNotFoundError("Contact-only search section was not verified")
        matches, _ = scoped_search_matches(boxes, contact, 'contact')
        if len(matches) != 1:
            self.vision.shot("profile", "contact-result-not-unique")
            raise ChatNotFoundError(f"Contact-only OCR candidates={len(matches)}")
        return self._open_and_verify_contact_box(matches[0], expected_wechat_id)

    def prepare_text(self, contact: str, text: str) -> dict:
        navigation = self.open_chat(contact)
        if navigation.get('opened') is not True:
            raise ChatNotFoundError('chat_not_opened_or_verified')
        self.keyboard_only.click_input()
        self.keyboard_only._type_text(text)
        return {"action": "prepare_text", "transport": "hwnd", "navigation": navigation,
                "sent": False}

    def send_text(self, contact: str, text: str, *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Sending requires confirm=True")
        result = self.prepare_text(contact, text)
        self.keyboard_only._enter()
        result.update(action="send_text", sent=True)
        return result

    def prepare_mention(self, contact: str, member: str, text: str = "") -> dict:
        """Prepare a group @ draft through the focused WeChat editor.

        WeChat may require selecting the popup suggestion to turn the typed
        label into a real mention.  This method intentionally leaves that
        selection visible for confirmation instead of guessing a menu point.
        """
        if not member.strip():
            raise ValueError("member must not be empty")
        navigation = self.open_chat(contact)
        self.keyboard_only.click_input()
        self.keyboard_only._type_text(f"@{member}")
        if text:
            self.keyboard_only._type_text(f" {text}")
        return {"action": "prepare_mention", "transport": "hwnd", "navigation": navigation,
                "member": member, "text": text, "sent": False,
                "selection_required": True}

    def send_mention(self, contact: str, member: str, text: str = "", *,
                     confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Mention send requires confirm=True")
        navigation = self.open_chat(contact)
        self.keyboard_only.click_input()
        self.keyboard_only._type_text(f"@{member}")
        # In WeChat's group editor, Enter accepts the highlighted @ suggestion.
        # If no suggestion is shown, the explicit-confirmation boundary still
        # prevents this path from running accidentally.
        self.keyboard_only._enter()
        if text:
            self.keyboard_only._type_text(text)
        self.keyboard_only._enter()
        result = {"action": "send_mention", "transport": "hwnd", "navigation": navigation,
                  "member": member, "text": text, "sent": True,
                  "suggestion_selected_by": "enter"}
        return result

    def prepare_quote(self, contact: str, message: tuple[float, float],
                      quote_menu: tuple[float, float] | None = None, text: str = "") -> dict:
        """Open the message context menu, choose its calibrated Quote point,
        and prepare a reply draft.  Coordinates are supplied by calibration or
        OCR observation; this method itself only dispatches HWND messages.
        """
        navigation = self.open_chat(contact)
        self.right_click(*message)
        time.sleep(self._config.click_delay)
        if quote_menu is None:
            quote_menu = self._choose_context_menu_item(self._config.kw_quote)
        self.click(*quote_menu)
        if text:
            self.keyboard_only.click_input()
            self.keyboard_only._type_text(text)
        return {"action": "prepare_quote", "transport": "hwnd", "navigation": navigation,
                "message_point": list(message), "quote_menu": list(quote_menu),
                "text": text, "sent": False}

    def send_quote(self, contact: str, message: tuple[float, float],
                   quote_menu: tuple[float, float] | None = None, text: str = "", *,
                   confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Quote reply requires confirm=True")
        if not text.strip():
            raise ValueError("text must not be empty")
        result = self.prepare_quote(contact, message, quote_menu, text)
        self.keyboard_only._enter()
        result.update(action="send_quote", sent=True)
        return result

    def copy_message(self, message: tuple[float, float], *, contact: str | None = None,
                     copy_menu: tuple[float, float] | None = None) -> dict:
        """Copy one calibrated message via WeChat's normal context menu.

        Clipboard contents may be private: this method never reads or returns
        them.  A caller can supply a manually calibrated menu point, or opt
        into OCR observation for a unique ``复制`` menu label.
        """
        navigation = self.open_chat(contact) if contact else None
        self.right_click(*message)
        time.sleep(self._config.click_delay)
        if copy_menu is None:
            copy_menu = self._choose_context_menu_item(self._config.kw_copy_msg)
        self.click(*copy_menu)
        return {"action": "copy_message", "transport": "hwnd", "navigation": navigation,
                "message_point": list(message), "copy_menu": list(copy_menu),
                "clipboard_read": False}

    def prepare_profile_observation(self, contact: str,
                                    profile_entry: tuple[float, float] | None = None,
                                    expected_wechat_id: str | None = None) -> dict:
        """Open a chat and its calibrated profile-card entry; never sends."""
        if profile_entry is None:
            return self.open_contact_profile(contact, expected_wechat_id)
        navigation = self.open_chat(contact)
        self.click(*profile_entry)
        time.sleep(self._config.action_delay)
        return {"action": "prepare_profile_observation", "transport": "hwnd",
                "navigation": navigation, "profile_entry": list(profile_entry), "sent": False}

    def capture_visible_signature(self, wechat_id: str, database_path: str) -> dict:
        """OCR a visible profile card and save only an explicit signature value.

        This method does not navigate or click.  It intentionally refuses to
        infer a signature from arbitrary chat text, so a failed OCR pass cannot
        erase a previously observed value.
        """
        if not getattr(self._config, "ocr_verify_enabled", False):
            raise RuntimeError("OCR verification must be enabled for profile observation")
        from wechat_auto.primitives.vision import normalize_text
        from wechat_auto.storage import ProfileStore

        boxes = self.vision.ocr()
        signature = None
        for box in boxes:
            text = str(box.get("text", "")).strip()
            compact = normalize_text(text)
            if "个性签名" not in compact:
                continue
            remainder = compact.split("个性签名", 1)[1].lstrip(":：")
            if remainder:
                signature = remainder
                break
        with ProfileStore(database_path) as store:
            result = store.record_signature_observation(wechat_id, signature)
        return {"action": "capture_visible_signature", "transport": "none",
                "signature_observed": result["observed"], "status": result["status"],
                "changed_fields": result["changed_fields"]}

    def _prepare_clipboard_payload(self, contact: str, setter, value: str) -> dict:
        navigation = self.open_chat(contact)
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"Expected a file: {path}")
        setter(str(path))
        self.keyboard_only.click_input()
        self.keyboard_only._paste()
        return {"transport": "hwnd", "navigation": navigation,
                "path": str(path), "sent": False}

    def prepare_file(self, contact: str, path: str) -> dict:
        result = self._prepare_clipboard_payload(
            contact, lambda value: ClipboardHelper.set_files([value]), path
        )
        result["action"] = "prepare_file"
        return result

    def send_file(self, contact: str, path: str, *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("File send requires confirm=True")
        result = self.prepare_file(contact, path)
        self.keyboard_only._enter()
        result.update(action="send_file", sent=True)
        return result

    def prepare_image(self, contact: str, path: str) -> dict:
        result = self._prepare_clipboard_payload(contact, ClipboardHelper.set_image, path)
        result["action"] = "prepare_image"
        return result

    def send_image(self, contact: str, path: str, *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Image send requires confirm=True")
        result = self.prepare_image(contact, path)
        self.keyboard_only._enter()
        result.update(action="send_image", sent=True)
        return result

    def open_emoji(self) -> dict:
        return self.click(*self.layout.emoji_button) | {"action": "open_emoji"}

    def send_sticker(self, cell: tuple[float, float], *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Sticker send requires confirm=True")
        self.open_emoji()
        time.sleep(self._config.action_delay)
        self.click(*cell)
        return {"action": "send_sticker", "transport": "hwnd", "sent": True}

    def send_sticker_by_id(self, contact: str, sticker_id: str, catalog_path: str,
                           *, confirm: bool = False) -> dict:
        """Send one previously verified catalog item; never infer identity here."""
        if not confirm:
            raise PermissionError("Sticker send requires confirm=True")
        from wechat_auto.storage import StickerCatalog
        with StickerCatalog(catalog_path) as catalog:
            item = catalog.resolve(sticker_id, require_verified=True)
        if item is None:
            raise ValueError(f"Sticker is absent or unverified: {sticker_id}")
        current_size = self.vision.size()
        if tuple(current_size) != tuple(item["layout_size"]):
            raise ValueError(
                f"Sticker layout changed: catalog={item['layout_size']} current={current_size}"
            )
        navigation = self.open_chat(contact)
        self.open_emoji()
        time.sleep(self._config.action_delay)
        if item["page_steps"]:
            self.scroll(.65, .70, item["page_steps"])
            time.sleep(self._config.scroll_delay)
        self.click(*item["cell"])
        return {"action": "send_sticker_by_id", "transport": "hwnd",
                "sticker_id": sticker_id, "hint": item["hint"],
                "navigation": navigation, "sent": True}

    def open_moments(self) -> dict:
        self.click(*self.layout.discover_button)
        time.sleep(self._config.action_delay)
        boxes = (self.vision.find_text("朋友圈", timeout=2.0)
                 if getattr(self._config, "ocr_verify_enabled", False) else [])
        if boxes:
            box = boxes[0]
            width, height = self.vision.size()
            self.keyboard_only.click_window_fraction((box["x"] + box["w"] / 2) / width,
                                                     (box["y"] + box["h"] / 2) / height)
        else:
            self.click(*self.layout.moments_entry)
        time.sleep(self._config.action_delay)
        return {"action": "open_moments", "transport": "hwnd",
                "located_by": "ocr" if boxes else "calibrated_anchor",
                "verification": "not_guaranteed"}

    def like_moment(self, menu: tuple[float, float], like: tuple[float, float], *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Like requires confirm=True")
        self.click(*menu)
        time.sleep(self._config.click_delay)
        self.click(*like)
        return {"action": "like_moment", "transport": "hwnd", "dispatched": True}

    def comment_moment(self, menu: tuple[float, float], comment_button: tuple[float, float],
                       input_box: tuple[float, float], text: str, *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Comment requires confirm=True")
        for point in (menu, comment_button, input_box):
            self.click(*point)
            time.sleep(self._config.click_delay)
        self.keyboard_only._type_text(text)
        self.keyboard_only._enter()
        return {"action": "comment_moment", "transport": "hwnd", "dispatched": True}
