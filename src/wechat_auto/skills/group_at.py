"""GroupAt skill - group chat @ member reply (Tier 1, stub)."""

from __future__ import annotations

import logging
from typing import Any

from wechat_auto.skills.base import BaseSkill

logger = logging.getLogger(__name__)


class GroupAtSkill(BaseSkill):
    """Send @ member messages in group chats.

    Tier 1 skill covering:
        - send_group_at_message

    Note: Stub implementation - not yet fully implemented.
    """

    name = "send_group_at_message"

    def _run(self, **params) -> Any:
        group = params.get("group", "")
        mention = params.get("mention", "")
        message = params.get("message", "")
        return self.send_group_at_message(group, mention, message)

    def send_group_at_message(self, group: str, mention: str, message: str) -> None:
        """Send a message in a group chat mentioning (@) a member.

        Args:
            group: Group chat name.
            mention: Name of the member to @ (or "所有人" for @all).
            message: Message content.

        Note: Stub - not yet implemented.
        """
        raise NotImplementedError(
            "send_group_at_message() is not yet implemented. "
            "Full implementation should type '@' in the input box, "
            "select the member from the popup list, then type and send."
        )
