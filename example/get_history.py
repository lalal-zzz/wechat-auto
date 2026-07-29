"""获取聊天记录示例

用法:
    python example/get_history.py 张三
    python example/get_history.py 张三 10

功能:
    打开指定聊天窗口，滚动获取最近 N 条聊天记录。
    包括发送者、消息内容和时间信息。

前提:
    1. 微信桌面端已登录并运行
    2. 联系人或群聊名称存在
"""

from __future__ import annotations

import sys
import logging

from wechat_auto import AgentLoop
from wechat_auto.config import WeChatConfig, SessionConfig
from wechat_auto.skills.history import HistorySkill


def main():
    if len(sys.argv) < 2:
        print("用法: python example/get_history.py <联系人/群名> [消息条数]")
        print("示例: python example/get_history.py 张三 20")
        sys.exit(1)

    contact = sys.argv[1]
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    config = WeChatConfig()
    session = SessionConfig(auto_activate=True)

    print("正在连接微信...")
    agent = AgentLoop(config=config, session=session)
    agent.connect()

    print(f'正在获取 "{contact}" 的最近 {count} 条聊天记录...')
    skill = HistorySkill(
        agent.application, agent.finder, config, session, agent.healer
    )
    try:
        messages = skill.get_messages(contact, count=count)

        if not messages:
            print("未获取到聊天记录。")
        else:
            print(f"\n共获取 {len(messages)} 条消息:\n")
            print(f"{'序号':<6} {'发送者':<12} {'内容'}")
            print("-" * 60)
            for i, msg in enumerate(messages, 1):
                sender = msg.get("sender", "")
                content = msg.get("content", "")[:50]
                print(f"{i:<6} {sender:<12} {content}")

        # 获取最新一条消息
        latest = skill.get_latest_message(contact)
        if latest:
            print(f"\n最新消息: {latest.get('content', '')[:80]}")
    except Exception as e:
        print(f"✗ 获取失败: {e}")
    finally:
        agent.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    main()
