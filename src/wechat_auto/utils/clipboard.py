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
        logger.debug("Clipboard text set")

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
    def files_match(paths: list[str]) -> bool:
        """Verify the current CF_HDROP paths without exposing their contents."""
        from pathlib import Path

        import win32clipboard

        expected = [Path(path).resolve(strict=True) for path in paths]
        win32clipboard.OpenClipboard()
        try:
            if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_HDROP):
                return False
            actual = win32clipboard.GetClipboardData(win32clipboard.CF_HDROP)
            return [Path(path).resolve() for path in actual] == expected
        finally:
            win32clipboard.CloseClipboard()

    @staticmethod
    def image_matches(image_path: str) -> bool:
        """Compare the exact DIB payload that set_image would produce."""
        import io

        import win32clipboard
        from PIL import Image

        with Image.open(image_path) as image, io.BytesIO() as output:
            image.convert('RGB').save(output, 'BMP')
            expected = output.getvalue()[14:]
        win32clipboard.OpenClipboard()
        try:
            if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB):
                return False
            return win32clipboard.GetClipboardData(win32clipboard.CF_DIB) == expected
        finally:
            win32clipboard.CloseClipboard()

    @staticmethod
    def file_sha256(path) -> str:
        import hashlib

        digest = hashlib.sha256()
        with open(path, 'rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def copied_file_matches(name: str, size: int, sha256: str) -> bool:
        """Check one standard copied file by full name and bytes, without logging paths."""
        from pathlib import Path

        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_HDROP):
                return False
            files = win32clipboard.GetClipboardData(win32clipboard.CF_HDROP)
        finally:
            win32clipboard.CloseClipboard()
        if len(files) != 1:
            return False
        path = Path(files[0])
        return (path.is_file() and path.name.casefold() == name.casefold()
                and path.stat().st_size == size and ClipboardHelper.file_sha256(path) == sha256)

    @staticmethod
    def copied_image_matches(path: str) -> bool:
        """Require native Copy to return exactly the source image's RGB pixels."""
        from PIL import Image, ImageGrab

        copied = ImageGrab.grabclipboard()
        if isinstance(copied, list) and len(copied) == 1:
            try:
                with Image.open(copied[0]) as referenced:
                    copied = referenced.convert('RGB')
            except (OSError, ValueError, TypeError):
                return False
        if not isinstance(copied, Image.Image):
            return False
        with Image.open(path) as expected:
            expected = expected.convert('RGB')
            copied = copied.convert('RGB')
            return copied.size == expected.size and copied.tobytes() == expected.tobytes()

    @staticmethod
    def clear() -> None:
        """Clear the clipboard."""
        pyperclip.copy("")
