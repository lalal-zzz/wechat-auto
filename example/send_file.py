"""发送图片/文件示例

用法:
    python example/send_file.py 张三 C:\\path\\to\\image.png
    python example/send_file.py 张三 C:\\path\\to\\document.pdf

前提:
    1. 微信桌面端已登录并运行
    2. 文件路径存在
"""

from __future__ import annotations

import sys
import os
import logging

from wechat_auto import AgentLoop
from wechat_auto.config import WeChatConfig, SessionConfig
from wechat_auto.skills.messaging import MessagingSkill


def main():
    if len(sys.argv) < 3:
        print("用法: python example/send_file.py <联系人名称> <文件路径>")
        print("示例: python example/send_file.py 张三 C:\\\\Pictures\\\\photo.png")
        sys.exit(1)

    contact = sys.argv[1]
    file_path = sys.argv[2]

    if not os.path.isfile(file_path):
        print(f"✗ 文件不存在: {file_path}")
        sys.exit(1)

    config = WeChatConfig()
    session = SessionConfig(auto_activate=True)

    print("正在连接微信...")
    agent = AgentLoop(config=config, session=session)
    agent.connect()
    print(f"已连接微信。")

    # 直接使用 MessagingSkill 发送文件
    print(f'正在向 "{contact}" 发送文件: {file_path}')
    skill = MessagingSkill(
        agent.application, agent.finder, config, session, agent.healer
    )
    try:
        # 判断是图片还是普通文件
        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
            skill.send_image(contact, file_path)
            print("✓ 图片发送成功！")
        else:
            skill.send_file(contact, file_path)
            print("✓ 文件发送成功！")
    except Exception as e:
        print(f"✗ 发送失败: {e}")
    finally:
        agent.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    main()
