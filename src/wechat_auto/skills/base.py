"""Base skill class for all Tier 1 composite skill packages."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from wechat_auto.config import WeChatConfig, SessionConfig

if TYPE_CHECKING:
    from wechat_auto.core.application import Application
    from wechat_auto.ui.finder import ElementFinder
    from wechat_auto.engine.healer import EnvironmentHealer

logger = logging.getLogger(__name__)


class BaseSkill:
    """Base class for Tier 1 high-level skill packages.

    Each skill encapsulates a complex UI interaction workflow into a single
    callable action. The AI agent only needs to pass parameters — the skill
    handles all intermediate UI logic internally.

    Subclasses must define:
        - `name`: Unique skill identifier string.
        - `execute(**params)`: The skill's main entry point.
    """

    #: Unique skill identifier (override in subclass)
    name: str = "base_skill"

    def __init__(
        self,
        application: "Application",
        finder: "ElementFinder",
        config: WeChatConfig,
        session: SessionConfig,
        healer: "EnvironmentHealer" = None,
    ):
        self._app = application
        self._finder = finder
        self._config = config
        self._session = session
        self._healer = healer

    @property
    def window(self):
        """Shortcut to the main WeChat window."""
        return self._app.main_window

    def execute(self, **params) -> Any:
        """Unified skill entry point with automatic environment reset.

        Subclasses should override `_run(**params)` for actual logic.
        This wrapper ensures `reset_ui_environment()` is called in finally.
        """
        try:
            return self._run(**params)
        finally:
            if self._healer is not None:
                try:
                    self._healer.reset_ui_environment()
                except Exception as exc:
                    logger.warning("Post-skill environment reset failed: %s", exc)

    def _run(self, **params) -> Any:
        """Actual skill logic (override in subclass)."""
        raise NotImplementedError(f"Skill '{self.name}' has not implemented _run().")

    # ------------------------------------------------------------------
    # Common helpers
    # ------------------------------------------------------------------

    def _activate(self) -> None:
        """Bring WeChat to front if auto_activate is on."""
        if self._session.auto_activate:
            self._app.activate()

    def _open_chat(self, chat_name: str) -> None:
        """Open the specified chat conversation."""
        self._finder.open_chat(chat_name)
