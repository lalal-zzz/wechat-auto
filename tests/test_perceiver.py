"""Tests for Perceiver engine module (unit tests with mocks)."""

from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.engine.perceiver import Perceiver


class TestPerceiver:
    def test_init(self, mock_app, config):
        perceiver = Perceiver(mock_app, config)
        assert perceiver._app is mock_app
        assert perceiver._config is config

    def test_get_unread_no_window(self, config):
        """Test when main window is not accessible."""
        app = MagicMock()
        del app.main_window  # Remove attribute to trigger error
        app.main_window = property(lambda self: (_ for _ in ()).throw(RuntimeError("not connected")))

        perceiver = Perceiver(app, config)
        result = perceiver.get_unread_messages()
        assert result == []

    def test_get_unread_no_items(self, mock_app, config):
        """Test when no conversation list items are found."""
        mock_window = MagicMock()
        mock_window.descendants.return_value = []
        mock_app.main_window = mock_window

        perceiver = Perceiver(mock_app, config)
        result = perceiver.get_unread_messages()
        assert result == []

    def test_get_unread_with_unread_items(self, mock_app, config):
        """Test detecting unread messages from conversation items."""
        # Create mock list items with text indicating unread
        item1 = MagicMock()
        item1.window_text.return_value = "张三"
        item1.children.return_value = [
            MagicMock(window_text=MagicMock(return_value="张三")),
            MagicMock(window_text=MagicMock(return_value="3条未读")),
            MagicMock(window_text=MagicMock(return_value="开会资料收到了吗？")),
        ]

        item2 = MagicMock()
        item2.window_text.return_value = "李四"
        item2.children.return_value = [
            MagicMock(window_text=MagicMock(return_value="李四")),
            MagicMock(window_text=MagicMock(return_value="你好")),
        ]

        mock_window = MagicMock()
        mock_window.window_text.return_value = "微信"
        mock_app.main_window = mock_window

        perceiver = Perceiver(mock_app, config)
        with patch.object(perceiver, "_get_conversation_items", return_value=[item1, item2]):
            result = perceiver.get_unread_messages()

        assert len(result) == 1
        assert result[0]["contact"] == "张三"
        assert result[0]["unread_count"] == 3
        assert "开会资料" in result[0]["preview"]

    def test_get_unread_with_numeric_badge(self, mock_app, config):
        """Test detecting unread via standalone numeric badge."""
        item = MagicMock()
        item.window_text.return_value = ""
        item.children.return_value = [
            MagicMock(window_text=MagicMock(return_value="王五")),
            MagicMock(window_text=MagicMock(return_value="5")),
            MagicMock(window_text=MagicMock(return_value="最新消息")),
        ]

        mock_window = MagicMock()
        mock_app.main_window = mock_window

        perceiver = Perceiver(mock_app, config)
        with patch.object(perceiver, "_get_conversation_items", return_value=[item]):
            result = perceiver.get_unread_messages()

        assert len(result) == 1
        assert result[0]["contact"] == "王五"
        assert result[0]["unread_count"] == 5

    def test_get_unread_all_read(self, mock_app, config):
        """Test when all conversations have been read."""
        item = MagicMock()
        item.window_text.return_value = "张三"
        item.children.return_value = [
            MagicMock(window_text=MagicMock(return_value="张三")),
            MagicMock(window_text=MagicMock(return_value="最新消息")),
        ]

        mock_window = MagicMock()
        mock_app.main_window = mock_window

        perceiver = Perceiver(mock_app, config)
        with patch.object(perceiver, "_get_conversation_items", return_value=[item]):
            result = perceiver.get_unread_messages()
            assert result == []

    def test_has_unread_true(self, mock_app, config):
        """Test has_unread returns True when unread exists."""
        item = MagicMock()
        item.window_text.return_value = "张三"
        item.children.return_value = [
            MagicMock(window_text=MagicMock(return_value="2条未读")),
        ]

        mock_window = MagicMock()
        mock_app.main_window = mock_window

        perceiver = Perceiver(mock_app, config)
        with patch.object(perceiver, "_get_conversation_items", return_value=[item]):
            assert perceiver.has_unread() is True

    def test_has_unread_false(self, mock_app, config):
        """Test has_unread returns False when no unread."""
        mock_window = MagicMock()
        mock_app.main_window = mock_window

        perceiver = Perceiver(mock_app, config)
        with patch.object(perceiver, "_get_conversation_items", return_value=[]):
            assert perceiver.has_unread() is False

    def test_extract_unread_info_extracts_contact_and_count(self, mock_app, config):
        """Test the internal _extract_unread_info method."""
        item = MagicMock()
        item.window_text.return_value = "赵六"
        item.children.return_value = [
            MagicMock(window_text=MagicMock(return_value="赵六")),
            MagicMock(window_text=MagicMock(return_value="10条未读")),
            MagicMock(window_text=MagicMock(return_value="消息预览")),
        ]

        perceiver = Perceiver(mock_app, config)
        result = perceiver._extract_unread_info(item)

        assert result is not None
        assert result["contact"] == "赵六"
        assert result["unread_count"] == 10
        assert result["preview"] == "消息预览"

    def test_extract_unread_info_returns_none_for_read(self, mock_app, config):
        """Test _extract_unread_info returns None for read conversations."""
        item = MagicMock()
        item.window_text.return_value = "read user"
        item.children.return_value = [
            MagicMock(window_text=MagicMock(return_value="read user")),
            MagicMock(window_text=MagicMock(return_value="no new messages")),
        ]

        perceiver = Perceiver(mock_app, config)
        result = perceiver._extract_unread_info(item)
        assert result is None

    def test_collect_text_parts(self, mock_app, config):
        """Test the _collect_text_parts method."""
        item = MagicMock()
        item.window_text.return_value = "parent text"
        child1 = MagicMock()
        child1.window_text.return_value = "child1"
        child2 = MagicMock()
        child2.window_text.return_value = "child2"
        item.children.return_value = [child1, child2]

        perceiver = Perceiver(mock_app, config)
        parts = perceiver._collect_text_parts(item)
        assert "parent text" in parts
        assert "child1" in parts
        assert "child2" in parts
