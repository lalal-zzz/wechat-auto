"""Tests for messaging skill (unit tests with mocks)."""

from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.skills.messaging import MessagingSkill
from wechat_auto.exceptions import SendMessageError


class TestMessagingSkill:
    def test_send_text_success(self, mock_app, mock_finder, config, session):
        """Test successful text message sending."""
        # Set up mocks
        edit_box = MagicMock()
        mock_finder.find_child_by_title.return_value = edit_box
        mock_finder.find_all_children.return_value = [edit_box]

        skill = MessagingSkill(mock_app, mock_finder, config, session)

        with patch("wechat_auto.skills.messaging.ClipboardHelper") as mock_clip:
            with patch("wechat_auto.skills.messaging.KeyboardHelper") as mock_kb:
                skill.send_text("张三", "你好")

        mock_clip.set_text.assert_called_once_with("你好")
        mock_kb.paste.assert_called_once()
        mock_kb.press_enter.assert_called_once()

    def test_send_file_not_found(self, mock_app, mock_finder, config, session):
        """Test sending a non-existent file raises FileNotFoundError."""
        skill = MessagingSkill(mock_app, mock_finder, config, session)
        with pytest.raises(FileNotFoundError):
            skill.send_file("张三", "/nonexistent/path/file.txt")

    def test_send_text_no_edit_box(self, mock_app, mock_finder, config, session):
        """Test fallback to coordinate click when edit box not found."""
        mock_finder.find_child_by_title.side_effect = Exception("not found")
        mock_finder.find_all_children.return_value = []

        skill = MessagingSkill(mock_app, mock_finder, config, session)

        with patch("wechat_auto.skills.messaging.ClipboardHelper") as mock_clip:
            with patch("wechat_auto.skills.messaging.KeyboardHelper") as mock_kb:
                # Should succeed using _click_input_area fallback
                skill.send_text("张三", "test")

        mock_clip.set_text.assert_called_once_with("test")
        mock_kb.paste.assert_called_once()
