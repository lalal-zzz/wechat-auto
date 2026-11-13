from copy import deepcopy
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from PIL import Image

from wechat_auto.config import WeChatConfig
from wechat_auto.primitives.vision import VisionAutomation


def engine():
    mock = MagicMock()
    mock.name = 'fake'
    mock.return_value = [([[1, 2], [10, 2], [10, 8], [1, 8]], 'public', .99)], None
    return mock


def metadata():
    return {'hwnd': 1, 'pid': 2, 'class': 'Qt', 'owner_hwnd': 0,
            'rect': [0, 0, 100, 40], 'client_rect': [0, 0, 100, 40], 'dpi': 144}


def test_exact_frame_reuses_only_ocr_and_returns_independent_nested_boxes():
    ocr = engine()
    vision = VisionAutomation(None, WeChatConfig())
    image = Image.new('RGB', (100, 40))
    with patch.object(VisionAutomation, '_ocr', new_callable=PropertyMock, return_value=ocr):
        first = vision.recognize_image(image)
        expected = deepcopy(first)
        first[0]['text'] = 'changed'
        first[0]['window_fraction'][0] = 999
        second = vision.recognize_image(image.copy())
        assert second == expected
        second.clear()
        assert vision.recognize_image(image) == expected
    assert ocr.call_count == 1 and vision._ocr_cache_hits == 2


@pytest.mark.parametrize('change', ['pixel', 'size', 'region', 'window_size', 'upscale', 'engine'])
def test_any_image_or_coordinate_or_engine_input_change_reruns_ocr(change):
    ocr, other = engine(), engine()
    vision = VisionAutomation(None, WeChatConfig())
    image = Image.new('RGB', (100, 40))
    kwargs = {}
    with patch.object(VisionAutomation, '_ocr', new_callable=PropertyMock, return_value=ocr) as prop:
        vision.recognize_image(image)
        if change == 'pixel':
            image.putpixel((99, 39), (0, 0, 1))
        elif change == 'size':
            image = Image.new('RGB', (40, 100))
        elif change == 'region':
            kwargs['region'] = (10, 20, 100, 40)
        elif change == 'window_size':
            kwargs['window_size'] = (200, 80)
        elif change == 'upscale':
            kwargs['upscale'] = 2
        else:
            prop.return_value = other
        vision.recognize_image(image, **kwargs)
    assert ocr.call_count + other.call_count == 2


@pytest.mark.parametrize('field,value', [
    ('hwnd', 3), ('pid', 4), ('class', 'OtherQt'), ('owner_hwnd', 7),
    ('rect', [1, 0, 101, 40]), ('client_rect', [1, 0, 101, 40]), ('dpi', 96),
])
def test_live_window_identity_or_geometry_change_invalidates_cache(field, value):
    app = MagicMock()
    app.handle = 1
    meta = metadata()
    app.describe_window.side_effect = lambda hwnd: dict(meta)
    vision = VisionAutomation(app, WeChatConfig())
    ocr = engine()
    with patch.object(VisionAutomation, '_ocr', new_callable=PropertyMock, return_value=ocr):
        vision.recognize_image(Image.new('RGB', (100, 40)))
        meta[field] = value
        vision.recognize_image(Image.new('RGB', (100, 40)))
    assert ocr.call_count == 2


@pytest.mark.parametrize('failure', ['exception', 'empty', 'metadata_unavailable'])
def test_failed_empty_or_unbound_results_are_not_cached(failure):
    app = None
    ocr = engine()
    if failure == 'exception':
        ocr.side_effect = RuntimeError('OCR unavailable')
    elif failure == 'empty':
        ocr.return_value = [], None
    else:
        app = MagicMock()
        app.describe_window.side_effect = RuntimeError('Window unavailable')
    vision = VisionAutomation(app, WeChatConfig())
    with patch.object(VisionAutomation, '_ocr', new_callable=PropertyMock, return_value=ocr):
        for _ in range(2):
            if failure == 'exception':
                with pytest.raises(RuntimeError):
                    vision.recognize_image(Image.new('RGB', (100, 40)))
            else:
                vision.recognize_image(Image.new('RGB', (100, 40)))
    assert ocr.call_count == 2


