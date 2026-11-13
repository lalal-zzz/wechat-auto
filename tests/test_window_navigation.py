from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.core.application import Application
from wechat_auto.primitives.page_state import classify_page
from wechat_auto.primitives.window_observer import (
    WindowObserver,
    select_surface,
    window_summary,
)


def observed(page='chat', *, hwnd=11, main=True, overlays=(), panels=()):
    metadata = {'hwnd': hwnd, 'pid': 100, 'class': 'Qt', 'width': 1000, 'height': 800,
                'is_main': main, 'visible': True, 'enabled': True, 'minimized': False}
    state = {'page': page, 'size': [1000, 800], 'overlays': [{'key': key} for key in overlays],
             'panels': list(panels), 'composer': {'state': 'present' if page == 'chat' else 'unknown'}}
    return window_summary(metadata, {'ok': True, 'boxes': [{'text': 'private text'}], 'state': state})


def test_main_chat_and_embedded_search_stay_separate_without_private_ocr():
    window = observed(panels=[{'key': 'web_search'},
                              {'key': 'web_search', 'presentation': 'embedded_right_tab'}])
    assert window['role'] == 'main_client' and window['composer_present']
    assert len(window['surfaces']) == 2
    assert select_surface([window], 'chat')['target']['presentation'] == 'embedded_main'
    assert select_surface([window], 'web_search')['target']['presentation'] == 'embedded_right_tab'
    assert 'private text' not in str(window) and 'boxes' not in window
    assert window['identity_verified'] is False


def test_multiple_albums_require_explicit_disambiguation():
    windows = [observed('moments_person', hwnd=22, main=False),
               observed('moments_person', hwnd=33, main=False)]
    assert select_surface(windows, 'moments_person')['error'] == 'ambiguous_target_window'
    assert select_surface(windows, 'moments_person', hwnd=33)['target']['hwnd'] == 33


def test_visible_contacts_tree_is_a_surface_beside_selected_profile():
    meta = {'hwnd': 11, 'pid': 100, 'is_main': True, 'width': 1000, 'height': 800}
    summary = window_summary(meta, {'ok': True, 'state': {
        'page': 'contact_profile', 'size': [1000,800], 'contact_section': {'ok': True, 'state': 'expanded'}}})
    assert select_surface([summary], 'contacts')['target']['presentation'] == 'embedded_panel'
    assert select_surface([summary], 'contact_profile')['target']['presentation'] == 'embedded_main'


def test_unknown_disabled_and_stale_windows_are_not_action_targets():
    unknown = observed('unknown', hwnd=22, main=False)
    assert unknown['role'] == 'unknown_window'
    assert not select_surface([unknown], 'settings')['ok']
    disabled = observed('settings', hwnd=22, main=False)
    disabled['enabled'] = False
    assert select_surface([disabled], 'settings')['error'] == 'target_window_disabled'
    disabled['status'] = 'stale'
    assert select_surface([disabled], 'settings')['error'] == 'target_page_not_found'


def test_real_settings_public_labels_survive_icon_ocr_noise():
    boxes = [{'text': text, 'score': .98, 'x': 70, 'y': 60 + i * 60, 'w': 130, 'h': 25}
             for i, text in enumerate(['8账号与存储', '🔆通用', '快捷键', '通知', '插件', '关于微信'])]
    state = classify_page(boxes, (1000, 800))
    assert 'settings' in {s['key'] for s in state['content_windows']}
    # A single ordinary UI label is insufficient to label arbitrary windows.
    state = classify_page(boxes[2:3], (1000, 800))
    assert 'settings' not in {s['key'] for s in state['content_windows']}


def test_window_changes_during_ocr_invalidate_observation(config):
    app = MagicMock()
    before = {**observed(), 'rect': [10, 10, 1010, 810], 'client_rect': [10, 10, 1010, 810],
              'owner_hwnd': 0, 'dpi': 144}
    after = {**before, 'rect': [20, 10, 1020, 810]}
    app.list_windows.return_value = [before]
    app.describe_window.side_effect = [before, after]
    with patch('wechat_auto.primitives.vision.VisionAutomation') as vision:
        vision.return_value.observe_page.return_value = {'ok': True, 'state': {'page': 'chat', 'size': [1000, 800]}}
        result = WindowObserver(app, config).inspect()
    assert result[0]['status'] == 'stale' and result[0]['surfaces'] == []


def test_foreign_process_is_rejected_before_geometry_or_input():
    app = Application()
    app._hwnd = 11
    with patch.object(app, 'window_process_id', side_effect=[100, 200]), \
         patch('wechat_auto.core.application.user32') as api:
        with pytest.raises(PermissionError):
            app.describe_window(22)
        api.GetWindowRect.assert_not_called()


def test_reused_root_hwnd_cannot_rebind_to_foreign_process():
    app = Application()
    app._hwnd, app._connected_pid = 11, 100
    with patch.object(app, 'window_process_id', return_value=200), \
         patch('wechat_auto.core.application.user32') as api:
        with pytest.raises(PermissionError, match='reused'):
            app.list_windows()
        api.EnumWindows.assert_not_called()


