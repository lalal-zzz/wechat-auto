"""Keyboard interaction helpers."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pywinauto.application import WindowSpecification


class KeyboardHelper:
    """Provides common keyboard operations."""

    @staticmethod
    def send_keys(window: "WindowSpecification", keys: str, pause: float = 0.05) -> None:
        """Send keystrokes to a window.

        Args:
            window: Target window.
            keys: pywinauto key string (e.g. "^v", "{ENTER}").
            pause: Delay between keystrokes.
        """
        window.type_keys(keys, pause=pause)

    @staticmethod
    def press_enter(window: "WindowSpecification") -> None:
        window.type_keys("{ENTER}")

    @staticmethod
    def press_escape(window: "WindowSpecification") -> None:
        window.type_keys("{ESC}")

    @staticmethod
    def press_tab(window: "WindowSpecification") -> None:
        window.type_keys("{TAB}")

    @staticmethod
    def select_all(window: "WindowSpecification") -> None:
        window.type_keys("^a")

    @staticmethod
    def paste(window: "WindowSpecification") -> None:
        """Ctrl+V paste."""
        window.type_keys("^v")
        time.sleep(0.1)

    @staticmethod
    def copy(window: "WindowSpecification") -> None:
        """Ctrl+C copy."""
        window.type_keys("^c")
        time.sleep(0.1)

    @staticmethod
    def newline(window: "WindowSpecification") -> None:
        """Insert newline (Shift+Enter)."""
        window.type_keys("+{ENTER}")
