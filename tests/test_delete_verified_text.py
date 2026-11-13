from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from wechat_auto.actions.basic import BasicSkill


@pytest.mark.parametrize('failure', ['no_confirmation', 'no_recipient', 'different_body'])
def test_delete_rejects_unapproved_or_changed_draft_before_menu(mock_app, config, session, failure):
    skill = BasicSkill(mock_app, config, session)
    if failure != 'no_recipient':
        skill._recipient_lease = {'username': 'filehelper'}
    skill._checked_recipient_composer = MagicMock(return_value=({}, 'different', {}))
    skill.open_composer_context_menu = MagicMock()
    with pytest.raises((PermissionError, RuntimeError)):
        skill.delete_verified_text('filehelper', 'approved', confirm_discard=failure != 'no_confirmation')
    skill.open_composer_context_menu.assert_not_called()


@pytest.mark.parametrize('remaining', ['', 'approved'])
def test_character_delete_reports_success_only_after_empty_observation(mock_app, config, session, remaining):
    skill = BasicSkill(mock_app, config, session)
    lease = {'username': 'filehelper'}
    skill._recipient_lease = lease
    skill._vision_auto = MagicMock()
    frame = {'x': 300, 'y': 600, 'w': 680, 'h': 180}
    observation = {'state': {'size': [1000, 800]}, '_composer_body_boxes': [
        {'x': 310, 'y': 610, 'w': 120, 'h': 20}]}
    skill._checked_recipient_composer = MagicMock(side_effect=[(observation, 'approved', frame)] * 2 + [({}, remaining, frame)])
    skill.open_composer_context_menu = MagicMock()
    driver = MagicMock()
    with patch('wechat_auto.primitives.attachment_observer.has_card_sized_rectangle', return_value=False), \
         patch.object(BasicSkill, 'keyboard_only', new_callable=PropertyMock, return_value=driver), \
         patch('wechat_auto.actions.basic.time.sleep'):
        result = skill.delete_verified_text('filehelper', 'approved', confirm_discard=True)
    assert result['success'] == (remaining == '')
    assert result['delete_dispatched'] and not result['sent']
    driver.click_window_fraction.assert_called_once()
    driver.erase_backward.assert_called_once_with(8)
    skill.open_composer_context_menu.assert_not_called()
    driver._select_all_clear.assert_not_called()
