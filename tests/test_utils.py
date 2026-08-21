"""Tests for utils and finder modules (unit tests with mocks)."""

from unittest.mock import MagicMock, patch, ANY

import pytest

from wechat_auto.utils.keyboard import KeyboardHelper
from wechat_auto.utils.retry import retry_on_failure
from wechat_auto.ui.finder import ElementFinder
from wechat_auto.exceptions import ChatNotFoundError, ElementNotFoundError


# ==================================================================
# KeyboardHelper
# ==================================================================

class TestKeyboardHelper:
    def test_send_keys(self):
        window = MagicMock()
        KeyboardHelper.send_keys(window, "^v")
        window.type_keys.assert_called_once_with("^v", pause=0.05)

    def test_press_enter(self):
        window = MagicMock()
        KeyboardHelper.press_enter(window)
        window.type_keys.assert_called_once_with("{ENTER}")

    def test_press_escape(self):
        window = MagicMock()
        KeyboardHelper.press_escape(window)
        window.type_keys.assert_called_once_with("{ESC}")

    def test_press_tab(self):
        window = MagicMock()
        KeyboardHelper.press_tab(window)
        window.type_keys.assert_called_once_with("{TAB}")

    def test_select_all(self):
        window = MagicMock()
        KeyboardHelper.select_all(window)
        window.type_keys.assert_called_once_with("^a")

    def test_paste(self):
        window = MagicMock()
        KeyboardHelper.paste(window)
        window.type_keys.assert_called_once_with("^v")

    def test_copy(self):
        window = MagicMock()
        KeyboardHelper.copy(window)
        window.type_keys.assert_called_once_with("^c")

    def test_newline(self):
        window = MagicMock()
        KeyboardHelper.newline(window)
        window.type_keys.assert_called_once_with("+{ENTER}")


# ==================================================================
# ClipboardHelper (text only - image requires Windows)
# ==================================================================

class TestClipboardHelper:
    def test_set_text(self):
        from wechat_auto.utils.clipboard import ClipboardHelper

        with patch("wechat_auto.utils.clipboard.pyperclip") as mock_pyperclip:
            ClipboardHelper.set_text("hello")
            mock_pyperclip.copy.assert_called_once_with("hello")

    def test_get_text(self):
        from wechat_auto.utils.clipboard import ClipboardHelper

        with patch("wechat_auto.utils.clipboard.pyperclip") as mock_pyperclip:
            mock_pyperclip.paste.return_value = "clipboard text"
            result = ClipboardHelper.get_text()
            assert result == "clipboard text"

    def test_clear(self):
        from wechat_auto.utils.clipboard import ClipboardHelper

        with patch("wechat_auto.utils.clipboard.pyperclip") as mock_pyperclip:
            ClipboardHelper.clear()
            mock_pyperclip.copy.assert_called_once_with("")


# ==================================================================
# ElementFinder
# ==================================================================

