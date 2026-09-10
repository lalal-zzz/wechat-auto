from wechat_auto.exceptions import (
    ChatNotFoundError, SkillExecutionError, WeChatAutoError, WeChatNotRunningError,
)


def test_current_exception_hierarchy():
    assert issubclass(WeChatNotRunningError, WeChatAutoError)
    assert issubclass(ChatNotFoundError, WeChatAutoError)
    assert issubclass(SkillExecutionError, WeChatAutoError)
    assert "张三" in str(ChatNotFoundError("张三"))
