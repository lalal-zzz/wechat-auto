"""Pure HWND PrintWindow capture for OCR observation and evidence."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = os.path.join("tests", "artifacts")


class ScreenshotHelper:
    """Capture window/element screenshots and persist them as artifacts."""

    def __init__(self, output_dir: Optional[str] = None, enabled: bool = True):
        self._output_dir = output_dir or DEFAULT_OUTPUT_DIR
        self._enabled = enabled

    @property
    def output_dir(self) -> str:
        return self._output_dir

    @property
    def enabled(self) -> bool:
        return self._enabled

    def capture_window(self, hwnd: int) -> Optional["Image.Image"]:
        """Capture a top-level HWND without UIA or pywinauto."""
        if not self._enabled or not hwnd:
            return None
        import ctypes
        import win32gui
        import win32ui
        from PIL import Image

        window_dc = memory_dc = bitmap = None
        source_dc = 0
        try:
            left, top, right, bottom = win32gui.GetWindowRect(int(hwnd))
            width, height = right - left, bottom - top
            if width <= 0 or height <= 0:
                return None
            source_dc = win32gui.GetWindowDC(int(hwnd))
            window_dc = win32ui.CreateDCFromHandle(source_dc)
            memory_dc = window_dc.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(window_dc, width, height)
            memory_dc.SelectObject(bitmap)
            if not ctypes.windll.user32.PrintWindow(int(hwnd), memory_dc.GetSafeHdc(), 2):
                return None
            info = bitmap.GetInfo()
            bits = bitmap.GetBitmapBits(True)
            return Image.frombuffer(
                "RGB", (info["bmWidth"], info["bmHeight"]), bits,
                "raw", "BGRX", 0, 1,
            ).copy()
        except Exception as exc:
            logger.debug("capture_window(%s) failed: %s", hwnd, exc)
            return None
        finally:
            if bitmap is not None:
                win32gui.DeleteObject(bitmap.GetHandle())
            if memory_dc is not None:
                memory_dc.DeleteDC()
            if window_dc is not None:
                window_dc.DeleteDC()
            if source_dc:
                win32gui.ReleaseDC(int(hwnd), source_dc)

    def save(self, image: Optional["Image.Image"], skill: str, tag: str) -> Optional[str]:
        """Persist a captured image as ``<skill>_<timestamp>_<tag>.png``.

        Returns:
            The artifact path, or None when disabled or image is empty.
        """
        if not self._enabled or image is None:
            return None
        try:
            os.makedirs(self._output_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self._output_dir, f"{skill}_{stamp}_{tag}.png")
            image.save(path)
            logger.info("Screenshot saved: %s", path)
            return path
        except Exception as exc:
            logger.warning("Failed to save screenshot: %s", exc)
            return None

    def shot_window(self, hwnd: int, skill: str, tag: str) -> Optional[str]:
        """Capture and save a window in one call."""
        return self.save(self.capture_window(hwnd), skill, tag)
