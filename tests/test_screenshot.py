from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from wechat_auto.utils.screenshot import ScreenshotHelper


@pytest.fixture
def gdi():
    with (patch('win32gui.GetWindowRect', return_value=(0, 0, 2, 2)) as rect,
          patch('win32gui.GetWindowDC', return_value=10) as source,
          patch('win32gui.ReleaseDC') as release,
          patch('win32gui.DeleteObject') as delete,
          patch('win32ui.CreateDCFromHandle') as window,
          patch('win32ui.CreateBitmap') as bitmap,
          patch('ctypes.windll.user32.PrintWindow', return_value=1) as capture):
        memory = window.return_value.CreateCompatibleDC.return_value
        bitmap.return_value.GetInfo.return_value = {'bmWidth': 2, 'bmHeight': 2}
        bitmap.return_value.GetBitmapBits.return_value = b'\x01\x02\x03\x00' * 4
        yield {'rect': rect, 'source': source, 'release': release, 'delete': delete,
               'window': window, 'bitmap': bitmap, 'memory': memory, 'capture': capture}


def test_capture_copies_pixels_and_releases_all_gdi_resources(gdi):
    image = ScreenshotHelper().capture_window(1)
    assert image.size == (2, 2) and image.getpixel((0, 0)) == (3, 2, 1)
    gdi['delete'].assert_called_once()
    gdi['memory'].DeleteDC.assert_called_once()
    gdi['window'].return_value.DeleteDC.assert_called_once()
    gdi['release'].assert_called_once_with(1, 10)


@pytest.mark.parametrize('boundary', ['delete_bitmap', 'delete_memory', 'delete_window', 'release'])
def test_cleanup_failure_does_not_leak_other_handles_or_replace_image(gdi, boundary):
    target = {'delete_bitmap': gdi['delete'], 'delete_memory': gdi['memory'].DeleteDC,
              'delete_window': gdi['window'].return_value.DeleteDC, 'release': gdi['release']}[boundary]
    target.side_effect = RuntimeError('synthetic cleanup failure')
    assert ScreenshotHelper().capture_window(1) is not None
    gdi['delete'].assert_called_once()
    gdi['memory'].DeleteDC.assert_called_once()
    gdi['window'].return_value.DeleteDC.assert_called_once()
    gdi['release'].assert_called_once_with(1, 10)


@pytest.mark.parametrize('failure', ['print', 'geometry', 'bitmap_size', 'bits', 'zero_dc'])
def test_invalid_or_changed_capture_never_returns_a_frame(gdi, failure):
    if failure == 'print':
        gdi['capture'].return_value = 0
    elif failure == 'geometry':
        gdi['rect'].side_effect = [(0, 0, 2, 2), (1, 0, 3, 2)]
    elif failure == 'bitmap_size':
        gdi['bitmap'].return_value.GetInfo.return_value = {'bmWidth': 1, 'bmHeight': 2}
    elif failure == 'bits':
        gdi['bitmap'].return_value.GetBitmapBits.side_effect = RuntimeError('synthetic bits failure')
    elif failure == 'zero_dc':
        gdi['source'].return_value = 0
    assert ScreenshotHelper().capture_window(1) is None
    if failure == 'zero_dc':
        gdi['window'].assert_not_called()
    else:
        gdi['release'].assert_called_once_with(1, 10)


@pytest.mark.parametrize('skill,tag', [('..\\..\\escape', 'tag'), ('skill', '../escape'),
                                     ('C:escape', 'tag'), ('skill', 'bad\nname')])
def test_screenshot_labels_cannot_escape_output_directory(tmp_path, skill, tag):
    helper = ScreenshotHelper(str(tmp_path / 'captures'))
    assert helper.save(Image.new('RGB', (2, 2)), skill, tag) is None
    assert not list(tmp_path.rglob('*.png'))


