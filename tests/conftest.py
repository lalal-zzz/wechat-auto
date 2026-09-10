"""Test fixtures for wechat-auto tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from wechat_auto.config import WeChatConfig, SessionConfig


@pytest.fixture
def config():
    """Return a default WeChatConfig for testing."""
    return WeChatConfig()


@pytest.fixture
def session():
    """Return a default SessionConfig for testing."""
    return SessionConfig(auto_activate=False)


@pytest.fixture
def mock_app():
    """Return a mocked Application instance."""
    app = MagicMock()
    app.config = WeChatConfig()
    app.is_connected.return_value = True
    return app


@pytest.fixture
def mock_finder():
    """Compatibility fixture for tests whose call shape predates BaseSkill cleanup."""
    return MagicMock()