def skill_for_windows(mock_app, config, session, snapshots):
    skill = BasicSkill(mock_app, config, session)
    skill.inspect_windows = MagicMock(side_effect=snapshots)
    skill.page_operation = MagicMock(return_value={'success': True})
    return skill


def test_route_reselects_new_album_window_after_each_step(mock_app, config, session):
    skill = skill_for_windows(mock_app, config, session, [
        [observed('chat')], [observed('discover')],
        [observed('discover'), observed('moments_feed', hwnd=22, main=False)]])
    result = skill.navigate_page('moments_feed')
    assert result['success'] and result['target']['hwnd'] == 22
    assert [c.args[0] for c in skill.page_operation.call_args_list] == ['open_discover', 'open_moments']
    assert skill.inspect_windows.call_count == 3


def test_menu_operation_is_routed_to_menu_hwnd(mock_app, config, session):
    skill = skill_for_windows(mock_app, config, session, [
        [observed(), observed('unknown', hwnd=22, main=False, overlays=['main_menu'])],
        [observed(), observed('unknown', hwnd=33, main=False,
                              panels=[{'key': 'settings'}])]])
    assert skill.navigate_page('settings')['success']
    skill.page_operation.assert_called_once_with('open_settings', hwnd=22, expected_page='main_menu')


@pytest.mark.parametrize('auxiliary,reason', [
    (observed('unknown', hwnd=22, main=False), 'unrecognized_auxiliary_window'),
    (observed('unknown', hwnd=22, main=False, overlays=['confirm_dialog']), 'route_unavailable'),
])
def test_unknown_and_confirmation_popup_stop_navigation(mock_app, config, session, auxiliary, reason):
    skill = skill_for_windows(mock_app, config, session, [[observed(), auxiliary]])
    assert skill.navigate_page('contacts')['stop_reason'] == reason
    skill.page_operation.assert_not_called()


def test_failed_click_stops_multistep_route(mock_app, config, session):
    skill = skill_for_windows(mock_app, config, session, [[observed()]])
    skill.page_operation.return_value = {'success': False}
    result = skill.navigate_page('moments_feed')
    assert result['stop_reason'] == 'navigation_postcondition_failed'
    skill.page_operation.assert_called_once()


def test_restore_closes_known_auxiliary_and_keeps_main(mock_app, config, session):
    skill = skill_for_windows(mock_app, config, session, [
        [observed(), observed('unknown', hwnd=22, main=False, panels=[{'key': 'settings'}])],
        [observed()]])
    assert skill.restore_main_window()['success']
    skill.page_operation.assert_called_once_with('close', hwnd=22, expected_page='settings')


@pytest.mark.parametrize('page', ['contact_remark', 'moments_comment', 'moments_publish', 'file_picker'])
def test_restore_never_discards_editor_or_chooses_file(mock_app, config, session, page):
    auxiliary = observed('unknown', hwnd=22, main=False, overlays=[page])
    skill = skill_for_windows(mock_app, config, session, [[observed(), auxiliary]])
    assert skill.restore_main_window()['stop_reason'] == 'editor_requires_explicit_handling'
    skill.page_operation.assert_not_called()


def test_restore_does_not_close_main_client_showing_channels(mock_app, config, session):
    skill = skill_for_windows(mock_app, config, session, [[observed('channels')]])
    assert skill.restore_main_window()['success']
    skill.page_operation.assert_not_called()


@pytest.mark.parametrize('pages,expected_calls', [
    (['file_transfer', 'file_transfer'], 1),
    (['contacts', 'file_transfer', 'file_transfer'], 2),
    (['contacts', 'file_transfer', 'contacts'], 2),
])
def test_exact_chat_route_stops_repeated_edges_without_aliasing_filehelper(
        mock_app, config, session, pages, expected_calls):
    skill = skill_for_windows(mock_app, config, session, [[observed(page)] for page in pages])
    result = skill.navigate_page('chat', max_steps=6)
    assert not result['success']
    assert result['stop_reason'] == 'route_no_progress'
    assert skill.page_operation.call_count == expected_calls
    assert len(result['steps']) == expected_calls


def test_open_moments_accepts_already_observed_feed_without_another_click(mock_app, config, session):
    skill = skill_for_windows(mock_app, config, session, [[observed('moments_feed')]])
    result = skill.open_moments()
    assert result['success'] and result['action'] == 'open_moments'
    assert result['target']['page'] == 'moments_feed'
    skill.page_operation.assert_not_called()


def test_open_moments_preserves_route_failure(mock_app, config, session):
    skill = skill_for_windows(mock_app, config, session, [[observed('chat')]])
    skill.page_operation.return_value = {'success': False}
    result = skill.open_moments()
    assert not result['success']
    assert result['stop_reason'] == 'navigation_postcondition_failed'
