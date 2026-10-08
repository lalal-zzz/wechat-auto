from unittest.mock import MagicMock

import pytest

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.actions.contracts import StaleFrameError


def _skill(mock_app, mock_finder, config, session):
    skill = BasicSkill(mock_app, config, session)
    skill._keyboard_only_auto = MagicMock()
    skill._vision_auto = MagicMock()
    skill._focus_input = MagicMock()
    skill._contact_list_bounds = MagicMock(return_value=(1000, 800, [.05, .14, .40, 1.]))
    skill.ensure_contacts_section = MagicMock()
    skill.prepare_visual_review = MagicMock(return_value={'review_id': 'test', 'input_dispatched': False})
    return skill


def test_click_and_scroll_are_hwnd_only(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    assert skill.click(.2, .3)["transport"] == "hwnd"
    assert skill.scroll(.5, .5, 3)["transport"] == "hwnd"
    skill.keyboard_only.click_window_fraction.assert_called_once_with(.2, .3)
    skill.keyboard_only.wheel_window_fraction.assert_called_once_with(.5, .5, 3, embedded_content=False)
    result = skill.scroll(.8, .7, 2, embedded_content=True)
    assert result['embedded_content']
    skill.keyboard_only.wheel_window_fraction.assert_called_with(.8, .7, 2, embedded_content=True)


def test_action_receipt_uses_observed_coordinates(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    result = skill.click(.2, .3)
    assert result['coordinate_source'] == 'observed_frame'
    assert result['receipt_id'].startswith('ar')


def test_navigation_never_falls_back_to_fixed_coordinates(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.page_operation = MagicMock(return_value={'success': False})
    with pytest.raises(RuntimeError, match='postcondition'):
        skill.open_navigation('contacts')
    skill.keyboard_only.click_window_fraction.assert_not_called()


def test_navigation_recovery_runs_entire_observation_again(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    skill._page_operation_once = MagicMock(side_effect=[
        {'success': False, 'source_page': 'chat', 'after_pages': ['chat'], 'point': [.04, .27]},
        {'success': True, 'source_page': 'chat', 'after_pages': ['contacts'], 'point': [.03, .19]},
    ])
    result = skill.page_operation('open_contacts')
    assert skill._page_operation_once.call_count == 2
    assert result['success'] and result['automatic_retry']
    assert [a['point'] for a in result['attempts']] == [[.04, .27], [.03, .19]]


def test_resize_before_dispatch_reobserves_and_attempt_limit_stops(
    mock_app, mock_finder, config, session
):
    skill = _skill(mock_app, mock_finder, config, session)
    skill._page_operation_once = MagicMock(side_effect=StaleFrameError('resize'))
    result = skill.page_operation('open_contacts', max_attempts=3)
    assert skill._page_operation_once.call_count == 3
    assert result['success'] is False and result['input_dispatched'] is False
    assert all(a['error'] == 'stale_frame' for a in result['attempts'])
    skill.keyboard_only.click_window_fraction.assert_not_called()


def test_ambiguous_control_is_not_retried(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    skill._page_operation_once = MagicMock(side_effect=RuntimeError('ambiguous control'))
    with pytest.raises(RuntimeError, match='ambiguous'):
        skill.page_operation('open_contacts')
    skill._page_operation_once.assert_called_once()


def test_missing_current_glyph_recalculates_then_offers_image_review(mock_app, mock_finder, config, session):
    from wechat_auto.primitives.page_controls import NavigationControlError

    skill = _skill(mock_app, mock_finder, config, session)
    skill._page_operation_once = MagicMock(side_effect=NavigationControlError('glyph not unique'))
    result = skill.page_operation('open_chats')
    assert skill._page_operation_once.call_count == 2
    assert not result['success'] and not result['input_dispatched']
    assert result['visual_review']['review_id'] == 'test'
    skill.prepare_visual_review.assert_called_once_with('open_chats', hwnd=None)
    skill.keyboard_only.click_window_fraction.assert_not_called()


@pytest.mark.parametrize('operation,after', [
    ('open_contacts', ['chat', 'main_menu']), ('open_contacts', ['unknown']),
    ('open_main_menu', ['chat']), ('close_content_tab', ['web_search']),
])
def test_recovery_stops_on_changed_page_or_non_idempotent_action(
    mock_app, mock_finder, config, session, operation, after
):
    skill = _skill(mock_app, mock_finder, config, session)
    skill._page_operation_once = MagicMock(return_value={
        'success': False, 'source_page': 'chat', 'after_pages': after,
    })
    result = skill.page_operation(operation)
    assert result['automatic_retry'] is False
    skill._page_operation_once.assert_called_once()


def test_unverified_chat_search_never_presses_enter(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_navigation = MagicMock()
    skill.prepare_search = MagicMock()
    result = skill.open_chat("朋友")
    assert result["opened"] is False
    assert result["selection_required"] is True
    skill.prepare_search.assert_called_once_with("朋友")
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
    skill.keyboard_only.click_window_fraction_sync.assert_called_once_with(.10, .30)
    skill.vision.ocr.assert_not_called()


def test_row_index_cannot_select_with_old_fixed_coordinates(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    with pytest.raises(RuntimeError, match='removed'):
        skill.open_visible_chat_row(2)
    skill.keyboard_only.click_window_fraction.assert_not_called()


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


def test_old_semantic_mutation_coordinates_are_unavailable(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    with pytest.raises(RuntimeError, match='removed'):
        skill._semantic_click(21, 3)
    skill.keyboard_only.click_window_fraction.assert_not_called()


def test_prepare_text_uses_hwnd_driver(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_chat = MagicMock(return_value={"verified_by": "ocr", "opened": True})
    result = skill.prepare_text("target", "hello")
    assert result["sent"] is False
    skill._focus_input.assert_called_once()
    skill.keyboard_only._type_text.assert_called_once_with("hello")


def test_unselected_search_never_receives_reply_text(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_chat = MagicMock(return_value={'opened': False, 'selection_required': True})
    from wechat_auto.exceptions import ChatNotFoundError
    with pytest.raises(ChatNotFoundError, match='chat_not_opened'):
        skill.prepare_text('target', 'reply')
    skill._focus_input.assert_not_called()
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
    skill.open_navigation = MagicMock()
    skill.prepare_search = MagicMock()
    skill.vision.region_of.return_value = (0, 0, 400, 500)
    skill.vision.size.return_value = (1000, 800)
    skill.vision.ocr.side_effect = [
        [
            {"text": "联系人", "x": 100, "y": 150, "w": 50, "h": 20},
            {"text": "张三", "x": 120, "y": 200, "w": 60, "h": 20},
        ],
        [{"text": "微信号：wxid_test_friend", "x": 500, "y": 200, "w": 180, "h": 20}],
    ]

    result = skill.open_contact_profile("张三", "wxid_test_friend", max_contact_scroll_pages=0)

    assert result["verified_by"] == "contacts_page_and_profile_ocr"
    assert skill.keyboard_only.click_window_fraction.call_args_list[-1].args == (.15, .2625)
    skill.ensure_contacts_section.assert_called_once()
    skill.prepare_search.assert_not_called()


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
    skill.open_navigation = MagicMock()
    skill.prepare_search = MagicMock()
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
    skill._focus_input.assert_called_once()
    skill.keyboard_only._paste.assert_called_once()


def test_sticker_id_cannot_use_stored_cell_coordinates(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    with pytest.raises(RuntimeError, match='removed'):
        skill.send_sticker_by_id('target', 'sticker', 'catalog.sqlite3', confirm=True)
    skill.keyboard_only.click_window_fraction.assert_not_called()
def test_verified_send_requires_confirmation_and_stable_recipient(mock_app, config, session):
    from wechat_auto.actions.basic import BasicSkill
    skill = BasicSkill(mock_app, config, session)
    with pytest.raises(PermissionError, match='explicit confirmation'):
        skill.send_current_verified_text('test')
    with pytest.raises(PermissionError, match='recipient lease'):
        skill.send_current_verified_text('test', confirm=True)


def test_search_selection_never_accepts_an_unrelated_builtin(mock_app, config, session):
    from wechat_auto.actions.basic import BasicSkill
    skill = BasicSkill(mock_app, config, session)
    with pytest.raises(ValueError, match='built-in FileHelper'):
        skill.select_search_result('Other', section='function', username='filehelper')
    with pytest.raises(ValueError, match='contact/function'):
        skill.select_search_result('Someone', section='chat_history', username='wxid_test_x')


def test_confirmed_sticker_cannot_submit_unbound_raw_coordinates(mock_app,mock_finder,config,session):
    skill=_skill(mock_app,mock_finder,config,session)
    with pytest.raises(RuntimeError,match='current-frame asset matching'):
        skill.send_sticker((.4,.4),confirm=True)
    skill.keyboard_only.click_window_fraction.assert_not_called()
