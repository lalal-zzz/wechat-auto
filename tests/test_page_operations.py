import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.actions.pages import (
    OPERATIONS,
    list_page_capabilities,
    page_keys,
    plan_page_route,
    resolve_operation,
)
from wechat_auto.primitives.page_catalog import PAGES
from wechat_auto.primitives.page_state import classify_page


def test_operation_graph_only_references_catalogued_pages():
    known = {spec.key for spec in PAGES}
    for operation in OPERATIONS:
        assert set(operation.sources) <= known
        assert set(operation.targets) <= known
    assert {p['key'] for p in list_page_capabilities()['pages']} == known
    assert plan_page_route('contact_profile', 'settings') == ['open_main_menu', 'open_settings']
    assert plan_page_route('chat', 'moments_feed') == ['open_discover', 'open_moments']


def test_popup_blocks_underlying_navigation_and_mutations_have_no_generic_route():
    state = {'page': 'chat', 'overlays': [{'key': 'contact_remark'}]}
    with pytest.raises(RuntimeError, match='blocking popup'):
        resolve_operation('open_contacts', state)
    assert resolve_operation('cancel', state)[1] == 'contact_remark'
    with pytest.raises(ValueError):
        resolve_operation('send_text', state)


def test_actual_public_ocr_landmarks_replay():
    fixture = json.loads((Path(__file__).parent / 'fixtures/wechat_ui_public_landmarks.json').read_text(encoding='utf-8'))
    for sample in fixture['samples']:
        state = classify_page(sample['boxes'], tuple(sample['size']), geometry=sample['geometry'])
        assert state['page'] == sample['expected_page'], sample['name']
        assert {x['key'] for x in state['overlays']} == set(sample['expected_overlays']), sample['name']
        assert {x['key'] for x in state['panels']} == set(sample['expected_panels']), sample['name']
        assert {x['key'] for x in state['content_windows']} == set(sample['expected_content_windows']), sample['name']
    search = next(s for s in fixture['samples'] if s['name'] == 'embedded_search')
    state = classify_page(search['boxes'], tuple(search['size']), geometry=search['geometry'])
    assert state['page'] == 'file_transfer'
    assert state['composer']['role'] == 'chat_input'
    assert state['right_panel']['types'] == ['search']
    assert page_keys(state) >= {'file_transfer', 'web_search'}


def test_observation_failure_stops_action(mock_app, config, session):
    skill = BasicSkill(mock_app, config, session)
    skill._vision_auto = MagicMock()
    skill._keyboard_only_auto = MagicMock()
    skill.vision.observe_page.return_value = {'ok': False, 'error': 'ocr_failure'}
    with pytest.raises(RuntimeError, match='observation unavailable'):
        skill.page_operation('open_contacts')
    skill.keyboard_only.click_window_fraction.assert_not_called()


def test_main_window_is_never_closed_even_if_content_type_matches(mock_app, config, session):
    skill = BasicSkill(mock_app, config, session)
    skill._vision_auto = MagicMock()
    skill._keyboard_only_auto = MagicMock()
    skill.vision.observe_page.return_value = {'ok': True, 'state': {
        'page': 'channels', 'content_windows': [], 'overlays': [], 'panels': [],
    }}
    mock_app.list_windows.return_value = [{'hwnd': mock_app.handle, 'is_main': True, 'class': 'Qt'}]
    with pytest.raises(PermissionError, match='main client cannot be closed'):
        skill.page_operation('close')
    skill.keyboard_only.close_window.assert_not_called()


def test_cancel_receipt_is_false_when_editor_remains_visible(mock_app, config, session):
    skill = BasicSkill(mock_app, config, session)
    skill._vision_auto = MagicMock()
    skill._keyboard_only_auto = MagicMock()
    observation = {'ok': True, 'boxes': [
        {'text': '取消', 'score': .99, 'x': 40, 'y': 80, 'w': 20, 'h': 10}],
        'state': {'page': 'unknown', 'overlays': [{'key': 'contact_remark'}], 'size': [100, 100]}}
    skill.vision.observe_page.return_value = observation
    mock_app.list_windows.return_value = [{'hwnd': mock_app.handle, 'is_main': True, 'class': 'Qt'}]
    with patch('wechat_auto.actions.basic.time.sleep'):
        receipt = skill.page_operation('cancel')
    assert receipt['success'] is False
    assert receipt['automatic_retry'] is False
    skill.keyboard_only.click_window_fraction.assert_called_once_with(.5, .85)


