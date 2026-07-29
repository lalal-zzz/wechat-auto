"""Custom exceptions for wechat-auto package."""


class WeChatAutoError(Exception):
    """Base exception for wechat-auto."""

    pass


class WeChatNotRunningError(WeChatAutoError):
    """Raised when WeChat application is not running."""

    pass


class WeChatNotFoundError(WeChatAutoError):
    """Raised when WeChat window cannot be found."""

    pass


class ChatNotFoundError(WeChatAutoError):
    """Raised when the specified chat conversation cannot be found."""

    def __init__(self, chat_name: str = ""):
        self.chat_name = chat_name
        super().__init__(f"Chat not found: {chat_name}" if chat_name else "Chat not found")


class ContactNotFoundError(WeChatAutoError):
    """Raised when the specified contact cannot be found."""

    def __init__(self, contact_name: str = ""):
        self.contact_name = contact_name
        super().__init__(f"Contact not found: {contact_name}" if contact_name else "Contact not found")


class SendMessageError(WeChatAutoError):
    """Raised when message sending fails."""

    pass


class ElementNotFoundError(WeChatAutoError):
    """Raised when a UI element cannot be located."""

    def __init__(self, element_name: str = ""):
        self.element_name = element_name
        super().__init__(f"UI element not found: {element_name}" if element_name else "UI element not found")


class OperationTimeoutError(WeChatAutoError):
    """Raised when an operation exceeds its timeout."""

    def __init__(self, operation: str = "", timeout: float = 0):
        self.operation = operation
        self.timeout = timeout
        msg = f"Operation timed out: {operation} (timeout={timeout}s)" if operation else "Operation timed out"
        super().__init__(msg)


class MomentsError(WeChatAutoError):
    """Raised when a Moments-related operation fails."""

    pass


class EmojiNotFoundError(WeChatAutoError):
    """Raised when a specific emoji or sticker cannot be found."""

    def __init__(self, emoji_name: str = ""):
        self.emoji_name = emoji_name
        super().__init__(f"Emoji not found: {emoji_name}" if emoji_name else "Emoji not found")


class SkillExecutionError(WeChatAutoError):
    """Raised when a Tier 1 skill execution fails."""

    def __init__(self, skill_name: str = "", detail: str = ""):
        self.skill_name = skill_name
        self.detail = detail
        msg = f"Skill '{skill_name}' failed: {detail}" if skill_name else "Skill execution failed"
        super().__init__(msg)


class AtomicToolError(WeChatAutoError):
    """Raised when a Tier 2 atomic UI tool operation fails."""

    def __init__(self, tool_name: str = "", detail: str = ""):
        self.tool_name = tool_name
        self.detail = detail
        msg = f"Atomic tool '{tool_name}' failed: {detail}" if tool_name else "Atomic tool failed"
        super().__init__(msg)


class EnvironmentResetError(WeChatAutoError):
    """Raised when the UI environment reset/self-heal fails."""

    def __init__(self, detail: str = ""):
        self.detail = detail
        msg = f"Environment reset failed: {detail}" if detail else "Environment reset failed"
        super().__init__(msg)
