import io
from unittest.mock import MagicMock, patch

import pytest
import win32clipboard
from PIL import Image

from wechat_auto.utils.clipboard import ClipboardHelper


@pytest.fixture
def clipboard(monkeypatch):
    methods = {}
    for name in ('OpenClipboard', 'CloseClipboard', 'IsClipboardFormatAvailable', 'GetClipboardData'):
        methods[name] = MagicMock()
        monkeypatch.setattr(win32clipboard, name, methods[name])
    methods['IsClipboardFormatAvailable'].return_value = True
    return methods


@pytest.mark.parametrize('change', ['none', 'other_file', 'extra_file', 'missing_format'])
def test_file_payload_identity_is_checked_and_clipboard_closed(tmp_path, clipboard, change):
    path = tmp_path / 'synthetic.txt'
    path.write_text('test')
    actual = (str(path),)
    if change == 'other_file':
        actual = (str(tmp_path / 'other.txt'),)
    elif change == 'extra_file':
        actual += (str(tmp_path / 'extra.txt'),)
    elif change == 'missing_format':
        clipboard['IsClipboardFormatAvailable'].return_value = False
    clipboard['GetClipboardData'].return_value = actual
    assert ClipboardHelper.files_match([str(path)]) is (change == 'none')
    clipboard['CloseClipboard'].assert_called_once()


@pytest.mark.parametrize('change', ['none', 'different_pixels', 'missing_format'])
def test_image_payload_identity_is_checked(tmp_path, clipboard, change):
    path = tmp_path / 'synthetic.png'
    image = Image.new('RGB', (4, 4), 'red')
    image.save(path)
    with io.BytesIO() as output:
        image.save(output, 'BMP')
        payload = output.getvalue()[14:]
    if change == 'different_pixels':
        payload = payload[:-1] + bytes([payload[-1] ^ 1])
    elif change == 'missing_format':
        clipboard['IsClipboardFormatAvailable'].return_value = False
    clipboard['GetClipboardData'].return_value = payload
    assert ClipboardHelper.image_matches(str(path)) is (change == 'none')
    clipboard['CloseClipboard'].assert_called_once()


def test_read_error_releases_clipboard_without_logging_content(tmp_path, clipboard):
    path = tmp_path / 'synthetic.txt'
    path.write_text('test')
    clipboard['GetClipboardData'].side_effect = OSError('read failed')
    with pytest.raises(OSError):
        ClipboardHelper.files_match([str(path)])
    clipboard['CloseClipboard'].assert_called_once()


def test_clipboard_debug_log_never_contains_text(caplog):
    text = 'synthetic-private-body-never-log'
    with patch('wechat_auto.utils.clipboard.pyperclip.copy') as copy, caplog.at_level('DEBUG'):
        ClipboardHelper.set_text(text)
    copy.assert_called_once_with(text)
    assert text not in caplog.text
    assert 'Clipboard text set' in caplog.text


@pytest.mark.parametrize('change', ['none', 'cached_path', 'name', 'size', 'bytes', 'multiple', 'missing'])
def test_copied_file_requires_full_name_size_and_sha256(tmp_path, clipboard, change):
    path = tmp_path / 'wa-test.txt'
    path.write_bytes(b'hello')
    expected = ClipboardHelper.file_sha256(path)
    actual = path
    if change == 'cached_path':
        cache = tmp_path / 'cache'
        cache.mkdir()
        actual = cache / path.name
        actual.write_bytes(b'hello')
    elif change == 'name':
        actual = tmp_path / 'other.txt'
        actual.write_bytes(b'hello')
    elif change == 'size':
        actual.write_bytes(b'longer')
    elif change == 'bytes':
        actual.write_bytes(b'other')
    elif change == 'missing':
        clipboard['IsClipboardFormatAvailable'].return_value = False
    clipboard['GetClipboardData'].return_value = (str(actual), str(actual)) if change == 'multiple' else (str(actual),)
    assert ClipboardHelper.copied_file_matches('wa-test.txt', 5, expected) is (change in {'none', 'cached_path'})
    clipboard['CloseClipboard'].assert_called_once()
