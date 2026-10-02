import cv2
import numpy as np
import pytest
from PIL import Image

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.exceptions import ChatNotFoundError
from wechat_auto.primitives.contact_section import observe_contact_section


def sample(direction='expanded', scale=1):
    rgb = np.full((800, 1000, 3), 30, dtype='uint8')
    points = np.array([(110, 355), (120, 365), (130, 355)] if direction == 'expanded' else
                      [(115, 350), (125, 360), (115, 370)], dtype='int32')
    cv2.polylines(rgb, [points], False, (190, 190, 190), 3)
    image = Image.fromarray(rgb).resize((round(1000*scale), round(800*scale)))
    boxes = [{'text': text, 'score': .98, 'x': 150*scale, 'y': y*scale, 'w': 100*scale, 'h': 25*scale}
             for text, y in [('新的朋友', 180), ('公众号、服务号', 240), ('联系人', 350), ('张三', 430)]]
    state = {'page': 'contacts', 'region_bounds': {'conversation_list': [.10, .1, .40, 1.]}}
    return image, boxes, state


@pytest.mark.parametrize('direction', ['expanded', 'collapsed'])
@pytest.mark.parametrize('scale', [1, 1.5])
def test_contacts_scope_excludes_requests_and_survives_scaling(direction, scale):
    image, boxes, state = sample(direction, scale)
    result = observe_contact_section(image, boxes, state)
    assert result['ok'] and result['state'] == direction
    top = result['member_bounds'][1]*image.height
    assert boxes[0]['y'] < top and boxes[-1]['y'] > top


def test_another_category_stops_the_contacts_member_range():
    image, boxes, state = sample()
    boxes.append({'text': '群聊', 'x': 150, 'y': 500, 'w': 100, 'h': 25})
    assert observe_contact_section(image, boxes, state)['member_bounds'][3] == .625


def test_only_new_friends_cannot_be_treated_as_contacts():
    image, boxes, state = sample()
    result = observe_contact_section(image, boxes[:2], state)
    assert not result['ok'] and result['header_candidates'] == 0


def test_profile_does_not_open_same_name_under_new_friends(mock_app, config, session):
    skill = BasicSkill(mock_app, config, session)
    skill.open_navigation = lambda page: None
    skill.ensure_contacts_section = lambda: None
    image, _boxes, _ = sample()
    skill._vision_auto = type('Vision', (), {'ocr': lambda _: [
        {'text': '张三', 'x': 150, 'y': 210, 'w': 100, 'h': 25}], 'shot': lambda *args: None})()
    skill._contact_list_bounds = lambda: (image.width, image.height, [.10, .47, .40, 1.])
    from unittest.mock import MagicMock
    skill._keyboard_only_auto = MagicMock()
    with pytest.raises(ChatNotFoundError, match='personal Contacts'):
        skill.open_contact_profile('张三', 'alias', max_contact_scroll_pages=0)
    skill.keyboard_only.click_window_fraction.assert_not_called()


def test_ensure_contacts_clicks_only_collapsed_contacts_expander(mock_app, config, session):
    from unittest.mock import MagicMock, patch
    skill = BasicSkill(mock_app, config, session)
    skill._keyboard_only_auto = MagicMock()
    skill._observe_contact_section = MagicMock(side_effect=[
        {'section': {'ok': True, 'state': 'collapsed', 'expander_point': [.12, .45]}},
        {'section': {'ok': True, 'state': 'expanded', 'member_bounds': [.1, .47, .4, 1]}, 'size': (1000,800)},
    ])
    with patch('wechat_auto.actions.basic.time.sleep'):
        assert skill.ensure_contacts_section()['success']
    skill.keyboard_only.click_window_fraction.assert_called_once_with(.12, .45)
