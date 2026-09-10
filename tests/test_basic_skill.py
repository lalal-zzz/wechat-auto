from unittest.mock import MagicMock

import pytest

from wechat_auto.actions.basic import BasicSkill


def _skill(mock_app, mock_finder, config, session):
    skill = BasicSkill(mock_app, config, session)
    skill._keyboard_only_auto = MagicMock()
    skill._vision_auto = MagicMock()
    return skill


def test_click_and_scroll_are_hwnd_only(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    assert skill.click(.2, .3)["transport"] == "hwnd"
    assert skill.scroll(.5, .5, 3)["transport"] == "hwnd"
    skill.keyboard_only.click_window_fraction.assert_called_once_with(.2, .3)
    skill.keyboard_only.wheel_window_fraction.assert_called_once_with(.5, .5, 3)


def test_right_click_and_key_are_hwnd_only(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    assert skill.right_click(.2, .3)["transport"] == "hwnd"
    assert skill.press_key("escape")["transport"] == "hwnd"
    skill.keyboard_only.right_click_window_fraction.assert_called_once_with(.2, .3)
    skill.keyboard_only.press_key.assert_called_once_with("escape")


def test_external_actions_require_confirmation(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    with pytest.raises(PermissionError):
        skill.send_text("target", "hello")
    with pytest.raises(PermissionError):
        skill.send_sticker((.4, .4))
    with pytest.raises(PermissionError):
        skill.like_moment((.8, .8), (.7, .8))
    with pytest.raises(PermissionError):
        skill.send_file("target", "anything")
    with pytest.raises(PermissionError):
        skill.send_image("target", "anything")


def test_prepare_text_uses_hwnd_driver(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_chat = MagicMock(return_value={"verified_by": "ocr"})
    result = skill.prepare_text("target", "hello")
    assert result["sent"] is False
    skill.keyboard_only.click_input.assert_called_once()
    skill.keyboard_only._type_text.assert_called_once_with("hello")


def test_prepare_file_pastes_through_hwnd(mock_app, mock_finder, config, session, tmp_path):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_chat = MagicMock(return_value={"verified_by": "ocr"})
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"test")
    from unittest.mock import patch
    with patch("wechat_auto.actions.basic.ClipboardHelper.set_files") as set_files:
        result = skill.prepare_file("target", str(payload))
    assert result["sent"] is False
    set_files.assert_called_once_with([str(payload.resolve())])
    skill.keyboard_only.click_input.assert_called_once()
    skill.keyboard_only._paste.assert_called_once()


def test_send_sticker_by_id_requires_verified_catalog(
    mock_app, mock_finder, config, session, tmp_path
):
    from wechat_auto.storage import StickerCatalog
    catalog_path = tmp_path / "catalog.sqlite3"
    with StickerCatalog(catalog_path) as catalog:
        catalog.register("abc", hint="加油", cell=(.4, .5),
                         layout_size=(1000, 800), page_steps=2, verified=True)
    skill = _skill(mock_app, mock_finder, config, session)
    skill.vision.size.return_value = (1000, 800)
    skill.open_chat = MagicMock(return_value={"verified_by": "ocr"})
    skill.open_emoji = MagicMock()
    skill.scroll = MagicMock()
    skill.click = MagicMock()
    result = skill.send_sticker_by_id(
        "friend", "abc", str(catalog_path), confirm=True
    )
    assert result["sent"] is True
    skill.open_chat.assert_called_once_with("friend")
    skill.scroll.assert_called_once_with(.65, .70, 2)
    skill.click.assert_called_once_with(.4, .5)
