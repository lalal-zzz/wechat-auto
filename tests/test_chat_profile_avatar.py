import pytest
from PIL import Image, ImageDraw

from wechat_auto.primitives.page_controls import (
    NavigationControlError,
    find_private_chat_profile_avatar,
)


def fixture():
    image = Image.new('RGB', (1000, 700), (30, 30, 30))
    ImageDraw.Draw(image).rounded_rectangle((740, 110, 779, 149), radius=4, fill=(220, 220, 220))
    boxes = [{'text': '测试联系人', 'x': 730, 'y': 155, 'w': 60, 'h': 18}]
    boxes += [{'text': text, 'x': 730, 'y': y, 'w': 100, 'h': 18}
              for text, y in [('查找聊天内容', 220), ('消息免打扰', 260), ('置顶聊天', 300)]]
    state = {'geometry': {'right_panel_candidate': {'x': 700}},
             'composer': {'state': 'present'}}
    return image, boxes, state


def test_exact_member_name_and_current_square_supply_avatar_point():
    image, boxes, state = fixture()
    result = find_private_chat_profile_avatar(image, boxes, state, '测试联系人')
    assert result['window_fraction'] == pytest.approx((.7595, 129.5 / 700), abs=.002)


@pytest.mark.parametrize('failure', ['wrong_name', 'missing_anchor', 'missing_composer', 'duplicate_name'])
def test_incomplete_or_ambiguous_details_do_not_supply_point(failure):
    image, boxes, state = fixture()
    if failure == 'wrong_name':
        boxes[0]['text'] = '其他联系人'
    elif failure == 'missing_anchor':
        boxes.pop()
    elif failure == 'missing_composer':
        state['composer']['state'] = 'absent'
    else:
        boxes.append(dict(boxes[0]))
    with pytest.raises(NavigationControlError):
        find_private_chat_profile_avatar(image, boxes, state, '测试联系人')
