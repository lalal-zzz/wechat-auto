"""Perceiver - unread message sensing module."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wechat_auto.core.application import Application
    from wechat_auto.config import WeChatConfig

logger = logging.getLogger(__name__)


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

        Returns:
            List of dicts: [{contact: str, unread_count: int, preview: str}]

        Note:
            This is a stub implementation. Full implementation should scan
            sidebar red dots and [N条未读] markers in the session list.
        """
        # TODO: Implement UIA-based unread badge scanning
        logger.debug("Perceiver.get_unread_messages() called (stub).")
        return []

    def has_unread(self) -> bool:
        """Quick check if any unread messages exist."""
        return len(self.get_unread_messages()) > 0
