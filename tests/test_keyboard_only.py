from unittest.mock import patch

import pytest

from wechat_auto.primitives.keyboard_only import KeyboardOnlyDriver


def test_native_backspace_keys_stay_on_focused_hwnd_with_scan_codes():
    driver = KeyboardOnlyDriver(_FakeApplication(), foreground_mode='never')
    with patch.object(driver, '_focused_input_hwnd', return_value=42), \
         patch('wechat_auto.primitives.keyboard_only.user32') as api, \
         patch.object(driver, '_settle_ui'):
        api.MapVirtualKeyW.return_value = 0x0e
        driver.erase_backward(3)
    assert [call.args for call in api.PostMessageW.call_args_list] == [
        (42, 0x100, 8, 0x000e0001), (42, 0x101, 8, 0xc00e0001)] * 3
    api.SendMessageW.assert_not_called()


def test_extended_native_key_sets_extended_and_release_bits():
    driver = KeyboardOnlyDriver(_FakeApplication(), foreground_mode='never')
    with patch.object(driver, '_focused_input_hwnd', return_value=42), \
         patch('wechat_auto.primitives.keyboard_only.user32') as api:
        api.MapVirtualKeyW.return_value = 0xe04f
        driver._wm_key(0x23, True)
        driver._wm_key(0x23, False)
    assert [call.args[3] for call in api.PostMessageW.call_args_list] == [0x014f0001, 0xc14f0001]


@pytest.mark.parametrize('count', [0, -1, True])
def test_invalid_backspace_count_never_dispatches(count):
    driver = KeyboardOnlyDriver(_FakeApplication(), foreground_mode='never')
    with patch('wechat_auto.primitives.keyboard_only.user32') as api:
        with pytest.raises(ValueError):
            driver.erase_backward(count)
        api.PostMessageW.assert_not_called()


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


def test_hover_sends_only_mousemove_and_never_clicks_or_types():
    driver = KeyboardOnlyDriver(_FakeApplication(), foreground_mode='never')
    driver._rect = lambda: (0, 0, 1000, 800)
    with patch('wechat_auto.primitives.keyboard_only.user32') as api:
        api.ScreenToClient.return_value = 1
        driver.hover_window_fraction(.4, .3)
        api.SendMessageW.assert_called_once_with(1, 0x200, 0, 400 | (240 << 16))
        api.PostMessageW.assert_not_called()
        api.reset_mock()
        with pytest.raises(ValueError):
            driver.hover_window_fraction(-.1, .3)
        api.SendMessageW.assert_not_called()
        api.ScreenToClient.return_value = 0
        with pytest.raises(RuntimeError, match='ScreenToClient'):
            driver.hover_window_fraction(.4, .3)
        api.SendMessageW.assert_not_called()


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
    assert [c.args[1] for c in api.SendMessageW.call_args_list] == [0x21, 0x20, 0x200, 0x201, 0x202]
    assert api.SendMessageW.call_args_list[0].args[2:] == (1, 1 | (0x201 << 16))


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


@pytest.mark.parametrize('notches,delta', [(2, -120), (-3, 120), (0, 0)])
def test_wheel_posts_normal_window_detents_in_each_direction(notches, delta):
    driver = KeyboardOnlyDriver(_FakeApplication())
    driver._rect = lambda: (0, 0, 1000, 800)
    with patch("wechat_auto.primitives.keyboard_only.user32") as api, \
         patch.object(driver, '_settle_ui') as settle:
        api.PostMessageW.return_value = 1
        driver.wheel_window_fraction(.65, .72, notches)
    assert api.PostMessageW.call_count == abs(notches)
    assert settle.call_count == abs(notches)
    for call in api.PostMessageW.call_args_list:
        assert call.args == (1, 0x20A, (delta & 0xffff) << 16, 650 | (576 << 16))


def test_wheel_rejection_stops_remaining_detents():
    driver = KeyboardOnlyDriver(_FakeApplication(), foreground_mode='never')
    driver._rect = lambda: (0, 0, 1000, 800)
    with patch('wechat_auto.primitives.keyboard_only.user32') as api, \
         patch.object(driver, '_settle_ui') as settle:
        api.PostMessageW.side_effect = [1, 0, 1]
        with pytest.raises(RuntimeError, match='WM_MOUSEWHEEL'):
            driver.wheel_window_fraction(.65, .72, 3)
        assert api.PostMessageW.call_count == 2
        settle.assert_called_once()


def test_embedded_wheel_routes_to_unique_render_hwnd_with_screen_coordinates():
    driver = KeyboardOnlyDriver(_FakeApplication(), foreground_mode='never')
    driver._rect = lambda: (100, 200, 1100, 1000)
    with patch.object(driver, '_browser_pointer_hwnd', return_value=42) as resolve, \
         patch('wechat_auto.primitives.keyboard_only.user32') as api, \
         patch.object(driver, '_settle_ui'):
        api.PostMessageW.return_value = 1
        driver.wheel_window_fraction(.8, .7, 2, embedded_content=True)
        resolve.assert_called_once_with(.8, .7, render=True)
        assert all(c.args == (42, 0x20a, (-120 & 0xffff) << 16, 900 | (760 << 16))
                   for c in api.PostMessageW.call_args_list)


def test_ambiguous_embedded_wheel_does_not_fall_back_to_main():
    driver = KeyboardOnlyDriver(_FakeApplication(), foreground_mode='never')
    driver._rect = lambda: (0, 0, 1000, 800)
    with patch.object(driver, '_browser_pointer_hwnd', side_effect=RuntimeError('ambiguous')), \
         patch('wechat_auto.primitives.keyboard_only.user32') as api:
        with pytest.raises(RuntimeError, match='ambiguous'):
            driver.wheel_window_fraction(.8, .7, 2, embedded_content=True)
        api.PostMessageW.assert_not_called()


@pytest.mark.parametrize('body_class', ['MMUIRenderSubWindowHW', 'Chrome_RenderWidgetHostHWND'])
def test_embedded_body_requires_host_ancestry_not_just_point_containment(body_class):
    driver = KeyboardOnlyDriver(_FakeApplication(), foreground_mode='never')
    driver._rect = lambda: (0, 0, 1000, 800)
    classes = {42: 'Chrome_WidgetWin_0', 43: body_class, 44: 'MMUIRenderSubWindowHW'}
    with patch('wechat_auto.primitives.keyboard_only.user32') as api:
        api.GetClassNameW.side_effect = lambda hwnd, buf, size: setattr(buf, 'value', classes[int(hwnd)])
        def rect(hwnd, ptr):
            ptr._obj.left, ptr._obj.top, ptr._obj.right, ptr._obj.bottom = (0, 0, 1000, 800)
            return 1
        api.GetWindowRect.side_effect = rect
        api.IsWindowVisible.return_value = 1
        api.EnumChildWindows.side_effect = lambda hwnd, callback, param: [callback(h, param) for h in classes]
        api.GetParent.return_value = 0
        api.IsChild.return_value = 0
        parents = {43: 45, 45: 42, 44: 1, 1: 0}
        api.GetAncestor.side_effect = lambda hwnd, flag: parents.get(hwnd, 0)
        assert driver._browser_pointer_hwnd(.8, .7, render=True) == 43
        parents[44] = 42
        with pytest.raises(RuntimeError, match='ambiguous'):
            driver._browser_pointer_hwnd(.8, .7, render=True)


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
        0x0021, 0x0020, 0x0200, 0x0201, 0x0202,
    ]
    api.SetForegroundWindow.assert_called_once_with(99)
