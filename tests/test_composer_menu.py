import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from wechat_auto.actions.basic import BasicSkill


def setup_menu(mock_app, config, session):
    mock_app.handle = 10
    main = {'hwnd': 10, 'pid': 2, 'rect': [0, 0, 1000, 800],
            'client_rect': [0, 0, 1000, 800], 'dpi': 96, 'is_main': True}
    popup = {**main, 'hwnd': 20, 'owner_hwnd': 10, 'class': 'QtToolSaveBits', 'is_main': False}
    mock_app.describe_window.side_effect = lambda hwnd: main if hwnd == 10 else popup
    mock_app.list_windows.side_effect = [[main, popup], [main]]
    target = MagicMock()
    target.handle = 20
    mock_app.for_window.return_value = target
    skill = BasicSkill(mock_app, config, session)
    skill._recipient_lease = {'username': 'filehelper', 'query': 'FileHelper', 'metadata': main}
    skill._composer_menu_origin = {'recipient': skill._recipient_lease, 'created_at': time.monotonic()}
    return skill, popup


@pytest.mark.parametrize('body', ['', 'existing draft'])
def test_open_menu_needs_verified_empty_composer(mock_app, config, session, body):
    skill, _ = setup_menu(mock_app, config, session)
    skill._keyboard_only_auto = MagicMock()
    skill._checked_recipient_composer = MagicMock(return_value=(
        {'state': {'size': [1000, 800]}}, body, {'x': 300, 'y': 600, 'w': 680, 'h': 180}))
    with patch('wechat_auto.actions.basic.time.sleep'):
        if body:
            with pytest.raises(RuntimeError, match='Existing draft'):
                skill.open_composer_context_menu('filehelper')
            skill.keyboard_only.right_click_window_fraction.assert_not_called()
        else:
            result = skill.open_composer_context_menu('filehelper')
            assert result['input_dispatched'] and not result['sent'] and not result['success']
            skill.keyboard_only.right_click_window_fraction.assert_called_once_with(.64, .8175)


@pytest.mark.parametrize('failure', [None, 'no_origin', 'expired', 'foreign_owner', 'anchors', 'stale'])
def test_dismiss_requires_origin_owned_popup_and_fresh_editor_anchors(mock_app, config, session, failure):
    skill, popup = setup_menu(mock_app, config, session)
    driver = MagicMock()
    if failure == 'no_origin':
        skill._composer_menu_origin = None
    elif failure == 'expired':
        skill._composer_menu_origin['created_at'] = 0
    elif failure == 'foreign_owner':
        popup['owner_hwnd'] = 99
    elif failure == 'stale':
        mock_app.describe_window.side_effect = lambda hwnd: (
            skill._recipient_lease['metadata'] if hwnd == 10 else {**popup, 'dpi': 144})
    observation = {'ok': True, 'boxes': [{'text': '粘贴'}, {'text': '全选'}]}
    if failure == 'anchors':
        observation['boxes'] = [{'text': '任意内容'}]
    with (patch('wechat_auto.primitives.vision.VisionAutomation') as observer,
          patch.object(BasicSkill, 'keyboard_only', new_callable=PropertyMock, return_value=driver),
          patch('wechat_auto.actions.basic.time.sleep')):
        observer.return_value.observe_page.return_value = observation
        if failure:
            with pytest.raises((RuntimeError, PermissionError)):
                skill.dismiss_composer_context_menu()
            driver.press_key.assert_not_called()
        else:
            result = skill.dismiss_composer_context_menu()
            assert result['success'] and not result['sent']
            driver.press_key.assert_called_once_with('escape')
        assert skill._composer_menu_origin is None


def test_actual_empty_editor_menu_has_dismiss_only_route():
    from wechat_auto.actions.pages import resolve_operation
    from wechat_auto.primitives.page_state import classify_page

    boxes = [{'text': '粘贴', 'x': 20, 'y': 20, 'w': 40, 'h': 20, 'score': .99},
             {'text': '边写边译', 'x': 20, 'y': 60, 'w': 80, 'h': 20, 'score': .99}]
    state = classify_page(boxes, (315, 186))
    operation, source = resolve_operation('dismiss', state)
    assert source == 'composer_menu' and operation.method == 'escape'
    with pytest.raises((RuntimeError, ValueError)):
        resolve_operation('send_file', state)


def test_replaced_menu_origin_is_consumed_without_action(mock_app, config, session):
    skill, _ = setup_menu(mock_app, config, session)
    skill._composer_menu_origin['origin_id'] = 'other-operation'
    with pytest.raises(PermissionError, match='replaced'):
        skill._consume_composer_context_menu(expected_origin_id='this-operation')
    assert skill._composer_menu_origin is None


