from wechat_auto.config import SessionConfig, WeChatConfig


def test_current_defaults_are_hwnd_only():
    config = WeChatConfig()
    assert config.wechat_class_name == "Qt51514QWindowIcon"
    assert config.action_driver == "hwnd"
    assert config.keyboard_input_mode == "wmchar"
    assert not hasattr(config, "enable_legacy_skills")
    assert not hasattr(config, "backend")


def test_session_overrides():
    session = SessionConfig()
    session.set("key", 42)
    assert session.get("key") == 42
