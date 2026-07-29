"""Tests for AtomicUITools module (unit tests with mocks)."""

from unittest.mock import MagicMock, patch, ANY

import pytest

from wechat_auto.atomic.tools import AtomicUITools
from wechat_auto.exceptions import AtomicToolError


class TestAtomicUITools:
    def test_init(self, mock_app, mock_finder, config):
        tools = AtomicUITools(mock_app, mock_finder, config)
        assert tools._app is mock_app
        assert tools._finder is mock_finder
        assert tools._config is config

    # ------------------------------------------------------------------
    # Tool 1: get_ui_tree
    # ------------------------------------------------------------------

    def test_get_ui_tree_basic(self, mock_app, mock_finder, config):
        mock_rect = MagicMock()
        mock_rect.left = 0
        mock_rect.top = 0
        mock_rect.right = 800
        mock_rect.bottom = 600

        mock_window = MagicMock()
        mock_window.window_text.return_value = "微信"
        mock_window.rectangle.return_value = mock_rect
        mock_window.children.return_value = []
        mock_app.main_window = mock_window

        tools = AtomicUITools(mock_app, mock_finder, config)
        tree = tools.get_ui_tree()

        assert tree["window_title"] == "微信"
        assert tree["rect"]["left"] == 0
        assert tree["rect"]["right"] == 800
        assert tree["controls"] == []

    def test_get_ui_tree_with_controls(self, mock_app, mock_finder, config):
        mock_rect = MagicMock()
        mock_rect.left = 0
        mock_rect.top = 0
        mock_rect.right = 800
        mock_rect.bottom = 600

        mock_child = MagicMock()
        mock_child.window_text.return_value = "发送"
        mock_child.element_info.control_type = "Button"
        mock_child.element_info.automation_id = "btn_send"
        mock_child.rectangle.return_value = mock_rect
        mock_child.children.return_value = []

        mock_window = MagicMock()
        mock_window.window_text.return_value = "微信"
        mock_window.rectangle.return_value = mock_rect
        mock_window.children.return_value = [mock_child]
        mock_app.main_window = mock_window

        tools = AtomicUITools(mock_app, mock_finder, config)
        tree = tools.get_ui_tree()

        assert len(tree["controls"]) == 1
        assert tree["controls"][0]["name"] == "发送"
        assert tree["controls"][0]["control_type"] == "Button"
        assert tree["controls"][0]["automation_id"] == "btn_send"

    def test_get_ui_tree_recursion_limit(self, mock_app, mock_finder, config):
        """Test that tree extraction respects depth limit."""
        from wechat_auto.atomic.tools import _MAX_TREE_DEPTH

        # Create deeply nested mock structure
        mock_rect = MagicMock()
        mock_rect.left = 0
        mock_rect.top = 0
        mock_rect.right = 100
        mock_rect.bottom = 100

        def make_mock_child(name):
            child = MagicMock()
            child.window_text.return_value = name
            child.element_info.control_type = "Pane"
            child.element_info.automation_id = ""
            child.rectangle.return_value = mock_rect
            return child

        # Create chain
        root = make_mock_child("root")
        current = root
        for i in range(_MAX_TREE_DEPTH + 5):
            child = make_mock_child(f"child_{i}")
            current.children.return_value = [child]
            current = child
        current.children.return_value = []

        mock_window = MagicMock()
        mock_window.window_text.return_value = "微信"
        mock_window.rectangle.return_value = mock_rect
        mock_window.children.return_value = [root]
        mock_app.main_window = mock_window

        tools = AtomicUITools(mock_app, mock_finder, config)
        tree = tools.get_ui_tree()

        # Should not crash, depth limit prevents infinite recursion
        assert "controls" in tree

    # ------------------------------------------------------------------
    # Tool 2: click
    # ------------------------------------------------------------------

    def test_click_success(self, mock_app, mock_finder, config):
        mock_element = MagicMock()
        mock_finder.find_child_by_title.return_value = mock_element

        tools = AtomicUITools(mock_app, mock_finder, config)
        tools.click("发送")

        mock_finder.find_child_by_title.assert_called_once()
        mock_finder.click.assert_called_once_with(mock_element)

    def test_click_failure(self, mock_app, mock_finder, config):
        mock_finder.find_child_by_title.side_effect = Exception("not found")

        tools = AtomicUITools(mock_app, mock_finder, config)
        with pytest.raises(AtomicToolError, match="Atomic click failed"):
            tools.click("nonexistent")

    # ------------------------------------------------------------------
    # Tool 3: input_text
    # ------------------------------------------------------------------

    def test_input_text_success(self, mock_app, mock_finder, config):
        mock_element = MagicMock()
        mock_finder.find_child_by_title.return_value = mock_element

        tools = AtomicUITools(mock_app, mock_finder, config)
        tools.input_text("搜索", "hello")

        mock_finder.find_child_by_title.assert_called_once()
        mock_finder.type_text.assert_called_once_with(mock_element, "hello")

    def test_input_text_failure(self, mock_app, mock_finder, config):
        mock_finder.find_child_by_title.side_effect = Exception("not found")

        tools = AtomicUITools(mock_app, mock_finder, config)
        with pytest.raises(AtomicToolError, match="Atomic input_text failed"):
            tools.input_text("nonexistent", "text")

    # ------------------------------------------------------------------
    # Tool 4: right_click
    # ------------------------------------------------------------------

    def test_right_click_success(self, mock_app, mock_finder, config):
        mock_element = MagicMock()
        mock_finder.find_child_by_title.return_value = mock_element

        tools = AtomicUITools(mock_app, mock_finder, config)
        tools.right_click("message")

        mock_finder.right_click.assert_called_once_with(mock_element)

    def test_right_click_failure(self, mock_app, mock_finder, config):
        mock_finder.find_child_by_title.side_effect = Exception("not found")

        tools = AtomicUITools(mock_app, mock_finder, config)
        with pytest.raises(AtomicToolError, match="Atomic right_click failed"):
            tools.right_click("nonexistent")

    # ------------------------------------------------------------------
    # Tool 5: scroll
    # ------------------------------------------------------------------

    def test_scroll_keyboard_fallback(self, mock_app, mock_finder, config):
        """Test scroll falls back to keyboard when element not found."""
        mock_window = MagicMock()
        mock_app.main_window = mock_window
        mock_finder.find_child_by_title.side_effect = Exception("not found")

        tools = AtomicUITools(mock_app, mock_finder, config)
        tools.scroll("", "down", 3)

        assert mock_window.type_keys.call_count == 3

    def test_scroll_with_element(self, mock_app, mock_finder, config):
        """Test scroll uses wheel_mouse_input when element found."""
        mock_element = MagicMock()
        mock_finder.find_child_by_title.return_value = mock_element
        mock_app.main_window = MagicMock()

        tools = AtomicUITools(mock_app, mock_finder, config)
        tools.scroll("list1", "down", 2)

        mock_element.wheel_mouse_input.assert_called_once()

    def test_scroll_up_direction(self, mock_app, mock_finder, config):
        """Test scroll up uses PGUP."""
        mock_window = MagicMock()
        mock_app.main_window = mock_window
        mock_finder.find_child_by_title.side_effect = Exception("not found")

        tools = AtomicUITools(mock_app, mock_finder, config)
        tools.scroll("", "up", 1)

        # Check that PGUP was sent
        calls = mock_window.type_keys.call_args_list
        assert any("{PGUP}" in str(call) for call in calls)

    def test_scroll_failure(self, mock_app, mock_finder, config):
        mock_window = MagicMock()
        mock_window.type_keys.side_effect = RuntimeError("fail")
        mock_app.main_window = mock_window
        mock_finder.find_child_by_title.side_effect = Exception("not found")

        tools = AtomicUITools(mock_app, mock_finder, config)
        with pytest.raises(AtomicToolError, match="Atomic scroll failed"):
            tools.scroll("", "down", 1)

    # ------------------------------------------------------------------
    # Tool 6: send_keyboard_shortcut
    # ------------------------------------------------------------------

    def test_send_keyboard_shortcut_success(self, mock_app, mock_finder, config):
        mock_window = MagicMock()
        mock_app.main_window = mock_window

        tools = AtomicUITools(mock_app, mock_finder, config)
        tools.send_keyboard_shortcut("^v")

        mock_window.type_keys.assert_called_once_with("^v")

    def test_send_keyboard_shortcut_failure(self, mock_app, mock_finder, config):
        mock_window = MagicMock()
        mock_window.type_keys.side_effect = RuntimeError("fail")
        mock_app.main_window = mock_window

        tools = AtomicUITools(mock_app, mock_finder, config)
        with pytest.raises(AtomicToolError, match="keyboard shortcut failed"):
            tools.send_keyboard_shortcut("^v")

    # ------------------------------------------------------------------
    # Tool 7: close_window
    # ------------------------------------------------------------------

    @patch("wechat_auto.atomic.tools._Desktop")
    def test_close_window_by_class(self, mock_desktop_cls, mock_app, mock_finder, config):
        mock_desktop = MagicMock()
        mock_desktop_cls.return_value = mock_desktop

        mock_popup = MagicMock()
        mock_popup.exists.return_value = True
        mock_desktop.window.return_value = mock_popup

        tools = AtomicUITools(mock_app, mock_finder, config)
        tools.close_window("SNSWnd")

        mock_popup.close.assert_called_once()

    @patch("wechat_auto.atomic.tools._Desktop")
    def test_close_window_fallback_altf4(self, mock_desktop_cls, mock_app, mock_finder, config):
        mock_window = MagicMock()
        mock_app.main_window = mock_window

        mock_desktop = MagicMock()
        mock_desktop_cls.return_value = mock_desktop
        mock_popup = MagicMock()
        mock_popup.exists.return_value = False
        mock_desktop.window.return_value = mock_popup

        tools = AtomicUITools(mock_app, mock_finder, config)
        tools.close_window("nonexistent")

        # Should fall back to Alt+F4
        mock_window.type_keys.assert_called_with("%{F4}")

    def test_close_window_empty_id(self, mock_app, mock_finder, config):
        tools = AtomicUITools(mock_app, mock_finder, config)
        with pytest.raises(AtomicToolError, match="requires a window_id"):
            tools.close_window("")

    @patch("wechat_auto.atomic.tools._Desktop")
    def test_close_window_by_title_fallback(self, mock_desktop_cls, mock_app, mock_finder, config):
        """Test closing by title when class name not found."""
        mock_desktop = MagicMock()
        mock_desktop_cls.return_value = mock_desktop

        # First call (class_name) returns not found, second (title) returns found
        mock_popup_by_class = MagicMock()
        mock_popup_by_class.exists.return_value = False

        mock_popup_by_title = MagicMock()
        mock_popup_by_title.exists.return_value = True

        mock_desktop.window.side_effect = [mock_popup_by_class, mock_popup_by_title]

        tools = AtomicUITools(mock_app, mock_finder, config)
        tools.close_window("朋友圈")

        mock_popup_by_title.close.assert_called_once()
