"""Tests for EnvironmentHealer engine module (unit tests with mocks)."""

from unittest.mock import MagicMock, patch, ANY

import pytest

from wechat_auto.engine.healer import EnvironmentHealer
from wechat_auto.exceptions import EnvironmentResetError
from wechat_auto.config import WeChatConfig


class TestEnvironmentHealer:
    def test_init(self, mock_app, mock_finder, config):
        healer = EnvironmentHealer(mock_app, mock_finder, config)
        assert healer._app is mock_app
        assert healer._finder is mock_finder
        assert healer._config is config

    def test_reset_calls_esc_and_navigate(self, mock_app, mock_finder, config):
        mock_window = MagicMock()
        mock_app.main_window = mock_window

        healer = EnvironmentHealer(mock_app, mock_finder, config)
        healer.reset_ui_environment()

        # Should press ESC 3 times
        assert mock_window.type_keys.call_count >= 3
        # Should navigate to chat list
        mock_finder.navigate_to_chat_list.assert_called_once()

    def test_reset_calls_close_popups(self, mock_app, mock_finder, config):
        mock_window = MagicMock()
        mock_app.main_window = mock_window

        healer = EnvironmentHealer(mock_app, mock_finder, config)
        with patch.object(healer, "close_popup_windows") as mock_close:
            healer.reset_ui_environment()
            mock_close.assert_called_once()

    def test_reset_raises_on_failure(self, mock_app, mock_finder, config):
        mock_app.main_window = MagicMock()
        mock_app.main_window.type_keys.side_effect = RuntimeError("fail")

        healer = EnvironmentHealer(mock_app, mock_finder, config)
        with patch.object(healer, "close_popup_windows"):
            with pytest.raises(EnvironmentResetError, match="Failed to reset"):
                healer.reset_ui_environment()

    @patch("wechat_auto.engine.healer._Desktop")
    def test_close_popup_windows_by_class(self, mock_desktop_cls, mock_app, mock_finder, config):
        import pywinauto

        healer = EnvironmentHealer(mock_app, mock_finder, config)
        healer.popup_classes = ["SNSWnd"]
        healer.popup_titles = []

        mock_desktop = MagicMock()
        mock_desktop_cls.return_value = mock_desktop

        mock_popup = MagicMock()
        mock_popup.exists.return_value = True
        mock_desktop.window.return_value = mock_popup

        healer.close_popup_windows()

        mock_popup.close.assert_called_once()

    @patch("wechat_auto.engine.healer._Desktop")
    def test_close_popup_windows_not_found(self, mock_desktop_cls, mock_app, mock_finder, config):
        healer = EnvironmentHealer(mock_app, mock_finder, config)
        healer.popup_classes = ["SNSWnd"]
        healer.popup_titles = []

        mock_desktop = MagicMock()
        mock_desktop_cls.return_value = mock_desktop

        mock_popup = MagicMock()
        mock_popup.exists.return_value = False
        mock_desktop.window.return_value = mock_popup

        healer.close_popup_windows()

        mock_popup.close.assert_not_called()

    @patch("wechat_auto.engine.healer._Desktop")
    def test_validate_state_clean(self, mock_desktop_cls, mock_app, mock_finder, config):
        healer = EnvironmentHealer(mock_app, mock_finder, config)
        healer.popup_classes = ["SNSWnd"]

        mock_desktop = MagicMock()
        mock_desktop_cls.return_value = mock_desktop
        mock_popup = MagicMock()
        mock_popup.exists.return_value = False
        mock_desktop.window.return_value = mock_popup

        mock_app.main_window = MagicMock()

        result = healer.validate_state()
        assert result is True

    def test_validate_state_main_window_error(self, mock_app, mock_finder, config):
        mock_app.main_window = MagicMock()
        mock_app.main_window.wrapper_object.side_effect = RuntimeError("disconnected")

        healer = EnvironmentHealer(mock_app, mock_finder, config)
        healer.popup_classes = []

        result = healer.validate_state()
        assert result is False

    @patch("wechat_auto.engine.healer._Desktop")
    def test_find_open_popups_finds_window(self, mock_desktop_cls, mock_app, mock_finder, config):
        healer = EnvironmentHealer(mock_app, mock_finder, config)
        healer.popup_classes = ["SNSWnd", "TopStoryWnd"]

        mock_desktop = MagicMock()
        mock_desktop_cls.return_value = mock_desktop

        # First popup exists, second doesn't
        def window_side_effect(**kwargs):
            mock_w = MagicMock()
            if kwargs.get("class_name") == "SNSWnd":
                mock_w.exists.return_value = True
            else:
                mock_w.exists.return_value = False
            return mock_w

        mock_desktop.window.side_effect = window_side_effect

        result = healer._find_open_popups()
        assert "SNSWnd" in result
        assert "TopStoryWnd" not in result

    def test_popup_classes_constant(self):
        """Verify the known popup window classes are defined."""
        assert "SNSWnd" in EnvironmentHealer.popup_classes
        assert "TopStoryWnd" in EnvironmentHealer.popup_classes
