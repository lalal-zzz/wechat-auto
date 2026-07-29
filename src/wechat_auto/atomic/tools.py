"""AtomicUITools - Tier 2 native UIA atomic control tools.

Provides 7 atomic tools for direct UI manipulation when Tier 1 skills
fail or encounter unknown interfaces:
    1. get_ui_tree(window_title) - Extract UIA control tree
    2. click(component_id) - Click a control
    3. input_text(component_id, text) - Type into a control
    4. right_click(component_id) - Right-click a control
    5. scroll(component_id, direction, distance) - Scroll a list/feed
    6. send_keyboard_shortcut(key_shortcut) - Send key combination
    7. close_window(window_id) - Force close a child window
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional, TYPE_CHECKING

from wechat_auto.config import WeChatConfig
from wechat_auto.exceptions import AtomicToolError, ElementNotFoundError

if TYPE_CHECKING:
    from wechat_auto.core.application import Application
    from wechat_auto.ui.finder import ElementFinder

logger = logging.getLogger(__name__)


class AtomicUITools:
    """Tier 2 atomic UI control tools for low-level UIA interaction.

    Used as a fallback when Tier 1 skills cannot handle a scenario.
    The AI agent reads the control tree JSON and manipulates controls
    directly by their identifiers.
    """

    def __init__(
        self,
        application: "Application",
        finder: "ElementFinder",
        config: WeChatConfig,
    ):
        self._app = application
        self._finder = finder
        self._config = config

    # ------------------------------------------------------------------
    # Tool 1: get_ui_tree
    # ------------------------------------------------------------------

    def get_ui_tree(self, window_title: str = None) -> dict:
        """Extract the UIA control tree of a window.

        Args:
            window_title: Target window title. If None, uses main window.

        Returns:
            Structured dict containing control IDs, types, and names.

        Note:
            Stub implementation - returns basic window info.
            Full implementation should recursively enumerate all controls.
        """
        try:
            win = self._app.main_window
            rect = win.rectangle()

            # TODO: Recursively enumerate descendants into structured JSON
            tree = {
                "window_title": window_title or win.window_text(),
                "rect": {
                    "left": rect.left,
                    "top": rect.top,
                    "right": rect.right,
                    "bottom": rect.bottom,
                },
                "controls": [],  # Stub: empty control list
            }
            logger.debug("get_ui_tree() returned (stub): %s", tree["window_title"])
            return tree
        except Exception as exc:
            raise AtomicToolError(f"Failed to get UI tree: {exc}") from exc

    # ------------------------------------------------------------------
    # Tool 2: click
    # ------------------------------------------------------------------

    def click(self, component_id: str = "", **kwargs) -> None:
        """Click a UI control by its identifier.

        Args:
            component_id: Control title/name to locate and click.

        Raises:
            AtomicToolError: If the control cannot be found or clicked.
        """
        try:
            win = self._app.main_window
            element = self._finder.find_child_by_title(
                win, component_id, timeout=self._config.find_element_timeout
            )
            self._finder.click(element)
            logger.debug("Atomic click: %s", component_id)
        except Exception as exc:
            raise AtomicToolError(f"Atomic click failed for '{component_id}': {exc}") from exc

    # ------------------------------------------------------------------
    # Tool 3: input_text
    # ------------------------------------------------------------------

    def input_text(self, component_id: str = "", text: str = "", **kwargs) -> None:
        """Type text into a specified input control.

        Args:
            component_id: Control title/name of the input box.
            text: Text to input.

        Raises:
            AtomicToolError: If the control cannot be found.
        """
        try:
            win = self._app.main_window
            element = self._finder.find_child_by_title(
                win, component_id, control_type="Edit",
                timeout=self._config.find_element_timeout
            )
            self._finder.type_text(element, text)
            logger.debug("Atomic input_text: %s -> '%s'", component_id, text[:30])
        except Exception as exc:
            raise AtomicToolError(
                f"Atomic input_text failed for '{component_id}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Tool 4: right_click
    # ------------------------------------------------------------------

    def right_click(self, component_id: str = "", **kwargs) -> None:
        """Right-click a UI control (e.g. to open context menu).

        Args:
            component_id: Control title/name to right-click.

        Raises:
            AtomicToolError: If the control cannot be found.
        """
        try:
            win = self._app.main_window
            element = self._finder.find_child_by_title(
                win, component_id, timeout=self._config.find_element_timeout
            )
            self._finder.right_click(element)
            logger.debug("Atomic right_click: %s", component_id)
        except Exception as exc:
            raise AtomicToolError(
                f"Atomic right_click failed for '{component_id}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Tool 5: scroll
    # ------------------------------------------------------------------

    def scroll(self, component_id: str = "", direction: str = "down", distance: int = 3, **kwargs) -> None:
        """Scroll a list or feed control.

        Args:
            component_id: Control title/name of the scrollable area.
            direction: "up" or "down".
            distance: Number of scroll steps.

        Note:
            Stub implementation using keyboard Page Up/Down.
            Full implementation should use wheel_mouse_input on the target.
        """
        try:
            win = self._app.main_window
            key = "{PGDN}" if direction == "down" else "{PGUP}"
            for _ in range(distance):
                win.type_keys(key)
                time.sleep(self._config.scroll_delay)
            logger.debug("Atomic scroll: %s %s x%d", component_id, direction, distance)
        except Exception as exc:
            raise AtomicToolError(f"Atomic scroll failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Tool 6: send_keyboard_shortcut
    # ------------------------------------------------------------------

    def send_keyboard_shortcut(self, key_shortcut: str = "", **kwargs) -> None:
        """Send a keyboard shortcut combination.

        Args:
            key_shortcut: pywinauto key string (e.g. "^v", "{ENTER}", "{ESC}").

        Raises:
            AtomicToolError: If sending fails.
        """
        try:
            win = self._app.main_window
            win.type_keys(key_shortcut)
            time.sleep(self._config.action_delay)
            logger.debug("Atomic keyboard shortcut: %s", key_shortcut)
        except Exception as exc:
            raise AtomicToolError(
                f"Atomic keyboard shortcut failed for '{key_shortcut}': {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Tool 7: close_window
    # ------------------------------------------------------------------

    def close_window(self, window_id: str = "", **kwargs) -> None:
        """Force close a specific child window.

        Args:
            window_id: Window class name or title (e.g. "SNSWnd", "TopStoryWnd").

        Note:
            Stub implementation - sends Alt+F4 to active window.
            Full implementation should find window by class/title and close it.
        """
        try:
            # TODO: Find window by class name and close programmatically
            win = self._app.main_window
            win.type_keys("%{F4}")
            time.sleep(self._config.action_delay)
            logger.debug("Atomic close_window: %s", window_id)
        except Exception as exc:
            raise AtomicToolError(
                f"Atomic close_window failed for '{window_id}': {exc}"
            ) from exc
