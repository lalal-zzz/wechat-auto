"""获取未读消息示例

用法:
    python example/get_unread.py

功能:
    扫描微信会话列表中的未读消息，打印出联系人名称、未读条数和消息预览。
    这对应闭环引擎的 Step 1 (Perceive)。

前提:
    1. 微信桌面端已登录并运行
"""

from __future__ import annotations

import logging

from wechat_auto import AgentLoop
from wechat_auto.config import WeChatConfig, SessionConfig
from wechat_auto.engine.perceiver import Perceiver


def main():
    config = WeChatConfig()
    session = SessionConfig(auto_activate=False)  # 不强制激活窗口

    print("正在连接微信...")
    agent = AgentLoop(config=config, session=session)
    agent.connect()
    print("已连接微信。\n")

    # 使用 Perceiver 扫描未读消息
    perceiver = Perceiver(agent.application, config)
    print("正在扫描未读消息...")
    unread = perceiver.get_unread_messages()

    if not unread:
        print("✓ 没有未读消息。")
    else:
        print(f"发现 {len(unread)} 个未读会话:\n")
        print(f"{'序号':<6} {'联系人':<15} {'未读数':<8} {'预览'}")
        print("-" * 60)
        for i, item in enumerate(unread, 1):
            contact = item.get("contact", "未知")
            count = item.get("unread_count", 0)
            preview = item.get("preview", "")
            print(f"{i:<6} {contact:<15} {count:<8} {preview}")

    agent.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    main()
