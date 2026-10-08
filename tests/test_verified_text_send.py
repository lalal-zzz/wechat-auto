from unittest.mock import MagicMock, patch

import pytest
from PIL import Image, ImageDraw

from wechat_auto.actions.basic import BasicSkill


def fixture_skill(mock_app, config, session, *, existing='', rendered='test'):
    skill = BasicSkill(mock_app, config, session)
    metadata = {'hwnd': 1, 'pid': 2, 'rect': [0,0,1000,800], 'client_rect': [0,0,1000,800], 'dpi': 96}
    mock_app.handle = 1
    mock_app.describe_window.return_value = metadata
    mock_app.list_windows.return_value = [{'is_main':True}]
    skill._recipient_lease = {'username': 'filehelper','query': 'FileHelper','metadata': metadata}
    skill._keyboard_only_auto = MagicMock()
    skill._vision_auto = MagicMock()
    frame = {'x': 300,'y': 600,'w': 680,'h': 180}
    def observation(body, outgoing=False):
        boxes = [{'text': 'FileHelper','x': 350,'y': 50,'w': 120,'h': 25,'score': .99},
                 {'text': '发送','x': 900,'y': 740,'w': 45,'h': 25,'score': .99},
                 {'text': '0','x': 600,'y': 740,'w': 20,'h': 25,'score': .99}]
        composer = [{'text': b['text'],'box_index': i} for i,b in enumerate(boxes) if i]
        if body:
            boxes.append({'text': body,'x': 330,'y': 650,'w': 200,'h': 25,'score': .99})
            composer.append({'text': body,'box_index': 3})
        if outgoing:
            boxes.append({'text': 'test','x': 700,'y': 400,'w': 200,'h': 25,'score': .99})
        state = {'size': [1000,800], 'composer': {'state':'present'},
                     'geometry': {'composer_candidates':[frame]},
                     'regions': {'conversation_header':[{'text':'FileHelper','box_index':0}],
                              'composer':composer}}
        return {'ok': True,'state': state,'boxes': boxes}
    skill.vision.observe_page.side_effect = [observation(existing), observation(rendered), observation('',True)]
    image = Image.new('RGB',(1000,800),(30,30,30))
    ImageDraw.Draw(image).rectangle((700,400,900,425), fill=(90,210,70))
    skill.vision._last_observed_image = image
    return skill


def test_action_row_icon_is_not_a_draft_and_send_is_verified_once(mock_app, config, session):
    skill = fixture_skill(mock_app,config,session)
    with patch('wechat_auto.actions.basic.time.sleep'):
        result = skill.send_current_verified_text('test',confirm=True)
    assert result['sent'] and not result['delivery_verified'] and not result['automatic_retry']
    skill.keyboard_only._type_text.assert_called_once_with('test')
    assert skill.keyboard_only.click_window_fraction.call_count == 2
    assert skill._recipient_lease is None


def test_real_zero_draft_is_preserved_without_typing(mock_app, config, session):
    skill = fixture_skill(mock_app,config,session,existing='0')
    with pytest.raises(RuntimeError,match='Existing draft'):
        skill.send_current_verified_text('test',confirm=True)
    skill.keyboard_only._type_text.assert_not_called()
    skill.keyboard_only.click_window_fraction.assert_not_called()


def test_unverified_rendered_body_never_dispatches_send(mock_app, config, session):
    skill = fixture_skill(mock_app,config,session,rendered='different')
    with patch('wechat_auto.actions.basic.time.sleep'), pytest.raises(RuntimeError,match='exactly observed'):
        skill.send_current_verified_text('test',confirm=True)
    assert skill.keyboard_only.click_window_fraction.call_count == 1


def test_same_text_preview_in_another_chat_does_not_hide_new_outgoing_message(mock_app, config, session):
    skill = fixture_skill(mock_app,config,session)
    observations = list(skill.vision.observe_page.side_effect)
    observations[0]['boxes'].append({'text':'test','x':120,'y':200,'w':150,'h':25,'score':.99})
    skill.vision.observe_page.side_effect = observations
    with patch('wechat_auto.actions.basic.time.sleep'):
        assert skill.send_current_verified_text('test',confirm=True)['sent']
