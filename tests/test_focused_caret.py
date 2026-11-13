"""Public Win32 caret coordinates must belong to the connected client."""
from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.core.application import Application


@pytest.mark.parametrize('case', ['valid', 'background', 'missing', 'foreign_focus',
                                 'foreign_caret', 'wrong_pid', 'empty_rect',
                                 'mapping_failed', 'window_changed', 'hidden',
                                 'disabled', 'minimized', 'thread_unavailable',
                                 'caret_changed', 'focus_changed', 'caret_read_failed'])
def test_public_caret_observation(case):
    app = Application()
    app._hwnd = 123
    app._expected_process_id = MagicMock(return_value=987)
    app.window_process_id = MagicMock(return_value=987)
    scope = {'pid': 987, 'rect': [100, 200, 900, 800],
             'visible': True, 'enabled': True, 'minimized': False}
    app.describe_window = MagicMock(return_value=scope)
    api = MagicMock()
    api.GetForegroundWindow.return_value = 456 if case == 'background' else 123
    api.GetWindowThreadProcessId.return_value = 0 if case == 'thread_unavailable' else 22
    api.IsChild.side_effect = lambda parent, child: child == 124
    calls = []
    def gui(_thread, pointer):
        calls.append(True)
        info = pointer._obj
        info.hwndFocus = 999 if case == 'foreign_focus' or (case == 'focus_changed' and len(calls) > 1) else 123
        info.hwndCaret = 999 if case == 'foreign_caret' else 124
        info.rcCaret.left, info.rcCaret.top = 5, 6
        info.rcCaret.right, info.rcCaret.bottom = (5 if case == 'empty_rect' else 7), 8
        if case == 'caret_changed' and len(calls) > 1:
            info.rcCaret.top = 7
        return case != 'missing' and not (case == 'caret_read_failed' and len(calls) > 1)
    api.GetGUIThreadInfo.side_effect = gui
    def to_screen(_hwnd, pointer):
        point = pointer._obj
        point.x += 110
        point.y += 220
        return case != 'mapping_failed'
    api.ClientToScreen.side_effect = to_screen
    if case == 'wrong_pid':
        app.window_process_id.return_value = 777
    if case == 'window_changed':
        app.describe_window.side_effect = [scope, {**scope, 'rect': [0, 0, 800, 600]}]
    for key in ('hidden', 'disabled', 'minimized'):
        if case == key:
            scope[{'hidden': 'visible', 'disabled': 'enabled', 'minimized': 'minimized'}[key]] = key == 'minimized'
    with patch('wechat_auto.core.application.user32', api):
        result = app.focused_caret_rect()
    assert result == ([15, 26, 17, 28] if case == 'valid' else None)
