"""Messaging skill - send text, file, and image messages (Tier 1)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from wechat_auto.skills.base import BaseSkill
from wechat_auto.exceptions import SendMessageError, ContactNotFoundError
from wechat_auto.utils.clipboard import ClipboardHelper
from wechat_auto.utils.keyboard import KeyboardHelper
from wechat_auto.utils.retry import retry_on_failure

logger = logging.getLogger(__name__)


class MessagingSkill(BaseSkill):
    """Send text, image, and file messages in WeChat.

    Tier 1 skill covering:
        - send_text_message
        - send_image_or_sticker
        - send_file
    """

    name = "send_text_message"

    def _run(self, **params) -> Any:
        """Default execute routes to send_text."""
        contact = params.get("contact", "")
        message = params.get("message", "")
        return self.send_text(contact, message)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=2, delay=1.0)
    def send_text(self, contact: str, message: str) -> None:
        """Send a text message.

        Args:
            contact: Name of the contact or group.
            message: Text content to send.
        """
        logger.info("Sending text to %s: %s", contact, message[:40])
        self._activate()
        self._open_chat(contact)
        time.sleep(self._config.action_delay)

        edit_box = self._find_message_box()

        ClipboardHelper.set_text(message)
        if edit_box is not None:
            edit_box.click_input()
        else:
            self._click_input_area()
        time.sleep(self._config.click_delay)
        KeyboardHelper.paste(self.window)
        time.sleep(self._config.action_delay)

        self._send_current()
        time.sleep(self._config.after_send_delay)
        logger.info("Text sent successfully.")

    @retry_on_failure(max_retries=2, delay=1.0)
    def send_file(self, contact: str, file_path: str) -> None:
        """Send a file.

        Args:
            contact: Name of the contact or group.
            file_path: Absolute path to the file.
        """
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        logger.info("Sending file to %s: %s", contact, file_path)
        self._activate()
        self._open_chat(contact)
        time.sleep(self._config.action_delay)

        ClipboardHelper.set_text(file_path)
        edit_box = self._find_message_box()
        if edit_box is not None:
            edit_box.click_input()
        else:
            self._click_input_area()
        time.sleep(self._config.click_delay)
        KeyboardHelper.paste(self.window)
        time.sleep(self._config.action_delay)
        self._send_current()
        time.sleep(self._config.after_send_delay)
        logger.info("File sent successfully.")

    @retry_on_failure(max_retries=2, delay=1.0)
    def send_image(self, contact: str, image_path: str) -> None:
        """Send an image.

        Args:
            contact: Name of the contact or group.
            image_path: Absolute path to the image file.
        """
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        logger.info("Sending image to %s: %s", contact, image_path)
        self._activate()
        self._open_chat(contact)
        time.sleep(self._config.action_delay)

        ClipboardHelper.set_image(image_path)
        edit_box = self._find_message_box()
        if edit_box is not None:
            edit_box.click_input()
        else:
            self._click_input_area()
        time.sleep(self._config.click_delay)
        KeyboardHelper.paste(self.window)
        time.sleep(self._config.action_delay)
        self._send_current()
        time.sleep(self._config.after_send_delay)
        logger.info("Image sent successfully.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _open_chat(self, chat_name: str) -> None:
        """Open chat via search."""
        logger.info("Opening chat: %s", chat_name)
        self._finder.open_chat(chat_name)

    def _find_message_box(self):
        """Locate the message input edit box in the current chat."""
        try:
            children = self._finder.find_all_children(self.window, control_type="Edit")
            if children:
                # Usually the message input box is the last Edit control
                return children[-1]
        except Exception:
            pass

        try:
            return self._finder.find_child_by_title(
                self.window, "", control_type="Edit", timeout=1.0
            )
        except Exception:
            pass

        return None

    def _send_current(self) -> None:
        """Press Enter to send the current message."""
        KeyboardHelper.press_enter(self.window)

    def _click_input_area(self) -> None:
        """Click the bottom-right message input area."""
        try:
            rect = self.window.rectangle()
            # Calculate coordinates for the input region (lower right quadrant)
            x = rect.left + int((rect.right - rect.left) * 0.6)
            y = rect.top + int((rect.bottom - rect.top) * 0.8)
            logger.debug("Focusing input area at (%d, %d)", x, y)
            self.window.click_input(coords=(x, y))
        except Exception as exc:
            logger.debug("Click input area failed: %s", exc)
