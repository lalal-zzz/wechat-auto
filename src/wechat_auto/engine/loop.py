"""AgentLoop - main closed-loop orchestration engine."""

from __future__ import annotations

import logging
import time
from typing import Optional

from wechat_auto.config import WeChatConfig, SessionConfig
from wechat_auto.core.application import Application
from wechat_auto.ui.finder import ElementFinder
from wechat_auto.engine.perceiver import Perceiver
from wechat_auto.engine.router import SkillRouter
from wechat_auto.engine.healer import EnvironmentHealer

logger = logging.getLogger(__name__)


class AgentLoop:
    """Closed-loop AI Agent main orchestration engine.

    Implements the full workflow:
        Step 1. Perceive  — poll for unread messages
        Step 2. Decide    — route to appropriate skill/tool
        Step 3. Execute   — Tier 1 skill or Tier 2 atomic fallback
        Step 4. Validate  — reset environment, ensure idle state

    Usage::

        from wechat_auto import AgentLoop

        agent = AgentLoop()
        agent.connect()
        agent.run(poll_interval=5.0)  # continuous loop
    """

    def __init__(
        self,
        config: Optional[WeChatConfig] = None,
        session: Optional[SessionConfig] = None,
    ):
        self._config = config or WeChatConfig()
        self._session = session or SessionConfig()

        # Set up logging
        logging.basicConfig(level=getattr(logging, self._config.log_level, logging.INFO))

        # Core components
        self._application = Application(self._config)
        self._finder: Optional[ElementFinder] = None

        # Engine components
        self._perceiver: Optional[Perceiver] = None
        self._router: Optional[SkillRouter] = None
        self._healer: Optional[EnvironmentHealer] = None

        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> "AgentLoop":
        """Connect to WeChat and initialize all engine components."""
        self._application.connect()
        if self._session.auto_activate:
            self._application.activate()

        self._finder = ElementFinder(self._application, self._config)
        self._init_engine()
        logger.info("AgentLoop connected and ready.")
        return self

    def disconnect(self) -> None:
        """Disconnect from WeChat and stop the loop."""
        self._running = False
        self._application.disconnect()
        self._finder = None
        logger.info("AgentLoop disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._application.is_connected()

    @property
    def application(self) -> Application:
        return self._application

    @property
    def finder(self) -> ElementFinder:
        if self._finder is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._finder

    @property
    def router(self) -> SkillRouter:
        if self._router is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._router

    @property
    def healer(self) -> EnvironmentHealer:
        if self._healer is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return self._healer

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, poll_interval: float = 5.0) -> None:
        """Run the closed-loop agent continuously.

        Args:
            poll_interval: Seconds between each perception cycle.
        """
        self._running = True
        logger.info("AgentLoop started (poll_interval=%.1fs).", poll_interval)

        while self._running:
            try:
                self.step()
            except Exception as exc:
                logger.error("AgentLoop step failed: %s", exc)
                # Self-heal on error
                try:
                    self._healer.reset_ui_environment()
                except Exception:
                    pass
            time.sleep(poll_interval)

    def stop(self) -> None:
        """Signal the loop to stop."""
        self._running = False

    def step(self) -> None:
        """Execute a single closed-loop cycle.

        Step 1: Perceive — check for unread messages
        Step 2: Decide & Route — determine action
        Step 3: Execute — run skill or atomic tool
        Step 4: Validate & Reset — restore idle state
        """
        # Step 1: Perceive
        unread = self._perceiver.get_unread_messages()
        if not unread:
            logger.debug("No unread messages. Idle.")
            return

        logger.info("Perceived %d unread conversation(s).", len(unread))

        # Step 2 & 3: Decide and Execute (for each unread)
        for item in unread:
            contact = item.get("contact", "")
            logger.info("Processing unread from: %s", contact)
            # Default action: open chat (actual AI decision logic to be integrated)
            try:
                self._router.route("open_contact_chat", {"target": contact})
            except Exception as exc:
                logger.warning("Failed to process '%s': %s", contact, exc)

        # Step 4: Validate & Reset
        self._healer.reset_ui_environment()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _init_engine(self) -> None:
        """Initialize engine sub-components."""
        self._perceiver = Perceiver(self._application, self._config)
        self._router = SkillRouter()
        self._healer = EnvironmentHealer(self._application, self._finder, self._config)

        # Register Tier 2 atomic tools as fallback
        from wechat_auto.atomic.tools import AtomicUITools

        atomic = AtomicUITools(self._application, self._finder, self._config)
        self._router.set_atomic_tools(atomic)

        # Register Tier 1 skills
        self._register_skills()

    def _register_skills(self) -> None:
        """Register all Tier 1 skills with the router."""
        from wechat_auto.skills.messaging import MessagingSkill
        from wechat_auto.skills.emoji import EmojiSkill
        from wechat_auto.skills.quote import QuoteSkill
        from wechat_auto.skills.history import HistorySkill
        from wechat_auto.skills.contact import ContactSkill
        from wechat_auto.skills.moments import MomentsSkill

        # Initialize skills
        skills = [
            MessagingSkill(self._application, self._finder, self._config, self._session, self._healer),
            EmojiSkill(self._application, self._finder, self._config, self._session, self._healer),
            QuoteSkill(self._application, self._finder, self._config, self._session, self._healer),
            HistorySkill(self._application, self._finder, self._config, self._session, self._healer),
            ContactSkill(self._application, self._finder, self._config, self._session, self._healer),
            MomentsSkill(self._application, self._finder, self._config, self._session, self._healer),
        ]

        for skill in skills:
            self._router.register_skill(skill.name, skill.execute)
