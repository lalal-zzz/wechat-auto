"""Tests for wechat_auto.config module."""

from wechat_auto.config import WeChatConfig, SessionConfig


class TestWeChatConfig:
    def test_defaults(self):
        cfg = WeChatConfig()
        assert cfg.wechat_class_name == "Qt51514QWindowIcon"
        assert cfg.wechat_title == "微信"
        assert cfg.backend == "uia"  # uia required for WeChat Qt5/DirectUI
        assert cfg.auto_start is False
        assert cfg.default_timeout == 10.0
        assert cfg.max_retries == 3

    def test_custom_values(self):
        cfg = WeChatConfig(backend="win32", default_timeout=20.0)
        assert cfg.backend == "win32"
        assert cfg.default_timeout == 20.0


class TestSessionConfig:
    def test_defaults(self):
        sess = SessionConfig()
        assert sess.auto_activate is True
        assert sess.minimize_after is False
        assert sess.silent_mode is False

    def test_overrides(self):
        sess = SessionConfig()
        sess.set("custom_key", 42)
        assert sess.get("custom_key") == 42
        assert sess.get("missing", "default") == "default"
