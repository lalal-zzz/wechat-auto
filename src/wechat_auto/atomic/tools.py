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

try:
    from pywinauto import Desktop as _Desktop
except ImportError:  # pragma: no cover
    _Desktop = None

if TYPE_CHECKING:
    from wechat_auto.core.application import Application
    from wechat_auto.ui.finder import ElementFinder

logger = logging.getLogger(__name__)

# Maximum recursion depth for UI tree extraction to prevent infinite loops
_MAX_TREE_DEPTH = 10
# Maximum children per node to avoid extremely large trees
_MAX_CHILDREN_PER_NODE = 50


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

        Recursively enumerates all descendant controls of the target
        window and returns a structured JSON-like dict containing
        control IDs, types, names, and bounding rectangles.

        Args:
            window_title: Target window title. If None, uses main window.

        Returns:
            Structured dict::

                {
                    "window_title": str,
                    "rect": {"left", "top", "right", "bottom"},
                    "controls": [
                        {
                            "id": str,
                            "control_type": str,
                            "name": str,
                            "automation_id": str,
                            "rect": {...},
                            "children": [...],
                        },
                    ],
                }

        Raises:
            AtomicToolError: If the UI tree extraction fails.
        """
        try:
            if window_title:
                # Try to find the specific window
                desktop = _Desktop(backend=self._config.backend) if _Desktop else None
                if desktop is None:
                    raise AtomicToolError("pywinauto Desktop not available")
                win = desktop.window(title=window_title)
                if not win.exists(timeout=2.0):
                    raise AtomicToolError(
                        f"Window not found: {window_title}"
                    )
                win = win.wrapper_object()
            else:
                win = self._app.main_window

            rect = win.rectangle()

            tree = {
                "window_title": win.window_text(),
                "rect": {
                    "left": rect.left,
                    "top": rect.top,
                    "right": rect.right,
                    "bottom": rect.bottom,
                },
                "controls": self._extract_controls(win, depth=0),
            }
            logger.debug(
                "get_ui_tree() extracted %d top-level controls for: %s",
                len(tree["controls"]),
                tree["window_title"],
            )
            return tree
        except AtomicToolError:
            raise
        except Exception as exc:
            raise AtomicToolError(f"Failed to get UI tree: {exc}") from exc

    def _extract_controls(self, element, depth: int = 0) -> list[dict]:
        """Recursively extract control info from an element's children.

        Args:
            element: Parent UI element wrapper.
            depth: Current recursion depth (prevents infinite loops).

        Returns:
            List of control info dicts.
        """
        if depth >= _MAX_TREE_DEPTH:
            return []

        controls: list[dict] = []
        try:
            children = element.children()
            for i, child in enumerate(children):
                if i >= _MAX_CHILDREN_PER_NODE:
                    logger.debug("Truncating at %d children (depth=%d)", i, depth)
                    break

                info = self._extract_single_control(child, depth)
                if info is not None:
                    controls.append(info)
        except Exception as exc:
            logger.debug("Error extracting children at depth %d: %s", depth, exc)

        return controls

    def _extract_single_control(self, element, depth: int) -> Optional[dict]:
        """Extract info from a single control element.

        Args:
            element: UI element wrapper.
            depth: Current recursion depth.

        Returns:
            Control info dict, or None if extraction fails.
        """
        try:
            name = element.window_text()
            ctrl_type = self._safe_get_type(element)
            auto_id = self._safe_get_automation_id(element)
            rect = self._safe_get_rect(element)

            info: dict = {
                "name": name or "",
                "control_type": ctrl_type or "",
                "automation_id": auto_id or "",
            }
            if rect:
                info["rect"] = rect

            # Recursively extract children
            child_controls = self._extract_controls(element, depth + 1)
            if child_controls:
                info["children"] = child_controls

            return info
        except Exception as exc:
            logger.debug("Error extracting control at depth %d: %s", depth, exc)
            return None

    def _safe_get_type(self, element) -> str:
        """Safely get the control type of an element."""
        try:
            return str(element.element_info.control_type or "")
        except Exception:
            return ""

    def _safe_get_automation_id(self, element) -> str:
        """Safely get the automation ID of an element."""
        try:
            return str(element.element_info.automation_id or "")
        except Exception:
            return ""

    def _safe_get_rect(self, element) -> Optional[dict]:
        """Safely get the bounding rectangle of an element."""
        try:
            rect = element.rectangle()
            return {
                "left": rect.left,
                "top": rect.top,
                "right": rect.right,
                "bottom": rect.bottom,
            }
        except Exception:
            return None

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

        Tries wheel_mouse_input on the target element first, then falls
        back to keyboard Page Up/Down keys.

        Args:
            component_id: Control title/name of the scrollable area.
            direction: "up" or "down".
            distance: Number of scroll steps.

        Raises:
            AtomicToolError: If scrolling fails.
        """
        try:
            win = self._app.main_window

            # Try to find the target element and scroll it directly
            scrolled = False
            if component_id:
                try:
                    element = self._finder.find_child_by_title(
                        win, component_id, timeout=2.0
                    )
                    wheel_dist = -distance * 3 if direction == "up" else distance * 3
                    element.wheel_mouse_input(wheel_dist=wheel_dist)
                    scrolled = True
                except Exception:
                    pass

            # Fallback: keyboard Page Up/Down
            if not scrolled:
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

        Tries to find the window by class name first, then by title,
        and closes it using the pywinauto close() method. Falls back
        to sending Alt+F4 if the window cannot be explicitly found.

        Args:
            window_id: Window class name or title (e.g. "SNSWnd", "TopStoryWnd").

        Raises:
            AtomicToolError: If the window cannot be closed.
        """
        if not window_id:
            raise AtomicToolError("close_window requires a window_id")

        try:
            desktop = _Desktop(backend=self._config.backend) if _Desktop else None

            # Try by class name first
            try:
                popup = desktop.window(class_name=window_id)
                if popup.exists(timeout=2.0):
                    logger.debug("Closing window by class_name: %s", window_id)
                    popup.close(timeout=3.0)
                    time.sleep(self._config.action_delay)
                    return
            except Exception:
                pass

            # Try by title
            try:
                popup = desktop.window(title=window_id)
                if popup.exists(timeout=2.0):
                    logger.debug("Closing window by title: %s", window_id)
                    popup.close(timeout=3.0)
                    time.sleep(self._config.action_delay)
                    return
            except Exception:
                pass

            # Fallback: send Alt+F4 to the active window
            logger.debug("Window '%s' not found, sending Alt+F4 fallback.", window_id)
            win = self._app.main_window
            win.type_keys("%{F4}")
            time.sleep(self._config.action_delay)
        except AtomicToolError:
            raise
        except Exception as exc:
            raise AtomicToolError(
                f"Atomic close_window failed for '{window_id}': {exc}"
            ) from exc
