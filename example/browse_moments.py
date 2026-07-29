"""朋友圈浏览与点赞示例

用法:
    python example/browse_moments.py              # 浏览最新3屏朋友圈
    python example/browse_moments.py --like 5      # 浏览并点赞最新5条
    python example/browse_moments.py --comment 0 "写得好！"  # 评论第1条

功能:
    打开朋友圈，滚动收集动态信息（作者、内容、时间），
    可选执行点赞或评论操作。

前提:
    1. 微信桌面端已登录并运行
"""

from __future__ import annotations

import sys
import logging

from wechat_auto import AgentLoop
from wechat_auto.config import WeChatConfig, SessionConfig
from wechat_auto.skills.moments import MomentsSkill


def main():
    # 解析参数
    like_count = 0
    comment_index = -1
    comment_text = ""
    scroll_times = 3

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--like" and i + 1 < len(args):
            like_count = int(args[i + 1])
            i += 2
        elif args[i] == "--comment" and i + 2 < len(args):
            comment_index = int(args[i + 1])
            comment_text = args[i + 2]
            i += 3
        elif args[i] == "--scroll" and i + 1 < len(args):
            scroll_times = int(args[i + 1])
            i += 2
        else:
            i += 1

    config = WeChatConfig()
    session = SessionConfig(auto_activate=True)

    print("正在连接微信...")
    agent = AgentLoop(config=config, session=session)
    agent.connect()

    skill = MomentsSkill(
        agent.application, agent.finder, config, session, agent.healer
    )

    try:
        # 浏览朋友圈
        print(f"正在浏览朋友圈（滚动 {scroll_times} 次）...")
        posts = skill.browse(scroll_times=scroll_times)

        if not posts:
            print("未获取到朋友圈动态。")
        else:
            print(f"\n共获取 {len(posts)} 条动态:\n")
            print(f"{'序号':<6} {'作者':<12} {'时间':<12} {'内容'}")
            print("-" * 70)
            for i, post in enumerate(posts):
                author = post.get("author", "")
                content = post.get("content", "")[:40]
                time_str = post.get("time", "")
                print(f"{i:<6} {author:<12} {time_str:<12} {content}")

        # 点赞
        if like_count > 0:
            print(f"\n正在点赞最新 {like_count} 条动态...")
            liked = skill.like_latest(count=like_count)
            print(f"✓ 成功点赞 {liked} 条动态。")

        # 评论
        if comment_index >= 0 and comment_text:
            print(f"\n正在评论第 {comment_index + 1} 条动态: \"{comment_text}\"")
            skill.comment_moment(post_index=comment_index, comment=comment_text)
            print("✓ 评论发送成功！")

        # 获取时间线（按小时过滤）
        print("\n正在获取最近 6 小时内的动态...")
        timeline = skill.get_my_timeline(limit=20, hours_range=6)
        print(f"最近 6 小时内有 {len(timeline)} 条动态。")

    except Exception as e:
        print(f"✗ 操作失败: {e}")
    finally:
        agent.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    main()
