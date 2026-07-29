"""Unread skill - unread message queue inspection (Tier 1).

Uses the Perceiver engine component to scan for unread messages
in the WeChat conversation list.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from wechat_auto.skills.base import BaseSkill

if TYPE_CHECKING:
    from wechat_auto.engine.perceiver import Perceiver

logger = logging.getLogger(__name__)


class UnreadSkill(BaseSkill):
    """Check and retrieve unread message queue.

    Tier 1 skill covering:
        - get_unread_messages

    Delegates to the Perceiver engine component for the actual
    UIA-based scanning of red-dot badges and [N条未读] markers.
    """

    name = "get_unread_messages"

    def _run(self, **params) -> Any:
        return self.get_unread_messages()

    def get_unread_messages(self) -> list[dict]:
        """Scan sidebar and conversation list for unread messages.

        Uses the Perceiver to scan the conversation list for unread
        badges and red-dot markers.

        Returns:
            List of dicts::

                [
                    {
                        "contact": str,
                        "unread_count": int,
                        "preview": str,
                    }
                ]

            Returns an empty list if no unread messages are found.
        """
        logger.info("Checking unread messages via Perceiver.")
        perceiver = self._get_perceiver()
        if perceiver is None:
            logger.warning("No perceiver available, cannot check unread messages.")
            return []
        return perceiver.get_unread_messages()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_perceiver(self) -> "Perceiver | None":
        """Get the Perceiver instance from the engine.

        The Perceiver is not directly injected into skills, so we
        create one on-the-fly using the available application and config.
        """
        try:
            from wechat_auto.engine.perceiver import Perceiver

            return Perceiver(self._app, self._config)
        except Exception as exc:
            logger.warning("Could not create Perceiver: %s", exc)
            return None
