"""GroupAt skill - group chat @ member reply (Tier 1)."""

from __future__ import annotations

import logging
import time
from typing import Any

from wechat_auto.skills.base import BaseSkill
from wechat_auto.exceptions import SendMessageError
from wechat_auto.utils.clipboard import ClipboardHelper
from wechat_auto.utils.keyboard import KeyboardHelper
from wechat_auto.utils.retry import retry_on_failure

logger = logging.getLogger(__name__)


class GroupAtSkill(BaseSkill):
    """Send @ member messages in group chats.

    Tier 1 skill covering:
        - send_group_at_message

    Workflow:
        1. Open the target group chat
        2. Type '@' in the input box to trigger the member selection popup
        3. Type or search the member name
        4. Click the matching member from the popup list
        5. Type the message content
        6. Press Enter to send
    """

    name = "send_group_at_message"

    def _run(self, **params) -> Any:
        group = params.get("group", "")
        mention = params.get("mention", "")
        message = params.get("message", "")
        return self.send_group_at_message(group, mention, message)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=2, delay=1.0)
    def send_group_at_message(self, group: str, mention: str, message: str) -> None:
        """Send a message in a group chat mentioning (@) a member.

        Args:
            group: Group chat name.
            mention: Name of the member to @ (or "所有人" for @all).
            message: Message content.

        Raises:
            SendMessageError: If sending fails.
        """
        logger.info("Sending @%s in group %s: %s", mention, group, message[:40])
        self._activate()
        self._open_chat(group)
        time.sleep(self._config.action_delay)

        edit_box = self._find_message_box()
        if edit_box is not None:
            edit_box.click_input()
        else:
            self._click_input_area()
        time.sleep(self._config.click_delay)

        # Step 1: Type '@' to trigger member selection popup
        self.window.type_keys("@")
        time.sleep(self._config.action_delay)

        # Step 2: Type the member name to filter the popup list
        ClipboardHelper.set_text(mention)
        KeyboardHelper.paste(self.window)
        time.sleep(self._config.search_timeout)

        # Step 3: Require one exact member match in the popup
        self._select_member_from_popup(mention)

        # Step 4: Type the message content
        if message:
            ClipboardHelper.set_text(message)
            KeyboardHelper.paste(self.window)
            time.sleep(self._config.action_delay)

        # Step 5: Press Enter to send
        KeyboardHelper.press_enter(self.window)
        time.sleep(self._config.after_send_delay)
        logger.info("Group @ message sent successfully.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_message_box(self):
        """Locate the message input edit box in the current chat."""
        try:
            return self._finder.find_child_by_title(
                self.window, "", control_type="Edit",
                timeout=self._config.find_element_timeout,
            )
        except Exception:
            try:
                children = self._finder.find_all_children(self.window, control_type="Edit")
                if children:
                    return children[-1]
            except Exception:
                pass
        return None

    def _click_input_area(self) -> None:
        """Click the expected message input area for new WeChat (Weixin)."""
        try:
            rect = self.window.rectangle()
            x = rect.left + int((rect.right - rect.left) * 0.65)
            y = rect.top + int((rect.bottom - rect.top) * 0.85)
            self.window.click_input(coords=(x, y))
        except Exception as exc:
            raise SendMessageError(
                "Cannot locate message input area in group chat."
            ) from exc

    def _select_member_from_popup(self, member_name: str) -> None:
        """Select a member from the @-mention popup list.

        Args:
            member_name: Name of the member to select (used for logging).

        The popup appears as a List/ListItem control after typing '@'.  Result
        order is not safe to use for an identity-bearing action.
        """
        try:
            if self._finder.click_unique_exact_list_item(self.window, member_name):
                time.sleep(self._config.click_delay)
                logger.debug("Selected member '%s' from popup.", member_name)
                return
        except Exception as exc:
            raise SendMessageError(
                f"Cannot select an unambiguous @ member: {member_name}"
            ) from exc

        raise SendMessageError(f"Cannot select an unambiguous @ member: {member_name}")
