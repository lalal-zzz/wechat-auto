from unittest.mock import MagicMock, patch

import pytest

from wechat_auto.config import SessionConfig
from wechat_auto.engine.loop import AgentLoop


@pytest.mark.parametrize('boundary', ['connect', 'activate', 'basic', 'register'])
@pytest.mark.parametrize('interrupt', [False, True])
def test_partial_connection_releases_state_and_preserves_original_failure(boundary, interrupt):
    failure = KeyboardInterrupt() if interrupt else RuntimeError('synthetic startup failure')
    with (patch('wechat_auto.engine.loop.Application') as factory,
          patch('wechat_auto.engine.loop.BasicSkill') as basic,
          patch('wechat_auto.engine.loop.SkillRouter') as router):
        app = factory.return_value
        app.is_connected.return_value = True
        target = {'connect': app.connect, 'activate': app.activate,
                  'basic': basic, 'register': router.return_value.register_skill}[boundary]
        target.side_effect = failure
        agent = AgentLoop(session=SessionConfig(auto_activate=True))
        with pytest.raises(type(failure)) as captured:
            agent.connect()
        assert captured.value is failure
        app.disconnect.assert_called_once()
        assert not agent.is_connected
        assert agent._router is None and agent._basic_skill is None
        with pytest.raises(RuntimeError, match='Not connected'):
            _ = agent.router


def test_connection_cleanup_error_does_not_replace_startup_failure():
    with patch('wechat_auto.engine.loop.Application') as factory:
        app = factory.return_value
        app.connect.side_effect = ValueError('original startup failure')
        app.disconnect.side_effect = RuntimeError('secondary cleanup failure')
        app.is_connected.return_value = True
        agent = AgentLoop()
        with pytest.raises(ValueError, match='original startup'):
            agent.connect()
        assert not agent.is_connected
        assert agent._router is None and agent._basic_skill is None


def test_repeated_connect_keeps_current_runtime_instance():
    with patch('wechat_auto.engine.loop.Application') as factory:
        app = factory.return_value
        app.is_connected.return_value = True
        agent = AgentLoop(session=SessionConfig(auto_activate=False)).connect()
        basic, router = agent.basic_skill, agent.router
        assert agent.connect() is agent
        assert agent.basic_skill is basic and agent.router is router
        app.connect.assert_called_once()
        app.disconnect.assert_not_called()


def test_disconnect_failure_still_revokes_runtime():
    with patch('wechat_auto.engine.loop.Application') as factory:
        app = factory.return_value
        app.is_connected.return_value = True
        agent = AgentLoop(session=SessionConfig(auto_activate=False)).connect()
        agent._running = True
        app.disconnect.side_effect = RuntimeError('synthetic detach failure')
        with pytest.raises(RuntimeError, match='detach failure'):
            agent.disconnect()
        assert not agent._running and not agent.is_connected
        assert agent._router is None and agent._basic_skill is None


def test_disconnected_step_does_not_activate_or_read_observer():
    observer = MagicMock()
    with patch('wechat_auto.engine.loop.Application') as factory:
        agent = AgentLoop(observer=observer)
        with pytest.raises(RuntimeError, match='Not connected'):
            agent.step()
        factory.return_value.ensure_interactable.assert_not_called()
        observer.get_unread_messages.assert_not_called()


def test_failed_startup_can_reconnect_with_fresh_runtime():
    with patch('wechat_auto.engine.loop.Application') as factory:
        app = factory.return_value
        app.is_connected.return_value = True
        app.activate.side_effect = RuntimeError('synthetic activation failure')
        agent = AgentLoop(session=SessionConfig(auto_activate=True))
        with pytest.raises(RuntimeError):
            agent.connect()
        app.activate.side_effect = None
        agent.connect()
        assert agent.is_connected and agent.router.available_skills == ['basic_action']
        assert app.connect.call_count == 2
        app.disconnect.assert_called_once()


def test_lost_hwnd_revokes_access_before_ui_or_observer_read():
    observer = MagicMock()
    with patch('wechat_auto.engine.loop.Application') as factory:
        app = factory.return_value
        app.is_connected.return_value = True
        agent = AgentLoop(session=SessionConfig(auto_activate=True), observer=observer).connect()
        app.is_connected.return_value = False
        for read in (lambda: agent.router, lambda: agent.basic_skill, agent.step):
            with pytest.raises(RuntimeError, match='Not connected'):
                read()
        app.ensure_interactable.assert_not_called()
        observer.get_unread_messages.assert_not_called()


def test_run_recovers_after_partial_startup_without_logging_private_exception(caplog):
    with (patch('wechat_auto.engine.loop.Application') as factory,
          patch('wechat_auto.engine.loop.time.sleep')):
        app = factory.return_value
        app.is_connected.return_value = True
        app.connect.side_effect = [RuntimeError('PRIVATE_BODY_SENTINEL'), None]
        agent = AgentLoop(session=SessionConfig(auto_activate=False))
        agent.step = MagicMock(side_effect=agent.stop)
        agent.run()
        assert app.connect.call_count == 2
        app.disconnect.assert_called_once()
        agent.step.assert_called_once()
        assert not agent._running
        assert 'PRIVATE_BODY_SENTINEL' not in caplog.text
        assert 'RuntimeError' in caplog.text


def test_run_interrupt_always_resets_running_flag():
    with (patch('wechat_auto.engine.loop.Application') as factory,
          patch('wechat_auto.engine.loop.time.sleep')):
        factory.return_value.is_connected.return_value = True
        agent = AgentLoop(session=SessionConfig(auto_activate=False))
        agent.step = MagicMock(side_effect=KeyboardInterrupt())
        with pytest.raises(KeyboardInterrupt):
            agent.run()
        assert not agent._running
