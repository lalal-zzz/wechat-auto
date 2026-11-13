"""Pure HWND PrintWindow capture for OCR observation and evidence."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = os.path.join("data", "screenshots")


class ScreenshotHelper:
    """Capture window/element screenshots and persist them as artifacts."""

    def __init__(self, output_dir: str | None = None, enabled: bool = True):
        self._output_dir = output_dir or DEFAULT_OUTPUT_DIR
        self._enabled = enabled

    @property
    def output_dir(self) -> str:
        return self._output_dir

    @property
    def enabled(self) -> bool:
        return self._enabled

    def capture_window(self, hwnd: int) -> Image.Image | None:
        """Capture a top-level HWND without UIA or pywinauto."""
        if not self._enabled or not hwnd:
            return None
        import ctypes

        import win32gui
        import win32ui
        from PIL import Image

        window_dc = memory_dc = bitmap = None
        source_dc = 0
        previous_bitmap = None
        try:
            left, top, right, bottom = win32gui.GetWindowRect(int(hwnd))
            width, height = right - left, bottom - top
            if width <= 0 or height <= 0:
                return None
            source_dc = win32gui.GetWindowDC(int(hwnd))
            if not source_dc:
                return None
            window_dc = win32ui.CreateDCFromHandle(source_dc)
            memory_dc = window_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(window_dc, width, height)
            previous_bitmap = memory_dc.SelectObject(bitmap)
            if not ctypes.windll.user32.PrintWindow(int(hwnd), memory_dc.GetSafeHdc(), 2):
                return None
            info = bitmap.GetInfo()
            if (info["bmWidth"], info["bmHeight"]) != (width, height):
                return None
            bits = bitmap.GetBitmapBits(True)
            image = Image.frombuffer(
                "RGB", (info["bmWidth"], info["bmHeight"]), bits,
                "raw", "BGRX", 0, 1,
            ).copy()
            if win32gui.GetWindowRect(int(hwnd)) != (left, top, right, bottom):
                return None
            return image
        except Exception as exc:
            logger.debug("Window capture failed (%s)", type(exc).__name__)
            return None
        finally:
            cleanup = []
            if previous_bitmap is not None and memory_dc is not None:
                cleanup.append(lambda: memory_dc.SelectObject(previous_bitmap))
            if bitmap is not None:
                cleanup.append(lambda: win32gui.DeleteObject(bitmap.GetHandle()))
            if memory_dc is not None:
                cleanup.append(memory_dc.DeleteDC)
            if window_dc is not None:
                cleanup.append(window_dc.DeleteDC)
            if source_dc:
                cleanup.append(lambda: win32gui.ReleaseDC(int(hwnd), source_dc))
            for release in cleanup:
                try:
                    release()
                except Exception as exc:
                    logger.debug("Capture resource cleanup failed (%s)", type(exc).__name__)

    def capture_visible_window(self, hwnd: int) -> Image.Image | None:
        """Read the visible foreground frame; reject background/changed windows.

        This composite includes owned popups. It is suitable for checking the
        visible search field, not for treating overlays as main-window content.
        """
        if not self._enabled or not hwnd:
            return None
        import win32gui
        from PIL import ImageGrab

        try:
            foreground = win32gui.GetForegroundWindow()
            if (not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd)
                    or win32gui.GetAncestor(foreground, 3) != hwnd):
                return None
            rect = win32gui.GetWindowRect(hwnd)
            if rect[2] <= rect[0] or rect[3] <= rect[1]:
                return None
            image = ImageGrab.grab(bbox=rect, all_screens=True)
            if (win32gui.GetWindowRect(hwnd) != rect
                    or win32gui.GetForegroundWindow() != foreground
                    or not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd)
                    or image.size != (rect[2]-rect[0], rect[3]-rect[1])):
                return None
            return image
        except Exception:
            return None

    def save(self, image: Image.Image | None, skill: str, tag: str) -> str | None:
        """Save unique PNG evidence beneath the selected local output directory."""
        if not self._enabled or image is None:
            return None
        # Labels are filename components, never paths or Windows drive syntax.
        if any(not isinstance(label, str) or not label or len(label) > 80
               or label in {'.', '..'} or label[-1:] in {'.', ' '}
               or re.search(r'[\x00-\x1f<>:"/\\|?*]', label) for label in (skill, tag)):
            return None
        path = None
        created = False
        try:
            os.makedirs(self._output_dir, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            path = os.path.join(self._output_dir, f"{skill}_{stamp}_{uuid4().hex}_{tag}.png")
            with open(path, 'xb') as stream:
                created = True
                image.save(stream, format='PNG')
            logger.info("Screenshot saved")
            return path
        except Exception as exc:
            logger.warning("Failed to save screenshot (%s)", type(exc).__name__)
            if created and path is not None:
                try:
                    os.remove(path)
                except OSError:
                    pass
            return None

    def shot_window(self, hwnd: int, skill: str, tag: str) -> str | None:
        """Capture and save a window in one call."""
        return self.save(self.capture_window(hwnd), skill, tag)
