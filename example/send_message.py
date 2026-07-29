"""发送文本消息示例

用法:
    python example/send_message.py 张三 "你好，这是自动发送的消息"

前提:
    1. 微信桌面端已登录并运行
    2. 联系人 "张三" 在通讯录中存在
"""

from __future__ import annotations

import sys
import logging

from wechat_auto import AgentLoop
from wechat_auto.config import WeChatConfig, SessionConfig


def main():
    if len(sys.argv) < 3:
        print("用法: python example/send_message.py <联系人名称> <消息内容>")
        print("示例: python example/send_message.py 张三 你好")
        sys.exit(1)

    contact = sys.argv[1]
    message = sys.argv[2]

    # 配置
    config = WeChatConfig()
    session = SessionConfig(auto_activate=True)

    # 连接微信
    print(f"正在连接微信...")
    agent = AgentLoop(config=config, session=session)
    agent.connect()
    print(f"已连接微信，当前窗口: {agent.application.get_window_rect()}")

    # 通过路由器发送消息
    print(f'正在向 "{contact}" 发送消息: "{message}"')
    try:
        agent.router.route("send_text_message", {
            "contact": contact,
            "message": message,
        })
        print("✓ 消息发送成功！")
    except Exception as e:
        print(f"✗ 发送失败: {e}")
    finally:
        agent.disconnect()
        print("已断开连接。")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    main()
