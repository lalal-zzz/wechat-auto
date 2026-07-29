"""UIA 控件树提取示例

用法:
    python example/get_ui_tree.py                    # 提取主窗口控件树
    python example/get_ui_tree.py 朋友圈            # 提取朋友圈窗口控件树

功能:
    使用 Tier 2 原子工具提取当前微信窗口的完整 UIA 控件树，
    以 JSON 格式打印。用于调试 UI 自动化时定位控件。

前提:
    1. 微信桌面端已登录并运行
"""

from __future__ import annotations

import sys
import json
import logging

from wechat_auto import AgentLoop
from wechat_auto.config import WeChatConfig, SessionConfig
from wechat_auto.atomic.tools import AtomicUITools


def main():
    window_title = sys.argv[1] if len(sys.argv) > 1 else None

    config = WeChatConfig()
    session = SessionConfig(auto_activate=False)

    print("正在连接微信...")
    agent = AgentLoop(config=config, session=session)
    agent.connect()

    atomic = AtomicUITools(agent.application, agent.finder, config)

    target = window_title or "微信主窗口"
    print(f"正在提取控件树: {target}")
    try:
        tree = atomic.get_ui_tree(window_title=window_title)

        # 统计控件数
        def count_controls(controls):
            total = len(controls)
            for ctrl in controls:
                if "children" in ctrl:
                    total += count_controls(ctrl["children"])
            return total

        total = count_controls(tree.get("controls", []))
        print(f"窗口标题: {tree.get('window_title', '')}")
        print(f"窗口区域: {tree.get('rect', {})}")
        print(f"顶层控件数: {len(tree.get('controls', []))}")
        print(f"总控件数(含子控件): {total}\n")

        # 打印完整树（截断显示）
        tree_str = json.dumps(tree, ensure_ascii=False, indent=2)
        if len(tree_str) > 5000:
            print(tree_str[:5000])
            print(f"\n... (已截断，完整输出共 {len(tree_str)} 字符)")
        else:
            print(tree_str)

    except Exception as e:
        print(f"✗ 提取控件树失败: {e}")
    finally:
        agent.disconnect()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    main()
