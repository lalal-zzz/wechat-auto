from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image, ImageDraw

from wechat_auto.actions.basic import BasicSkill


def fixture_skill(mock_app, config, session, *, existing='', rendered='test'):
    skill = BasicSkill(mock_app, config, session)
    metadata = {'hwnd': 1, 'pid': 2, 'rect': [0,0,1000,800], 'client_rect': [0,0,1000,800], 'dpi': 96}
    mock_app.handle = 1
    mock_app.describe_window.return_value = metadata
    mock_app.list_windows.return_value = [{'is_main':True}]
    skill._recipient_lease = {'username': 'filehelper','query': 'FileHelper','metadata': metadata}
    skill._keyboard_only_auto = MagicMock()
    skill._vision_auto = MagicMock()
    frame = {'x': 300,'y': 600,'w': 680,'h': 180}
    def observation(body, outgoing=False):
        boxes = [{'text': 'FileHelper','x': 350,'y': 50,'w': 120,'h': 25,'score': .99},
                 {'text': '发送','x': 900,'y': 740,'w': 45,'h': 25,'score': .99},
                 {'text': '0','x': 600,'y': 740,'w': 20,'h': 25,'score': .99}]
        composer = [{'text': b['text'],'box_index': i} for i,b in enumerate(boxes) if i]
        if body:
            boxes.append({'text': body,'x': 330,'y': 650,'w': 200,'h': 25,'score': .99})
            composer.append({'text': body,'box_index': 3})
        if outgoing:
            boxes.append({'text': 'test','x': 700,'y': 400,'w': 200,'h': 25,'score': .99})
        state = {'size': [1000,800], 'composer': {'state':'present'},
                     'geometry': {'composer_candidates':[frame]},
                     'regions': {'conversation_header':[{'text':'FileHelper','box_index':0}],
                              'composer':composer}}
        return {'ok': True,'state': state,'boxes': boxes}
    skill.vision.observe_page.side_effect = [observation(existing), observation(rendered), observation('',True)]
    image = Image.new('RGB',(1000,800),(30,30,30))
    ImageDraw.Draw(image).rectangle((700,400,900,425), fill=(90,210,70))
    skill.vision._last_observed_image = image
    return skill


def test_action_row_icon_is_not_a_draft_and_send_is_verified_once(mock_app, config, session):
    skill = fixture_skill(mock_app,config,session)
    with patch('wechat_auto.actions.basic.time.sleep'):
        result = skill.send_current_verified_text('test',confirm=True)
    assert result['sent'] and not result['delivery_verified'] and not result['automatic_retry']
    skill.keyboard_only._type_text.assert_called_once_with('test')
    assert skill.keyboard_only.click_window_fraction.call_count == 2
    assert skill._recipient_lease is None


def test_dispatch_guard_can_stop_after_draft_preparation(mock_app, config, session):
    skill = fixture_skill(mock_app, config, session)
    guard = MagicMock(side_effect=PermissionError("synthetic stale context"))
    with patch('wechat_auto.actions.basic.time.sleep'), pytest.raises(PermissionError, match="stale context"):
        skill.execute(action="send_text", contact="filehelper", text="test", confirm=True, before_dispatch=guard)
    guard.assert_called_once_with()
    skill.keyboard_only._type_text.assert_called_once_with("test")
    skill.keyboard_only.click_window_fraction.assert_called_once()
    assert skill._recipient_lease is None


@pytest.mark.parametrize("changed_body", [False, True])
def test_dispatch_guard_reobserves_draft_and_button(mock_app, config, session, changed_body):
    skill = fixture_skill(mock_app, config, session)
    before, prepared, outgoing = list(skill.vision.observe_page.side_effect)
    refreshed = deepcopy(prepared)
    refreshed["boxes"][1]["x"] += 15
    if changed_body:
        refreshed["boxes"][3]["text"] = "user edit"
    skill.vision.observe_page.side_effect = [before, prepared, refreshed, outgoing]
    guard = MagicMock()

    with patch('wechat_auto.actions.basic.time.sleep'):
        if changed_body:
            with pytest.raises(RuntimeError, match="changed during dispatch checks"):
                skill.send_text("filehelper", "test", confirm=True, before_dispatch=guard)
            skill.keyboard_only.click_window_fraction.assert_called_once()
        else:
            assert skill.send_text("filehelper", "test", confirm=True, before_dispatch=guard)["sent"]
            skill.keyboard_only.click_window_fraction.assert_called_with(0.9375, 0.940625)
    guard.assert_called_once_with()


