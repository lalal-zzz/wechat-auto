from unittest.mock import MagicMock, patch

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
    skill.open_contact_profile = MagicMock(return_value={"verified_by": "ocr", "opened": True})
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
    skill._recipient_lease = {'username': 'target'}
    frame = {'x': 20, 'y': 50, 'w': 60, 'h': 40}
    skill._checked_recipient_composer = MagicMock(side_effect=[
        ({'state': {'size': [100, 100]}}, '', frame), ({}, 'hello', frame)])
    with patch('wechat_auto.actions.basic.time.sleep'):
        result = skill.prepare_text("target", "hello")
    assert result["sent"] is False
    assert result['prepared'] is True
    skill._focus_input.assert_not_called()
    skill.keyboard_only.click_window_fraction.assert_called_once_with(.5, .62)
    skill.keyboard_only._type_text.assert_called_once_with("hello")


def test_unselected_search_never_receives_reply_text(mock_app, mock_finder, config, session):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_chat = MagicMock(return_value={'opened': False, 'selection_required': True})
    with pytest.raises(PermissionError, match='Stable contact'):
        skill.prepare_text('target', 'reply')
    skill._focus_input.assert_not_called()
    skill.keyboard_only._type_text.assert_not_called()


def test_prepare_mention_uses_verified_empty_draft_path_without_accepting_suggestion(
    mock_app, mock_finder, config, session
):
    skill = _skill(mock_app, mock_finder, config, session)
    skill._recipient_lease = {'username': 'stable@chatroom'}
    skill.prepare_text = MagicMock(return_value={'prepared': False, 'success': False})
    result = skill.prepare_mention('stable@chatroom', '张三', '你好')
    skill.prepare_text.assert_called_once_with('stable@chatroom', '@张三 你好')
    assert not result['mention_verified'] and not result['sent']
    assert result['selection_required'] and not result['prepared']
    skill.keyboard_only._enter.assert_not_called()


@pytest.mark.parametrize('action,args', [
    ('send_mention', ('group@chatroom', '张三', '你好')),
    ('send_quote', ('contact', (.5, .6), (.6, .5), '回复')),
    ('prepare_quote', ('contact', (.5, .6))),
])
def test_unverified_mention_and_quote_never_navigate_type_or_submit(
    mock_app, mock_finder, config, session, action, args
):
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_chat = MagicMock(return_value={'opened': True})
    skill.prepare_text = MagicMock()
    skill.prepare_quote = MagicMock() if action == 'send_quote' else skill.prepare_quote
    skill.click = MagicMock()
    skill.right_click = MagicMock()
    kwargs = {'confirm': True} if action.startswith('send_') else {}
    with pytest.raises(PermissionError):
        getattr(skill, action)(*args, **kwargs)
    skill.open_chat.assert_not_called()
    skill.prepare_text.assert_not_called()
    skill.click.assert_not_called()
    skill.right_click.assert_not_called()
    skill._focus_input.assert_not_called()
    skill.keyboard_only._type_text.assert_not_called()
    skill.keyboard_only._enter.assert_not_called()


@pytest.mark.parametrize('lease,contact', [
    (None, 'stable@chatroom'),
    ({'username': 'other@chatroom'}, 'stable@chatroom'),
    ({'username': 'ordinary'}, 'ordinary'),
    ({'username': 'filehelper'}, 'filehelper'),
])
def test_mention_draft_rejects_missing_or_wrong_group_identity(mock_app, mock_finder, config, session, lease, contact):
    skill = _skill(mock_app, mock_finder, config, session)
    skill._recipient_lease = lease
    skill.open_chat = MagicMock(return_value={'opened': True})
    skill.prepare_text = MagicMock()
    with pytest.raises(PermissionError, match='group recipient'):
        skill.prepare_mention(contact, 'member')
    skill.open_chat.assert_not_called()
    skill.prepare_text.assert_not_called()
    skill.keyboard_only._type_text.assert_not_called()


@pytest.mark.parametrize('action,args,error', [
    ('send_mention', ('group@chatroom', 'member'), PermissionError),
    ('send_quote', ('contact', (.5, .6), None, 'reply'), PermissionError),
    ('prepare_mention', ('group@chatroom', '  '), ValueError),
])
def test_mention_and_quote_validation_has_no_ui_effects(mock_app, mock_finder, config, session, action, args, error):
    skill = _skill(mock_app, mock_finder, config, session)
    with pytest.raises(error):
        getattr(skill, action)(*args)
    skill._focus_input.assert_not_called()
    skill.keyboard_only._type_text.assert_not_called()
    skill.keyboard_only._enter.assert_not_called()


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


