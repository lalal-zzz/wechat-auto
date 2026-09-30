"""No-vision keyboard/coordinate driver for Weixin 4.x.

Weixin 4.x may expose only a canvas-like UIA shell.  This module deliberately
does not import UIA, OCR, screenshots, or process-memory helpers.  It uses the
normal foreground window, clipboard paste, and a small set of layout anchors.

The send operation is opt-in: ``send_text(..., confirm=True)`` is required to
press Enter.  The default only prepares a draft, which makes calibration and
dry-run testing safe.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from wechat_auto.utils.clipboard import ClipboardHelper

if TYPE_CHECKING:
    from wechat_auto.core.application import Application


user32 = ctypes.windll.user32
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
WM_SETCURSOR = 0x0020
WM_MOUSEACTIVATE = 0x0021
MK_LBUTTON = 0x0001
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
MK_RBUTTON = 0x0002
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_MOUSEWHEEL = 0x020A
WM_PASTE = 0x0302
WM_CLOSE = 0x0010
VK_CONTROL = 0x11
VK_A = 0x41
VK_BACK = 0x08
VK_F = 0x46
VK_V = 0x56
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
SW_HIDE = 0
SW_SHOW = 5
SW_MINIMIZE = 6


class _GuiThreadInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD), ("flags", wt.DWORD),
        ("hwndActive", wt.HWND), ("hwndFocus", wt.HWND),
        ("hwndCapture", wt.HWND), ("hwndMenuOwner", wt.HWND),
        ("hwndMoveSize", wt.HWND), ("hwndCaret", wt.HWND),
        ("rcCaret", wt.RECT),
    ]


@dataclass(frozen=True)
class KeyboardOnlyLayout:
    """Fractional anchors measured from the complete top-level window."""

    # Center of the left search box on the supported Weixin 4.x wide layout.
    # The former .178 anchor lands near its edge on a three-column window.
    search_x: float = 0.140
    search_y: float = 0.084
    input_x: float = 0.660
    input_y: float = 0.850

    @classmethod
    def from_screen_points(
        cls,
        rect: tuple[int, int, int, int],
        search: tuple[int, int],
        input_box: tuple[int, int],
    ) -> KeyboardOnlyLayout:
        """Create anchors from two user-supplied screen points.

        This is manual calibration: no screenshot, OCR, or UIA inspection is
        performed.  The resulting fractions remain usable after moving or
        resizing the window.
        """
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            raise ValueError("window rect must have positive width and height")
        return cls(
            search_x=(search[0] - left) / width,
            search_y=(search[1] - top) / height,
            input_x=(input_box[0] - left) / width,
            input_y=(input_box[1] - top) / height,
        )

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(self.__dict__, stream, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> KeyboardOnlyLayout:
        with open(path, "r", encoding="utf-8") as stream:
            values = json.load(stream)
        return cls(**{key: float(values[key]) for key in (
            "search_x", "search_y", "input_x", "input_y"
        )})


class KeyboardOnlyDriver:
    """Drive the self-drawn client without UIA or visual recognition."""

    def __init__(
        self,
        application: Application,
        layout: KeyboardOnlyLayout | None = None,
        search_mode: str = "click",
        input_mode: str = "wmchar",
        auto_activate: bool = True,
        foreground_mode: str | None = None,
    ):
        self.application = application
        self.layout = layout or KeyboardOnlyLayout()
        if search_mode not in {"click", "shortcut"}:
            raise ValueError("search_mode must be 'click' or 'shortcut'")
        if input_mode not in {"winmsg", "wmchar"}:
            raise ValueError("input_mode must be 'winmsg' or 'wmchar'")
        self.search_mode = search_mode
        self.input_mode = input_mode
        self.auto_activate = bool(auto_activate)
        self.foreground_mode = foreground_mode or ("leave" if auto_activate else "restore")
        if self.foreground_mode not in {"leave", "restore", "never"}:
            raise ValueError("foreground_mode must be 'leave', 'restore' or 'never'")
        self._lease_depth = 0
        self._previous_foreground = 0

    @contextmanager
    def foreground_lease(self) -> Iterator[None]:
        """Temporarily activate MMUI and restore the user's prior foreground."""
        outer = self._lease_depth == 0
        if outer:
            self._previous_foreground = int(user32.GetForegroundWindow() or 0)
            if self.foreground_mode != "never":
                self.application.activate()
        self._lease_depth += 1
        try:
            yield
        finally:
            self._lease_depth -= 1
            if (outer and self.foreground_mode == "restore"
                    and self._previous_foreground
                    and user32.IsWindow(self._previous_foreground)):
                user32.SetForegroundWindow(self._previous_foreground)
            if outer:
                self._previous_foreground = 0

    def _settle_ui(self) -> None:
        """Allow Qt/MMUI to consume the synchronous message and settle state."""
        config = getattr(self.application, "config", None)
        delay = max(0.0, float(getattr(config, "ui_settle_delay", 0.12)))
        if delay:
            time.sleep(delay)

    def _window_state(self) -> tuple[bool, bool]:
        hwnd = self.application.handle
        return bool(user32.IsWindowVisible(hwnd)), bool(user32.IsIconic(hwnd))

    def _restore_window_state(self, state: tuple[bool, bool]) -> None:
        hwnd = self.application.handle
        visible, iconic = state
        if iconic:
            user32.ShowWindow(hwnd, SW_MINIMIZE)
        elif visible:
            user32.ShowWindow(hwnd, SW_SHOW)
        else:
            user32.ShowWindow(hwnd, SW_HIDE)

    @contextmanager
    def preserve_window_state(self) -> Iterator[None]:
        """Restore hidden/minimized/visible state after an operation."""
        state = self._window_state()
        try:
            yield
        finally:
            self._restore_window_state(state)

    def _rect(self) -> tuple[int, int, int, int]:
        rect = wt.RECT()
        if not user32.GetWindowRect(self.application.handle, ctypes.byref(rect)):
            raise RuntimeError("Cannot read the WeChat window rectangle")
        return rect.left, rect.top, rect.right, rect.bottom

    def point(self, fx: float, fy: float) -> tuple[int, int]:
        """Convert a fractional window anchor to a screen point."""
        left, top, right, bottom = self._rect()
        return (
            left + round((right - left) * fx),
            top + round((bottom - top) * fy),
        )

    def _browser_pointer_hwnd(self, fx: float, fy: float, *, render: bool = False) -> int:
        """Find the unique visible embedded Chromium HWND containing this point."""
        sx, sy = self.point(fx, fy)
        wanted = "Chrome_RenderWidgetHostHWND" if render else "Chrome_WidgetWin_0"
        matches = []
        callback_type = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

        def collect(hwnd, _param):
            name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, name, 256)
            rect = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            if (name.value == wanted and user32.IsWindowVisible(hwnd)
                    and rect.left <= sx < rect.right and rect.top <= sy < rect.bottom):
                matches.append(int(hwnd))
            return True

        user32.EnumChildWindows(self.application.handle, callback_type(collect), 0)
        if len(matches) != 1:
            raise RuntimeError("Embedded content HWND is absent or ambiguous")
        return matches[0]

    def _click_window_fraction(self, fx: float, fy: float, *,
                               target_hwnd: int | None = None) -> None:
        """Send a client-area click to the top-level HWND without moving the mouse."""
        hwnd = target_hwnd or self.application.handle
        sx, sy = self.point(fx, fy)
        point = wt.POINT(sx, sy)
        if not user32.ScreenToClient(hwnd, ctypes.byref(point)):
            raise RuntimeError("ScreenToClient failed")
        lparam = (point.x & 0xFFFF) | ((point.y & 0xFFFF) << 16)
        # Weixin 4.x's MMUI shell dispatches the actual hit-test from its
        # top-level WndProc.  Synchronous delivery is important: PostMessage
        # can leave the move/down/up sequence unassociated and silently lose
        # the click, especially when Weixin is not the foreground window.
        for message, wparam in ((WM_MOUSEMOVE, 0), (WM_LBUTTONDOWN, MK_LBUTTON),
                                (WM_LBUTTONUP, 0)):
            user32.SendMessageW(hwnd, message, wparam, lparam)

    def _right_click_window_fraction(self, fx: float, fy: float) -> None:
        """Send a right click to a client point without moving the cursor."""
        hwnd = self.application.handle
        sx, sy = self.point(fx, fy)
        point = wt.POINT(sx, sy)
        if not user32.ScreenToClient(hwnd, ctypes.byref(point)):
            raise RuntimeError("ScreenToClient failed")
        lparam = (point.x & 0xFFFF) | ((point.y & 0xFFFF) << 16)
        user32.SendMessageW(hwnd, WM_RBUTTONDOWN, MK_RBUTTON, lparam)
        user32.SendMessageW(hwnd, WM_RBUTTONUP, 0, lparam)

    def _wm_key(self, vk: int, down: bool = True) -> None:
        hwnd = self._focused_input_hwnd()
        lparam = 0x00000001 if down else 0xC0000001
        if not user32.PostMessageW(hwnd, WM_KEYDOWN if down else WM_KEYUP, vk, lparam):
            raise RuntimeError("PostMessageW(key) failed")

    def _focused_input_hwnd(self) -> int:
        """Return Weixin's focused descendant HWND when Win32 exposes one.

        This is focus routing only: it neither inspects a UIA tree nor reads
        process memory.  Pointer gestures remain addressed to the main HWND.
        """
        main = int(self.application.handle)
        try:
            thread_id = user32.GetWindowThreadProcessId(main, None)
            info = _GuiThreadInfo()
            info.cbSize = ctypes.sizeof(_GuiThreadInfo)
            if (thread_id and user32.GetGUIThreadInfo(thread_id, ctypes.byref(info))
                    and info.hwndFocus
                    and (int(info.hwndFocus) == main or user32.IsChild(main, info.hwndFocus))):
                return int(info.hwndFocus)
        except Exception:
            pass
        return main

    def _wm_chord(self, vk: int) -> None:
        self._wm_key(VK_CONTROL, True)
        self._wm_key(vk, True)
        self._wm_key(vk, False)
        self._wm_key(VK_CONTROL, False)

    def _wm_char_text(self, text: str) -> None:
        """Send Unicode WM_CHAR units to the focused Qt editor.

        This is deliberately separate from WM_KEYDOWN: Qt accepts the
        resulting UTF-16 characters in the focused self-drawn editor, while
        it may ignore synthetic key messages for text entry.  The caller must
        have focused the desired editor first.  No clipboard is touched.
        """
        hwnd = self._focused_input_hwnd()
        if any(ord(ch) < 32 for ch in text):
            raise ValueError("WM_CHAR text must be single-line printable text")
        encoded = text.encode("utf-16-le")
        for offset in range(0, len(encoded), 2):
            code_unit = int.from_bytes(encoded[offset:offset + 2], "little")
            if not user32.PostMessageW(hwnd, WM_CHAR, code_unit, 0):
                raise RuntimeError("PostMessageW(WM_CHAR) failed")

    def _type_text(self, text: str) -> None:
        if self.input_mode == "wmchar":
            self._wm_char_text(text)
        else:
            ClipboardHelper.set_text(text)
            self._paste()

    def _select_all_clear(self) -> None:
        self._wm_chord(VK_A)
        self._wm_key(VK_BACK, True)
        self._wm_key(VK_BACK, False)

    def _paste(self) -> None:
        # A direct standard paste message is forwarded by Weixin's Qt shell
        # to its focused editor more reliably than a synthetic Ctrl+V chord.
        if not user32.PostMessageW(self._focused_input_hwnd(), WM_PASTE, 0, 0):
            raise RuntimeError("PostMessageW(WM_PASTE) failed")

    def _enter(self) -> None:
        self._wm_key(VK_RETURN, True)
        self._wm_key(VK_RETURN, False)

    def wheel_window_fraction(self, fx: float, fy: float, notches: int = 3) -> None:
        """Post a normal mouse-wheel message to the top-level WeChat HWND.

        ``notches > 0`` means scroll down. This neither moves the cursor nor
        uses input injection; Qt receives its ordinary window message.
        """
        if not 0.0 <= fx <= 1.0 or not 0.0 <= fy <= 1.0:
            raise ValueError("wheel coordinates must be window fractions")
        if notches == 0:
            return
        with self.foreground_lease():
            sx, sy = self.point(fx, fy)
            lparam = (sx & 0xFFFF) | ((sy & 0xFFFF) << 16)
            delta = -120 * int(notches)
            wparam = (delta & 0xFFFF) << 16
            if not user32.PostMessageW(self.application.handle, WM_MOUSEWHEEL, wparam, lparam):
                raise RuntimeError("PostMessageW(WM_MOUSEWHEEL) failed")
            self._settle_ui()

    def click_search(self) -> None:
        with self.foreground_lease():
            self._click_window_fraction(self.layout.search_x, self.layout.search_y)
            self._settle_ui()

    def focus_search(self) -> None:
        """Focus Weixin's left search box using the configured safe route."""
        if self.search_mode == "shortcut":
            with self.foreground_lease():
                self._wm_chord(VK_F)
                self._settle_ui()
            return
        self.click_search()

    def click_window_fraction(self, fx: float, fy: float) -> None:
        """Click a calibrated self-drawn location through ``WM_LBUTTON*``.

        This is for controls such as a user's sticker-grid cell where WeChat
        exposes no UIA element.  The caller must supply a verified layout
        anchor; this driver deliberately does not guess a sticker identity.
        """
        if not 0.0 <= fx <= 1.0 or not 0.0 <= fy <= 1.0:
            raise ValueError("click coordinates must be window fractions")
        with self.foreground_lease():
            self._click_window_fraction(fx, fy)
            self._settle_ui()

    def drag_window_fraction(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        """Move a caller-verified divider using the existing HWND transport."""
        if any(not 0 <= value <= 1 for value in (*start, *end)):
            raise ValueError("Drag coordinates must be window fractions")
        hwnd = self.application.handle
        def packed(fx, fy):
            point = wt.POINT(*self.point(fx, fy))
            if not user32.ScreenToClient(hwnd, ctypes.byref(point)):
                raise RuntimeError("ScreenToClient failed")
            return (point.x & 0xFFFF) | ((point.y & 0xFFFF) << 16)
        with self.foreground_lease():
            first = packed(*start)
            user32.SendMessageW(hwnd, WM_MOUSEMOVE, 0, first)
            user32.SendMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, first)
            try:
                for step in range(1, 13):
                    point = packed(*(a + (b - a) * step / 12 for a, b in zip(start, end)))
                    user32.SendMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, point)
                    time.sleep(.025)
            finally:
                user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, packed(*end))
            self._settle_ui()

    def click_window_fraction_sync(self, fx: float, fy: float) -> None:
        """Synchronously dispatch one verified row click to the main HWND."""
        if not 0.0 <= fx <= 1.0 or not 0.0 <= fy <= 1.0:
            raise ValueError("click coordinates must be window fractions")
        with self.foreground_lease():
            self._click_window_fraction(fx, fy)
            self._settle_ui()

    def click_content_fraction(self, fx: float, fy: float, *, render: bool = False) -> None:
        """Route tab-strip/body messages to the embedded Chromium child HWND."""
        if not 0 <= fx <= 1 or not 0 <= fy <= 1:
            raise ValueError("click coordinates must be window fractions")
        with self.foreground_lease():
            hwnd = self._browser_pointer_hwnd(fx, fy, render=render)
            self._click_window_fraction(fx, fy, target_hwnd=hwnd)
            self._settle_ui()

    def right_click_window_fraction(self, fx: float, fy: float) -> None:
        """Right-click a calibrated point through ``WM_RBUTTON*``."""
        if not 0.0 <= fx <= 1.0 or not 0.0 <= fy <= 1.0:
            raise ValueError("click coordinates must be window fractions")
        with self.foreground_lease():
            self._right_click_window_fraction(fx, fy)
            self._settle_ui()

    def press_key(self, key: str) -> None:
        """Send one supported navigation key to the top-level HWND."""
        keys = {"enter": VK_RETURN, "escape": VK_ESCAPE, "backspace": VK_BACK}
        try:
            vk = keys[key.lower()]
        except KeyError as exc:
            raise ValueError(f"Unsupported HWND key: {key}") from exc
        with self.foreground_lease():
            self._wm_key(vk, True)
            self._wm_key(vk, False)
            self._settle_ui()

    def close_window(self) -> None:
        """Request ordinary window closure; callers must forbid main-client closure."""
        if not user32.PostMessageW(self.application.handle, WM_CLOSE, 0, 0):
            raise RuntimeError("PostMessageW(WM_CLOSE) failed")
        self._settle_ui()

    def click_input(self) -> None:
        with self.foreground_lease():
            self._click_window_fraction(self.layout.input_x, self.layout.input_y)
            self._settle_ui()

    def prepare_chat_search(self, contact: str, settle: float = 1.2) -> None:
        """Populate search, but never press Enter or choose a result."""
        if not contact:
            raise ValueError("contact must not be empty")
        with self.foreground_lease():
            self.focus_search()
            self._select_all_clear()
            self._type_text(contact)
            time.sleep(max(0.0, settle))

    def open_chat(self, contact: str, settle: float = 1.2) -> None:
        """Compatibility alias for safe search preparation.

        Selection belongs to ``BasicSkill`` after it verifies that the query
        really reached a Weixin search surface.  This method intentionally
        never presses Enter: an unverified focus can otherwise send the query
        text as a real chat message.
        """
        self.prepare_chat_search(contact, settle=settle)

    def prepare_draft(self, contact: str, message: str, settle: float = 1.2) -> None:
        """Open a chat and place text in its input box; never sends it."""
        self.open_chat(contact, settle=settle)
        self.click_input()
        self._type_text(message)

    def send_text(self, contact: str, message: str, *, confirm: bool = False,
                  settle: float = 1.2) -> None:
        """Send through normal input only when the caller explicitly confirms."""
        self.prepare_draft(contact, message, settle=settle)
        if not confirm:
            return
        self._enter()
