"""Quote skill - quote and reply to messages (Tier 1)."""

from __future__ import annotations

import logging
import time
from typing import Any

from wechat_auto.skills.base import BaseSkill
from wechat_auto.exceptions import ElementNotFoundError, SendMessageError
from wechat_auto.utils.clipboard import ClipboardHelper
from wechat_auto.utils.keyboard import KeyboardHelper
from wechat_auto.utils.retry import retry_on_failure

logger = logging.getLogger(__name__)


class QuoteSkill(BaseSkill):
    """Quote a message and reply in WeChat.

    Tier 1 skill covering:
        - send_quoted_message
    """

    name = "send_quoted_message"

    def _run(self, **params) -> Any:
        contact = params.get("contact", "")
        reply_text = params.get("reply_text", "")
        message_index = params.get("message_index", -1)
        return self.quote_and_reply(contact, reply_text, message_index)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=2, delay=1.0)
    def quote_and_reply(self, contact: str, reply_text: str, message_index: int = -1) -> None:
        """Quote a message and type a reply.

        Args:
            contact: Chat name.
            reply_text: Reply text.
            message_index: Index in the visible message list (-1 = latest).
        """
        logger.info("Quote-reply to %s: %s", contact, reply_text[:40])
        self._activate()
        self._open_chat(contact)
        time.sleep(self._config.action_delay)

        message = self._get_message_element(message_index)
        if message is None:
            raise ElementNotFoundError("Could not locate target message.")

        self._finder.right_click(message)
        time.sleep(self._config.action_delay)

        self._click_context_menu_item(self._config.kw_quote)
        time.sleep(self._config.action_delay)

        self._type_and_send_reply(reply_text)
        time.sleep(self._config.after_send_delay)
        logger.info("Quote-reply sent successfully.")

    def forward_message(self, contact: str, target_contact: str, message_index: int = -1) -> None:
        """Forward a message to another contact.

        Args:
            contact: Source chat name.
            target_contact: Target chat to forward to.
            message_index: Index of message to forward.
        """
        logger.info("Forward message from %s to %s", contact, target_contact)
        self._activate()
        self._open_chat(contact)
        time.sleep(self._config.action_delay)

        message = self._get_message_element(message_index)
        if message is None:
            raise ElementNotFoundError("Could not locate target message.")

        self._finder.right_click(message)
        time.sleep(self._config.action_delay)

        self._click_context_menu_item(self._config.kw_forward)
        time.sleep(self._config.action_delay)

        ClipboardHelper.set_text(target_contact)
        KeyboardHelper.paste(self.window)
        time.sleep(self._config.action_delay)
        KeyboardHelper.press_enter(self.window)
        time.sleep(self._config.after_send_delay)
        logger.info("Message forwarded.")

    def copy_message(self, contact: str, message_index: int = -1) -> str:
        """Copy a message to clipboard and return its text.

        Args:
            contact: Chat name.
            message_index: Message index.

        Returns:
            The clipboard text after copy.
        """
        self._activate()
        self._open_chat(contact)
        time.sleep(self._config.action_delay)

        message = self._get_message_element(message_index)
        if message is None:
            raise ElementNotFoundError("Could not locate target message.")

        self._finder.right_click(message)
        time.sleep(self._config.action_delay)
        self._click_context_menu_item(self._config.kw_copy_msg)
        time.sleep(self._config.action_delay)

        return ClipboardHelper.get_text()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_message_element(self, index: int):
        """Get a message element from the chat list by index."""
        try:
            messages = self._finder.find_all_children(self.window, control_type="ListItem")
            if not messages:
                return None
            idx = index if index >= 0 else len(messages) + index
            if 0 <= idx < len(messages):
                return messages[idx]
            return None
        except Exception:
            return None

    def _click_context_menu_item(self, keyword: str) -> None:
        """Click an item in the right-click context menu."""
        try:
            menu_item = self._finder.find_child_by_title(
                self.window, keyword, timeout=self._config.find_element_timeout
            )
            self._finder.click(menu_item)
        except Exception as exc:
            raise ElementNotFoundError(f"Context menu item '{keyword}' not found.") from exc

    def _type_and_send_reply(self, text: str) -> None:
        """Type reply text and press Enter to send."""
        edit_box = None
        try:
            edit_boxes = self._finder.find_all_children(self.window, control_type="Edit")
            if edit_boxes:
                edit_box = edit_boxes[-1]
        except Exception:
            pass

        if edit_box is None:
            raise SendMessageError("Cannot find message input box for reply.")

        edit_box.click_input()
        time.sleep(self._config.click_delay)

        ClipboardHelper.set_text(text)
        KeyboardHelper.paste(self.window)
        time.sleep(self._config.action_delay)
        KeyboardHelper.press_enter(self.window)
