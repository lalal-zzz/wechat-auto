"""Contact skill - precise contact search and chat opening (Tier 1)."""

from __future__ import annotations

import logging
import time
from typing import Any

from wechat_auto.skills.base import BaseSkill
from wechat_auto.exceptions import ContactNotFoundError
from wechat_auto.utils.clipboard import ClipboardHelper
from wechat_auto.utils.keyboard import KeyboardHelper
from wechat_auto.utils.retry import retry_on_failure

logger = logging.getLogger(__name__)


class ContactSkill(BaseSkill):
    """Search and locate contacts in WeChat.

    Tier 1 skill covering:
        - open_contact_chat (via contacts tab search)
        - reset_ui_environment (contact search cleanup)

    Core rule: MUST use the contacts-tab dedicated search box,
    NEVER the global main search box (to avoid confusing contacts
    with official accounts).
    """

    name = "open_contact_chat"

    def _run(self, **params) -> Any:
        target = params.get("target", "")
        return self.open_chat_via_contacts(target)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=2, delay=1.0)
    def search(self, keyword: str) -> list[str]:
        """Search contacts by keyword via the contacts tab.

        Args:
            keyword: Search string (partial name, pinyin, etc.).

        Returns:
            List of matching contact names.
        """
        logger.info("Searching contacts: %s", keyword)
        self._activate()

        # Navigate to contacts tab (mandatory per spec)
        self._finder.navigate_to_contacts()
        time.sleep(self._config.action_delay)

        # Open search
        self._finder.open_search()
        time.sleep(self._config.action_delay)

        # Type keyword
        ClipboardHelper.set_text(keyword)
        KeyboardHelper.paste(self.window)
        time.sleep(self._config.search_timeout)

        # Collect results
        results = self._collect_search_results()
        # Close search
        KeyboardHelper.press_escape(self.window)
        logger.info("Found %d contacts matching '%s'.", len(results), keyword)
        return results

    def open_chat_via_contacts(self, contact_name: str) -> None:
        """Open a chat by searching through the contacts tab.

        Args:
            contact_name: Target contact name.
        """
        logger.info("Opening contact chat: %s", contact_name)
        self._activate()

        self._finder.navigate_to_contacts()
        time.sleep(self._config.action_delay)

        self._finder.open_search()
        time.sleep(self._config.action_delay)

        ClipboardHelper.set_text(contact_name)
        KeyboardHelper.paste(self.window)
        time.sleep(self._config.search_timeout)

        if not self._finder.click_unique_exact_list_item(self.window, contact_name):
            KeyboardHelper.press_escape(self.window)
            raise ContactNotFoundError(contact_name)
        time.sleep(self._config.action_delay)

        # Clear search state with Esc
        KeyboardHelper.press_escape(self.window)
        logger.info("Opened chat with: %s", contact_name)

    def exists(self, contact_name: str) -> bool:
        """Check if a contact exists by exact name."""
        results = self.search(contact_name)
        return any(contact_name == name for name in results)

    def get_contact_info(self, contact_name: str) -> dict | None:
        """Get basic visible info of a contact.

        Args:
            contact_name: Contact name.

        Returns:
            Dict with name and visible details, or None.
        """
        logger.info("Getting info for: %s", contact_name)
        self._activate()
        self._finder.navigate_to_contacts()
        time.sleep(self._config.action_delay)

        self._finder.open_search()
        ClipboardHelper.set_text(contact_name)
        KeyboardHelper.paste(self.window)
        time.sleep(self._config.search_timeout)

        try:
            if self._finder.click_unique_exact_list_item(self.window, contact_name):
                time.sleep(self._config.action_delay)
                info = self._read_contact_detail()
                KeyboardHelper.press_escape(self.window)
                return info
        except Exception as exc:
            logger.warning("Could not get contact info: %s", exc)
            KeyboardHelper.press_escape(self.window)

        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_search_results(self) -> list[str]:
        """Collect contact names from search results."""
        results: list[str] = []
        try:
            items = self._finder.find_all_children(self.window, control_type="ListItem")
            for item in items:
                try:
                    name = item.window_text()
                    if name:
                        results.append(name)
                except Exception:
                    continue
        except Exception:
            pass
        return results

    def _read_contact_detail(self) -> dict | None:
        """Read visible contact details from the detail pane."""
        try:
            texts = self._finder.find_all_children(self.window, control_type="Text")
            parts = []
            for t in texts:
                try:
                    val = t.window_text()
                    if val:
                        parts.append(val)
                except Exception:
                    continue

            if not parts:
                return None

            return {
                "name": parts[0] if parts else "",
                "details": parts[1:] if len(parts) > 1 else [],
            }
        except Exception:
            return None
