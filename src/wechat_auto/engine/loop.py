"""Latest runtime: one BasicSkill plus an optional read-only observer."""
from __future__ import annotations

import logging
import time

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.config import SessionConfig, WeChatConfig
from wechat_auto.core.application import Application
from wechat_auto.engine.router import SkillRouter

logger = logging.getLogger(__name__)


class AgentLoop:
    def __init__(self, config: WeChatConfig | None = None,
                 session: SessionConfig | None = None, observer=None):
        self._config = config or WeChatConfig()
        self._session = session or SessionConfig()
        self._application = Application(self._config)
        self._observer = observer
        self._router: SkillRouter | None = None
        self._basic_skill: BasicSkill | None = None
        self._running = False

    def connect(self) -> AgentLoop:
        self._application.connect()
        if self._session.auto_activate:
            self._application.activate()
        self._router = SkillRouter()
        self._basic_skill = BasicSkill(self._application, self._config, self._session)
        self._router.register_skill(self._basic_skill.name, self._basic_skill.execute)
        return self

    def disconnect(self) -> None:
        self._running = False
        self._application.disconnect()
        self._router = None
        self._basic_skill = None

    @property
    def is_connected(self) -> bool:
        return self._application.is_connected()

    @property
    def application(self) -> Application:
        return self._application

    @property
    def router(self) -> SkillRouter:
        if self._router is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._router

    @property
    def basic_skill(self) -> BasicSkill:
        if self._basic_skill is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._basic_skill

    def step(self) -> dict:
        if self._session.auto_activate:
            self._application.ensure_interactable()
        if self._observer is None:
            return {"unread": [], "actions": [], "observer": "not_configured"}
        return {"unread": self._observer.get_unread_messages(), "actions": []}

    def run(self, poll_interval: float = 5.0) -> None:
        self._running = True
        while self._running:
            try:
                if not self.is_connected:
                    self.connect()
                self.step()
            except Exception as exc:
                logger.error("AgentLoop step failed: %s", exc)
            time.sleep(poll_interval)

    def stop(self) -> None:
        self._running = False
