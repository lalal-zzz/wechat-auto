from unittest.mock import MagicMock, patch

import pytest
from PIL import Image, ImageDraw

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.primitives.image_preview import find_image_preview
from wechat_auto.utils.clipboard import ClipboardHelper


def source_image():
    im = Image.new('RGB', (160, 100), '#16324a')
    d = ImageDraw.Draw(im)
    for y in range(3):
        for x in range(5):
            d.rectangle((x*30+5, y*30+5, x*30+28, y*30+28),
                        fill=((x*41+43)%256, (y*83+67)%256, ((x+y)*53+19)%256))
    return im


@pytest.mark.parametrize('case', ['single', 'duplicate', 'missing', 'flat'])
def test_preview_matching_is_only_a_unique_candidate(tmp_path, case):
    source = source_image() if case != 'flat' else Image.new('RGB', (160, 100), 'red')
    path = tmp_path/'test.png'
    source.save(path)
    im = Image.new('RGB', (700, 400), '#1e1e1e')
    if case != 'missing':
        im.paste(source.resize((120, 75)), (150, 200))
    if case == 'duplicate':
        im.paste(source.resize((120, 75)), (350, 200))
    frame = {'x': 100, 'y': 180, 'w': 550, 'h': 200}
    if case == 'single':
        candidate = find_image_preview(im, frame, path)
        assert not candidate['identity_verified']
        assert candidate['box'][:2] == pytest.approx([150, 200], abs=2)
    else:
        with pytest.raises(RuntimeError):
            find_image_preview(im, frame, path)


@pytest.mark.parametrize('case', ['same', 'changed_pixel', 'size', 'copied_file', 'changed_file', 'multiple_files', 'non_image_file'])
def test_native_clipboard_image_requires_exact_pixels(tmp_path, case):
    source = source_image()
    path = tmp_path/'test.png'
    source.save(path)
    copied = source.copy()
    if case == 'changed_pixel':
        copied.putpixel((0, 0), (255, 255, 255))
    elif case == 'size':
        copied = source.resize((80, 50))
    elif case == 'copied_file':
        copied = [str(path)]
    elif case == 'changed_file':
        different = source.copy()
        different.putpixel((0, 0), (255, 255, 255))
        different.save(tmp_path/'different.png')
        copied = [str(tmp_path/'different.png')]
    elif case == 'multiple_files':
        copied = [str(path), str(path)]
    elif case == 'non_image_file':
        (tmp_path/'plain.txt').write_text('not an image')
        copied = [str(tmp_path/'plain.txt')]
    with patch('PIL.ImageGrab.grabclipboard', return_value=copied):
        assert ClipboardHelper.copied_image_matches(str(path)) is (case in {'same', 'copied_file'})


@pytest.mark.parametrize('failure', ['approval', 'recipient', 'preview'])
def test_image_discard_refuses_before_any_menu(mock_app, config, session, tmp_path, failure):
    path = tmp_path/'test.png'
    source_image().save(path)
    skill = BasicSkill(mock_app, config, session)
    skill._keyboard_only_auto = MagicMock()
    skill._recipient_lease = None if failure == 'recipient' else {'username': 'filehelper'}
    skill._checked_recipient_composer = MagicMock(side_effect=RuntimeError('No preview'))
    if failure == 'preview':
        result = skill.cancel_verified_image('filehelper', str(path), confirm_discard=True)
        assert not result['success'] and not result['dispatched']
    else:
        with pytest.raises(PermissionError):
            skill.cancel_verified_image('filehelper', str(path), confirm_discard=failure != 'approval')
    skill.keyboard_only.right_click_window_fraction.assert_not_called()


@pytest.mark.parametrize('menu_transition', [False, True])
@pytest.mark.parametrize('case', ['success', 'clipboard_mismatch', 'pixels_changed', 'delete_unknown',
                                  'copy_only', 'copy_clipboard_changed'])
