"""Emoji skill - send builtin/custom emoji and stickers (Tier 1)."""

from __future__ import annotations

import logging
import time
from typing import Any

from wechat_auto.skills.base import BaseSkill
from wechat_auto.exceptions import EmojiNotFoundError
from wechat_auto.utils.retry import retry_on_failure

logger = logging.getLogger(__name__)


class EmojiSkill(BaseSkill):
    """Search and send emoji/stickers within a WeChat chat.

    Tier 1 skill covering:
        - send_builtin_sticker
    """

    name = "send_builtin_sticker"

    def _run(self, **params) -> Any:
        contact = params.get("contact", "")
        keyword = params.get("keyword", "")
        return self.send_emoji(contact, keyword)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=2, delay=1.0)
    def send_emoji(self, contact: str, keyword: str) -> None:
        """Search for an emoji by keyword and send it.

        Args:
            contact: Name of the contact or group.
            keyword: Search keyword for the emoji.
        """
        logger.info("Sending emoji to %s: keyword=%s", contact, keyword)
        self._activate()
        self._open_chat(contact)
        time.sleep(self._config.action_delay)

        self._open_emoji_panel()
        time.sleep(self._config.action_delay)

        self._search_emoji(keyword)
        time.sleep(self._config.action_delay)

        self._select_first_result()
        time.sleep(self._config.after_send_delay)
        logger.info("Emoji sent successfully.")

    def send_custom_emoji(self, contact: str, index: int = 0) -> None:
        """Send a custom emoji from the user's collection.

        Args:
            contact: Chat name.
            index: Index of the emoji in the custom collection (0-based).
        """
        logger.info("Sending custom emoji to %s: index=%d", contact, index)
        self._activate()
        self._open_chat(contact)
        time.sleep(self._config.action_delay)

        self._open_emoji_panel()
        time.sleep(self._config.action_delay)

        self._switch_to_custom_tab()
        time.sleep(self._config.action_delay)

        self._select_emoji_by_index(index)
        time.sleep(self._config.after_send_delay)
        logger.info("Custom emoji sent.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _open_emoji_panel(self) -> None:
        """Open the emoji panel by clicking the emoji button."""
        try:
            emoji_btn = self._finder.find_child_by_title(
                self.window, self._config.kw_emoji_btn, timeout=self._config.find_element_timeout
            )
            self._finder.click(emoji_btn)
        except Exception:
            logger.debug("Emoji button not found, trying keyboard shortcut.")
            self.window.type_keys(self._config.shortcut_emoji)

    def _search_emoji(self, keyword: str) -> None:
        """Type a keyword into the emoji search box."""
        try:
            search_box = self._finder.find_child_by_title(
                self.window, self._config.kw_search_box, timeout=self._config.search_timeout
            )
            search_box.click_input()
            search_box.set_edit_text(keyword)
        except Exception as exc:
            raise EmojiNotFoundError(f"Cannot find emoji search box for keyword: {keyword}") from exc

    def _select_first_result(self) -> None:
        """Click the first emoji result in the search results."""
        try:
            results = self._finder.find_all_children(self.window, control_type="ListItem")
            if not results:
                results = self._finder.find_all_children(self.window, control_type="Button")
            if results:
                self._finder.click(results[0])
            else:
                raise EmojiNotFoundError("No emoji results found.")
        except Exception as exc:
            raise EmojiNotFoundError("Failed to select emoji result.") from exc

    def _switch_to_custom_tab(self) -> None:
        """Switch to the custom emoji tab in the emoji panel."""
        try:
            tabs = self._finder.find_all_children(self.window, control_type="TabItem")
            if len(tabs) >= 2:
                self._finder.click(tabs[1])
        except Exception:
            logger.debug("Could not switch to custom emoji tab.")

    def _select_emoji_by_index(self, index: int) -> None:
        """Select an emoji by its position index."""
        try:
            items = self._finder.find_all_children(self.window, control_type="ListItem")
            if not items:
                items = self._finder.find_all_children(self.window, control_type="Button")
            if index < len(items):
                self._finder.click(items[index])
            else:
                raise EmojiNotFoundError(f"Emoji index {index} out of range (found {len(items)} items).")
        except Exception as exc:
            raise EmojiNotFoundError(f"Failed to select emoji at index {index}.") from exc
