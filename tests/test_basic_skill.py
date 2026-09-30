from unittest.mock import MagicMock

import pytest

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.actions.contracts import LayoutProfile


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


def test_action_receipt_and_layout_mismatch_gate(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    result = skill.click(.2, .3)
    assert result["transport"] == "hwnd"
    assert result["receipt_id"].startswith("ar")
    assert result["executed_at"]
    skill.layout_profile = LayoutProfile("4.1", 1000, 800, profile_id="strict")
    skill.vision.size.return_value = (900, 800)
    with pytest.raises(RuntimeError, match="layout mismatch"):
        skill.click(.2, .3)


def test_navigation_uses_pixel_probe_without_ocr(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.vision.is_green_at.side_effect = [False, True]

    result = skill.open_navigation("contacts")

    assert result["ocr_used"] is False
    assert result["attempts"] == 2
    skill.vision.ocr.assert_not_called()


def test_navigation_uses_ocr_marker_only_as_explicit_fallback(
    mock_app, mock_finder, config, session
):
    config.ocr_verify_enabled = True
    skill = _skill(mock_app, mock_finder, config, session)
    skill.vision.is_green_at.return_value = False
    skill.vision.ocr.return_value = [{"text": "通讯录", "x": 0, "y": 0, "w": 10, "h": 10}]

    result = skill.open_navigation("contacts")

    assert result["verified_by"] == "ocr_page_marker"
    assert result["ocr_used"] is True
    skill.keyboard_only.click_window_fraction.assert_called_once_with(
        skill.layout.contacts_button[0], skill.layout.contacts_button[1]
    )


def test_unverified_chat_search_never_presses_enter(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    result = skill.open_chat("朋友")
    assert result["opened"] is False
    assert result["selection_required"] is True
    skill.keyboard_only.prepare_chat_search.assert_called_once_with("朋友")
    skill.keyboard_only._enter.assert_not_called()


def test_open_chat_by_avatar_uses_local_template_without_ocr(
    mock_app, mock_finder, config, session
):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_navigation = MagicMock(return_value={"page": "chats", "ocr_used": False})
    skill.vision.find_avatar.return_value = {
        "x": .10, "y": .30, "score": .91, "margin": .12, "ocr_used": False,
    }
    result = skill.open_chat_by_avatar(b"avatar")
    assert result["ocr_used"] is False
    skill.keyboard_only.click_window_fraction_sync.assert_called_once_with(.17, .30)
    skill.vision.ocr.assert_not_called()


def test_open_visible_chat_row_uses_hwnd_and_pixel_probe(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_navigation = MagicMock(return_value={"page": "chats", "ocr_used": False})
    skill.vision.is_green_at.return_value = True
    result = skill.open_visible_chat_row(2)
    assert result["ocr_used"] is False
    skill.keyboard_only.click_window_fraction.assert_called_once_with(.17, .309)
    skill.vision.ocr.assert_not_called()


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


def test_contact_mutation_requires_confirmation_bound_to_username(
    mock_app, mock_finder, config, session
):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_contact_profile = MagicMock(return_value={"verified_by": "ocr"})
    with pytest.raises(PermissionError, match="wxid_test_friend"):
        skill.execute_contact_action(
            username="wxid_test_friend", contact_action="delete_contact", ui_query="朋友",
            confirm=True, confirmation_target="wxid_test_other",
        )


def test_set_remark_uses_calibrated_semantics_and_verifies_result(
    mock_app, mock_finder, config, session
):
    config.ocr_verify_enabled = True
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_contact_profile = MagicMock(return_value={"verified_by": "ocr"})
    skill.vision.size.return_value = (1000, 800)
    skill.vision.ocr.return_value = [{"text": "新备注"}]
    skill.layout_profile = LayoutProfile(
        "4.1.13.12", 1000, 800,
        elements={
            "21.03:remark": [.70, .20],
            "23.01:remark_input": [.60, .30],
            "23.02:save": [.90, .10],
        },
    )
    result = skill.execute_contact_action(
        username="wxid_test_friend", contact_action="set_remark", ui_query="朋友",
        value="新备注", confirm=True, confirmation_target="wxid_test_friend",
    )
    assert result["verified_by"] == "profile_ocr_after_write"
    assert [call.args for call in skill.keyboard_only.click_window_fraction.call_args_list] == [
        (.70, .20), (.60, .30), (.90, .10),
    ]
    skill.keyboard_only._type_text.assert_called_once_with("新备注")


def test_prepare_text_uses_hwnd_driver(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_chat = MagicMock(return_value={"verified_by": "ocr", "opened": True})
    result = skill.prepare_text("target", "hello")
    assert result["sent"] is False
    skill.keyboard_only.click_input.assert_called_once()
    skill.keyboard_only._type_text.assert_called_once_with("hello")


def test_unselected_search_never_receives_reply_text(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_chat = MagicMock(return_value={'opened': False, 'selection_required': True})
    from wechat_auto.exceptions import ChatNotFoundError
    with pytest.raises(ChatNotFoundError, match='chat_not_opened'):
        skill.prepare_text('target', 'reply')
    skill.keyboard_only.click_input.assert_not_called()
    skill.keyboard_only._type_text.assert_not_called()


def test_prepare_mention_is_hwnd_only_and_requires_selection(
    mock_app, mock_finder, config, session
):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_chat = MagicMock(return_value={"verified_by": "ocr"})
    result = skill.prepare_mention("群聊", "张三", "你好")
    assert result["selection_required"] is True
    assert result["sent"] is False
    assert [call.args[0] for call in skill.keyboard_only._type_text.call_args_list] == [
        "@张三", " 你好"
    ]


def test_quote_send_requires_confirmation_and_uses_hwnd(
    mock_app, mock_finder, config, session
):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_chat = MagicMock(return_value={"verified_by": "ocr"})
    with pytest.raises(PermissionError):
        skill.send_quote("好友", (.5, .6), (.6, .5), "回复")
    result = skill.send_quote("好友", (.5, .6), (.6, .5), "回复", confirm=True)
    assert result["sent"] is True
    skill.keyboard_only._enter.assert_called_once()


def test_copy_message_uses_ocr_menu_coordinate_without_reading_clipboard(
    mock_app, mock_finder, config, session
):
    config.ocr_verify_enabled = True
    skill = _skill(mock_app, mock_finder, config, session)
    skill.right_click = MagicMock()
    skill.click = MagicMock()
    skill.vision.ocr.return_value = [{"text": "复制", "x": 100, "y": 200, "w": 40, "h": 20}]
    skill.vision.size.return_value = (1000, 800)
    result = skill.copy_message((.5, .6))
    assert result["clipboard_read"] is False
    skill.right_click.assert_called_once_with(.5, .6)
    skill.click.assert_called_once_with(.12, .2625)


def test_quote_can_locate_context_menu_item_with_ocr(mock_app, mock_finder, config, session):
    config.ocr_verify_enabled = True
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_chat = MagicMock(return_value={"verified_by": "ocr"})
    skill.right_click = MagicMock()
    skill.click = MagicMock()
    skill.vision.ocr.return_value = [{"text": "引用", "x": 400, "y": 300, "w": 40, "h": 20}]
    skill.vision.size.return_value = (1000, 800)
    result = skill.prepare_quote("好友", (.5, .6), text="草稿")
    assert result["quote_menu"] == [.42, .3875]
    skill.click.assert_called_once_with(.42, .3875)


def test_open_contact_profile_uses_only_verified_contacts_result(
    mock_app, mock_finder, config, session
):
    config.ocr_verify_enabled = True
    skill = _skill(mock_app, mock_finder, config, session)
    skill.vision.region_of.return_value = (0, 0, 400, 500)
    skill.vision.size.return_value = (1000, 800)
    skill.vision.ocr.side_effect = [
        [{"text": "通讯录", "x": 100, "y": 50, "w": 60, "h": 20}],
        [
            {"text": "联系人", "x": 100, "y": 150, "w": 50, "h": 20},
            {"text": "张三", "x": 120, "y": 200, "w": 60, "h": 20},
        ],
        [{"text": "微信号：wxid_test_friend", "x": 500, "y": 200, "w": 180, "h": 20}],
    ]

    result = skill.open_contact_profile("张三", "wxid_test_friend", max_contact_scroll_pages=0)

    assert result["verified_by"] == "contacts_page_and_profile_ocr"
    assert skill.keyboard_only.click_window_fraction.call_args_list[-1].args == (.15, .2625)


@pytest.mark.parametrize('visible', ['微信号', '微信号：wxid_test_friend_extra', '微信号：other'])
def test_contact_profile_requires_exact_visible_identity(mock_app, mock_finder, config, session, visible):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.vision.size.return_value = (1000, 800)
    skill.vision.ocr.return_value = [{'text': visible, 'x': 500, 'y': 200, 'w': 150, 'h': 20}]
    from wechat_auto.exceptions import ChatNotFoundError
    with pytest.raises(ChatNotFoundError, match='did not match'):
        skill._open_and_verify_contact_box({'x': 120, 'y': 200, 'w': 60, 'h': 20}, 'wxid_test_friend')


def test_open_contact_profile_rejects_missing_contact_section(
    mock_app, mock_finder, config, session
):
    config.ocr_verify_enabled = True
    skill = _skill(mock_app, mock_finder, config, session)
    skill.vision.size.return_value = (1000, 800)
    skill.vision.ocr.side_effect = [
        [{"text": "通讯录", "x": 100, "y": 50, "w": 60, "h": 20}],
        [{"text": "文章", "x": 100, "y": 150, "w": 50, "h": 20}],
    ]

    from wechat_auto.exceptions import ChatNotFoundError
    with pytest.raises(ChatNotFoundError):
        skill.open_contact_profile("张三", max_contact_scroll_pages=0)


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