def test_image_discard_only_deletes_after_native_copy_and_fresh_frame(
        mock_app, config, session, tmp_path, case, menu_transition):
    path = tmp_path/'test.png'
    source_image().save(path)
    skill = BasicSkill(mock_app, config, session)
    lease = {'username': 'filehelper'}
    skill._recipient_lease = lease
    frame = {'x': 0, 'y': 0, 'w': 400, 'h': 200}
    preview = {'box': [10, 10, 120, 75], 'window_fraction': [.2, .2]}
    observation = {'_image_preview': preview, '_composer_body_boxes': []}
    skill._checked_recipient_composer = MagicMock(return_value=(observation, '', frame))
    skill._composer_fingerprint = MagicMock(side_effect=(['first', 'changed']
        if case == 'pixels_changed' else None), return_value='digest')
    skill._keyboard_only_auto = MagicMock()
    menu = {'hwnd': 22, 'pid': 1, 'class': 'QtToolSaveBits', 'owner_hwnd': 1,
            'rect': [0, 0, 200, 200], 'client_rect': [0, 0, 200, 200], 'dpi': 144}
    buttons = [{'text': name, 'x': 10, 'y': 10+i*30, 'w': 50, 'h': 20, 'score': .99}
               for i, name in enumerate(['剪切', '复制', '另存为.', '编辑'])]
    first = (lease, mock_app, menu, {'boxes': buttons, 'state': {'size': [200, 200]}})
    selection = [{**button, 'text': name} for button, name in zip(
        buttons, ['剪切', '复制', '粘贴', '删除'], strict=True)]
    second = (lease, mock_app, menu, {'boxes': selection, 'state': {'size': [200, 200]}})
    skill._consume_composer_context_menu = MagicMock(side_effect=[
        first, second if menu_transition else first])
    mock_app.describe_window.return_value = menu
    child = MagicMock()
    if case == 'delete_unknown':
        child.keyboard_only.click_window_fraction.side_effect = [None, RuntimeError('Unknown')]
    with patch('wechat_auto.actions.basic.BasicSkill', return_value=child), \
         patch('wechat_auto.actions.basic.time.sleep'), \
         patch.object(ClipboardHelper, 'set_text'), \
         patch.object(ClipboardHelper, 'copied_image_matches', return_value=case != 'clipboard_mismatch'), \
         patch('win32clipboard.GetClipboardSequenceNumber', side_effect=[
             100, 100, 101, 101, 102 if case == 'copy_clipboard_changed' else 101]):
        if case in {'copy_only', 'copy_clipboard_changed'}:
            result = skill.copy_image_identity('filehelper', str(path))
            assert result['success'] is (case == 'copy_only')
            assert result['sent'] is False
            child.keyboard_only.click_window_fraction.assert_called_once()
            return
        result = skill.cancel_verified_image('filehelper', str(path), confirm_discard=True)
    assert result['cancelled'] is (case == 'success')
    assert result['sent'] is False and result['automatic_retry'] is False
    assert result['dispatched'] is (case in {'success', 'delete_unknown'})
    assert child.keyboard_only.click_window_fraction.call_count == (
        2 if case in {'success', 'delete_unknown'} else 1)


@pytest.mark.parametrize('case', ['unverified', 'verified', 'source_changed',
                                  'recipient_changed', 'copy_exception'])
def test_image_preparation_requires_native_identity_and_unchanged_source_recipient(
        mock_app, config, session, tmp_path, case):
    path = tmp_path/'test.png'
    source_image().save(path)
    skill = BasicSkill(mock_app, config, session)
    skill._recipient_lease = {'username': 'filehelper'}
    skill._keyboard_only_auto = MagicMock()
    skill._prepare_clipboard_payload = MagicMock(return_value={
        'prepared': False, 'input_dispatched': True, 'sent': False,
        'verified_by': 'attachment_preview_not_verified'})
    def copied(*args):
        if case == 'source_changed':
            Image.new('RGB', (160, 100), 'red').save(path)
        elif case == 'recipient_changed':
            skill._recipient_lease = dict(skill._recipient_lease)
        elif case == 'copy_exception':
            raise RuntimeError('Copy failed')
        return {'success': case != 'unverified', 'identity_verified': case != 'unverified'}
    skill.copy_image_identity = MagicMock(side_effect=copied)
    result = skill.prepare_image('filehelper', str(path))
    assert result['prepared'] is (case == 'verified')
    assert result['success'] is (case == 'verified')
    assert result['sent'] is False and result['automatic_retry'] is False
    skill.keyboard_only._enter.assert_not_called()
