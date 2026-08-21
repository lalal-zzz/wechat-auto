"""Element finder — locate UI elements inside the WeChat window."""

from __future__ import annotations

import logging
import time
from typing import Optional, TYPE_CHECKING

from wechat_auto.config import WeChatConfig
from wechat_auto.exceptions import ChatNotFoundError, ElementNotFoundError, OperationTimeoutError

if TYPE_CHECKING:
    from wechat_auto.core.application import Application

logger = logging.getLogger(__name__)


class ElementFinder:
    """High-level helper for finding and interacting with UI elements."""

    def __init__(self, application: "Application", config: WeChatConfig):
        self._app = application
        self._config = config

    # ------------------------------------------------------------------
    # Finding elements
    # ------------------------------------------------------------------

    def find_child_by_title(
        self,
        parent,
        title: str,
        control_type: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        """Find a child element by its title (name/text).

        Args:
            parent: Parent WindowSpecification or wrapper.
            title: Exact or partial title to match.
            control_type: Optional UIA control type filter (e.g. "Button", "Text").
            timeout: Maximum seconds to wait (default from config).

        Returns:
            The found wrapper object.

        Raises:
            ElementNotFoundError: If the element cannot be found within timeout.
        """
        timeout = timeout if timeout is not None else self._config.find_element_timeout
        deadline = time.monotonic() + timeout

        kwargs = {"title": title}
        if control_type:
            kwargs["control_type"] = control_type

        last_err = None
        while time.monotonic() < deadline:
            try:
                elem = parent.child_window(**kwargs)
                wrapper = elem.wrapper_object()
                logger.debug("Found element: title=%r type=%s", title, control_type)
                return wrapper
            except Exception as exc:
                last_err = exc
                time.sleep(0.2)

        raise ElementNotFoundError(f"title={title!r} type={control_type}") from last_err

    def find_child_by_regex(
        self,
        parent,
        title_re: str,
        control_type: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        """Find a child element by regex title pattern."""
        timeout = timeout if timeout is not None else self._config.find_element_timeout
        deadline = time.monotonic() + timeout

        kwargs = {"title_re": title_re}
        if control_type:
            kwargs["control_type"] = control_type

        last_err = None
        while time.monotonic() < deadline:
            try:
                elem = parent.child_window(**kwargs)
                wrapper = elem.wrapper_object()
                return wrapper
            except Exception as exc:
                last_err = exc
                time.sleep(0.2)

        raise ElementNotFoundError(f"title_re={title_re!r}") from last_err

    def find_all_children(
        self,
        parent,
        control_type: Optional[str] = None,
    ) -> list:
        """Return all child wrappers (optionally filtered by control type)."""
        try:
            if control_type:
                return parent.descendants(control_type=control_type)
            return parent.children()
        except Exception:
            return []

    def find_by_automation_id(self, parent, automation_id: str, timeout: Optional[float] = None):
        """Find element by AutomationId."""
        timeout = timeout if timeout is not None else self._config.find_element_timeout
        deadline = time.monotonic() + timeout
        last_err = None
        while time.monotonic() < deadline:
            try:
                elem = parent.child_window(auto_id=automation_id)
                wrapper = elem.wrapper_object()
                return wrapper
            except Exception as exc:
                last_err = exc
                time.sleep(0.2)
        raise ElementNotFoundError(f"automation_id={automation_id!r}") from last_err

    def exists(
        self,
        parent,
        title: str,
        control_type: Optional[str] = None,
        timeout: float = 2.0,
    ) -> bool:
        """Check if an element exists (non-raising)."""
        try:
            self.find_child_by_title(parent, title, control_type, timeout=timeout)
            return True
        except ElementNotFoundError:
            return False

    # ------------------------------------------------------------------
    # Interaction helpers
    # ------------------------------------------------------------------

    def click(self, element, delay: Optional[float] = None) -> None:
        """Click an element with optional pre-delay."""
        delay = delay if delay is not None else self._config.click_delay
        time.sleep(delay)
        element.click_input()

    def double_click(self, element, delay: Optional[float] = None) -> None:
        delay = delay if delay is not None else self._config.click_delay
        time.sleep(delay)
        element.double_click_input()

    def right_click(self, element, delay: Optional[float] = None) -> None:
        delay = delay if delay is not None else self._config.click_delay
        time.sleep(delay)
        element.click_input(button="right")

    def type_text(self, element, text: str, clear_first: bool = True) -> None:
        """Type text into a focused element."""
        if clear_first:
            element.set_edit_text("")
        element.type_keys(text, pause=self._config.type_delay)

    def click_unique_exact_list_item(self, parent, expected_name: str) -> bool:
        """Click a result only when exactly one item names the requested target.

        Search result ordering is not an identity guarantee.  In particular,
        Weixin can put recent conversations, public accounts, and fuzzy matches
        before an exact result.  This method deliberately refuses both zero and
        ambiguous matches so callers cannot act on the wrong conversation.
        """
        matches = []
        for item in self.find_all_children(parent, control_type="ListItem"):
            texts = []
            try:
                texts.append(item.window_text().strip())
            except Exception:
                pass
            for child in self.find_all_children(item, control_type="Text"):
                try:
                    texts.append(child.window_text().strip())
                except Exception:
                    pass
            if expected_name in texts:
                matches.append(item)

        if len(matches) != 1:
            logger.warning(
                "Refusing to select %r: expected one exact ListItem match, found %d.",
                expected_name,
                len(matches),
            )
            return False

        self.click(matches[0])
        return True

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def navigate_to_chat_list(self) -> None:
        """Click the chat list tab in the sidebar."""
        win = self._app.main_window
        try:
            btn = self.find_child_by_title(win, self._config.kw_chat_list, timeout=self._config.find_element_timeout)
            self.click(btn)
        except ElementNotFoundError:
            # Fallback: use keyboard shortcut or coordinate click
            logger.debug("Chat list button not found, using Ctrl+1 shortcut.")
            win.type_keys("^1")
        time.sleep(self._config.action_delay)

    def navigate_to_contacts(self) -> None:
        """Click the contacts tab in the sidebar."""
        win = self._app.main_window
        try:
            btn = self.find_child_by_title(win, self._config.kw_contacts, timeout=self._config.find_element_timeout)
            self.click(btn)
        except ElementNotFoundError:
            logger.debug("Contacts button not found, using Ctrl+2 shortcut.")
            win.type_keys("^2")
        time.sleep(self._config.action_delay)

    def open_search(self) -> None:
        """Open the search box via Ctrl+F keyboard shortcut."""
        win = self._app.main_window
        win.type_keys(self._config.shortcut_search)
        time.sleep(self._config.action_delay)

    def open_chat(self, chat_name: str) -> None:
        """Open a specific chat by name using search (Ctrl+F + paste + select result).

        Strategy:
            1. Focus search box (Ctrl+F), clear existing content.
            2. Paste chat name via clipboard.
            3. Select one exact matching ListItem.

        For safety, a fuzzy match, no match, or more than one exact match is
        treated as a failed lookup.  The method never selects the first result.
        """
        from wechat_auto.utils.clipboard import ClipboardHelper
        from wechat_auto.utils.keyboard import KeyboardHelper

        win = self._app.main_window

        # Step 1: Open search with Ctrl+F and clear old text
        self.open_search()
        time.sleep(self._config.action_delay)
        win.type_keys("^a{BACKSPACE}")
        time.sleep(0.1)

        # Step 2: Paste chat name via clipboard
        ClipboardHelper.set_text(chat_name)
        KeyboardHelper.paste(win)
        time.sleep(max(1.0, self._config.search_timeout / 2))

        # Step 3: Never use result ordering as identity.
        if not self.click_unique_exact_list_item(win, chat_name):
            KeyboardHelper.press_escape(win)
            raise ChatNotFoundError(chat_name)

        time.sleep(self._config.action_delay)
        logger.info("Opened chat: %s", chat_name)

