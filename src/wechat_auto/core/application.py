"""Application wrapper for WeChat process."""

from __future__ import annotations

import logging
from typing import Optional

from pywinauto import Application as PywinautoApp
from pywinauto.application import WindowSpecification

from wechat_auto.config import WeChatConfig
from wechat_auto.exceptions import WeChatNotRunningError, WeChatNotFoundError

logger = logging.getLogger(__name__)


class Application:
    """Wraps pywinauto.Application to connect to a running WeChat instance."""

    def __init__(self, config: Optional[WeChatConfig] = None):
        self._config = config or WeChatConfig()
        self._app: Optional[PywinautoApp] = None
        self._main_window: Optional[WindowSpecification] = None

    @property
    def config(self) -> WeChatConfig:
        return self._config

    @property
    def app(self) -> PywinautoApp:
        if self._app is None:
            raise WeChatNotRunningError("Not connected to WeChat. Call connect() first.")
        return self._app

    @property
    def main_window(self) -> WindowSpecification:
        if self._main_window is None:
            raise WeChatNotFoundError("Main window not available. Call connect() first.")
        return self._main_window

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> "Application":
        """Connect to a running WeChat instance.

        Tries multiple strategies: by title, by new Weixin class name,
        and by legacy WeChat class name.

        Returns:
            self for method chaining.

        Raises:
            WeChatNotRunningError: If WeChat is not running.
            WeChatNotFoundError: If the main window cannot be found.
        """
        logger.info("Connecting to WeChat (backend=%s)...", self._config.backend)

        # Try multiple connection strategies
        strategies = [
            ("title", {"title": self._config.wechat_title}),
            ("class_name", {"class_name": self._config.wechat_class_name}),
            ("legacy_class", {"class_name": self._config.wechat_class_name_legacy}),
        ]

        connected = False
        last_exc = None

        for name, kwargs in strategies:
            try:
                logger.debug("Trying strategy: %s (%s)", name, kwargs)
                self._app = PywinautoApp(backend=self._config.backend).connect(
                    **kwargs, timeout=self._config.default_timeout
                )
                connected = True
                logger.info("Connected via strategy: %s", name)
                break
            except Exception as exc:
                last_exc = exc
                logger.debug("Strategy %s failed: %s", name, exc)
                continue

        if not connected:
            raise WeChatNotRunningError(
                "Cannot connect to WeChat. Make sure it is running and logged in."
            ) from last_exc

        # Find the main window
        self._main_window = self._find_main_window()
        if self._main_window is None:
            raise WeChatNotFoundError("WeChat main window not found.")

        logger.info("Successfully connected to WeChat.")
        return self

    def _find_main_window(self) -> Optional[WindowSpecification]:
        """Try to find the main window using multiple criteria.

        The new WeChat (Weixin) uses Qt with a custom renderer, so
        app.window() specifications may fail. We iterate app.windows()
        which returns actual wrapper objects.
        """
        assert self._app is not None

        # Strategy 1: iterate actual windows (most reliable for Qt WeChat)
        try:
            all_windows = self._app.windows()
            # Prefer the window with title matching wechat_title
            for win in all_windows:
                try:
                    title = win.window_text()
                    cls = win.class_name()
                    if title == self._config.wechat_title:
                        # Create a WindowSpecification from this wrapper
                        spec = self._app.window(handle=win.handle)
                        logger.debug("Found main window via windows() title match: %s", title)
                        return spec
                except Exception:
                    continue

            # Fallback: use first visible top-level window
            for win in all_windows:
                try:
                    if win.is_visible() and win.window_text():
                        spec = self._app.window(handle=win.handle)
                        logger.debug("Found main window via windows() first visible: %s", win.window_text())
                        return spec
                except Exception:
                    continue
        except Exception:
            pass

        # Strategy 2: top_window
        try:
            win = self._app.top_window()
            win.wrapper_object()
            logger.debug("Found main window via top_window()")
            return win
        except Exception:
            pass

        # Strategy 3: by title
        try:
            win = self._app.window(title=self._config.wechat_title)
            win.wrapper_object()
            return win
        except Exception:
            pass

        # Strategy 4: by class name
        try:
            win = self._app.window(class_name=self._config.wechat_class_name)
            win.wrapper_object()
            return win
        except Exception:
            pass

        return None

    def is_connected(self) -> bool:
        """Check whether we are connected to a WeChat instance."""
        if self._app is None or self._main_window is None:
            return False
        try:
            self._main_window.wrapper_object()
            return True
        except Exception:
            return False

    def activate(self) -> None:
        """Bring the WeChat main window to the foreground."""
        win = self.main_window
        if win.is_minimized():
            win.restore()
        if not win.is_active():
            win.set_focus()

    def minimize(self) -> None:
        """Minimize the WeChat main window."""
        self.main_window.minimize()

    def get_window_rect(self) -> tuple[int, int, int, int]:
        """Return (left, top, right, bottom) of the main window."""
        rect = self.main_window.rectangle()
        return (rect.left, rect.top, rect.right, rect.bottom)

    def disconnect(self) -> None:
        """Release references (does not close WeChat)."""
        self._main_window = None
        self._app = None
        logger.info("Disconnected from WeChat.")
