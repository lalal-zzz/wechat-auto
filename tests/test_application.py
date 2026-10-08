import ctypes
import ctypes.wintypes as wt
from unittest.mock import patch

import pytest

from wechat_auto.core.application import Application
from wechat_auto.exceptions import WeChatNotRunningError


class FakeKernel32:
    GetCurrentThreadId = staticmethod(lambda: 111)


class FakeUser32:
    def __init__(self, windows):
        self.windows = windows
        self.shown = []
        self.foreground = 0
        self.attach_calls = []

    def EnumWindows(self, callback, lparam):
        for hwnd in self.windows:
            callback(hwnd, lparam)

    def IsWindow(self, hwnd): return hwnd in self.windows
    def IsWindowVisible(self, hwnd): return int(self.windows.get(hwnd, {}).get("visible", False))
    def IsIconic(self, hwnd): return int(self.windows.get(hwnd, {}).get("iconic", False))
    def GetWindowTextLengthW(self, hwnd): return len(self.windows.get(hwnd, {}).get("title", ""))
    def GetWindowTextW(self, hwnd, buffer, _length): buffer.value = self.windows[hwnd]["title"]
    def GetClassNameW(self, hwnd, buffer, _length): buffer.value = self.windows[hwnd]["cls"]
    def GetWindowLongW(self, hwnd, _index): return self.windows[hwnd].get("style", 0xB6C70000)
    def GetWindowRect(self, hwnd, pointer):
        rect = ctypes.cast(pointer, ctypes.POINTER(wt.RECT)).contents
        rect.left, rect.top, rect.right, rect.bottom = self.windows[hwnd]["rect"]
        return 1
    def ShowWindow(self, hwnd, command):
        self.shown.append((hwnd, command))
        self.windows[hwnd].update(visible=True, iconic=False)
        return 1
    def SetForegroundWindow(self, hwnd): self.foreground = hwnd; return 1
    def GetForegroundWindow(self): return self.foreground
    def GetWindowThreadProcessId(self, _hwnd, pid):
        if pid:
            ctypes.cast(pid, ctypes.POINTER(wt.DWORD)).contents.value = 9876
        return 4242
    def AttachThreadInput(self, src, dst, value): self.attach_calls.append((src, dst, bool(value))); return 1
    def BringWindowToTop(self, _hwnd): return 1
    def SetProcessDpiAwarenessContext(self, _value): return 1


def _main(visible=False, iconic=False):
    return {123: {"title": "微信", "cls": "Qt51514QWindowIcon",
                  "visible": visible, "iconic": iconic,
                  "rect": (100, 100, 1100, 800)}}


def test_discovers_exact_weixin_4_window():
    api = FakeUser32(_main())
    with patch("wechat_auto.core.application.user32", api), \
         patch("wechat_auto.core.application.WNDENUMPROC", side_effect=lambda fn: fn):
        assert Application()._find_wechat_main_hwnd() == 123


def test_discovers_weixin_when_title_is_active_chat_name():
    windows = _main()
    windows[123]["title"] = "阿里嘎多"
    api = FakeUser32(windows)
    with patch("wechat_auto.core.application.user32", api), \
         patch("wechat_auto.core.application.WNDENUMPROC", side_effect=lambda fn: fn):
        assert Application()._find_wechat_main_hwnd() == 123


def test_discovers_minimized_weixin_with_active_chat_title():
    windows = _main(visible=True, iconic=True)
    windows[123]["title"] = "阿里嘎多"
    api = FakeUser32(windows)
    with patch("wechat_auto.core.application.user32", api), \
         patch("wechat_auto.core.application.WNDENUMPROC", side_effect=lambda fn: fn):
        assert Application()._find_wechat_main_hwnd() == 123


def test_connect_restores_hidden_window_without_uia():
    api = FakeUser32(_main())
    with patch("wechat_auto.core.application.user32", api), \
         patch("wechat_auto.core.application.WNDENUMPROC", side_effect=lambda fn: fn), \
         patch("wechat_auto.core.application.time.sleep"):
        app = Application().connect()
    assert app.handle == 123
    assert api.shown == [(123, 9)]


def test_connect_rejects_other_windows():
    api = FakeUser32({7: {"title": "微信", "cls": "Other", "visible": True,
                          "iconic": False, "rect": (0, 0, 500, 500)}})
    with (
        patch("wechat_auto.core.application.user32", api),
        patch("wechat_auto.core.application.WNDENUMPROC", side_effect=lambda fn: fn),
        pytest.raises(WeChatNotRunningError),
    ):
        Application().connect()


def test_visible_window_is_not_woken_by_observation_loop():
    api = FakeUser32(_main(visible=True))
    app = Application(); app._hwnd = 123
    with patch("wechat_auto.core.application.user32", api):
        assert app.ensure_interactable() is False
    assert api.shown == []


def test_auxiliary_binding_keeps_main_and_rejects_foreign_process():
    app = Application(); app._hwnd = 123
    with patch.object(Application, 'window_process_id', side_effect=lambda h: 5 if h in {123, 456} else 6):
        child = app.for_window(456)
        assert child.handle == 456 and app.handle == 123
        with pytest.raises(PermissionError, match='connected Weixin process'):
            app.for_window(999)


def test_minimized_main_is_not_replaced_by_a_large_album_of_the_same_class():
    windows = _main(visible=True, iconic=True)
    windows[123]['rect'] = (-32000, -32000, -31763, -31961)
    windows[456] = {'title': '相册', 'cls': 'Qt51514QWindowIcon', 'visible': True,
                    'iconic': False, 'rect': (0, 0, 1600, 1000), 'style': 0xD60B0000}
    api = FakeUser32(windows)
    with patch('wechat_auto.core.application.user32', api), \
         patch('wechat_auto.core.application.WNDENUMPROC', side_effect=lambda fn: fn):
        assert Application()._find_wechat_main_hwnd() == 123


def test_a_popup_with_the_configured_title_cannot_authenticate_a_main_window():
    windows = _main(visible=True)
    windows[123]['style'] = 0xD60B0000
    api = FakeUser32(windows)
    with patch('wechat_auto.core.application.user32', api), \
         patch('wechat_auto.core.application.WNDENUMPROC', side_effect=lambda fn: fn):
        assert Application()._find_wechat_main_hwnd() is None


def test_multiple_native_main_frames_require_explicit_selection():
    windows = _main(visible=True)
    windows[456] = {**windows[123], 'rect': (0, 0, 1600, 1000)}
    api = FakeUser32(windows)
    with patch('wechat_auto.core.application.user32', api), \
         patch('wechat_auto.core.application.WNDENUMPROC', side_effect=lambda fn: fn), \
         pytest.raises(WeChatNotRunningError, match='Multiple Weixin main windows'):
        Application()._find_wechat_main_hwnd()