def test_prepare_text_requires_stable_identity_and_preserves_existing_draft(mock_app, config, session):
    skill = fixture_skill(mock_app, config, session, existing='0')
    with pytest.raises(PermissionError, match='Stable contact'):
        skill.prepare_text('FileHelper', 'test')
    with pytest.raises(RuntimeError, match='Existing draft'):
        skill.prepare_text('filehelper', 'test')
    skill.keyboard_only.click_window_fraction.assert_not_called()
    skill.keyboard_only._type_text.assert_not_called()


@pytest.mark.parametrize('blocked', ['window', 'header', 'panel', 'overlay', 'auxiliary'])
def test_prepare_text_changed_context_never_inputs(mock_app, config, session, blocked):
    skill = fixture_skill(mock_app, config, session)
    observations = list(skill.vision.observe_page.side_effect)
    if blocked == 'window':
        mock_app.describe_window.return_value = {**skill._recipient_lease['metadata'], 'dpi': 144}
    elif blocked == 'header':
        observations[0]['state']['regions']['conversation_header'][0]['text'] = 'Other'
    elif blocked == 'panel':
        observations[0]['state']['panels'] = [{'key': 'web_search'}]
    elif blocked == 'overlay':
        observations[0]['state']['overlays'] = [{'key': 'message_menu'}]
    else:
        mock_app.list_windows.return_value = [{'is_main': True}, {'is_main': False}]
    skill.vision.observe_page.side_effect = observations
    with pytest.raises(RuntimeError):
        skill.prepare_text('filehelper', 'test')
    skill.keyboard_only.click_window_fraction.assert_not_called()
    skill.keyboard_only._type_text.assert_not_called()
    skill.keyboard_only._enter.assert_not_called()


@pytest.mark.parametrize('rendered,expected', [('test', True), ('different', False)])
def test_prepared_text_observes_draft_without_sending(mock_app, config, session, rendered, expected):
    skill = fixture_skill(mock_app, config, session, rendered=rendered)
    with patch('wechat_auto.actions.basic.time.sleep'):
        result = skill.prepare_text('filehelper', 'test')
    assert result['prepared'] is expected
    assert result['success'] is expected
    assert result['sent'] is False
    assert result['input_dispatched'] is True
    skill.keyboard_only.click_window_fraction.assert_called_once()
    skill.keyboard_only._type_text.assert_called_once_with('test')
    skill.keyboard_only._enter.assert_not_called()


def prepared_draft_skill(mock_app, config, session):
    skill = fixture_skill(mock_app, config, session)
    observations = list(skill.vision.observe_page.side_effect)
    skill.vision.observe_page.side_effect = [observations[0], observations[1],
                                            observations[1], observations[1], observations[2]]
    with patch('wechat_auto.actions.basic.time.sleep'):
        assert skill.prepare_text('filehelper', 'test')['cancellation_available']
    return skill, observations


def test_owned_unchanged_draft_cancels_once_without_send(mock_app, config, session):
    skill, _ = prepared_draft_skill(mock_app, config, session)
    with patch('wechat_auto.actions.basic.time.sleep'):
        result = skill.cancel_prepared_text('filehelper')
    assert result['success'] and result['cancelled'] and result['clear_dispatched']
    assert result['sent'] is False
    skill.keyboard_only.erase_backward.assert_called_once_with(4)
    skill.keyboard_only._enter.assert_not_called()
    with pytest.raises(PermissionError, match='owned draft'):
        skill.cancel_prepared_text('filehelper')


@pytest.mark.parametrize('change', ['pixels', 'body', 'recipient', 'frame', 'no_lease', 'expired'])
def test_changed_or_unowned_draft_is_never_cleared(mock_app, config, session, change):
    skill, observations = prepared_draft_skill(mock_app, config, session)
    if change == 'pixels':
        skill.vision._last_observed_image.putpixel((400, 650), (255, 0, 0))
    elif change == 'body':
        observations[1]['boxes'][3]['text'] = 'edited'
        observations[1]['state']['regions']['composer'][-1]['text'] = 'edited'
    elif change == 'recipient':
        skill._recipient_lease = dict(skill._recipient_lease)
    elif change == 'frame':
        observations[1]['state']['geometry']['composer_candidates'][0]['w'] -= 1
    elif change == 'expired':
        skill._prepared_text_lease['expires_at'] = 0
    else:
        skill._prepared_text_lease = None
    with pytest.raises((RuntimeError, PermissionError)):
        skill.cancel_prepared_text('filehelper')
    skill.keyboard_only._select_all_clear.assert_not_called()
    skill.keyboard_only.erase_backward.assert_not_called()


