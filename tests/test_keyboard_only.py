from wechat_auto.primitives.keyboard_only import KeyboardOnlyDriver, KeyboardOnlyLayout
from unittest.mock import patch
import pytest


def test_unicode_units_and_control_rejection():
    driver = KeyboardOnlyDriver(_FakeApplication(), input_mode="wmchar")
    with patch("wechat_auto.primitives.keyboard_only.user32") as api:
        driver._wm_char_text("测试😀")
        assert [c.args[2] for c in api.SendMessageW.call_args_list] == [0x6D4B, 0x8BD5, 0xD83D, 0xDE00]
        api.reset_mock()
        with pytest.raises(ValueError):
            driver._wm_char_text("a\nb")
        api.SendMessageW.assert_not_called()


class _FakeApplication:
    handle = 1


def test_fractional_anchor_uses_full_window_rect():
    driver = KeyboardOnlyDriver(_FakeApplication())
    driver._rect = lambda: (100, 200, 1100, 900)

    assert driver.point(0.178, 0.084) == (278, 259)
    assert driver.point(0.660, 0.850) == (760, 795)


def test_layout_can_be_calibrated_without_visual_dependencies():
    layout = KeyboardOnlyLayout(search_x=0.2, search_y=0.1, input_x=0.7, input_y=0.8)
    driver = KeyboardOnlyDriver(_FakeApplication(), layout)
    driver._rect = lambda: (0, 0, 1000, 1000)

    assert driver.point(layout.search_x, layout.search_y) == (200, 100)
    assert driver.point(layout.input_x, layout.input_y) == (700, 800)


def test_layout_can_be_calibrated_from_screen_points(tmp_path):
    layout = KeyboardOnlyLayout.from_screen_points(
        (100, 200, 1100, 900),
        search=(278, 259),
        input_box=(760, 795),
    )
    path = tmp_path / "keyboard-layout.json"
    layout.save(str(path))
    loaded = KeyboardOnlyLayout.load(str(path))

    assert loaded == layout


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
    assert api.SendMessageW.call_count == 6