def test_repeated_saves_do_not_overwrite_previous_evidence(tmp_path):
    helper = ScreenshotHelper(str(tmp_path))
    with patch('wechat_auto.utils.screenshot.datetime') as clock:
        clock.now.return_value.strftime.return_value = 'same-timestamp'
        first = helper.save(Image.new('RGB', (2, 2), 'red'), 'test', 'same')
        second = helper.save(Image.new('RGB', (2, 2), 'blue'), 'test', 'same')
    assert first and second and first != second
    with Image.open(first) as image:
        assert image.getpixel((0, 0)) == (255, 0, 0)
    with Image.open(second) as image:
        assert image.getpixel((0, 0)) == (0, 0, 255)

@pytest.mark.parametrize('boundary', ['window_dc', 'memory_dc', 'bitmap', 'compatible', 'select'])
def test_partial_gdi_allocation_still_releases_source(gdi, boundary):
    target = {'window_dc': gdi['window'], 'memory_dc': gdi['window'].return_value.CreateCompatibleDC,
              'bitmap': gdi['bitmap'], 'compatible': gdi['bitmap'].return_value.CreateCompatibleBitmap,
              'select': gdi['memory'].SelectObject}[boundary]
    target.side_effect = RuntimeError('synthetic allocation failure')
    assert ScreenshotHelper().capture_window(1) is None
    gdi['release'].assert_called_once_with(1, 10)


def test_previous_bitmap_restore_failure_still_releases_all_resources(gdi):
    gdi['memory'].SelectObject.side_effect = [MagicMock(), RuntimeError('synthetic restore failure')]
    assert ScreenshotHelper().capture_window(1) is not None
    assert gdi['memory'].SelectObject.call_count == 2
    gdi['delete'].assert_called_once()
    gdi['memory'].DeleteDC.assert_called_once()
    gdi['release'].assert_called_once_with(1, 10)


@pytest.mark.parametrize('failure', [None, 'foreground', 'geometry', 'hidden', 'minimized', 'size'])
def test_visible_capture_rechecks_foreground_geometry_visibility_and_size(failure):
    with (patch('win32gui.GetForegroundWindow', side_effect=[1, 2 if failure == 'foreground' else 1]),
          patch('win32gui.IsWindowVisible', side_effect=[True, failure != 'hidden']),
          patch('win32gui.IsIconic', side_effect=[False, failure == 'minimized']),
          patch('win32gui.GetAncestor', return_value=1),
          patch('win32gui.GetWindowRect', side_effect=[(0, 0, 2, 2), (0, 0, 3 if failure == 'geometry' else 2, 2)]),
          patch('PIL.ImageGrab.grab', return_value=Image.new('RGB', (3 if failure == 'size' else 2, 2)))):
        image = ScreenshotHelper().capture_visible_window(1)
        assert (image is not None) is (failure is None)


def test_failed_png_save_removes_only_its_partial_file(tmp_path):
    image = MagicMock()
    def failed(stream, **kwargs):
        stream.write(b'partial')
        raise OSError('synthetic PNG failure')
    image.save.side_effect = failed
    helper = ScreenshotHelper(str(tmp_path))
    assert helper.save(image, 'test', 'partial') is None
    assert not list(tmp_path.iterdir())


def test_exclusive_save_collision_preserves_existing_evidence(tmp_path):
    helper = ScreenshotHelper(str(tmp_path))
    with (patch('wechat_auto.utils.screenshot.datetime') as clock,
          patch('wechat_auto.utils.screenshot.uuid4') as identifier):
        clock.now.return_value.strftime.return_value = 'same'
        identifier.return_value.hex = 'same'
        first = helper.save(Image.new('RGB', (2, 2), 'red'), 'test', 'same')
        assert helper.save(Image.new('RGB', (2, 2), 'blue'), 'test', 'same') is None
    with Image.open(first) as image:
        assert image.getpixel((0, 0)) == (255, 0, 0)
