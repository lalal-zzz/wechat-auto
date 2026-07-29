"""History skill - chat history retrieval and search (Tier 1)."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from wechat_auto.skills.base import BaseSkill
from wechat_auto.exceptions import ElementNotFoundError
from wechat_auto.utils.clipboard import ClipboardHelper
from wechat_auto.utils.keyboard import KeyboardHelper
from wechat_auto.utils.retry import retry_on_failure

logger = logging.getLogger(__name__)


class HistorySkill(BaseSkill):
    """Retrieve and navigate chat history in WeChat.

    Tier 1 skill covering:
        - get_chat_history
    """

    name = "get_chat_history"

    def _run(self, **params) -> Any:
        contact = params.get("contact", "")
        max_messages = params.get("max_messages", 20)
        return self.get_messages(contact, max_messages)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=2, delay=1.0)
    def get_messages(self, contact: str, max_messages: int = 20) -> list[dict]:
        """Get visible chat messages.

        Args:
            contact: Chat name.
            max_messages: Maximum number of messages to return.

        Returns:
            List of message dicts with keys: sender, content, time.
        """
        logger.info("Getting %d messages from %s", max_messages, contact)
        self._activate()
        self._open_chat(contact)
        time.sleep(self._config.action_delay)

        messages = self._collect_messages(max_messages)
        logger.info("Collected %d messages.", len(messages))
        return messages

    def scroll_up(self, contact: str, steps: int = 3) -> None:
        """Scroll up in the chat to load older messages.

        Args:
            contact: Chat name.
            steps: Number of scroll steps.
        """
        logger.info("Scrolling up in chat %s (%d steps)", contact, steps)
        self._activate()
        self._open_chat(contact)
        time.sleep(self._config.action_delay)

        message_area = self._find_message_area()
        if message_area is None:
            raise ElementNotFoundError("Cannot locate message area for scrolling.")

        for _ in range(steps):
            message_area.wheel_mouse_input(wheel_dist=-3)
            time.sleep(self._config.scroll_delay)
        time.sleep(self._config.history_page_wait)
        logger.info("Scroll completed.")

    def search_in_chat(self, contact: str, keyword: str) -> list[dict]:
        """Search for messages containing keyword within a chat.

        Args:
            contact: Chat name.
            keyword: Search keyword.

        Returns:
            List of matching messages.
        """
        logger.info("Searching in chat %s: %s", contact, keyword)
        self._activate()
        self._open_chat(contact)
        time.sleep(self._config.action_delay)

        self.window.type_keys("^f")
        time.sleep(self._config.action_delay)

        ClipboardHelper.set_text(keyword)
        KeyboardHelper.paste(self.window)
        time.sleep(self._config.search_timeout)

        results = self._collect_messages(20)
        KeyboardHelper.press_escape(self.window)
        return results

    def get_latest_message(self, contact: str) -> Optional[dict]:
        """Get the latest message in a chat."""
        messages = self.get_messages(contact, max_messages=1)
        return messages[-1] if messages else None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_message_area(self):
        """Find the scrollable message list area."""
        try:
            return self._finder.find_child_by_title(
                self.window, "", control_type="List", timeout=self._config.find_element_timeout
            )
        except Exception:
            try:
                lists = self._finder.find_all_children(self.window, control_type="List")
                if lists:
                    return lists[0]
            except Exception:
                pass
        return None

    def _collect_messages(self, max_messages: int) -> list[dict]:
        """Collect message data from visible UI elements."""
        results: list[dict] = []
        try:
            items = self._finder.find_all_children(self.window, control_type="ListItem")
            if not items:
                return results
            items = items[-max_messages:]
            for item in items:
                msg = self._parse_message_item(item)
                if msg:
                    results.append(msg)
        except Exception as exc:
            logger.debug("Error collecting messages: %s", exc)
        return results

    def _parse_message_item(self, item) -> Optional[dict]:
        """Parse a single ListItem into a message dict."""
        try:
            name = ""
            content = ""
            timestamp = ""

            texts = item.children()
            text_parts = []
            for child in texts:
                try:
                    t = child.window_text()
                    if t:
                        text_parts.append(t)
                except Exception:
                    continue

            if len(text_parts) >= 2:
                name = text_parts[0]
                content = " ".join(text_parts[1:])
            elif len(text_parts) == 1:
                content = text_parts[0]

            return {"sender": name, "content": content, "time": timestamp}
        except Exception:
            return None
