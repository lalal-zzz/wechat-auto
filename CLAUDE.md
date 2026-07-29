# CLAUDE.md — 开发环境指南

## 项目概述

WeChat Auto 是基于 Windows 桌面端微信的无人值守全自动化 AI Agent 系统。
采用 UIA 控件树解析 + 双层动作空间（Tier 1 技能包 + Tier 2 原子工具）+ 闭环引擎。

## 环境要求

- **OS**: Windows 10/11（需支持 UIA）
- **Python**: 3.9+（开发环境使用 `python`）
- **微信桌面端**: 需已登录运行（窗口标题"微信"，类名 `WeChatMainWndForPC` 或 `Qt51514QWindowIcon`）

## 安装依赖

```powershell
python -m pip install pywinauto pyperclip pillow pytest
```

## 项目结构

```
wechat-auto/
├── src/wechat_auto/          # 核心库
│   ├── core/application.py   # 微信连接（pywinauto backend=win32）
│   ├── ui/finder.py          # UIA 控件查找、搜索、导航
│   ├── config.py             # 配置（窗口标题、延迟、popup类名等）
│   ├── exceptions.py         # 自定义异常
│   ├── engine/               # 闭环引擎
│   │   ├── loop.py           # AgentLoop 主循环
│   │   ├── perceiver.py      # 未读消息感知
│   │   ├── router.py         # 技能路由（Tier1→Tier2降级）
│   │   └── healer.py         # 环境自愈（独立容错）
│   ├── skills/               # Tier 1: 9个已实现技能
│   ├── atomic/tools.py       # Tier 2: 7个原子工具
│   └── utils/                # clipboard, keyboard, retry
├── example/                  # 9个端到端示例脚本
├── tests/                    # 单元测试（180+ tests）
├── agents.md                 # 架构文档
├── CLAUDE.md                 # 本文件
└── README.md                 # 系统规格说明书
```

## 运行测试

```powershell
# 全部单元测试
python -m pytest tests/ -v

# 单个测试文件
python -m pytest tests/test_skills.py -v
```

## 运行示例脚本

确保微信已登录运行，然后：

```powershell
# 设置环境
cd <local-path>
$env:PYTHONIOENCODING="utf-8"

# 扫描未读消息
python example/get_unread.py

# 发送文本消息（文件传输助手是安全测试目标）
python example/send_message.py 文件传输助手 "测试消息"

# 闭环引擎单次运行
python example/full_loop_demo.py --once

# 提取UIA控件树（调试用）
python example/get_ui_tree.py
```

## 开发规范

1. **联系人搜索**: 必须先走通讯录搜索框；找不到时回退全局搜索（`MessagingSkill._open_chat`）
2. **状态归位**: 技能执行后 `BaseSkill.execute()` 的 finally 必定调用 `healer.reset_ui_environment()`
3. **Healer 容错**: 每个自愈步骤独立 try/except，单步失败不阻断后续
4. **编码**: 所有脚本运行时需设置 `PYTHONIOENCODING=utf-8`（Windows 中文环境）
5. **PowerShell**: 不支持 `&&`，用 `;` 分隔命令

## 新增技能流程

1. 在 `src/wechat_auto/skills/` 创建技能文件，继承 `BaseSkill`
2. 实现 `_run(**params)` 方法
3. 在 `engine/loop.py` 的 `_register_skills()` 中注册
4. 在 `skills/__init__.py` 中导出
5. 编写对应测试到 `tests/`