@pytest.mark.parametrize('failure', [None, 'draft', 'duplicate', 'clipboard', 'stale', 'recipient', 'size', 'low_score'])
def test_attachment_menu_paste_checks_identity_body_payload_and_current_control(mock_app, config, session, failure):
    skill, menu = setup_menu(mock_app, config, session)
    lease = skill._recipient_lease
    target = mock_app.for_window.return_value
    paste = {'text': '粘贴', 'x': 20, 'y': 20, 'w': 40, 'h': 20, 'score': .99}
    observation = {'ok': True, 'state': {'size': [1000, 800]}, 'boxes': [paste]}
    skill.open_composer_context_menu = MagicMock()
    skill._consume_composer_context_menu = MagicMock(return_value=(lease, target, menu, observation))
    skill._checked_recipient_composer = MagicMock(return_value=({}, 'edited' if failure == 'draft' else '', {}))
    verify = MagicMock(return_value=failure != 'clipboard')
    if failure == 'duplicate':
        observation['boxes'].append(dict(paste))
    elif failure == 'stale':
        mock_app.describe_window.side_effect = None
        mock_app.describe_window.return_value = {**menu, 'dpi': 144}
    elif failure == 'recipient':
        skill._consume_composer_context_menu.return_value = (dict(lease), target, menu, observation)
    elif failure == 'size':
        observation['state']['size'] = [1001, 800]
    elif failure == 'low_score':
        paste['score'] = .2
    driver = MagicMock()
    with patch.object(BasicSkill, 'keyboard_only', new_callable=PropertyMock, return_value=driver):
        if failure:
            with pytest.raises(RuntimeError):
                skill._paste_attachment_via_menu(lease, 'synthetic.txt', verify)
            driver.click_window_fraction.assert_not_called()
        else:
            skill._paste_attachment_via_menu(lease, 'synthetic.txt', verify)
            driver.click_window_fraction.assert_called_once_with(.04, .0375)
            verify.assert_called_once_with('synthetic.txt')
        driver._paste.assert_not_called()
        driver._enter.assert_not_called()


def test_only_the_exact_approved_menu_can_coexist_with_composer_check(mock_app, config, session):
    skill, menu = setup_menu(mock_app, config, session)
    mock_app.list_windows.side_effect = None
    mock_app.list_windows.return_value = [skill._recipient_lease['metadata'], menu]
    from PIL import Image

    skill._vision_auto = MagicMock()
    skill.vision._last_observed_image = Image.new('RGB', (1000, 800), (30, 30, 30))
    skill.vision.observe_page.return_value = {'ok': True, 'boxes': [
        {'text': '发送', 'x': 900, 'y': 740, 'w': 45, 'h': 25}], 'state': {
            'regions': {'conversation_header': [{'text': 'FileHelper'}], 'composer': []},
            'composer': {'state': 'present'},
            'geometry': {'composer_candidates': [{'x': 300, 'y': 600, 'w': 680, 'h': 180}]}}}
    with pytest.raises(RuntimeError, match='auxiliary'):
        skill._checked_recipient_composer(skill._recipient_lease)
    _, body, _ = skill._checked_recipient_composer(skill._recipient_lease, allowed_popup=dict(menu))
    assert body == ''
    skill.vision.observe_page.assert_called_once_with(visible=False)
    altered = {**menu, 'owner_hwnd': 99}
    with pytest.raises(RuntimeError, match='auxiliary'):
        skill._checked_recipient_composer(skill._recipient_lease, allowed_popup=altered)


@pytest.mark.parametrize('failure', [None, 'clipboard_before', 'unchanged_after', 'identity',
                                    'source_change', 'card', 'duplicate', 'read_error', 'expired_before_copy', 'menu_anchors',
                                    'post_copy_card', 'post_copy_recipient', 'post_copy_read', 'missing_frame'])
