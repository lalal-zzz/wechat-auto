"""Unread skill - unread message queue inspection (Tier 1, stub)."""

from __future__ import annotations

import logging
from typing import Any

from wechat_auto.skills.base import BaseSkill

logger = logging.getLogger(__name__)


class UnreadSkill(BaseSkill):
    """Check and retrieve unread message queue.

    Tier 1 skill covering:
        - get_unread_messages

    Note: Stub implementation - not yet fully implemented.
    """

    name = "get_unread_messages"

    def _run(self, **params) -> Any:
        return self.get_unread_messages()

    def get_unread_messages(self) -> list[dict]:
        """Scan sidebar and conversation list for unread messages.

        Returns:
            List of dicts: [{contact: str, unread_count: int, preview: str}]

        Note: Stub - not yet implemented.
        """
        raise NotImplementedError(
            "get_unread_messages() is not yet implemented. "
            "Full implementation should scan red dots and [N条未读] markers."
        )
