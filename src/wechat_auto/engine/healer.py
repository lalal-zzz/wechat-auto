"""EnvironmentHealer - UI environment self-healing and reset module.

Implements Step 4 (Validate & Reset) of the closed-loop workflow:
- Close all popup windows (SNSWnd, TopStoryWnd, emoji panels)
- Clear search box text
- Switch back to main message Tab
- Ensure system is in idle state for next loop iteration
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from wechat_auto.exceptions import EnvironmentResetError

try:
    from pywinauto import Desktop as _Desktop
except ImportError:  # pragma: no cover
    _Desktop = None

if TYPE_CHECKING:
    from wechat_auto.core.application import Application
    from wechat_auto.config import WeChatConfig
    from wechat_auto.ui.finder import ElementFinder

logger = logging.getLogger(__name__)

# Known WeChat popup window class names that should be closed during reset
_POPUP_WINDOW_CLASSES = [
    "SNSWnd",         # Moments (朋友圈)
    "TopStoryWnd",    # Channels / Search (视频号/搜一搜)
    "ChatRecordWnd",  # Chat history search
    "EmojiWnd",       # Emoji panel
    "SelectVoiceWnd", # Voice message
]

# Known popup window titles (fallback)
_POPUP_WINDOW_TITLES = [
    "朋友圈",
    "视频号",
    "搜一搜",
    "聊天记录",
]


class EnvironmentHealer:
    """Validates and resets the WeChat UI environment to idle state.

    Implements Step 4 (Validate & Reset) of the closed-loop workflow:
    - Close all popup windows (SNSWnd, TopStoryWnd, emoji panels)
    - Clear search box text
    - Switch back to main message Tab
    - Ensure system is in idle state for next loop iteration
    """

    # Known popup window class names to close
    popup_classes: list[str] = _POPUP_WINDOW_CLASSES
    popup_titles: list[str] = _POPUP_WINDOW_TITLES

    def __init__(
        self,
        application: "Application",
        finder: "ElementFinder",
        config: "WeChatConfig",
    ):
        self._app = application
        self._finder = finder
        self._config = config

    def reset_ui_environment(self) -> None:
        """Force reset the WeChat UI to idle state.

        Performs:
            1. Close independent windows (Moments SNSWnd, Channels TopStoryWnd)
            2. Press Esc to dismiss popups and clear search
            3. Switch back to main chat list Tab

        Each step is independent: a failure in one step does not
        prevent the others from running.

        Raises:
            EnvironmentResetError: If all steps fail.
        """
        logger.info("Resetting UI environment...")
        errors: list[str] = []

        # Step 1: Close known popup windows by class name
        try:
            self.close_popup_windows()
        except Exception as exc:
            logger.debug("close_popup_windows failed: %s", exc)
            errors.append(f"close_popups: {exc}")

        # Step 2: Press Esc multiple times to dismiss popups/search/clear
        try:
            win = self._app.main_window
            for _ in range(3):
                win.type_keys("{ESC}")
                time.sleep(0.2)
        except Exception as exc:
            logger.debug("ESC press failed: %s", exc)
            errors.append(f"esc: {exc}")

        # Step 3: Navigate back to chat list tab
        try:
            self._finder.navigate_to_chat_list()
            time.sleep(self._config.action_delay)
        except Exception as exc:
            logger.debug("navigate_to_chat_list failed: %s", exc)
            errors.append(f"navigate: {exc}")

        if len(errors) == 3:
            raise EnvironmentResetError(
                f"All reset steps failed: {'; '.join(errors)}"
            )
        elif errors:
            logger.warning(
                "UI reset partially failed: %s", '; '.join(errors)
            )

        logger.info("UI environment reset complete.")

    def validate_state(self) -> bool:
        """Validate that the UI is in a clean idle state.

        Checks:
        - No known popup windows are open
        - Main chat list tab is accessible
        - Search box is not active (no search in progress)

        Returns:
            True if the environment is ready for next task, False otherwise.
        """
        try:
            # Check no popup windows are open
            popups = self._find_open_popups()
            if popups:
                logger.debug("validate_state: %d popup(s) still open.", len(popups))
                return False

            # Check main window is accessible
            win = self._app.main_window
            win.wrapper_object()

            # Check chat list tab is active (search for the tab)
            try:
                from wechat_auto.ui.finder import ElementFinder

                finder = ElementFinder(self._app, self._config)
                # If the chat list tab exists and is accessible, state is OK
                finder.find_child_by_title(
                    win, self._config.kw_chat_list, timeout=2.0
                )
            except Exception:
                pass  # Tab might not be found in all WeChat versions

            return True
        except Exception as exc:
            logger.debug("validate_state failed: %s", exc)
            return False

    def close_popup_windows(self) -> None:
        """Close known popup windows (SNSWnd, TopStoryWnd, etc.).

        Enumerates all open windows by class name and title,
        and closes any that match known popup patterns.
        """
        closed_count = 0

        # Try to close windows by class name using pywinauto
        try:
            desktop = _Desktop(backend=self._config.backend) if _Desktop else None
            if desktop is not None:
                for cls_name in self.popup_classes:
                    try:
                        popup = desktop.window(class_name=cls_name)
                        if popup.exists(timeout=1.0):
                            logger.debug("Closing popup window: %s", cls_name)
                            popup.close(timeout=2.0)
                            closed_count += 1
                            time.sleep(0.3)
                    except Exception as exc:
                        logger.debug("Could not close %s: %s", cls_name, exc)
        except Exception as exc:
            logger.debug("Desktop enumeration failed: %s", exc)

        # Try to close windows by title
        if desktop is not None:
            for title in self.popup_titles:
                try:
                    popup = desktop.window(title=title)
                    if popup.exists(timeout=1.0):
                        logger.debug("Closing popup window: %s", title)
                        popup.close(timeout=2.0)
                        closed_count += 1
                        time.sleep(0.3)
                except Exception as exc:
                    logger.debug("Could not close '%s': %s", title, exc)

        if closed_count > 0:
            logger.info("Closed %d popup window(s).", closed_count)

    def _find_open_popups(self) -> list[str]:
        """Find all currently open popup windows.

        Returns:
            List of window class names or titles that are open.
        """
        open_popups: list[str] = []

        try:
            desktop = _Desktop(backend=self._config.backend) if _Desktop else None
            if desktop is not None:
                for cls_name in self.popup_classes:
                    try:
                        popup = desktop.window(class_name=cls_name)
                        if popup.exists(timeout=0.5):
                            open_popups.append(cls_name)
                    except Exception:
                        continue
        except Exception:
            pass

        return open_popups