def test_window_change_during_inference_does_not_publish_cache_entry():
    app = MagicMock()
    app.handle = 1
    meta = metadata()
    app.describe_window.side_effect = lambda hwnd: dict(meta)
    ocr = engine()
    result = ocr.return_value
    def infer(image):
        meta['dpi'] += 1
        return result
    ocr.side_effect = infer
    vision = VisionAutomation(app, WeChatConfig())
    with patch.object(VisionAutomation, '_ocr', new_callable=PropertyMock, return_value=ocr):
        vision.recognize_image(Image.new('RGB', (100, 40)))
        vision.recognize_image(Image.new('RGB', (100, 40)))
    assert ocr.call_count == 2 and vision._ocr_frame_cache is None


def test_cache_retains_only_the_last_frame():
    vision = VisionAutomation(None, WeChatConfig())
    ocr = engine()
    first = Image.new('RGB', (100, 40))
    second = first.copy()
    second.putpixel((0, 0), (1, 0, 0))
    with patch.object(VisionAutomation, '_ocr', new_callable=PropertyMock, return_value=ocr):
        for image in (first, second, first):
            vision.recognize_image(image)
    assert ocr.call_count == 3


def test_geometry_change_during_cache_lookup_forces_new_inference():
    app = MagicMock()
    app.handle = 1
    old = metadata()
    changed = {**old, 'dpi': 96}
    app.describe_window.side_effect = [old, old, old, changed, changed]
    vision = VisionAutomation(app, WeChatConfig())
    ocr = engine()
    with patch.object(VisionAutomation, '_ocr', new_callable=PropertyMock, return_value=ocr):
        vision.recognize_image(Image.new('RGB', (100, 40)))
        vision.recognize_image(Image.new('RGB', (100, 40)))
    assert ocr.call_count == 2 and vision._ocr_frame_cache is None


def test_cached_ocr_still_captures_and_recomputes_current_geometry_and_page():
    from wechat_auto.primitives.page_geometry import observe_geometry
    from wechat_auto.primitives.page_state import classify_page

    vision = VisionAutomation(None, WeChatConfig())
    first = Image.new('RGB', (100, 40))
    current = first.copy()
    vision.capture = MagicMock(side_effect=[first, current])
    ocr = engine()
    with patch.object(VisionAutomation, '_ocr', new_callable=PropertyMock, return_value=ocr), \
         patch('wechat_auto.primitives.page_geometry.observe_geometry', wraps=observe_geometry) as geometry, \
         patch('wechat_auto.primitives.page_state.classify_page', wraps=classify_page) as classify:
        assert vision.observe_page()['ok']
        assert vision.observe_page()['ok']
    assert vision.capture.call_count == classify.call_count == 2
    assert geometry.call_count >= 2
    assert any(call.args[0] is current for call in geometry.call_args_list)
    assert vision._last_observed_image is current
    assert ocr.call_count == 1


@pytest.mark.parametrize('mode', ['P', 'RGBA'])
def test_cache_preserves_resize_then_rgb_preprocessing(mode):
    import numpy as np

    if mode == 'P':
        image = Image.new('P', (2, 2))
        image.putpalette([255, 0, 0, 0, 0, 255])
        image.putdata([0, 1, 1, 0])
    else:
        image = Image.new('RGBA', (2, 2))
        image.putdata([(255, 0, 0, 255), (0, 0, 255, 40),
                       (0, 0, 255, 40), (255, 0, 0, 255)])
    vision = VisionAutomation(None, WeChatConfig())
    ocr = engine()
    expected = np.asarray(image.resize((4, 4)).convert('RGB'))
    converted = image.convert('RGB')
    other = np.asarray(converted.resize((4, 4)).convert('RGB'))
    with patch.object(VisionAutomation, '_ocr', new_callable=PropertyMock, return_value=ocr):
        vision.recognize_image(image, upscale=2)
        assert np.array_equal(ocr.call_args.args[0], expected)
        vision.recognize_image(converted, upscale=2)
    assert ocr.call_count == (1 if np.array_equal(expected, other) else 2)
