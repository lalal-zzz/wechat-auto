"""Clipboard interaction helpers."""

from __future__ import annotations

import logging
from typing import Optional

import pyperclip

logger = logging.getLogger(__name__)


class ClipboardHelper:
    """Cross-platform clipboard operations via pyperclip."""

    @staticmethod
    def set_text(text: str) -> None:
        """Copy text to the system clipboard."""
        pyperclip.copy(text)
        logger.debug("Clipboard set: %s", text[:50] + "..." if len(text) > 50 else text)

    @staticmethod
    def get_text() -> str:
        """Get text from the system clipboard."""
        return pyperclip.paste()

    @staticmethod
    def set_image(image_path: str) -> None:
        """Copy an image to the clipboard (Windows only).

        Uses PIL/Pillow to load the image and win32clipboard to set it.
        """
        try:
            import io
            import ctypes
            import ctypes.wintypes
            from PIL import Image

            img = Image.open(image_path).convert("DIB")
            output = io.BytesIO()
            img.save(output, "BMP")
            data = output.getvalue()[14:]  # skip BMP file header (14 bytes)
            output.close()

            CF_DIB = 8
            kernel32 = ctypes.windll.kernel32
            user32 = ctypes.windll.user32

            user32.OpenClipboard(0)
            user32.EmptyClipboard()
            hMem = kernel32.GlobalAlloc(0x0042, len(data))  # GMEM_MOVEABLE | GMEM_ZEROINIT
            pMem = kernel32.GlobalLock(hMem)
            ctypes.cdll.msvcrt.memcpy_s(ctypes.c_void_p(pMem), len(data), data, len(data))
            kernel32.GlobalUnlock(hMem)
            user32.SetClipboardData(CF_DIB, hMem)
            user32.CloseClipboard()
            logger.debug("Image copied to clipboard: %s", image_path)
        except Exception as exc:
            logger.error("Failed to set image to clipboard: %s", exc)
            raise

    @staticmethod
    def clear() -> None:
        """Clear the clipboard."""
        pyperclip.copy("")
