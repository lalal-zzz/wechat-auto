import time
from unittest.mock import MagicMock

import pytest

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.utils.clipboard import ClipboardHelper


@pytest.mark.parametrize('failure', [None, 'copy_false', 'missing_lease', 'recipient', 'path', 'size',
                                    'hash', 'pixels', 'expired', 'future', 'source_during_paste',
                                    'source_during_copy', 'copy_error'])
def test_file_preparation_requires_original_payload_and_fresh_card(mock_app, config, session, tmp_path, failure):
    skill = BasicSkill(mock_app, config, session)
    source = tmp_path / 'synthetic.txt'
    source.write_bytes(b'abc')
    recipient = {'username': 'filehelper'}
    skill._recipient_lease = recipient
    identity = {'recipient': recipient, 'path': str(source.resolve()), 'size': 3,
                'sha256': ClipboardHelper.file_sha256(source), 'card_digest': 'pixels',
                'created_at': time.monotonic()}
    skill._attachment_identity_lease = {'obsolete': True}

    def pasted(*args, **kwargs):
        assert skill._attachment_identity_lease is None
        if failure == 'source_during_paste':
            source.write_bytes(b'xyz')
        return {'prepared': False, 'sent': False, 'input_dispatched': True,
                'verified_by': 'attachment_preview_not_verified'}

    def copied(*args):
        if failure == 'copy_error':
            raise RuntimeError('synthetic read failure')
        if failure == 'source_during_copy':
            source.write_bytes(b'xyz')
        if failure == 'recipient':
            skill._recipient_lease = dict(recipient)
        key = {'path': 'path', 'size': 'size', 'hash': 'sha256', 'pixels': 'card_digest'}.get(failure)
        if key:
            identity[key] = {'path': str(tmp_path / 'other.txt'), 'size': 4,
                             'sha256': 'other', 'card_digest': ''}[key]
        if failure in {'expired', 'future'}:
            identity['created_at'] = time.monotonic() + (-121 if failure == 'expired' else 121)
        skill._attachment_identity_lease = None if failure == 'missing_lease' else identity
        return {'identity_verified': failure != 'copy_false'}

    skill._prepare_clipboard_payload = MagicMock(side_effect=pasted)
    skill.copy_attachment_identity = MagicMock(side_effect=copied)
    skill._keyboard_only_auto = MagicMock()
    result = skill.prepare_file('filehelper', str(source))
    assert result['prepared'] is (failure is None)
    assert result['success'] is (failure is None)
    assert result['identity_verified'] is (failure is None)
    assert not result['sent'] and not result['automatic_retry']
    assert bool(skill._attachment_identity_lease) is (failure is None)
    if failure == 'source_during_paste':
        skill.copy_attachment_identity.assert_not_called()
    else:
        skill.copy_attachment_identity.assert_called_once_with('filehelper', str(source.resolve()))
    skill.keyboard_only._enter.assert_not_called()


@pytest.mark.parametrize('action', ['send_file', 'send_image'])
def test_prepare_success_cannot_release_unverified_attachment_submission(mock_app, config, session, action):
    skill = BasicSkill(mock_app, config, session)
    skill.prepare_file = MagicMock(return_value={'prepared': True, 'identity_verified': True})
    skill.prepare_image = MagicMock(return_value={'prepared': True})
    skill._keyboard_only_auto = MagicMock()
    with pytest.raises(PermissionError, match='verification required'):
        getattr(skill, action)('filehelper', 'synthetic', confirm=True)
    skill.prepare_file.assert_not_called()
    skill.prepare_image.assert_not_called()
    skill.keyboard_only._enter.assert_not_called()
