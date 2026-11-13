import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.utils.clipboard import ClipboardHelper


def setup_cancel(mock_app, config, session, tmp_path):
    mock_app.handle = 10
    main = {'hwnd': 10, 'pid': 2, 'rect': [0, 0, 1000, 800],
            'client_rect': [0, 0, 1000, 800], 'dpi': 96}
    menu = {**main, 'hwnd': 20, 'owner_hwnd': 10, 'class': 'QtToolSaveBits'}
    mock_app.describe_window.side_effect = lambda hwnd: main if hwnd == 10 else menu
    target = MagicMock()
    target.handle = 20
    payload = tmp_path / 'wa-test.txt'
    payload.write_bytes(b'abc')
    card = {'box': [300, 400, 300, 80]}
    skill = BasicSkill(mock_app, config, session)
    lease = {'username': 'filehelper', 'metadata': main}
    identity = {'recipient': lease, 'path': str(payload.resolve()), 'sha256': ClipboardHelper.file_sha256(payload),
                'size': 3, 'card': card, 'card_digest': 'exact-card-pixels', 'created_at': time.monotonic()}
    skill._recipient_lease = lease
    skill._attachment_identity_lease = identity
    skill._current_attachment_card = MagicMock(return_value=(card, lease))
    labels = [{'text': text, 'x': 20, 'y': 20+i*40, 'w': 40, 'h': 20, 'score': .99}
              for i, text in enumerate(('剪切', '复制', '粘贴', '删除'))]
    observation = {'state': {'size': [1000, 800]}, 'boxes': labels}
    skill.open_attachment_context_menu = MagicMock(return_value={'menu_origin_id': 'own-menu'})
    skill._consume_composer_context_menu = MagicMock(return_value=(lease, target, menu, observation))
    card_text = {'text': 'wa-test.txt', 'x': 310, 'y': 420, 'w': 100, 'h': 20}
    before = {'_composer_body_boxes': [card_text]}
    after = {'_composer_body_boxes': []}
    frame = {'x': 300, 'y': 400, 'w': 650, 'h': 350}
    skill._checked_recipient_composer = MagicMock(side_effect=[(before, '', frame), (before, '', frame), (after, '', frame)])
    skill._composer_fingerprint = MagicMock(return_value='exact-card-pixels')
    skill._vision_auto = MagicMock()
    return skill, payload, identity, observation


@pytest.mark.parametrize('failure', [None, 'no_confirmation', 'no_identity', 'expired', 'recipient',
                                    'source', 'card', 'pixels', 'other_text', 'duplicate', 'low_score', 'existing_other_text', 'replaced_since_copy', 'legacy_identity'])
def test_cancel_is_bound_to_verified_card_and_never_clears_editor(mock_app, config, session, tmp_path, failure):
    skill, payload, identity, observation = setup_cancel(mock_app, config, session, tmp_path)
    if failure == 'no_identity':
        skill._attachment_identity_lease = None
    elif failure == 'expired':
        identity['created_at'] = 0
    elif failure == 'recipient':
        skill._recipient_lease = dict(skill._recipient_lease)
    elif failure == 'source':
        payload.write_bytes(b'xyz')
    elif failure == 'card':
        skill._current_attachment_card.return_value = ({'box': [301, 400, 300, 80]}, skill._recipient_lease)
    elif failure == 'pixels':
        skill._composer_fingerprint.side_effect = ['exact-card-pixels', 'changed']
    elif failure == 'replaced_since_copy':
        identity['card_digest'] = 'previous-card'
    elif failure == 'legacy_identity':
        identity.pop('card_digest')
    elif failure == 'other_text':
        readings = list(skill._checked_recipient_composer.side_effect)
        readings[1] = ({'_composer_body_boxes': [{'text': 'changed', 'x': 310, 'y': 510, 'w': 100, 'h': 20}]}, '', readings[0][2])
        skill._checked_recipient_composer.side_effect = readings
    elif failure == 'existing_other_text':
        readings = list(skill._checked_recipient_composer.side_effect)
        readings[0][0]['_composer_body_boxes'].append({'text': 'keep', 'x': 310, 'y': 510, 'w': 50, 'h': 20})
        skill._checked_recipient_composer.side_effect = readings
    elif failure == 'duplicate':
        observation['boxes'].append(dict(observation['boxes'][-1]))
    elif failure == 'low_score':
        observation['boxes'][-1]['score'] = .2
    driver = MagicMock()
    with (patch.object(BasicSkill, 'keyboard_only', new_callable=PropertyMock, return_value=driver),
          patch('wechat_auto.primitives.attachment_observer.has_card_sized_rectangle', return_value=False),
          patch('wechat_auto.actions.basic.time.sleep')):
        if failure:
            with pytest.raises((RuntimeError, PermissionError)):
                skill.cancel_verified_attachment('filehelper', str(payload), confirm_discard=failure != 'no_confirmation')
            driver.click_window_fraction.assert_not_called()
        else:
            result = skill.cancel_verified_attachment('filehelper', str(payload), confirm_discard=True)
            assert result['cancelled'] and result['success'] and not result['sent']
            driver.click_window_fraction.assert_called_once_with(.04, .1875)
            assert payload.read_bytes() == b'abc'
            assert skill._attachment_identity_lease is None
            with pytest.raises(PermissionError):
                skill.cancel_verified_attachment('filehelper', str(payload), confirm_discard=True)
        driver._select_all_clear.assert_not_called()
        driver._enter.assert_not_called()
        driver._paste.assert_not_called()


@pytest.mark.parametrize('failure', ['remaining_card', 'other_text_after', 'source_after', 'dispatch_error', 'read_error'])
def test_uncertain_cancel_is_not_retried(mock_app, config, session, tmp_path, failure):
    skill, payload, _, _ = setup_cancel(mock_app, config, session, tmp_path)
    readings = list(skill._checked_recipient_composer.side_effect)
    if failure == 'other_text_after':
        readings[-1] = ({'_composer_body_boxes': [{'text': 'unexpected', 'x': 310, 'y': 510, 'w': 100, 'h': 20}]}, '', readings[-1][2])
    elif failure == 'read_error':
        readings[-1] = RuntimeError('synthetic observer failure')
    skill._checked_recipient_composer.side_effect = readings
    driver = MagicMock()
    if failure == 'dispatch_error':
        driver.click_window_fraction.side_effect = RuntimeError('synthetic uncertain dispatch')
    elif failure == 'source_after':
        driver.click_window_fraction.side_effect = lambda *args: payload.write_bytes(b'xyz')
    with (patch.object(BasicSkill, 'keyboard_only', new_callable=PropertyMock, return_value=driver),
          patch('wechat_auto.primitives.attachment_observer.has_card_sized_rectangle', return_value=failure == 'remaining_card'),
          patch('wechat_auto.actions.basic.time.sleep')):
        result = skill.cancel_verified_attachment('filehelper', str(payload), confirm_discard=True)
        assert not result['cancelled'] and result['dispatched'] and not result['automatic_retry']
        with pytest.raises(PermissionError):
            skill.cancel_verified_attachment('filehelper', str(payload), confirm_discard=True)
        driver.click_window_fraction.assert_called_once()