def test_copy_file_identity_is_fresh_and_never_modifies_draft(mock_app, config, session, tmp_path, failure):
    skill, menu = setup_menu(mock_app, config, session)
    lease = skill._recipient_lease
    target = mock_app.for_window.return_value
    payload = tmp_path / 'wa-test.txt'
    payload.write_bytes(b'abc')
    card = {'box': [300, 400, 300, 80]}
    skill._current_attachment_card = MagicMock(return_value=(card, lease))
    skill._composer_fingerprint = MagicMock(return_value='verified-card-pixels')
    if failure and failure.startswith('post_copy'):
        last = (dict(card, box=[301, 400, 300, 80]), lease) if failure == 'post_copy_card' else (card, dict(lease))
        if failure == 'post_copy_read':
            last = RuntimeError('synthetic post-copy observer failure')
        skill._current_attachment_card.side_effect = [(card, lease), (card, lease), last]
    elif failure == 'missing_frame':
        skill._composer_fingerprint.return_value = None

    def opened(*args):
        skill._composer_menu_origin = {'kind': 'attachment_card', 'candidate': card,
                                      'created_at': 0 if failure == 'expired_before_copy' else time.monotonic(),
                                      'origin_id': 'synthetic-origin'}
        return {'menu_origin_id': 'synthetic-origin'}

    skill.open_attachment_context_menu = MagicMock(side_effect=opened)
    copy = {'text': '复制', 'x': 20, 'y': 40, 'w': 40, 'h': 20, 'score': .99}
    observation = {'state': {'size': [1000, 800]}, 'boxes': [copy,
        {'text': '剪切'}, {'text': '粘贴'}, {'text': '删除'}]}
    skill._consume_composer_context_menu = MagicMock(return_value=(lease, target, menu, observation))
    if failure == 'card':
        skill._current_attachment_card.side_effect = [(card, lease), ({'box': [301, 400, 300, 80]}, lease)]
    elif failure == 'duplicate':
        observation['boxes'].append(dict(copy))
    elif failure == 'menu_anchors':
        observation['boxes'].pop()
    sequences = [10, 12] if failure == 'clipboard_before' else [10, 10, 10 if failure == 'unchanged_after' else 11]
    driver = MagicMock()
    with (patch('win32clipboard.GetClipboardSequenceNumber', side_effect=sequences),
          patch('wechat_auto.actions.basic.ClipboardHelper.set_text'),
          patch('wechat_auto.actions.basic.ClipboardHelper.copied_file_matches', return_value=failure != 'identity') as match,
          patch.object(BasicSkill, 'keyboard_only', new_callable=PropertyMock, return_value=driver),
          patch('wechat_auto.actions.basic.time.sleep')):
        if failure == 'source_change':
            def changed(*args):
                payload.write_bytes(b'xyz')
                return True
            match.side_effect = changed
        elif failure == 'read_error':
            match.side_effect = OSError('synthetic read failure')
        if failure in {'clipboard_before', 'card', 'duplicate', 'expired_before_copy', 'menu_anchors'}:
            with pytest.raises((RuntimeError, PermissionError)):
                skill.copy_attachment_identity('filehelper', str(payload))
            driver.click_window_fraction.assert_not_called()
        else:
            result = skill.copy_attachment_identity('filehelper', str(payload))
            assert result['identity_verified'] is (failure is None)
            assert not result['sent'] and result['dispatched']
            driver.click_window_fraction.assert_called_once_with(.04, .0625)
            assert bool(skill._attachment_identity_lease) is (failure is None)
            if failure is None:
                assert skill._attachment_identity_lease['card_digest'] == 'verified-card-pixels'
        driver._enter.assert_not_called()
        driver._select_all_clear.assert_not_called()


def test_actual_selection_menu_is_known_but_has_no_generic_delete_or_copy():
    from wechat_auto.actions.pages import resolve_operation
    from wechat_auto.primitives.page_state import classify_page

    boxes = [{'text': text, 'x': 20, 'y': 20+i*40, 'w': 45, 'h': 20, 'score': .99}
             for i, text in enumerate(('剪切', '复制', '粘贴', '删除'))]
    state = classify_page(boxes, (315, 292))
    assert resolve_operation('dismiss', state)[1] == 'composer_selection_menu'
    with pytest.raises(ValueError):
        resolve_operation('delete', state)
    with pytest.raises(ValueError):
        resolve_operation('copy', state)


@pytest.mark.parametrize('labels,recognized', [
    (['剪切', '复制', '粘贴', '删除'], True),
    (['剪切', '复制', '另存为.', '编辑'], True),
    (['复制', '另存为.', '编辑'], False),
])
def test_image_and_file_editor_selection_menu_observation(labels, recognized):
    from wechat_auto.primitives.page_state import classify_page

    boxes = [{'text': text, 'score': .99, 'x': 20, 'y': 20+i*40, 'w': 80, 'h': 20}
             for i, text in enumerate(labels)]
    state = classify_page(boxes, (315, 296))
    assert ('composer_selection_menu' in {p['key'] for p in state['overlays']}) is recognized


@pytest.mark.parametrize('image_origin', [False, True])
def test_image_copy_menu_requires_its_own_origin(mock_app, config, session, image_origin):
    skill, _ = setup_menu(mock_app, config, session)
    if image_origin:
        skill._composer_menu_origin['kind'] = 'image_preview'
    with patch('wechat_auto.primitives.vision.VisionAutomation') as observer:
        observer.return_value.observe_page.return_value = {'ok': True, 'boxes': [
            {'text': text} for text in ['剪切', '复制', '另存为.', '编辑']]}
        if image_origin:
            assert skill._consume_composer_context_menu()[0] is skill._recipient_lease
        else:
            with pytest.raises(RuntimeError, match='anchors absent'):
                skill._consume_composer_context_menu()
