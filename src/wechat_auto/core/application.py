"""Pure Win32 HWND connection and window-state management for Weixin 4.x."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import os
import subprocess
import time

from wechat_auto.config import WeChatConfig
from wechat_auto.exceptions import WeChatNotRunningError

logger = logging.getLogger(__name__)
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
SW_RESTORE = 9
SW_MINIMIZE = 6


class Application:
    """Find and manage the supported Weixin 4.x top-level HWND."""

    def __init__(self, config: WeChatConfig | None = None):
        self._config = config or WeChatConfig()
        self._hwnd: int | None = None

    @property
    def config(self) -> WeChatConfig:
        return self._config

    @property
    def handle(self) -> int:
        if not self._hwnd:
            raise WeChatNotRunningError("Not connected to WeChat")
        return self._hwnd

    def connect(self) -> Application:
        self._ensure_dpi_awareness()
        hwnd = self._find_wechat_main_hwnd()
        if hwnd is None and self._config.auto_start:
            executable = self._config.executable_path or self._find_executable()
            if executable:
                subprocess.Popen([executable], close_fds=True)
                deadline = time.monotonic() + self._config.launch_wait_timeout
                while time.monotonic() < deadline and hwnd is None:
                    time.sleep(.5)
                    hwnd = self._find_wechat_main_hwnd()
        if hwnd is None:
            raise WeChatNotRunningError("Cannot find logged-in Weixin 4.x top-level window")
        self._hwnd = int(hwnd)
        self.ensure_interactable()
        logger.info("Connected to WeChat HWND %d", self._hwnd)
        return self

    def disconnect(self) -> None:
        self._hwnd = None

    @staticmethod
    def window_process_id(hwnd: int) -> int:
        pid = wt.DWORD()
        if not user32.IsWindow(hwnd):
            raise RuntimeError("Window is no longer available")
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            raise RuntimeError("Window process is unavailable")
        return int(pid.value)

    def list_windows(self) -> list[dict]:
        """Visible top-level windows in the connected client process, without titles."""
        pid = self.window_process_id(self.handle)
        rows = []

        def collect(hwnd, _param):
            if not user32.IsWindowVisible(hwnd):
                return True
            try:
                if self.window_process_id(hwnd) != pid:
                    return True
            except RuntimeError:
                return True  # Window disappeared during enumeration.
            rect = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            rows.append({"hwnd": int(hwnd), "pid": pid, "class": cls.value,
                         "width": rect.right - rect.left, "height": rect.bottom - rect.top,
                         "is_main": int(hwnd) == self.handle})
            return True

        user32.EnumWindows(WNDENUMPROC(collect), 0)
        return rows

    def for_window(self, hwnd: int) -> Application:
        """Bind an auxiliary HWND only after checking the connected process."""
        if self.window_process_id(hwnd) != self.window_process_id(self.handle):
            raise PermissionError("Target window does not belong to the connected Weixin process")
        bound = Application(self.config)
        bound._hwnd = int(hwnd)
        return bound

    def window_metadata(self) -> dict:
        """Read dimensions, DPI and executable file version through Win32."""
        import win32api

        pid = self.window_process_id(self.handle)
        kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
        kernel32.OpenProcess.restype = wt.HANDLE
        process = kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            raise RuntimeError("Cannot query Weixin executable metadata")
        try:
            name = ctypes.create_unicode_buffer(32768)
            length = wt.DWORD(len(name))
            kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR,
                                                           ctypes.POINTER(wt.DWORD)]
            if not kernel32.QueryFullProcessImageNameW(process, 0, name, ctypes.byref(length)):
                raise RuntimeError("Cannot query Weixin executable path")
            info = win32api.GetFileVersionInfo(name.value, "\\")
            ms, ls = info["FileVersionMS"], info["FileVersionLS"]
            version = f"{ms >> 16}.{ms & 65535}.{ls >> 16}.{ls & 65535}"
        finally:
            kernel32.CloseHandle.argtypes = [wt.HANDLE]
            kernel32.CloseHandle(process)
        left, top, right, bottom = self.get_window_rect()
        return {"wechat_version": version, "width": right - left, "height": bottom - top,
                "dpi": int(user32.GetDpiForWindow(self.handle)), "pid": pid}

    def is_connected(self) -> bool:
        return bool(self._hwnd and user32.IsWindow(self._hwnd))

    def activate(self) -> None:
        self._wake_window(self.handle)

    def ensure_interactable(self) -> bool:
        hwnd = self.handle
        if user32.IsIconic(hwnd) or not user32.IsWindowVisible(hwnd):
            return self._wake_window(hwnd)
        return False

    def minimize(self) -> None:
        user32.ShowWindow(self.handle, SW_MINIMIZE)

    def get_window_rect(self) -> tuple[int, int, int, int]:
        rect = wt.RECT()
        if not user32.GetWindowRect(self.handle, ctypes.byref(rect)):
            raise RuntimeError("Cannot read WeChat window rectangle")
        return rect.left, rect.top, rect.right, rect.bottom

    def resize_window(self, width: int, height: int) -> None:
        if not 640 <= width <= 4096 or not 480 <= height <= 2160:
            raise ValueError("Unsupported audit window size")
        if not user32.SetWindowPos(self.handle, 0, 0, 0, width, height, 0x0002 | 0x0004 | 0x0010):
            raise RuntimeError("Window resize failed")

    def _find_wechat_main_hwnd(self) -> int | None:
        found: list[tuple[int, int]] = []

        def callback(hwnd, _lparam):
            length = user32.GetWindowTextLengthW(hwnd)
            title_buffer = ctypes.create_unicode_buffer(length + 1)
            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title_buffer, length + 1)
            user32.GetClassNameW(hwnd, class_buffer, 256)
            if class_buffer.value == self._config.wechat_class_name:
                rect = wt.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
                # Weixin changes the top-level title to the active chat name.
                # Class plus a normal-sized window is the stable identifier;
                # the configured title remains accepted for splash/idle state.
                if (title_buffer.value == self._config.wechat_title
                        or area >= 500_000 or user32.IsIconic(hwnd)):
                    found.append((int(hwnd), area))
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        return max(found, key=lambda item: item[1])[0] if found else None

    def _wake_window(self, hwnd: int) -> bool:
        if not user32.IsWindow(hwnd):
            return False
        if user32.IsIconic(hwnd) or not user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(.3)
        self._force_foreground(hwnd)
        return bool(user32.IsWindowVisible(hwnd))

    @staticmethod
    def _force_foreground(hwnd: int) -> None:
        user32.SetForegroundWindow(hwnd)
        if user32.GetForegroundWindow() == hwnd:
            return
        foreground = user32.GetForegroundWindow()
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
        current_thread = kernel32.GetCurrentThreadId()
        attached = False
        try:
            if foreground_thread and foreground_thread != current_thread:
                attached = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(current_thread, foreground_thread, False)

    @staticmethod
    def _ensure_dpi_awareness() -> None:
        try:
            if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                return
        except Exception:
            pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass

    def _find_executable(self) -> str | None:
        candidates = [
            r"D:\software\微信\Weixin\Weixin.exe",
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Tencent", "Weixin", "Weixin.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Tencent", "Weixin", "Weixin.exe"),
        ]
        return next((path for path in candidates if path and os.path.isfile(path)), None)