def test_quote_ocr_label_does_not_authenticate_message_coordinates(mock_app, mock_finder, config, session):
    config.ocr_verify_enabled = True
    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_chat = MagicMock(return_value={'opened': True})
    skill.vision.ocr.return_value = [{'text': '引用', 'x': 400, 'y': 300, 'w': 40, 'h': 20}]
    with pytest.raises(PermissionError, match='message identity'):
        skill.prepare_quote('contact', (.5, .6), text='draft')
    skill.open_chat.assert_not_called()
    skill.vision.ocr.assert_not_called()


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
    skill.open_chat = MagicMock(return_value={"verified_by": "ocr", "opened": True})
    skill._recipient_lease = {'username': 'target'}
    skill._paste_attachment_via_menu = MagicMock()
    skill.copy_attachment_identity = MagicMock(return_value={'identity_verified': False})
    skill._checked_recipient_composer = MagicMock(return_value=(
        {'state': {'size': [1000, 800]}}, '', {'x': 300, 'y': 600, 'w': 680, 'h': 180}))
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"test")
    from unittest.mock import patch
    with (patch("wechat_auto.actions.basic.ClipboardHelper.set_files") as set_files,
          patch("wechat_auto.actions.basic.ClipboardHelper.files_match", return_value=True)):
        result = skill.prepare_file("target", str(payload))
    assert result["sent"] is False
    set_files.assert_called_once_with([str(payload.resolve())])
    assert result['prepared'] is False
    skill._focus_input.assert_not_called()
    skill._paste_attachment_via_menu.assert_called_once()
    skill.keyboard_only._paste.assert_not_called()


@pytest.mark.parametrize('action', [
    'prepare_file', 'prepare_image', 'send_file', 'send_image',
    'prepare_mention', 'send_mention', 'prepare_quote', 'send_quote',
    'copy_message', 'prepare_profile_observation',
])
def test_unopened_search_stops_all_dependent_chat_actions(
    mock_app, mock_finder, config, session, tmp_path, action
):
    from unittest.mock import patch

    from wechat_auto.exceptions import ChatNotFoundError

    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_chat = MagicMock(return_value={'opened': False, 'selection_required': True})
    skill.click = MagicMock()
    skill.right_click = MagicMock()
    payload = tmp_path / 'payload.bin'
    payload.write_bytes(b'synthetic')
    arguments = {
        'prepare_file': (('target', str(payload)), {}),
        'prepare_image': (('target', str(payload)), {}),
        'send_file': (('target', str(payload)), {'confirm': True}),
        'send_image': (('target', str(payload)), {'confirm': True}),
        'prepare_mention': (('target', 'member', 'draft'), {}),
        'send_mention': (('target', 'member', 'draft'), {'confirm': True}),
        'prepare_quote': (('target', (.5, .6), (.6, .5), 'draft'), {}),
        'send_quote': (('target', (.5, .6), (.6, .5), 'draft'), {'confirm': True}),
        'copy_message': (((.5, .6),), {'contact': 'target'}),
        'prepare_profile_observation': (('target', (.5, .6)), {}),
    }
    args, kwargs = arguments[action]
    with (
        patch('wechat_auto.actions.basic.ClipboardHelper.set_files') as files,
        patch('wechat_auto.actions.basic.ClipboardHelper.set_image') as image,
        pytest.raises((ChatNotFoundError, PermissionError)),
    ):
        getattr(skill, action)(*args, **kwargs)
    files.assert_not_called()
    image.assert_not_called()
    skill._focus_input.assert_not_called()
    skill.keyboard_only._type_text.assert_not_called()
    skill.keyboard_only._paste.assert_not_called()
    skill.keyboard_only._enter.assert_not_called()
    skill.click.assert_not_called()
    skill.right_click.assert_not_called()


@pytest.mark.parametrize('action', ['send_file', 'send_image', 'send_mention'])
def test_unverified_external_submission_never_claims_sent(
    mock_app, mock_finder, config, session, tmp_path, action
):
    from unittest.mock import patch

    skill = _skill(mock_app, mock_finder, config, session)
    skill.open_chat = MagicMock(return_value={'opened': True})
    if action != 'send_mention':
        skill._recipient_lease = {'username': 'target'}
        skill._paste_attachment_via_menu = MagicMock()
        skill._checked_recipient_composer = MagicMock(return_value=(
            {'state': {'size': [1000, 800]}}, '', {'x': 300, 'y': 600, 'w': 680, 'h': 180}))
    payload = tmp_path / 'payload.bin'
    payload.write_bytes(b'synthetic')
    args = ('target', 'member', 'draft') if action == 'send_mention' else ('target', str(payload))
    with (
        patch('wechat_auto.actions.basic.ClipboardHelper.set_files'),
        patch('wechat_auto.actions.basic.ClipboardHelper.set_image'),
        patch('wechat_auto.actions.basic.ClipboardHelper.files_match', return_value=True),
        patch('wechat_auto.actions.basic.ClipboardHelper.image_matches', return_value=True),
    ):
        if action != 'send_mention':
            with pytest.raises(PermissionError, match='verification required'):
                getattr(skill, action)(*args, confirm=True)
            skill.keyboard_only._enter.assert_not_called()
            return
        with pytest.raises(PermissionError, match='group/member'):
            getattr(skill, action)(*args, confirm=True)
    skill.keyboard_only._enter.assert_not_called()
    skill.keyboard_only._type_text.assert_not_called()


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
