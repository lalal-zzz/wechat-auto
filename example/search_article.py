"""公众号文章搜索示例

用法:
    python example/search_article.py 人工智能
    python example/search_article.py "深度学习教程"

功能:
    使用微信全局搜索（Ctrl+F）搜索公众号文章，
    收集并打印搜索结果列表（标题、公众号名、摘要）。

注意:
    使用全局搜索框（非通讯录搜索框），因为搜索的是文章不是联系人。

前提:
    1. 微信桌面端已登录并运行
"""

from __future__ import annotations

import sys
import logging

from wechat_auto import AgentLoop
from wechat_auto.config import WeChatConfig, SessionConfig
from wechat_auto.skills.channels import ChannelsSkill


def main():
    if len(sys.argv) < 2:
        print("用法: python example/search_article.py <关键词>")
        print("示例: python example/search_article.py 人工智能")
        sys.exit(1)

    keyword = sys.argv[1]

    config = WeChatConfig()
    session = SessionConfig(auto_activate=True)

    print("正在连接微信...")
    agent = AgentLoop(config=config, session=session)
    agent.connect()

    print(f'正在搜索公众号文章: "{keyword}"')
    skill = ChannelsSkill(
        agent.application, agent.finder, config, session, agent.healer
    )
    try:
        results = skill.search_official_article(keyword)

        if not results:
            print("未找到相关文章。")
        else:
            print(f"\n共找到 {len(results)} 篇文章:\n")
            print(f"{'序号':<6} {'公众号':<15} {'标题':<25} {'摘要'}")
            print("-" * 75)
            for i, article in enumerate(results, 1):
                account = article.get("account", "")
                title = article.get("title", "")[:22]
                summary = article.get("summary", "")[:30]
                print(f"{i:<6} {account:<15} {title:<25} {summary}")

    except Exception as e:
        print(f"✗ 搜索失败: {e}")
    finally:
        agent.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    main()
