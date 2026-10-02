from unittest.mock import patch

import pytest

from wechat_auto.primitives.keyboard_only import KeyboardOnlyDriver


def test_unicode_units_and_control_rejection():
    driver = KeyboardOnlyDriver(_FakeApplication(), input_mode="wmchar")
    with patch("wechat_auto.primitives.keyboard_only.user32") as api:
        driver._wm_char_text("测试😀")
        assert [c.args[2] for c in api.PostMessageW.call_args_list] == [0x6D4B, 0x8BD5, 0xD83D, 0xDE00]
        api.reset_mock()
        with pytest.raises(ValueError):
            driver._wm_char_text("a\nb")
        api.PostMessageW.assert_not_called()


class _FakeApplication:
    handle = 1

    def activate(self):
        return None


def test_divider_drag_keeps_button_pressed_and_releases_on_failure():
    driver = KeyboardOnlyDriver(_FakeApplication(), foreground_mode='never')
    driver._rect = lambda: (0, 0, 1000, 800)
    with patch('wechat_auto.primitives.keyboard_only.user32') as api, \
         patch('wechat_auto.primitives.keyboard_only.time.sleep'):
        api.ScreenToClient.return_value = 1
        driver.drag_window_fraction((.3, .5), (.4, .5))
        calls = api.SendMessageW.call_args_list
        assert calls[1].args[1:3] == (0x201, 1)
        assert all(c.args[1:3] == (0x200, 1) for c in calls[2:-1])
        assert calls[-1].args[1:3] == (0x202, 0)
        api.reset_mock()
        def fail_on_move(hwnd, message, button, point):
            if message == 0x200 and button == 1:
                raise RuntimeError('drag interrupted')
        api.SendMessageW.side_effect = fail_on_move
        with pytest.raises(RuntimeError, match='interrupted'):
            driver.drag_window_fraction((.3, .5), (.4, .5))
        assert api.SendMessageW.call_args_list[-1].args[1:3] == (0x202, 0)
        api.reset_mock()
        with pytest.raises(ValueError):
            driver.drag_window_fraction((-.1, .5), (.4, .5))
        api.SendMessageW.assert_not_called()


def test_fractional_anchor_uses_full_window_rect():
    driver = KeyboardOnlyDriver(_FakeApplication())
    driver._rect = lambda: (100, 200, 1100, 900)

    assert driver.point(0.178, 0.084) == (278, 259)
    assert driver.point(0.660, 0.850) == (760, 795)


def test_embedded_tab_click_targets_browser_child_not_main():
    driver = KeyboardOnlyDriver(_FakeApplication(), foreground_mode='never')
    driver._rect = lambda: (100, 200, 1100, 1000)
    with patch.object(driver, '_browser_pointer_hwnd', return_value=42), \
         patch('wechat_auto.primitives.keyboard_only.user32') as api:
        api.ScreenToClient.return_value = 1
        driver.click_content_fraction(.8, .1)
    assert {c.args[0] for c in api.SendMessageW.call_args_list} == {42}
    assert [c.args[1] for c in api.SendMessageW.call_args_list] == [0x200, 0x201, 0x202]


def test_missing_embedded_hwnd_never_falls_back_to_main_click():
    driver = KeyboardOnlyDriver(_FakeApplication(), foreground_mode='never')
    with patch.object(driver, '_browser_pointer_hwnd', side_effect=RuntimeError('ambiguous')), \
         patch('wechat_auto.primitives.keyboard_only.user32') as api, \
         pytest.raises(RuntimeError):
        driver.click_content_fraction(.8, .1)
    api.SendMessageW.assert_not_called()



def test_search_mode_is_explicit():
    assert KeyboardOnlyDriver(_FakeApplication(), search_mode="shortcut").search_mode == "shortcut"
    assert KeyboardOnlyDriver(_FakeApplication(), input_mode="winmsg").input_mode == "winmsg"
    assert KeyboardOnlyDriver(_FakeApplication(), input_mode="wmchar").input_mode == "wmchar"
    with pytest.raises(TypeError):
        KeyboardOnlyDriver(_FakeApplication(), click_mode="physical")
    with pytest.raises(ValueError):
        KeyboardOnlyDriver(_FakeApplication(), input_mode="physical")


def test_wheel_posts_normal_window_message():
    driver = KeyboardOnlyDriver(_FakeApplication())
    driver._rect = lambda: (0, 0, 1000, 800)
    with patch("wechat_auto.primitives.keyboard_only.user32") as api:
        api.PostMessageW.return_value = 1
        driver.wheel_window_fraction(.65, .72, 2)
    assert api.PostMessageW.called


def test_wmchar_paste_and_supported_key_stay_on_hwnd():
    driver = KeyboardOnlyDriver(_FakeApplication(), input_mode="wmchar")
    with patch("wechat_auto.primitives.keyboard_only.user32") as api:
        driver._paste()
        driver.press_key("escape")
    assert api.PostMessageW.call_count == 3


def test_restore_mode_click_is_synchronous_and_restores_foreground():
    app = _FakeApplication()
    driver = KeyboardOnlyDriver(app, auto_activate=False)
    driver._rect = lambda: (0, 0, 1000, 800)
    with patch("wechat_auto.primitives.keyboard_only.user32") as api:
        api.ScreenToClient.return_value = 1
        api.GetForegroundWindow.return_value = 99
        api.IsWindow.return_value = 1
        driver.click_window_fraction(.2, .3)
    assert [call.args[1] for call in api.SendMessageW.call_args_list] == [
        0x0200, 0x0201, 0x0202,
    ]
    api.SetForegroundWindow.assert_called_once_with(99)