def test_search_clears_existing_query_and_ignores_microphone_ocr(mock_app, config, session):
    from PIL import Image

    skill = BasicSkill(mock_app, config, session)
    skill._vision_auto = MagicMock()
    skill._keyboard_only_auto = MagicMock()
    skill.vision.capture.return_value = Image.new('RGB', (200, 100))
    field = {'x': 10, 'y': 10, 'w': 100, 'h': 30}
    def text_box(text, x=20, w=50):
        return {'text': text, 'x': x, 'y': 15, 'w': w, 'h': 15, 'score': .99}
    skill.vision.recognize_image.side_effect = [[text_box('旧关键词')],
        [text_box('搜索'), text_box('O', x=100, w=5)], [text_box('新关键词')]]
    with patch('wechat_auto.primitives.page_geometry.observe_geometry', return_value={'search_field_candidates': [field]}), \
         patch('wechat_auto.primitives.page_controls.find_search_clear', return_value=[(95, 25)]), \
         patch('wechat_auto.actions.basic.time.sleep'), \
         patch('wechat_auto.utils.screenshot.ScreenshotHelper.capture_visible_window', return_value=Image.new('RGB',(200,100))):
        assert skill.prepare_search('新关键词')['selection_required'] is True
    assert skill.vision.recognize_image.call_args.args[0].size == (75, 30)
    assert skill.vision.recognize_image.call_args.kwargs['region'] == (23, 10, 75, 30)
    skill.keyboard_only._select_all_clear.assert_not_called()
    skill.keyboard_only._type_text.assert_called_once_with('新关键词')
    assert skill.keyboard_only.click_window_fraction.call_args_list[0].args == (.475, .25)
    skill.keyboard_only._enter.assert_not_called()


def test_search_geometry_failure_never_types(mock_app, config, session):
    from PIL import Image

    skill = BasicSkill(mock_app, config, session)
    skill._vision_auto = MagicMock()
    skill._keyboard_only_auto = MagicMock()
    skill.vision.capture.return_value = Image.new('RGB', (200, 100))
    with patch('wechat_auto.utils.screenshot.ScreenshotHelper.capture_visible_window', return_value=Image.new('RGB',(200,100))), \
         patch('wechat_auto.primitives.page_geometry.observe_geometry', return_value={'search_field_candidates': []}), \
         pytest.raises(RuntimeError, match='absent or ambiguous'):
        skill.prepare_search('关键词')
    skill.keyboard_only._type_text.assert_not_called()


def test_search_reset_rejects_unknown_or_foreign_auxiliary_without_keys(mock_app, config, session):
    skill = BasicSkill(mock_app, config, session)
    skill._keyboard_only_auto = MagicMock()
    skill.inspect_windows = MagicMock(return_value=[{'is_main':False,'status':'unknown'}])
    with pytest.raises(RuntimeError, match='recognized owned search'):
        skill.reset_search_popup()
    skill.keyboard_only.press_key.assert_not_called()


def test_search_reset_verifies_popup_disappearance_before_new_input(mock_app, config, session):
    skill = BasicSkill(mock_app, config, session)
    skill._keyboard_only_auto = MagicMock()
    popup = {'hwnd':5,'is_main':False,'status':'recognized','owner_hwnd':mock_app.handle,
             'surfaces':[{'page':'search_suggestions'}]}
    skill.inspect_windows = MagicMock(return_value=[popup])
    mock_app.list_windows.return_value = [popup]
    with patch('wechat_auto.actions.basic.time.sleep'), pytest.raises(RuntimeError, match='did not dismiss'):
        skill.reset_search_popup()
    skill.keyboard_only.press_key.assert_called_once_with('escape')
    skill.keyboard_only._type_text.assert_not_called()


def test_divider_drag_rejects_stale_point_and_verifies_actual_movement(mock_app, config, session):
    from PIL import Image
    skill = BasicSkill(mock_app, config, session)
    skill._vision_auto = MagicMock()
    skill._keyboard_only_auto = MagicMock()
    skill.vision.capture.return_value = Image.new('RGB', (1000, 800))
    before = {'vertical_separators': [{'x': 300}], 'composer_candidates': []}
    with patch('wechat_auto.primitives.page_geometry.observe_geometry', return_value=before):
        with pytest.raises(RuntimeError, match='unique current divider'):
            skill.drag_divider((.31, .4), (.4, .4))
        skill.keyboard_only.drag_window_fraction.assert_not_called()
        assert skill.drag_divider((.3, .4), (.4, .4))['success'] is False
    with patch('wechat_auto.primitives.page_geometry.observe_geometry', side_effect=[
            before, {'vertical_separators': [{'x': 400}], 'composer_candidates': []}]):
        assert skill.drag_divider((.3, .4), (.4, .4))['success'] is True