def test_cancellation_rechecks_after_focus_and_does_not_retry_uncertain_clear(mock_app, config, session):
    skill, _ = prepared_draft_skill(mock_app, config, session)
    skill.keyboard_only.erase_backward.side_effect = RuntimeError('uncertain')
    with patch('wechat_auto.actions.basic.time.sleep'):
        result = skill.cancel_prepared_text('filehelper')
    assert not result['cancelled'] and result['clear_dispatched']
    assert result['verified_by'] == 'result_unknown'
    with pytest.raises(PermissionError):
        skill.cancel_prepared_text('filehelper')
    skill.keyboard_only.erase_backward.assert_called_once_with(4)


def test_user_edit_after_cancel_focus_prevents_clear(mock_app, config, session):
    skill, observations = prepared_draft_skill(mock_app, config, session)
    calls = 0

    def observe(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            skill.vision._last_observed_image.putpixel((401, 650), (255, 0, 0))
        return observations[1]

    skill.vision.observe_page.side_effect = observe
    result = skill.cancel_prepared_text('filehelper')
    assert not result['cancelled'] and not result['clear_dispatched']
    assert result['verified_by'] == 'draft_changed_after_focus'
    skill.keyboard_only._select_all_clear.assert_not_called()
    skill.keyboard_only.erase_backward.assert_not_called()
    with pytest.raises(PermissionError):
        skill.cancel_prepared_text('filehelper')


@pytest.mark.parametrize('action,setter', [('prepare_file', 'set_files'), ('prepare_image', 'set_image')])
@pytest.mark.parametrize('blocked_at', [0, 1, 2, 3])
def test_attachment_identity_and_draft_changes_prevent_paste(
    mock_app, config, session, tmp_path, action, setter, blocked_at
):
    skill = fixture_skill(mock_app, config, session)
    observations = list(skill.vision.observe_page.side_effect)
    skill.vision.observe_page.side_effect = [observations[1] if i == blocked_at else observations[0]
                                            for i in range(1, 4)]
    if blocked_at == 0:
        skill._recipient_lease = None
    payload = tmp_path / 'synthetic.bin'
    payload.write_bytes(b'test')
    with patch(f'wechat_auto.actions.basic.ClipboardHelper.{setter}') as set_clipboard:
        with pytest.raises((PermissionError, RuntimeError)):
            getattr(skill, action)('filehelper', str(payload))
        assert set_clipboard.call_count == (0 if blocked_at <= 1 else 1)
    skill.keyboard_only._paste.assert_not_called()
    skill.keyboard_only._enter.assert_not_called()


@pytest.mark.parametrize('action,setter', [('prepare_file', 'set_files'), ('prepare_image', 'set_image')])
def test_attachment_paste_is_not_a_verified_preview(mock_app, config, session, tmp_path, action, setter):
    skill = fixture_skill(mock_app, config, session)
    skill._paste_attachment_via_menu = MagicMock()
    skill.copy_attachment_identity = MagicMock(return_value={'identity_verified': False})
    empty = next(iter(skill.vision.observe_page.side_effect))
    skill.vision.observe_page.side_effect = [empty, empty, empty]
    payload = tmp_path / 'synthetic.bin'
    payload.write_bytes(b'test')
    verifier = 'files_match' if action == 'prepare_file' else 'image_matches'
    with (patch(f'wechat_auto.actions.basic.ClipboardHelper.{setter}'),
          patch(f'wechat_auto.actions.basic.ClipboardHelper.{verifier}', return_value=True)):
        result = getattr(skill, action)('filehelper', str(payload))
    assert result['prepared'] is False and result['sent'] is False
    assert result['verified_by'] == 'attachment_preview_not_verified'
    skill._paste_attachment_via_menu.assert_called_once()
    skill.keyboard_only._paste.assert_not_called()
    skill.keyboard_only._enter.assert_not_called()


@pytest.mark.parametrize('action', ['prepare_file', 'prepare_image'])
def test_clipboard_changed_before_attachment_paste_is_rejected(mock_app, config, session, tmp_path, action):
    skill = fixture_skill(mock_app, config, session)
    empty = next(iter(skill.vision.observe_page.side_effect))
    skill.vision.observe_page.side_effect = [empty, empty, empty]
    payload = tmp_path / 'synthetic.bin'
    payload.write_bytes(b'test')
    setter = 'set_files' if action == 'prepare_file' else 'set_image'
    verifier = 'files_match' if action == 'prepare_file' else 'image_matches'
    with (patch(f'wechat_auto.actions.basic.ClipboardHelper.{setter}'),
          patch(f'wechat_auto.actions.basic.ClipboardHelper.{verifier}', return_value=False),
          pytest.raises(RuntimeError, match='clipboard payload changed')):
        getattr(skill, action)('filehelper', str(payload))
    skill.keyboard_only._paste.assert_not_called()
    skill.keyboard_only._enter.assert_not_called()


def test_real_zero_draft_is_preserved_without_typing(mock_app, config, session):
    skill = fixture_skill(mock_app,config,session,existing='0')
    with pytest.raises(RuntimeError,match='Existing draft'):
        skill.send_current_verified_text('test',confirm=True)
    skill.keyboard_only._type_text.assert_not_called()
    skill.keyboard_only.click_window_fraction.assert_not_called()


@pytest.mark.parametrize('typed', [False, True])
def test_composer_gate_distinguishes_guide_from_same_typed_body(mock_app, config, session, typed):
    text = '按住鼠标语音输入文字'
    skill = fixture_skill(mock_app, config, session, existing=text)
    image = skill.vision._last_observed_image
    draw = ImageDraw.Draw(image)
    for x in range(335, 520, 10):
        draw.rectangle((x, 655, x+2, 665), fill=(220 if typed else 125,)*3)
    draw.rectangle((905, 745, 912, 752), fill=(100,)*3)
    _, body, _ = skill._checked_recipient_composer(skill._recipient_lease)
    assert bool(body) is typed


def test_explicit_existing_draft_send_does_not_replace_or_retype(mock_app, config, session):
    skill = fixture_skill(mock_app, config, session, existing='test')
    with patch('wechat_auto.actions.basic.time.sleep'):
        result = skill.send_current_verified_text('test', confirm=True, use_existing_draft=True)
    assert result['sent'] and result['dispatched']
    skill.keyboard_only._type_text.assert_not_called()
    skill.keyboard_only._select_all_clear.assert_not_called()
    skill.keyboard_only.erase_backward.assert_not_called()
    skill.keyboard_only.click_window_fraction.assert_called_once()
    assert skill._recipient_lease is None


@pytest.mark.parametrize('existing,rendered', [('', 'test'), ('other', 'test'), ('test', 'changed')])
def test_existing_draft_send_requires_exact_confirmed_body_twice(mock_app, config, session, existing, rendered):
    skill = fixture_skill(mock_app, config, session, existing=existing, rendered=rendered)
    with pytest.raises(RuntimeError, match='no send dispatched'):
        skill.send_current_verified_text('test', confirm=True, use_existing_draft=True)
    skill.keyboard_only._type_text.assert_not_called()
    skill.keyboard_only.click_window_fraction.assert_not_called()


def test_unverified_rendered_body_never_dispatches_send(mock_app, config, session):
    skill = fixture_skill(mock_app,config,session,rendered='different')
    with patch('wechat_auto.actions.basic.time.sleep'), pytest.raises(RuntimeError,match='exactly observed'):
        skill.send_current_verified_text('test',confirm=True)
    assert skill.keyboard_only.click_window_fraction.call_count == 1


def test_same_text_preview_in_another_chat_does_not_hide_new_outgoing_message(mock_app, config, session):
    skill = fixture_skill(mock_app,config,session)
    observations = list(skill.vision.observe_page.side_effect)
    observations[0]['boxes'].append({'text':'test','x':120,'y':200,'w':150,'h':25,'score':.99})
    skill.vision.observe_page.side_effect = observations
    with patch('wechat_auto.actions.basic.time.sleep'):
        assert skill.send_current_verified_text('test',confirm=True)['sent']


def test_send_text_rejects_changed_stable_recipient_without_input(mock_app, config, session):
    skill = fixture_skill(mock_app, config, session)
    with pytest.raises(PermissionError, match='Stable contact'):
        skill.send_text('wxid_test_other', 'test', confirm=True)
    skill.keyboard_only._type_text.assert_not_called()
    skill.keyboard_only._enter.assert_not_called()


def test_send_text_uses_verified_single_dispatch_path(mock_app, config, session):
    skill = fixture_skill(mock_app, config, session)
    with patch('wechat_auto.actions.basic.time.sleep'):
        result = skill.send_text('filehelper', 'test', confirm=True)
    assert result['success'] and result['sent']
    skill.keyboard_only._enter.assert_not_called()
    assert skill._recipient_lease is None


def test_post_dispatch_observation_failure_preserves_unknown_and_consumes_lease(mock_app, config, session):
    skill = fixture_skill(mock_app, config, session)
    observations = list(skill.vision.observe_page.side_effect)
    skill.vision.observe_page.side_effect = observations[:2] + [RuntimeError('private OCR detail')]
    with patch('wechat_auto.actions.basic.time.sleep'):
        result = skill.send_current_verified_text('test', confirm=True)
    assert result['dispatched'] is True and result['sent'] is False
    assert result['verified_by'] == 'result_unknown'
    assert result['error_type'] == 'RuntimeError'
    assert 'private' not in repr(result)
    assert skill._recipient_lease is None
    assert skill.keyboard_only.click_window_fraction.call_count == 2


@pytest.mark.parametrize('change', ['recipient', 'size', 'overlay', 'composer', 'failure'])
def test_changed_post_dispatch_page_cannot_prove_success(mock_app, config, session, change):
    skill = fixture_skill(mock_app, config, session)
    observations = list(skill.vision.observe_page.side_effect)
    after = observations[-1]
    if change == 'recipient':
        after['state']['regions']['conversation_header'] = [{'text': 'Other'}]
    elif change == 'size':
        after['state']['size'] = [1200, 800]
    elif change == 'overlay':
        after['state']['overlays'] = ['unknown']
    elif change == 'composer':
        after['state']['composer']['state'] = 'absent'
    else:
        after['boxes'].append({'text': '发送失败', 'x': 400, 'y': 300, 'w': 80, 'h': 20})
    skill.vision.observe_page.side_effect = observations
    with patch('wechat_auto.actions.basic.time.sleep'):
        result = skill.send_current_verified_text('test', confirm=True)
    assert result['dispatched'] and not result['success'] and not result['sent']
    assert skill._recipient_lease is None
    with pytest.raises(PermissionError):
        skill.send_current_verified_text('test', confirm=True)
    assert skill.keyboard_only.click_window_fraction.call_count == 2

@pytest.mark.parametrize('action', ['prepare_text', 'send_current_verified_text', 'prepare_file', 'prepare_image'])
@pytest.mark.parametrize('pixels', ['enabled', 'missing'])
def test_empty_ocr_with_enabled_send_or_missing_pixels_preserves_draft(mock_app, config, session, tmp_path, action, pixels):
    skill = fixture_skill(mock_app, config, session)
    if pixels == 'enabled':
        ImageDraw.Draw(skill.vision._last_observed_image).rectangle((895, 735, 955, 775), fill=(7, 193, 96))
    else:
        skill.vision._last_observed_image = None
    source = tmp_path / 'synthetic.bin'
    source.write_bytes(b'abc')
    with (patch('wechat_auto.actions.basic.ClipboardHelper.set_files') as files,
          patch('wechat_auto.actions.basic.ClipboardHelper.set_image') as image,
          pytest.raises(RuntimeError, match='Empty OCR')):
        if action == 'send_current_verified_text':
            skill.send_current_verified_text('test', confirm=True)
        else:
            getattr(skill, action)('filehelper', str(source) if action.startswith('prepare_f') or action == 'prepare_image' else 'test')
    files.assert_not_called()
    image.assert_not_called()
    skill.keyboard_only.click_window_fraction.assert_not_called()
    skill.keyboard_only._type_text.assert_not_called()
    skill.keyboard_only._paste.assert_not_called()
    skill.keyboard_only._enter.assert_not_called()


def test_owned_draft_retains_original_spaces_for_bounded_backspace(mock_app, config, session):
    skill = fixture_skill(mock_app, config, session, rendered='a b')
    observations = list(skill.vision.observe_page.side_effect)
    skill.vision.observe_page.side_effect = [observations[0], observations[1],
                                            observations[1], observations[1], observations[2]]
    with patch('wechat_auto.actions.basic.time.sleep'):
        assert skill.prepare_text('filehelper', 'a b')['prepared']
        assert skill._prepared_text_lease['original_text'] == 'a b'
        assert skill.cancel_prepared_text('filehelper')['cancelled']
    skill.keyboard_only.erase_backward.assert_called_once_with(3)
    skill.keyboard_only._select_all_clear.assert_not_called()
