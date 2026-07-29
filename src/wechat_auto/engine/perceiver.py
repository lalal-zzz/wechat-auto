"""Perceiver - unread message sensing module.

Implements Step 1 (Perceive) of the closed-loop workflow by scanning
the WeChat conversation list for unread badges and red-dot markers.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wechat_auto.core.application import Application
    from wechat_auto.config import WeChatConfig

logger = logging.getLogger(__name__)

# Regex to detect unread count patterns like "3条未读" or just a number badge
_UNREAD_PATTERN = re.compile(r"(\d+)\s*条未读")
_RED_DOT_INDICATOR = "..."  # WeChat uses this for unread indicator when count unknown


class Perceiver:
    """Senses the WeChat UI environment for unread messages and state changes.

    This module implements Step 1 (Perceive) of the closed-loop workflow:
    polling the sidebar and conversation list for unread badges.
    """

    def __init__(self, application: "Application", config: "WeChatConfig"):
        self._app = application
        self._config = config

    def get_unread_messages(self) -> list[dict]:
        """Scan for unread messages in the conversation list.

        Iterates through ListItem controls in the main chat list and
        extracts unread conversations by detecting red-dot badges or
        "[N条未读]" text patterns.

        Returns:
            List of dicts::

                [
                    {
                        "contact": str,
                        "unread_count": int,
                        "preview": str,
                    }
                ]

            Returns an empty list if no unread messages are found or
            if the conversation list cannot be accessed.
        """
        logger.debug("Perceiver.get_unread_messages() called.")
        results: list[dict] = []

        try:
            win = self._app.main_window
        except Exception as exc:
            logger.warning("Cannot access main window: %s", exc)
            return results

        # Collect all ListItem controls in the conversation list
        list_items = self._get_conversation_items(win)
        if not list_items:
            logger.debug("No conversation list items found.")
            return results

        for item in list_items:
            info = self._extract_unread_info(item)
            if info is not None:
                results.append(info)

        logger.info("Perceived %d unread conversation(s).", len(results))
        return results

    def has_unread(self) -> bool:
        """Quick check if any unread messages exist."""
        return len(self.get_unread_messages()) > 0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_conversation_items(self, win) -> list:
        """Retrieve conversation ListItem controls from the main window.

        Tries multiple strategies to locate the conversation list:
        1. Find a List container with the conversation list name
        2. Find all ListItem controls directly
        """
        items: list = []

        # Strategy 1: Find List container then its ListItems
        try:
            from wechat_auto.ui.finder import ElementFinder

            finder = ElementFinder(self._app, self._config)
            list_container = finder.find_child_by_title(
                win,
                self._config.kw_chat_list,
                control_type="List",
                timeout=2.0,
            )
            if list_container is not None:
                items = list_container.children(control_type="ListItem")
                if items:
                    return items
        except Exception:
            pass

        # Strategy 2: Find all ListItem controls directly
        try:
            descendants = win.descendants(control_type="ListItem")
            if descendants:
                return list(descendants)
        except Exception:
            pass

        return items

    def _extract_unread_info(self, item) -> dict | None:
        """Extract unread info from a single conversation ListItem.

        Looks for:
        - Text matching "N条未读" pattern
        - Red-dot / numeric badge text
        - Contact name and latest message preview

        Returns:
            Dict with contact, unread_count, preview if unread,
            None otherwise.
        """
        try:
            text_parts = self._collect_text_parts(item)
            if not text_parts:
                return None

            contact_name = ""
            preview = ""
            unread_count = 0

            for part in text_parts:
                # Check for "[N条未读]" pattern
                match = _UNREAD_PATTERN.search(part)
                if match:
                    unread_count = int(match.group(1))
                    continue

                # Check for standalone number (red-dot badge)
                if part.strip().isdigit() and unread_count == 0:
                    unread_count = int(part.strip())
                    continue

                # Check for red-dot indicator (unknown count)
                if part.strip() == _RED_DOT_INDICATOR:
                    unread_count = max(unread_count, 1)
                    continue

            # If no unread count detected, this conversation is not unread
            if unread_count == 0:
                return None

            # Extract contact name and preview from remaining text
            non_badge_parts = [
                p for p in text_parts
                if not _UNREAD_PATTERN.search(p)
                and not p.strip().isdigit()
                and p.strip() != _RED_DOT_INDICATOR
            ]

            if non_badge_parts:
                contact_name = non_badge_parts[0]
            if len(non_badge_parts) > 1:
                preview = non_badge_parts[1]

            return {
                "contact": contact_name,
                "unread_count": unread_count,
                "preview": preview,
            }
        except Exception as exc:
            logger.debug("Error extracting unread info from item: %s", exc)
            return None

    def _collect_text_parts(self, element) -> list[str]:
        """Collect all text content from an element and its children."""
        parts: list[str] = []

        try:
            # Get the element's own text
            own_text = element.window_text()
            if own_text:
                parts.append(own_text)
        except Exception:
            pass

        try:
            # Get text from child elements
            children = element.children()
            for child in children:
                try:
                    text = child.window_text()
                    if text and text not in parts:
                        parts.append(text)
                except Exception:
                    continue
        except Exception:
            pass

        return parts