class TestElementFinder:
    def test_init(self, mock_app, config):
        finder = ElementFinder(mock_app, config)
        assert finder._app is mock_app
        assert finder._config is config

    def test_find_child_by_title_success(self, mock_app, config):
        mock_window = MagicMock()
        mock_app.main_window = mock_window

        mock_element = MagicMock()
        mock_window.child_window.return_value = mock_element
        mock_element.wrapper_object.return_value = MagicMock()

        finder = ElementFinder(mock_app, config)
        with patch("wechat_auto.ui.finder.time.sleep"):
            result = finder.find_child_by_title(mock_window, "发送", timeout=1.0)

        assert result is not None

    def test_find_child_by_title_timeout(self, mock_app, config):
        mock_window = MagicMock()
        mock_app.main_window = mock_window

        mock_element = MagicMock()
        mock_window.child_window.return_value = mock_element
        mock_element.wrapper_object.side_effect = Exception("not found")

        finder = ElementFinder(mock_app, config)
        with patch("wechat_auto.ui.finder.time.sleep"):
            with patch("wechat_auto.ui.finder.time.monotonic", side_effect=[0, 10, 20]):
                with pytest.raises(ElementNotFoundError):
                    finder.find_child_by_title(mock_window, "nonexistent", timeout=0.1)

    def test_find_all_children_success(self, mock_app, config):
        mock_parent = MagicMock()
        mock_child1 = MagicMock()
        mock_child2 = MagicMock()
        mock_parent.descendants.return_value = [mock_child1, mock_child2]

        finder = ElementFinder(mock_app, config)
        result = finder.find_all_children(mock_parent, control_type="ListItem")
        assert len(result) == 2

    def test_find_all_children_empty(self, mock_app, config):
        """Test that exceptions return empty list."""
        mock_parent = MagicMock()
        mock_parent.descendants.side_effect = Exception("error")
        mock_parent.children.side_effect = Exception("error")

        finder = ElementFinder(mock_app, config)
        result = finder.find_all_children(mock_parent, control_type="ListItem")
        assert result == []

    def test_find_by_automation_id_success(self, mock_app, config):
        mock_parent = MagicMock()
        mock_element = MagicMock()
        mock_parent.child_window.return_value = mock_element
        mock_element.wrapper_object.return_value = MagicMock()

        finder = ElementFinder(mock_app, config)
        with patch("wechat_auto.ui.finder.time.sleep"):
            result = finder.find_by_automation_id(mock_parent, "btn1", timeout=1.0)
        assert result is not None

    def test_find_by_automation_id_timeout(self, mock_app, config):
        mock_parent = MagicMock()
        mock_element = MagicMock()
        mock_parent.child_window.return_value = mock_element
        mock_element.wrapper_object.side_effect = Exception("not found")

        finder = ElementFinder(mock_app, config)
        with patch("wechat_auto.ui.finder.time.sleep"):
            with patch("wechat_auto.ui.finder.time.monotonic", side_effect=[0, 10, 20]):
                with pytest.raises(ElementNotFoundError):
                    finder.find_by_automation_id(mock_parent, "nonexistent", timeout=0.1)

    def test_exists_true(self, mock_app, config):
        mock_parent = MagicMock()
        mock_element = MagicMock()
        mock_parent.child_window.return_value = mock_element
        mock_element.wrapper_object.return_value = MagicMock()

        finder = ElementFinder(mock_app, config)
        with patch("wechat_auto.ui.finder.time.sleep"):
            result = finder.exists(mock_parent, "发送", timeout=1.0)
        assert result is True

    def test_exists_false(self, mock_app, config):
        mock_parent = MagicMock()
        mock_element = MagicMock()
        mock_parent.child_window.return_value = mock_element
        mock_element.wrapper_object.side_effect = Exception("not found")

        finder = ElementFinder(mock_app, config)
        with patch("wechat_auto.ui.finder.time.sleep"):
            with patch("wechat_auto.ui.finder.time.monotonic", side_effect=[0, 10, 20]):
                result = finder.exists(mock_parent, "nonexistent", timeout=0.1)
        assert result is False

    def test_click(self, mock_app, config):
        mock_element = MagicMock()
        finder = ElementFinder(mock_app, config)
        with patch("wechat_auto.ui.finder.time.sleep"):
            finder.click(mock_element)
        mock_element.click_input.assert_called_once()

    def test_double_click(self, mock_app, config):
        mock_element = MagicMock()
        finder = ElementFinder(mock_app, config)
        with patch("wechat_auto.ui.finder.time.sleep"):
            finder.double_click(mock_element)
        mock_element.double_click_input.assert_called_once()

    def test_right_click(self, mock_app, config):
        mock_element = MagicMock()
        finder = ElementFinder(mock_app, config)
        with patch("wechat_auto.ui.finder.time.sleep"):
            finder.right_click(mock_element)
        mock_element.click_input.assert_called_once_with(button="right")

    def test_type_text(self, mock_app, config):
        mock_element = MagicMock()
        finder = ElementFinder(mock_app, config)
        finder.type_text(mock_element, "hello", clear_first=True)
        mock_element.set_edit_text.assert_called_once_with("")
        mock_element.type_keys.assert_called_once()

    def test_navigate_to_chat_list(self, mock_app, config):
        mock_window = MagicMock()
        mock_btn = MagicMock()
        mock_app.main_window = mock_window

        finder = ElementFinder(mock_app, config)
        with patch.object(finder, "find_child_by_title", return_value=mock_btn) as mock_find:
            with patch("wechat_auto.ui.finder.time.sleep"):
                finder.navigate_to_chat_list()

        mock_find.assert_called()
        mock_btn.click_input.assert_called_once()  # click() calls click_input

    def test_navigate_to_chat_list_fallback(self, mock_app, config):
        """Test fallback to keyboard shortcut when button not found."""
        mock_window = MagicMock()
        mock_app.main_window = mock_window

        finder = ElementFinder(mock_app, config)
        with patch.object(finder, "find_child_by_title", side_effect=ElementNotFoundError("not found")):
            with patch("wechat_auto.ui.finder.time.sleep"):
                finder.navigate_to_chat_list()

        # Should fall back to Ctrl+1
        mock_window.type_keys.assert_called_with("^1")

    def test_navigate_to_contacts(self, mock_app, config):
        mock_window = MagicMock()
        mock_btn = MagicMock()
        mock_app.main_window = mock_window

        finder = ElementFinder(mock_app, config)
        with patch.object(finder, "find_child_by_title", return_value=mock_btn):
            with patch("wechat_auto.ui.finder.time.sleep"):
                finder.navigate_to_contacts()

        mock_btn.click_input.assert_called_once()

    def test_navigate_to_contacts_fallback(self, mock_app, config):
        mock_window = MagicMock()
        mock_app.main_window = mock_window

        finder = ElementFinder(mock_app, config)
        with patch.object(finder, "find_child_by_title", side_effect=ElementNotFoundError("not found")):
            with patch("wechat_auto.ui.finder.time.sleep"):
                finder.navigate_to_contacts()

        mock_window.type_keys.assert_called_with("^2")

    def test_open_search(self, mock_app, config):
        mock_window = MagicMock()
        mock_app.main_window = mock_window

        finder = ElementFinder(mock_app, config)
        with patch("wechat_auto.ui.finder.time.sleep"):
            finder.open_search()

        mock_window.type_keys.assert_called_once_with("^f")

    def test_open_chat(self, mock_app, config):
        """Test the open_chat method."""
        mock_window = MagicMock()
        mock_app.main_window = mock_window

        finder = ElementFinder(mock_app, config)
        with patch("wechat_auto.ui.finder.time.sleep"):
            with patch("wechat_auto.utils.clipboard.ClipboardHelper") as mock_clip:
                with patch("wechat_auto.utils.keyboard.KeyboardHelper") as mock_kb:
                    with patch.object(finder, "click_unique_exact_list_item", return_value=True):
                        finder.open_chat("张三")

        mock_clip.set_text.assert_called_once_with("张三")
        mock_kb.paste.assert_called_once()

    def test_open_chat_refuses_non_exact_search_result(self, mock_app, config):
        mock_window = MagicMock()
        mock_app.main_window = mock_window
        finder = ElementFinder(mock_app, config)

        with patch("wechat_auto.ui.finder.time.sleep"):
            with patch("wechat_auto.utils.clipboard.ClipboardHelper"):
                with patch("wechat_auto.utils.keyboard.KeyboardHelper") as mock_kb:
                    with pytest.raises(ChatNotFoundError):
                        finder.open_chat("文件传输助手")

        assert mock_window.type_keys.call_args_list == [
            (("^f",), {}),
            (("^a{BACKSPACE}",), {}),
        ]
        mock_kb.press_escape.assert_called_once_with(mock_window)

    def test_click_unique_exact_list_item_refuses_first_fuzzy_result(self, mock_app, config):
        finder = ElementFinder(mock_app, config)
        parent = MagicMock()
        fuzzy = MagicMock()
        exact = MagicMock()
        fuzzy.window_text.return_value = "文件传输助手测试群"
        exact.window_text.return_value = "文件传输助手"

        def children(target, control_type=None):
            if target is parent and control_type == "ListItem":
                return [fuzzy, exact]
            return []

        with patch.object(finder, "find_all_children", side_effect=children):
            with patch.object(finder, "click") as click:
                assert finder.click_unique_exact_list_item(parent, "文件传输助手") is True

        click.assert_called_once_with(exact)

    def test_click_unique_exact_list_item_refuses_ambiguous_results(self, mock_app, config):
        finder = ElementFinder(mock_app, config)
        parent = MagicMock()
        first = MagicMock()
        second = MagicMock()
        first.window_text.return_value = "张三"
        second.window_text.return_value = "张三"

        def children(target, control_type=None):
            if target is parent and control_type == "ListItem":
                return [first, second]
            return []

        with patch.object(finder, "find_all_children", side_effect=children):
            with patch.object(finder, "click") as click:
                assert finder.click_unique_exact_list_item(parent, "张三") is False

        click.assert_not_called()
