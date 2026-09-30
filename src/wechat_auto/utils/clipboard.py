"""Clipboard interaction helpers."""

from __future__ import annotations

import logging

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
        import io

        import win32clipboard
        from PIL import Image

        with Image.open(image_path) as image, io.BytesIO() as output:
            image.convert("RGB").save(output, "BMP")
            data = output.getvalue()[14:]
        ClipboardHelper._set_data(win32clipboard.CF_DIB, data)

    @staticmethod
    def _set_data(format_id: int, data: bytes) -> None:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(format_id, data)
        finally:
            win32clipboard.CloseClipboard()

    @staticmethod
    def set_files(paths: list[str]) -> None:
        """Set CF_HDROP with a Unicode DROPFILES payload (never path text)."""
        import struct
        from pathlib import Path

        import win32clipboard

        resolved = [Path(path).resolve(strict=True) for path in paths]
        if not resolved or any(not path.is_file() for path in resolved):
            raise ValueError("Expected one or more existing files")
        header = struct.pack("<IiiII", 20, 0, 0, 0, 1)
        names = ("\0".join(str(path) for path in resolved) + "\0\0").encode("utf-16le")
        ClipboardHelper._set_data(win32clipboard.CF_HDROP, header + names)

    @staticmethod
    def clear() -> None:
        """Clear the clipboard."""
        pyperclip.copy("")
