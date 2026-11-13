"""Native text copying must prove the complete literal body without deleting."""
import hashlib
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from PIL import Image

from wechat_auto.actions.basic import BasicSkill


@pytest.mark.parametrize('body', ['matched', 'changed', ''])
def test_open_text_menu_requires_exact_body_and_current_box(mock_app, config, session, body):
    skill = BasicSkill(mock_app, config, session)
    skill._recipient_lease = {'username': 'filehelper'}
    skill._keyboard_only_auto = MagicMock()
    skill._checked_recipient_composer = MagicMock(return_value=(
        {'state': {'size': [1000, 800]}, '_composer_body_boxes': [
            {'x': 350, 'y': 650, 'w': 100, 'h': 20}]}, body,
        {'x': 300, 'y': 600, 'w': 680, 'h': 180}))
    with patch('wechat_auto.actions.basic.time.sleep'):
        if body == 'matched':
            assert skill.open_composer_context_menu('filehelper', expected_text='matched')['sent'] is False
            skill.keyboard_only.right_click_window_fraction.assert_called_once_with(.4, .825)
        else:
            with pytest.raises(RuntimeError, match='differs'):
                skill.open_composer_context_menu('filehelper', expected_text='matched')
            skill.keyboard_only.right_click_window_fraction.assert_not_called()


@pytest.mark.parametrize('failure', [None, 'wrong_recipient', 'body', 'card', 'no_image',
                                   'duplicate', 'low_score', 'missing_digest', 'pixels',
                                   'metadata', 'clipboard_race', 'literal_mismatch',
                                   'no_copy', 'late_clipboard_change', 'composer_changed'])
def test_native_text_copy_proves_literal_body_and_never_deletes(mock_app, config, session, failure):
    skill = BasicSkill(mock_app, config, session)
    lease = {'username': 'filehelper'}
    skill._recipient_lease = lease
    skill._vision_auto = MagicMock()
    skill.vision._last_observed_image = None if failure == 'no_image' else Image.new('RGB', (1000, 800))
    frame = {'x': 300, 'y': 600, 'w': 680, 'h': 180}
    skill._checked_recipient_composer = MagicMock(return_value=(
        {'state': {'size': [1000, 800]}, '_composer_body_boxes': [{'x': 330, 'y': 630, 'w': 200, 'h': 20}]}, 'changed' if failure == 'body' else 'literaltext', frame))
    if failure == 'composer_changed':
        skill._checked_recipient_composer.side_effect = [({'state': {'size': [1000, 800]}, '_composer_body_boxes': [{'x': 330, 'y': 630, 'w': 200, 'h': 20}]}, 'literaltext', frame),
                                                       ({}, 'literaltext', {**frame, 'x': 301})]
    skill.open_composer_context_menu = MagicMock()
    menu = {'hwnd': 20, 'rect': [10, 10, 210, 110]}
    mock_app.describe_window.return_value = {**menu, 'hwnd': 21} if failure == 'metadata' else menu
    image = Image.new('RGB', (200, 100))
    observations = []
    for label in ('复制',):
        box = {'text': label, 'score': .2 if failure == 'low_score' else .99,
               'x': 20, 'y': 20, 'w': 40, 'h': 20}
        observations.append({'state': {'size': [200, 100]},
                             'boxes': [box, box] if failure == 'duplicate' else [box],
                             '_menu_frame_sha256': None if failure == 'missing_digest' else hashlib.sha256(image.tobytes()).hexdigest()})
    skill._consume_composer_context_menu = MagicMock(side_effect=[
        (lease, mock_app, menu, o) for o in observations])
    driver = MagicMock()
    sequences = [1, 1, 2, 2]
    if failure == 'clipboard_race':
        sequences = [1, 2]
    elif failure == 'no_copy':
        sequences = [1, 1, 1, 1]
    elif failure == 'late_clipboard_change':
        sequences = [1, 1, 2, 3]
    with (patch.object(BasicSkill, 'keyboard_only', new_callable=PropertyMock, return_value=driver),
          patch('wechat_auto.actions.basic.time.sleep'),
          patch('wechat_auto.primitives.attachment_observer.has_card_sized_rectangle', return_value=failure == 'card'),
          patch('wechat_auto.utils.clipboard.ClipboardHelper.set_text'),
          patch('wechat_auto.utils.clipboard.ClipboardHelper.get_text', return_value='different' if failure == 'literal_mismatch' else 'literal text'),
          patch('win32clipboard.GetClipboardSequenceNumber', side_effect=sequences),
          patch('wechat_auto.utils.screenshot.ScreenshotHelper.capture_window', return_value=Image.new('RGB', (200, 100), 'white') if failure == 'pixels' else image)):
        if failure in [None, 'literal_mismatch', 'no_copy', 'late_clipboard_change']:
            result = skill.copy_text_draft_identity('filehelper', 'literal text')
            assert result['success'] is (failure is None)
            assert result['identity_verified'] is (failure is None)
            assert result['sent'] is False and result['deletion_dispatched'] is False
            assert driver.click_window_fraction.call_count == 1
        else:
            with pytest.raises((RuntimeError, PermissionError)):
                skill.copy_text_draft_identity('other' if failure == 'wrong_recipient' else 'filehelper', 'literal text')
            driver.click_window_fraction.assert_not_called()
    driver.erase_backward.assert_not_called()
    driver._select_all_clear.assert_not_called()
    driver._type_text.assert_not_called()
    driver._enter.assert_not_called()
