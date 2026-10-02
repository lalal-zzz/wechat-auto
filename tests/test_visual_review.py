from unittest.mock import MagicMock, patch

import pytest
from PIL import Image, ImageDraw

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.actions.visual_review import VisualReviewStore


def frame():
    image = Image.new('RGB', (200, 120), '#222222')
    ImageDraw.Draw(image).rectangle((20, 20, 40, 40), outline='white', width=3)
    return image


def metadata():
    return {'hwnd': 11, 'pid': 100, 'class': 'Qt', 'rect': [0,0,200,120], 'client_rect': [0,0,200,120],
            'owner_hwnd': 0, 'dpi': 144, 'enabled': True, 'visible': True, 'minimized': False, 'is_main': True}


def test_review_is_single_use_and_coordinate_is_bound_to_image(tmp_path):
    store = VisualReviewStore(tmp_path)
    review = store.prepare('open_contacts', metadata(), frame())
    assert review['input_dispatched'] is False
    plan = store.consume(review['review_id'], [19,19,23,23], metadata(), frame())
    assert plan['point'] == [.1525, .25416666666666665]
    with pytest.raises(RuntimeError, match='consumed'):
        store.consume(review['review_id'], [19,19,23,23], metadata(), frame())


@pytest.mark.parametrize('change', ['move', 'owner', 'dpi', 'target', 'layout', 'expiry'])
def test_review_rejects_changed_target_or_expired_proposal(tmp_path, change):
    store = VisualReviewStore(tmp_path)
    review = store.prepare('open_contacts', metadata(), frame())
    meta, image = metadata(), frame()
    if change == 'move': meta['rect'] = [10,0,210,120]
    elif change == 'owner': meta['owner_hwnd'] = 22
    elif change == 'dpi': meta['dpi'] = 192
    elif change == 'target': ImageDraw.Draw(image).rectangle((20,20,40,40), fill='black')
    elif change == 'layout': ImageDraw.Draw(image).rectangle((80,0,199,119), fill='white')
    else: store.requests[review['review_id']]['created_at'] -= 121
    with pytest.raises(RuntimeError):
        store.consume(review['review_id'], [19,19,23,23], meta, image)


def test_tiny_noise_elsewhere_does_not_invalidate_stable_control(tmp_path):
    store = VisualReviewStore(tmp_path)
    review = store.prepare('open_contacts', metadata(), frame())
    image = frame()
    ImageDraw.Draw(image).line((150,70,150,75), fill='white')
    assert store.consume(review['review_id'], [19,19,23,23], metadata(), image)['operation'] == 'open_contacts'


def test_visual_review_never_accepts_sending_or_arbitrary_action(mock_app, config, session):
    skill = BasicSkill(mock_app, config, session)
    skill._keyboard_only_auto = MagicMock()
    for operation in ('send_text', 'delete_contact', 'download_media', 'click', 'cancel'):
        with pytest.raises(ValueError):
            skill.prepare_visual_review(operation)
    skill.keyboard_only.click_window_fraction.assert_not_called()


def reviewed_skill(mock_app, config, session, tmp_path, *, text=''):
    image = Image.new('RGB', (1000,800), '#222222')
    ImageDraw.Draw(image).rectangle((20,20,40,40), outline='white', width=3)
    meta = {**metadata(), 'rect': [0,0,1000,800], 'client_rect': [0,0,1000,800]}
    mock_app.handle = 11
    mock_app.for_window.return_value = mock_app
    mock_app.describe_window.return_value = meta
    skill = BasicSkill(mock_app, config, session)
    skill._visual_review_store = VisualReviewStore(tmp_path)
    token = skill._visual_review_store.prepare('open_contacts', meta, image)['review_id']
    skill._vision_auto = MagicMock()
    skill.vision.capture.return_value = image
    skill.vision.observe_page.return_value = {'ok': True, 'state': {'page': 'chat', 'overlays': []},
        'boxes': [{'text': text, 'x': 20, 'y': 20, 'w': 20, 'h': 20}] if text else []}
    skill._keyboard_only_auto = MagicMock()
    skill.inspect_windows = MagicMock(side_effect=[
        [{**meta, 'status': 'recognized', 'surfaces': [{'page': 'chat', 'layer': 'base'}]}],
        [{**meta, 'status': 'recognized', 'surfaces': [{'page': 'contacts', 'layer': 'base'}]}]])
    return skill, token


def test_agent_proposal_is_verified_after_one_basic_driver_action(mock_app, config, session, tmp_path):
    skill, token = reviewed_skill(mock_app, config, session, tmp_path)
    with patch('wechat_auto.primitives.page_geometry.observe_geometry', return_value={
        'vertical_separators': [{'x': 80}]}), patch('wechat_auto.actions.basic.time.sleep'):
        result = skill.apply_visual_review(token, [19,19,23,23], 'chat')
    assert result['success'] and result['coordinate_source'] == 'agent_reviewed_current_frame'
    skill.keyboard_only.click_window_fraction.assert_called_once()
    assert result['sent'] is False and result['automatic_retry'] is False


@pytest.mark.parametrize('label', ['发送', '删除联系人', '退出登录'])
def test_review_cannot_relabel_mutation_as_navigation(mock_app, config, session, tmp_path, label):
    skill, token = reviewed_skill(mock_app, config, session, tmp_path, text=label)
    with pytest.raises(PermissionError):
        skill.apply_visual_review(token, [19,19,23,23], 'chat')
    skill.keyboard_only.click_window_fraction.assert_not_called()


def test_agent_input_does_not_report_success_when_page_did_not_change(mock_app, config, session, tmp_path):
    skill, token = reviewed_skill(mock_app, config, session, tmp_path)
    first = skill.inspect_windows.side_effect
    # Both pre/post snapshots still show the source page.
    snapshot = next(iter(first))
    skill.inspect_windows.side_effect = [snapshot, snapshot]
    with patch('wechat_auto.primitives.page_geometry.observe_geometry', return_value={
        'vertical_separators': [{'x': 80}]}), patch('wechat_auto.actions.basic.time.sleep'):
        result = skill.apply_visual_review(token, [19,19,23,23], 'chat')
    assert not result['success'] and result['verified_by'] == 'postcondition_failed'
    skill.keyboard_only.click_window_fraction.assert_called_once()
