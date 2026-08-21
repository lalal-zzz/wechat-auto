"""Application wrapper for WeChat process."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import subprocess
import time
from typing import Optional

from pywinauto import Application as PywinautoApp
from pywinauto.application import WindowSpecification

from wechat_auto.config import WeChatConfig
from wechat_auto.exceptions import (
    WeChatNotReadyError,
    WeChatNotFoundError,
    WeChatNotRunningError,
)

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)


class Application:
    """Wraps pywinauto.Application to connect to a running WeChat instance."""

    def __init__(self, config: Optional[WeChatConfig] = None):
        self._config = config or WeChatConfig()
        self._app: Optional[PywinautoApp] = None
        self._main_window: Optional[WindowSpecification] = None
        self._hwnd: Optional[int] = None

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

    @property
    def handle(self) -> Optional[int]:
        return self._hwnd

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> "Application":
        """Connect to a running WeChat instance.

        First attempts precise HWND discovery and wake-up via Win32 API,
        then binds pywinauto with backend (default 'uia'). Falls back
        to standard title / class_name search strategies if needed.

        Returns:
            self for method chaining.

        Raises:
            WeChatNotRunningError: If WeChat is not running.
            WeChatNotFoundError: If the main window cannot be found.
        """
        logger.info("Connecting to WeChat (backend=%s)...", self._config.backend)

        # Primary Strategy: Precise HWND discovery
        hwnd = self._find_wechat_main_hwnd()

        if hwnd is None and self._config.auto_start:
            executable = self._config.executable_path or self._find_executable()
            if executable:
                logger.info("WeChat main window not visible; launching %s to wake up", executable)
                try:
                    subprocess.Popen([executable], close_fds=True)
                    deadline = time.monotonic() + self._config.launch_wait_timeout
                    while time.monotonic() < deadline:
                        time.sleep(0.5)
                        hwnd = self._find_wechat_main_hwnd()
                        if hwnd:
                            logger.info("Found WeChat main window HWND %d after launch", hwnd)
                            break
                except OSError as exc:
                    logger.warning("Failed to launch WeChat executable: %s", exc)

        connected = False
        last_exc = None

        if hwnd:
            try:
                # Restore and show window before binding
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.2)

                self._app = PywinautoApp(backend=self._config.backend).connect(handle=hwnd)
                self._hwnd = hwnd
                self._main_window = self._app.window(handle=hwnd)
                connected = True
                logger.info("Connected to WeChat via HWND %d (%s)", hwnd, self._config.backend)
            except Exception as exc:
                last_exc = exc
                logger.debug("Connecting via HWND %d failed: %s, falling back to name strategies", hwnd, exc)

        if not connected:
            # Fallback strategies: pywinauto standard matchers
            strategies = [
                ("title", {"title": self._config.wechat_title}),
                ("class_name", {"class_name": self._config.wechat_class_name}),
                ("legacy_class", {"class_name": self._config.wechat_class_name_legacy}),
            ]
            for name, kwargs in strategies:
                try:
                    logger.debug("Trying strategy: %s (%s)", name, kwargs)
                    self._app = PywinautoApp(backend=self._config.backend).connect(
                        **kwargs, timeout=2.0
                    )
                    self._main_window = self._find_main_window()
                    if self._main_window:
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

        if self._main_window is None:
            self._main_window = self._find_main_window()

        if self._main_window is None:
            raise WeChatNotFoundError("WeChat main window not found.")

        try:
            self._ensure_ready()
        except Exception:
            # A rejected connection must not be reported as usable through
            # ``is_connected`` on a subsequent call.
            self.disconnect()
            raise
        logger.info("Successfully connected to WeChat.")
        return self

    def _ensure_ready(self) -> None:
        """Fail early when a known modal dialog blocks all UI actions.

        A process/window connection alone does not mean WeChat can receive
        automation input.  Newer Weixin clients show the storage-location
        dialog inside the main UIA tree, so checking it here prevents examples
        from claiming a successful connection and then failing later while
        searching for unrelated controls.
        """
        try:
            texts = [
                element.window_text().strip()
                for element in self.main_window.descendants(control_type="Text")
            ]
        except Exception as exc:
            # Some client builds expose a partial UIA tree.  Do not reject a
            # usable connection solely because the readiness scan is absent.
            logger.debug("Could not inspect WeChat readiness: %s", exc)
            return

        if any("存储位置无法使用" in text for text in texts):
            raise WeChatNotReadyError(
                "WeChat is blocked by its storage-location dialog. Click “更改” "
                "in WeChat and choose an existing writable local folder, then "
                "restart the end-to-end test."
            )

        if any("扫码登录" in text for text in texts):
            raise WeChatNotReadyError(
                "WeChat is showing its login screen. Sign in to WeChat in this "
                "desktop session, then restart the end-to-end test."
            )

    def _find_wechat_main_hwnd(self) -> Optional[int]:
        """Find the main window HWND of WeChat using Windows API."""
        found_hwnds: list[tuple[int, int, str, str, tuple]] = []

        def callback(hwnd, lparam):
            # A taskbar-minimized WeChat window is not reported as visible by
            # some Windows builds.  It is nevertheless a valid, attachable
            # main window and must be restored before automation begins.
            is_minimized = bool(user32.IsIconic(hwnd))
            if not user32.IsWindowVisible(hwnd) and not is_minimized:
                return True

            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value

            cls_buff = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls_buff, 256)
            cls_name = cls_buff.value

            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            width = rect.right - rect.left
            height = rect.bottom - rect.top

            # Check if this window matches WeChat main window characteristics
            is_qt_wechat = cls_name == self._config.wechat_class_name and (title == self._config.wechat_title or "微信" in title)
            is_legacy_wechat = cls_name == self._config.wechat_class_name_legacy and (title == self._config.wechat_title or "微信" in title)
            is_generic_wechat = (title == self._config.wechat_title or "微信" in title) and ("Qt" in cls_name or "WeChat" in cls_name)

            # Minimized windows may report a tiny taskbar rectangle, so area
            # filtering is only valid for non-minimized windows.
            if (is_qt_wechat or is_legacy_wechat or is_generic_wechat) and (
                is_minimized or (width > 100 and height > 100)
            ):
                found_hwnds.append((hwnd, width * height, cls_name, title, (rect.left, rect.top, rect.right, rect.bottom)))
            return True

        cb = WNDENUMPROC(callback)
        user32.EnumWindows(cb, 0)

        if found_hwnds:
            # Sort by area descending (main window is the largest one)
            found_hwnds.sort(key=lambda x: x[1], reverse=True)
            best_hwnd = found_hwnds[0][0]
            logger.debug("Found WeChat main HWND %d (Class: %s, Title: %s, Rect: %s)",
                         best_hwnd, found_hwnds[0][2], found_hwnds[0][3], found_hwnds[0][4])
            return best_hwnd

        return None

    def _find_executable(self) -> Optional[str]:
        """Find a usable WeChat executable for tray-only sessions."""
        candidates = [
            r"D:\software\微信\Weixin\Weixin.exe",
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Tencent", "Weixin", "Weixin.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Tencent", "Weixin", "Weixin.exe"),
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Tencent", "WeChat", "WeChat.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Tencent", "WeChat", "WeChat.exe"),
        ]
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate
        return None

    def _find_main_window(self) -> Optional[WindowSpecification]:
        """Try to find the main window using multiple criteria."""
        assert self._app is not None

        if self._hwnd:
            try:
                spec = self._app.window(handle=self._hwnd)
                spec.wrapper_object()
                return spec
            except Exception:
                pass

        try:
            all_windows = self._app.windows()
            for win in all_windows:
                try:
                    title = win.window_text()
                    if title == self._config.wechat_title or "微信" in title:
                        return self._app.window(handle=win.handle)
                except Exception:
                    continue

            for win in all_windows:
                try:
                    if win.is_visible() and win.window_text():
                        return self._app.window(handle=win.handle)
                except Exception:
                    continue
        except Exception:
            pass

        try:
            win = self._app.top_window()
            win.wrapper_object()
            return win
        except Exception:
            pass

        try:
            win = self._app.window(title=self._config.wechat_title)
            win.wrapper_object()
            return win
        except Exception:
            pass

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
        try:
            if win.is_minimized():
                win.restore()
        except Exception:
            pass

        hwnd = getattr(win, "handle", self._hwnd)
        if hwnd:
            try:
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

        try:
            win.set_focus()
        except Exception as exc:
            logger.debug("set_focus fallback: %s", exc)

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
        self._hwnd = None
        logger.info("Disconnected from WeChat.")
