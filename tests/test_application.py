"""Tests for application readiness checks."""

import ctypes
import ctypes.wintypes
from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.core.application import Application
from wechat_auto.exceptions import WeChatNotReadyError


def test_storage_location_modal_blocks_connection_readiness():
    app = Application()
    text = MagicMock()
    text.window_text.return_value = "存储位置无法使用，将不能正常使用微信，请更改位置。"
    app._main_window = MagicMock()
    app._main_window.descendants.return_value = [text]

    with pytest.raises(WeChatNotReadyError, match="storage-location"):
        app._ensure_ready()


def test_readiness_allows_normal_window():
    app = Application()
    text = MagicMock()
    text.window_text.return_value = "微信"
    app._main_window = MagicMock()
    app._main_window.descendants.return_value = [text]

    app._ensure_ready()


def test_login_screen_blocks_connection_readiness():
    app = Application()
    text = MagicMock()
    text.window_text.return_value = "扫码登录"
    app._main_window = MagicMock()
    app._main_window.descendants.return_value = [text]

    with pytest.raises(WeChatNotReadyError, match="login screen"):
        app._ensure_ready()


def test_minimized_wechat_window_is_discovered():
    """A taskbar-minimized WeChat window is still a valid attach target."""

    class FakeUser32:
        def IsWindowVisible(self, hwnd):
            return 0

        def IsIconic(self, hwnd):
            return 1

        def GetWindowTextLengthW(self, hwnd):
            return 2

        def GetWindowTextW(self, hwnd, buffer, length):
            buffer.value = "微信"

        def GetClassNameW(self, hwnd, buffer, length):
            buffer.value = "Qt51514QWindowIcon"

        def GetWindowRect(self, hwnd, rect_ptr):
            rect = ctypes.cast(
                rect_ptr, ctypes.POINTER(ctypes.wintypes.RECT)
            ).contents
            rect.left, rect.top, rect.right, rect.bottom = 0, 0, 10, 10

        def EnumWindows(self, callback, lparam):
            callback(123, lparam)

    with patch("wechat_auto.core.application.user32", FakeUser32()):
        with patch("wechat_auto.core.application.WNDENUMPROC", side_effect=lambda cb: cb):
            assert Application()._find_wechat_main_hwnd() == 123
