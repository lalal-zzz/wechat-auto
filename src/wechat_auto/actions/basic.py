"""Single low-level action skill for Weixin 4.x.

Invariant: every UI mutation is delivered to the top-level HWND. OCR is only
an observer: it verifies a result or supplies a replacement coordinate after
the primary HWND route fails. It never performs the click itself.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from wechat_auto.exceptions import ChatNotFoundError
from wechat_auto.actions.base import BaseSkill
from wechat_auto.utils.clipboard import ClipboardHelper


@dataclass(frozen=True)
class BasicLayout:
    emoji_button: tuple[float, float] = (.372, .941)
    discover_button: tuple[float, float] = (.040, .366)
    moments_entry: tuple[float, float] = (.145, .145)


class BasicSkill(BaseSkill):
    """All primitive WeChat UI actions, with confirmation for external acts."""

    name = "basic_action"

    def __init__(self, *args, layout: BasicLayout | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if getattr(self._config, "action_driver", "hwnd") != "hwnd":
            raise ValueError("BasicSkill requires action_driver='hwnd'")
        self.layout = layout or BasicLayout()

    def _run(self, **params) -> Any:
        action = params.pop("action", "")
        handlers = {
            "open_chat": self.open_chat,
            "prepare_text": self.prepare_text,
            "send_text": self.send_text,
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
        return handlers[action](**params)

    def click(self, x: float, y: float) -> dict:
        self.keyboard_only.click_window_fraction(x, y)
        return {"action": "click", "transport": "hwnd", "point": [x, y]}

    def scroll(self, x: float, y: float, notches: int) -> dict:
        self.keyboard_only.wheel_window_fraction(x, y, notches)
        return {"action": "scroll", "transport": "hwnd", "notches": notches}

    def right_click(self, x: float, y: float) -> dict:
        self.keyboard_only.right_click_window_fraction(x, y)
        return {"action": "right_click", "transport": "hwnd", "point": [x, y]}

    def press_key(self, key: str) -> dict:
        self.keyboard_only.press_key(key)
        return {"action": "press_key", "transport": "hwnd", "key": key.lower()}

    def _title_matches(self, text: str) -> bool:
        from wechat_auto.primitives.vision import normalize_text
        boxes = self.vision.ocr(self.vision.region_of(.33, .04, .85, .12))
        joined = "".join(normalize_text(b.get("text", "")) for b in sorted(boxes, key=lambda b: (b["y"], b["x"])))
        alias = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9.]", "", normalize_text(text))
        return bool(alias and alias in joined)

    def open_chat(self, contact: str) -> dict:
        if not contact:
            raise ValueError("contact must not be empty")
        self._activate()
        driver = self.keyboard_only
        driver.open_chat(contact)
        time.sleep(self._config.action_delay + .5)
        if self._title_matches(contact):
            return {"action": "open_chat", "transport": "hwnd", "verified_by": "ocr"}
        if not getattr(self._config, "ocr_fallback_enabled", True):
            raise ChatNotFoundError(contact)
        return self._open_chat_ocr_fallback(contact)

    def _open_chat_ocr_fallback(self, contact: str) -> dict:
        from wechat_auto.primitives.vision import normalize_text
        driver = self.keyboard_only
        alias = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9.]", "", normalize_text(contact)) or contact
        driver.click_search()
        driver._select_all_clear()
        driver._type_text(alias)
        time.sleep(max(1.2, self._config.action_delay))
        region = self.vision.region_of(.05, .10, .55, .55)
        candidates = [b for b in self.vision.ocr(region)
                      if alias in normalize_text(b.get("text", ""))]
        # Ignore web suggestions above the explicit contact/group section by
        # preferring the bottom-most exact/containing result. Ambiguity remains
        # an error when multiple candidates share the same normalized label.
        exact = [b for b in candidates if normalize_text(b.get("text", "")) == alias]
        candidates = exact or candidates
        if len(candidates) != 1:
            raise ChatNotFoundError(f"{contact} (OCR candidates={len(candidates)})")
        box = candidates[0]
        width, height = self.vision.size()
        driver.click_window_fraction((box["x"] + box["w"] / 2) / width,
                                     (box["y"] + box["h"] / 2) / height)
        time.sleep(self._config.action_delay + .5)
        if not self._title_matches(alias):
            raise ChatNotFoundError(f"{contact} (replacement HWND click not verified)")
        return {"action": "open_chat", "transport": "hwnd", "verified_by": "ocr",
                "fallback": "ocr_coordinate"}

    def prepare_text(self, contact: str, text: str) -> dict:
        navigation = self.open_chat(contact)
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
        boxes = self.vision.find_text("朋友圈", timeout=2.0)
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
