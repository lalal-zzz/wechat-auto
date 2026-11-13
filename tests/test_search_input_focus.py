"""Search input must never fall through to a previously focused composer."""
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from wechat_auto.actions.basic import BasicSkill


@pytest.mark.parametrize('failure', ['missing_caret', 'composer_caret', 'boundary_caret',
                                     'moved_window', 'missing_frame', 'ambiguous_field',
                                     'moved_field', 'changed_during_caret'])
def test_search_focus_failure_dispatches_no_text(mock_app, config, session, failure):
    skill = BasicSkill(mock_app, config, session)
    skill._vision_auto = MagicMock()
    skill._keyboard_only_auto = MagicMock()
    skill.reset_search_popup = MagicMock()
    field = {'x': 10, 'y': 10, 'w': 100, 'h': 30}
    image = Image.new('RGB', (200, 100))
    scope = {'hwnd': 123, 'rect': [0, 0, 200, 100], 'dpi': 144}
    mock_app.describe_window.return_value = scope
    mock_app.focused_caret_rect.return_value = [25, 20, 27, 30]
    skill.vision.recognize_image.return_value = [
        {'text': '搜索', 'x': 30, 'y': 15, 'w': 30, 'h': 15}]
    fields = [field]
    frames = [image, image]
    if failure == 'missing_caret':
        mock_app.focused_caret_rect.return_value = None
    elif failure == 'composer_caret':
        mock_app.focused_caret_rect.return_value = [125, 75, 127, 85]
    elif failure == 'boundary_caret':
        mock_app.focused_caret_rect.return_value = [10, 20, 12, 30]
    elif failure == 'moved_window':
        mock_app.describe_window.side_effect = [scope, {**scope, 'dpi': 96}]
    elif failure == 'missing_frame':
        frames[1] = None
    elif failure == 'ambiguous_field':
        fields = [field, {**field, 'x': 120}]
    elif failure == 'moved_field':
        fields = [{**field, 'y': 50}]
    elif failure == 'changed_during_caret':
        mock_app.describe_window.side_effect = [scope, scope, {**scope, 'hwnd': 456}]
    with patch('wechat_auto.utils.screenshot.ScreenshotHelper.capture_visible_window', side_effect=frames), \
         patch('wechat_auto.primitives.page_geometry.observe_geometry', side_effect=[
             {'search_field_candidates': [field]}, {'search_field_candidates': fields}]), \
         patch('wechat_auto.actions.basic.time.sleep'), \
         pytest.raises(RuntimeError, match='typing stopped'):
        skill.prepare_search('不得进入聊天草稿')
    skill.keyboard_only._type_text.assert_not_called()
    skill.keyboard_only._enter.assert_not_called()


def test_caret_in_current_search_field_allows_query_only(mock_app, config, session):
    skill = BasicSkill(mock_app, config, session)
    skill._vision_auto = MagicMock()
    skill._keyboard_only_auto = MagicMock()
    skill.reset_search_popup = MagicMock()
    field = {'x': 10, 'y': 10, 'w': 100, 'h': 30}
    mock_app.describe_window.return_value = {'hwnd': 123}
    mock_app.focused_caret_rect.return_value = [25, 20, 27, 30]
    def box(text):
        return [{'text': text, 'x': 30, 'y': 15, 'w': 30, 'h': 15}]
    skill.vision.recognize_image.side_effect = [box('搜索'), box('查询')]
    with patch('wechat_auto.utils.screenshot.ScreenshotHelper.capture_visible_window', return_value=Image.new('RGB', (200, 100))), \
         patch('wechat_auto.primitives.page_geometry.observe_geometry', return_value={'search_field_candidates': [field]}), \
         patch('wechat_auto.actions.basic.time.sleep'):
        assert skill.prepare_search('查询')['sent'] is False
    skill.keyboard_only._type_text.assert_called_once_with('查询')
    skill.keyboard_only._enter.assert_not_called()
