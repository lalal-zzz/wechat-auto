"""Exceptions used by the current HWND/database architecture."""


class WeChatAutoError(Exception):
    pass


class WeChatNotRunningError(WeChatAutoError):
    pass


class ChatNotFoundError(WeChatAutoError):
    def __init__(self, chat_name: str = ""):
        self.chat_name = chat_name
        super().__init__(f"Chat not found: {chat_name}" if chat_name else "Chat not found")


class SkillExecutionError(WeChatAutoError):
    pass
