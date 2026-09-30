"""Minimal base for the single HWND action skill."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from wechat_auto.config import SessionConfig, WeChatConfig

if TYPE_CHECKING:
    from wechat_auto.core.application import Application
    from wechat_auto.primitives.vision import VisionAutomation


class BaseSkill:
    name = "base_skill"

    def __init__(self, application: Application, config: WeChatConfig,
                 session: SessionConfig):
        self._app = application
        self._config = config
        self._session = session

    @property
    def vision(self) -> VisionAutomation:
        if getattr(self, "_vision_auto", None) is None:
            from wechat_auto.primitives.vision import VisionAutomation
            self._vision_auto = VisionAutomation(
                self._app, self._config, shot_dir=self._session.screenshot_dir
            )
        return self._vision_auto

    @property
    def keyboard_only(self):
        if getattr(self, "_keyboard_only_auto", None) is None:
            from wechat_auto.primitives.keyboard_only import KeyboardOnlyDriver
            self._keyboard_only_auto = KeyboardOnlyDriver(
                self._app,
                search_mode=self._config.keyboard_search_mode,
                input_mode=self._config.keyboard_input_mode,
                auto_activate=self._session.auto_activate,
            )
        return self._keyboard_only_auto

    def execute(self, **params) -> Any:
        return self._run(**params)

    def _run(self, **params) -> Any:
        raise NotImplementedError

    def _activate(self) -> None:
        if self._session.auto_activate:
            self._app.activate()
