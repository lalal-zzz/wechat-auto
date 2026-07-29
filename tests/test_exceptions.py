"""Tests for wechat_auto.exceptions module."""

import pytest

from wechat_auto.exceptions import (
    WeChatAutoError,
    WeChatNotRunningError,
    WeChatNotFoundError,
    ChatNotFoundError,
    ContactNotFoundError,
    SendMessageError,
    ElementNotFoundError,
    OperationTimeoutError,
    MomentsError,
    EmojiNotFoundError,
    SkillExecutionError,
    AtomicToolError,
    EnvironmentResetError,
)


class TestExceptions:
    def test_base_exception(self):
        with pytest.raises(WeChatAutoError):
            raise WeChatAutoError("test error")

    def test_not_running_error(self):
        with pytest.raises(WeChatNotRunningError):
            raise WeChatNotRunningError("WeChat not running")

    def test_chat_not_found_with_name(self):
        err = ChatNotFoundError("张三")
        assert err.chat_name == "张三"
        assert "张三" in str(err)

    def test_chat_not_found_without_name(self):
        err = ChatNotFoundError()
        assert err.chat_name == ""
        assert "Chat not found" in str(err)

    def test_contact_not_found(self):
        err = ContactNotFoundError("李四")
        assert err.contact_name == "李四"

    def test_element_not_found(self):
        err = ElementNotFoundError("Button")
        assert err.element_name == "Button"

    def test_operation_timeout(self):
        err = OperationTimeoutError("send", 10.0)
        assert err.operation == "send"
        assert err.timeout == 10.0
        assert "10.0" in str(err)

    def test_emoji_not_found(self):
        err = EmojiNotFoundError("笑")
        assert err.emoji_name == "笑"
        assert "笑" in str(err)

    def test_hierarchy(self):
        """All exceptions inherit from WeChatAutoError."""
        for exc_cls in [
            WeChatNotRunningError,
            WeChatNotFoundError,
            ChatNotFoundError,
            ContactNotFoundError,
            SendMessageError,
            ElementNotFoundError,
            OperationTimeoutError,
            MomentsError,
            EmojiNotFoundError,
            SkillExecutionError,
            AtomicToolError,
            EnvironmentResetError,
        ]:
            assert issubclass(exc_cls, WeChatAutoError)

    def test_skill_execution_error(self):
        err = SkillExecutionError("send_text", "timeout")
        assert err.skill_name == "send_text"
        assert "send_text" in str(err)

    def test_atomic_tool_error(self):
        err = AtomicToolError("click", "element not found")
        assert err.tool_name == "click"
        assert "click" in str(err)

    def test_environment_reset_error(self):
        err = EnvironmentResetError("window stuck")
        assert err.detail == "window stuck"
        assert "window stuck" in str(err)
