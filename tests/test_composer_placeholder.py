import pytest
from PIL import Image, ImageDraw

from wechat_auto.primitives.page_controls import is_empty_composer_placeholder


@pytest.mark.parametrize('light', [False, True])
@pytest.mark.parametrize('state', ['placeholder', 'typed', 'enabled', 'other_text', 'missing_image'])
def test_only_known_dim_guide_with_disabled_send_is_empty(light, state):
    background = 245 if light else 30
    ink = (35 if light else 220) if state == 'typed' else (145 if light else 125)
    image = Image.new('RGB', (400, 200), (background,)*3)
    body = {'text': '按住鼠标 语音输入文字', 'x': 20, 'y': 20, 'w': 210, 'h': 20}
    send = {'x': 320, 'y': 150, 'w': 40, 'h': 20}
    draw = ImageDraw.Draw(image)
    for x in range(22, 225, 10):
        draw.rectangle((x, 24, x+2, 34), fill=(ink,)*3)
    if state == 'enabled':
        draw.rectangle((320, 150, 359, 169), fill=(0, 180, 100))
    else:
        draw.rectangle((325, 155, 332, 161), fill=(145 if light else 100,)*3)
    if state == 'other_text':
        body['text'] = '真实草稿不能忽略'
    assert is_empty_composer_placeholder(None if state == 'missing_image' else image,
                                         [body], send) is (state == 'placeholder')


def test_mixed_real_text_or_out_of_frame_is_not_empty():
    image = Image.new('RGB', (50, 50), (30,)*3)
    boxes = [{'text': '按住鼠标语音输入文字', 'x': -1, 'y': 0, 'w': 20, 'h': 10}]
    assert not is_empty_composer_placeholder(image, boxes, {'x': 20, 'y': 30, 'w': 10, 'h': 10})
    boxes.append({'text': '补充正文', 'x': 0, 'y': 10, 'w': 20, 'h': 10})
    assert not is_empty_composer_placeholder(image, boxes, {})
