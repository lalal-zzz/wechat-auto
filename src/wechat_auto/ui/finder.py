"""Element finder — locate UI elements inside the WeChat window."""

from __future__ import annotations

import logging
import time
from typing import Optional, TYPE_CHECKING

from wechat_auto.config import WeChatConfig
from wechat_auto.exceptions import ElementNotFoundError, OperationTimeoutError

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
        """Open a specific chat by name using search (Ctrl+F + paste + click result).

        In the new WeChat (Weixin), pressing Enter in the search box opens
        "搜一搜" (WeChat Search) instead of selecting the first chat result.
        Therefore we click the first result in the search dropdown.

        Strategy:
            1. Try to find and click a ListItem matching the name
            2. Fall back to coordinate-based click if no ListItem found
        """
        from wechat_auto.utils.clipboard import ClipboardHelper
        from wechat_auto.utils.keyboard import KeyboardHelper

        win = self._app.main_window

        # Step 1: Open search with Ctrl+F
        self.open_search()
        time.sleep(self._config.action_delay)

        # Step 2: Paste chat name via clipboard (supports CJK characters)
        ClipboardHelper.set_text(chat_name)
        KeyboardHelper.paste(win)
        time.sleep(self._config.search_timeout)

        # Step 3: Click the first search result
        # Strategy 1: Try to find ListItem elements and click the first match
        clicked = self._click_search_result_by_listitem(win, chat_name)
        if not clicked:
            # Strategy 2: Fall back to coordinate-based click
            self._click_first_search_result(win)
        time.sleep(self._config.action_delay)
        logger.info("Opened chat: %s", chat_name)

    def _click_search_result_by_listitem(self, win, chat_name: str) -> bool:
        """Try to click a search result by finding ListItem controls.

        Returns:
            True if a result was found and clicked, False otherwise.
        """
        try:
            items = self.find_all_children(win, control_type="ListItem")
            if not items:
                return False

            # Try to find a matching item first
            for item in items:
                try:
                    text = item.window_text()
                    if chat_name in text or text in chat_name:
                        self.click(item)
                        logger.debug("Clicked search result ListItem: %s", text)
                        return True
                except Exception:
                    continue

            # No exact match, click the first result
            self.click(items[0])
            logger.debug("Clicked first search result ListItem (no exact match).")
            return True
        except Exception as exc:
            logger.debug("ListItem search click failed: %s", exc)
            return False

    def _click_first_search_result(self, win) -> None:
        """Click the first chat result in the search dropdown by coordinate.

        Fallback when ListItem-based click fails.
        """
        import ctypes
        user32 = ctypes.windll.user32

        rect = win.rectangle()
        # Search results appear in the left panel, below the search bar
        x = rect.left + int((rect.right - rect.left) * 0.15)
        y = rect.top + int((rect.bottom - rect.top) * 0.18)
        logger.debug("Clicking first search result at (%d, %d)", x, y)
        user32.SetCursorPos(x, y)
        time.sleep(0.05)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
        time.sleep(0.03)
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
