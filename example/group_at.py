"""群聊@成员发送消息示例

用法:
    python example/group_at.py 工作群 张三 "请确认一下进度"
    python example/group_at.py 项目组 所有人 "明天开会"

功能:
    打开指定群聊，输入@符号触发成员选择弹窗，
    搜索并选择目标成员，然后输入消息内容并发送。

前提:
    1. 微信桌面端已登录并运行
    2. 群聊名称存在
    3. 被@的成员在群聊中
"""

from __future__ import annotations

import sys
import logging

from wechat_auto import AgentLoop
from wechat_auto.config import WeChatConfig, SessionConfig
from wechat_auto.skills.group_at import GroupAtSkill


def main():
    if len(sys.argv) < 4:
        print("用法: python example/group_at.py <群聊名称> <成员名称> <消息内容>")
        print("示例: python example/group_at.py 工作群 张三 请确认进度")
        print("      python example/group_at.py 项目组 所有人 明天开会")
        sys.exit(1)

    group = sys.argv[1]
    member = sys.argv[2]
    message = sys.argv[3]

    config = WeChatConfig()
    session = SessionConfig(auto_activate=True)

    print("正在连接微信...")
    agent = AgentLoop(config=config, session=session)
    agent.connect()

    print(f'正在群聊 "{group}" 中 @{member}: "{message}"')
    skill = GroupAtSkill(
        agent.application, agent.finder, config, session, agent.healer
    )
    try:
        skill.send_group_at_message(group, member, message)
        print(f"✓ 群聊@消息发送成功！")
    except Exception as e:
        print(f"✗ 发送失败: {e}")
    finally:
        agent.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    main()
