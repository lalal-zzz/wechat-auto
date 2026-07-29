"""闭环引擎完整演示

用法:
    python example/full_loop_demo.py
    python example/full_loop_demo.py --interval 3        # 3秒轮询
    python example/full_loop_demo.py --once               # 只执行一次

功能:
    启动 AgentLoop 闭环引擎，持续轮询未读消息。
    发现未读消息后自动打开对应聊天窗口，执行完毕后自愈重置环境。

    这演示了完整的闭环工作流:
        Step 1. Perceive  — 扫描未读消息红点
        Step 2. Decide    — 路由到 open_contact_chat 技能
        Step 3. Execute   — 打开聊天窗口
        Step 4. Validate  — 关闭弹窗、清空搜索、切回主Tab

前提:
    1. 微信桌面端已登录并运行
    2. 有未读消息时会自动打开对应聊天
"""

from __future__ import annotations

import sys
import time
import signal
import logging

from wechat_auto import AgentLoop
from wechat_auto.config import WeChatConfig, SessionConfig


def main():
    # 解析参数
    poll_interval = 5.0
    run_once = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--interval" and i + 1 < len(args):
            poll_interval = float(args[i + 1])
            i += 2
        elif args[i] == "--once":
            run_once = True
            i += 1
        else:
            i += 1

    config = WeChatConfig()
    session = SessionConfig(auto_activate=True)

    print("正在连接微信...")
    agent = AgentLoop(config=config, session=session)
    agent.connect()
    print(f"已连接微信。已注册技能: {agent.router.available_skills}\n")

    # 注册 Ctrl+C 信号处理
    def signal_handler(sig, frame):
        print("\n正在停止闭环引擎...")
        agent.stop()

    signal.signal(signal.SIGINT, signal_handler)

    if run_once:
        # 只执行一次 step
        print("=== 执行单次闭环 ===")
        print("Step 1: 感知未读消息...")
        try:
            agent.step()
            print("✓ 单次闭环完成。")
        except Exception as e:
            print(f"✗ 闭环执行失败: {e}")
        finally:
            agent.disconnect()
            print("已断开连接。")
        return

    # 持续运行
    print(f"=== 启动持续轮询 (间隔 {poll_interval}s) ===")
    print("按 Ctrl+C 停止。\n")

    cycle = 0
    try:
        agent._running = True
        while agent._running:
            cycle += 1
            print(f"--- 第 {cycle} 轮 ---")

            # Step 1: Perceive
            unread = agent._perceiver.get_unread_messages()
            if not unread:
                print("  无未读消息，空闲等待。")
            else:
                print(f"  发现 {len(unread)} 个未读会话:")
                for item in unread:
                    contact = item.get("contact", "未知")
                    count = item.get("unread_count", 0)
                    preview = item.get("preview", "")
                    print(f"    - {contact} ({count}条未读): {preview}")

                # Step 2 & 3: Decide & Execute
                for item in unread:
                    contact = item.get("contact", "")
                    try:
                        print(f"  → 正在处理: {contact}")
                        agent._router.route("open_contact_chat", {"target": contact})
                        print(f"  ✓ 已打开: {contact}")
                    except Exception as e:
                        print(f"  ✗ 处理失败 ({contact}): {e}")

                # Step 4: Validate & Reset
                try:
                    agent._healer.reset_ui_environment()
                    print("  ✓ 环境已重置。")
                except Exception as e:
                    print(f"  ✗ 环境重置失败: {e}")

            time.sleep(poll_interval)

    except Exception as e:
        print(f"闭环引擎异常: {e}")
    finally:
        agent.disconnect()
        print("闭环引擎已停止，连接已断开。")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    main()
