# WeChat Auto — 双层闭环 AI Agent 系统架构文档

## 1. 系统总览

本系统是一个基于 Windows 桌面端微信的无人值守全自动化 AI Agent 代理系统。采用原生 UIA（UI Automation）控件树解析，结合双层动作空间与闭环引擎实现自我感知、自动决策、精准执行与状态归位。

```
                    ┌─────────────────────────────────────────────────┐
                    │         AgentLoop (闭环引擎 / Brain)             │
                    │   Perceive → Decide → Execute → Validate/Reset  │
                    └────────────────────────┬────────────────────────┘
                                             │
                         ┌───────────────────┴───────────────────┐
                         ▼                                       ▼
             ┌───────────────────────┐              ┌───────────────────────┐
             │  Tier 1: skills/      │              │  Tier 2: atomic/      │
             │  高层复合技能包        │   降级兜底    │  原生UIA原子工具集     │
             │  (90% 日常场景)       │ ──────────▶  │  (10% 边缘场景)       │
             └───────────────────────┘              └───────────────────────┘
                         │                                       │
                         └───────────────────┬───────────────────┘
                                             ▼
                    ┌─────────────────────────────────────────────────┐
                    │           微信桌面端 UI 交互界面                  │
                    └─────────────────────────────────────────────────┘
```

---

## 2. 闭环引擎 (engine/)

闭环引擎是系统的"大脑"，负责编排整个自动化工作流。

### 2.1 模块组成

| 文件 | 类 | 职责 |
|------|-----|------|
| `engine/loop.py` | `AgentLoop` | 主循环编排：连接管理、组件初始化、持续轮询 |
| `engine/perceiver.py` | `Perceiver` | Step 1 感知：扫描未读消息红点与标记 |
| `engine/router.py` | `SkillRouter` | Step 2 决策路由：优先 Tier1，失败降级 Tier2 |
| `engine/healer.py` | `EnvironmentHealer` | Step 4 自愈：关闭弹窗、清空搜索、切回主Tab |

### 2.2 闭环工作流

```
Step 1. Perceive (感知)
    Perceiver.get_unread_messages() → 扫描会话列表未读标记
         │
         ▼
Step 2. Decide & Route (决策路由)
    SkillRouter.route(intent, params)
    ├── 匹配 Tier 1 技能 → 直接执行
    └── Tier 1 失败 → 降级 Tier 2 原子工具
         │
         ▼
Step 3. Execute (执行)
    ├── Tier 1: skill.execute(**params) — 一步到位
    └── Tier 2: atomic_tools.click/input/scroll... — 逐步操控
         │
         ▼
Step 4. Validate & Reset (校验与自愈)
    EnvironmentHealer.reset_ui_environment()
    → 关闭 SNSWnd/TopStoryWnd/表情面板
    → Esc 清空搜索残留
    → 切回主消息 Tab
    → 恢复空闲状态，等待下一次循环
```

### 2.3 调用关系

```
AgentLoop
 ├── Perceiver          (感知层)
 ├── SkillRouter        (路由层)
 │    ├── skills/*      (Tier 1 注册表)
 │    └── AtomicUITools (Tier 2 兜底)
 └── EnvironmentHealer  (自愈层)
```

---

## 3. Tier 1 技能清单 (skills/)

每个技能继承 `BaseSkill`，通过 `execute(**params)` 统一入口调用，内部自动触发环境复位。

| 技能类 | name 标识 | 功能 | 状态 |
|--------|-----------|------|------|
| `MessagingSkill` | `send_text_message` | 发送文本/图片/文件 | 已实现 |
| `EmojiSkill` | `send_builtin_sticker` | 发送内置/自定义表情 | 已实现 |
| `QuoteSkill` | `send_quoted_message` | 引用回复/转发/复制消息 | 已实现 |
| `HistorySkill` | `get_chat_history` | 聊天记录检索与滚动提取 | 已实现 |
| `ContactSkill` | `open_contact_chat` | 通讯录精准搜索与打开聊天 | 已实现 |
| `MomentsSkill` | `like_moment` | 朋友圈点赞/浏览 | 已实现 |
| `MomentsSkill` | `comment_moment` | 朋友圈评论 | 已实现 |
| `MomentsSkill` | `publish_moment` / `get_friend_moments` | 朋友圈发布/好友动态 | 桩(NotImplemented) |
| `UnreadSkill` | `get_unread_messages` | 未读消息队列检查 | 已实现 |
| `GroupAtSkill` | `send_group_at_message` | 群聊@成员回复 | 已实现 |
| `ChannelsSkill` | `search_official_article` | 公众号文章/视频号检索 | 已实现 |

### 3.1 技能基类 (BaseSkill)

```python
class BaseSkill:
    name: str = "base_skill"

    def __init__(self, application, finder, config, session, healer=None): ...

    def execute(self, **params) -> Any:
        """统一入口，finally 中自动调用 healer.reset_ui_environment()"""
        try:
            return self._run(**params)
        finally:
            self._healer.reset_ui_environment()

    def _run(self, **params) -> Any:
        """子类实现具体逻辑"""
        raise NotImplementedError
```

---

## 4. Tier 2 原子工具清单 (atomic/)

当 Tier 1 技能失败或遇到未知界面时，AI 降级使用以下 7 个原子工具直接操控 UIA 控件。

| # | 方法签名 | 功能 |
|---|----------|------|
| 1 | `get_ui_tree(window_title=None) -> dict` | 提取窗口 UIA 控件树 JSON |
| 2 | `click(component_id: str)` | 点击指定控件 |
| 3 | `input_text(component_id: str, text: str)` | 向输入框写入文本 |
| 4 | `right_click(component_id: str)` | 右键点击（弹出上下文菜单） |
| 5 | `scroll(component_id: str, direction: str, distance: int)` | 滚动列表/Feed |
| 6 | `send_keyboard_shortcut(key_shortcut: str)` | 发送按键组合 (^v, {ENTER}, {ESC}) |
| 7 | `close_window(window_id: str)` | 强制关闭子窗口 |

---

## 5. 模块依赖关系

```
wechat_auto/
├── engine/
│   ├── loop.py ──────────▶ core/application.py
│   │                   ──▶ ui/finder.py
│   │                   ──▶ engine/perceiver.py
│   │                   ──▶ engine/router.py
│   │                   ──▶ engine/healer.py
│   │                   ──▶ atomic/tools.py
│   │                   ──▶ skills/*
│   ├── router.py ────────▶ exceptions.py
│   └── healer.py ────────▶ ui/finder.py
│
├── skills/
│   ├── base.py ──────────▶ core/application.py, ui/finder.py, config.py
│   ├── messaging.py ─────▶ utils/clipboard.py, utils/keyboard.py
│   ├── emoji.py ─────────▶ utils/retry.py
│   ├── quote.py ─────────▶ utils/clipboard.py, utils/keyboard.py
│   ├── history.py ───────▶ utils/clipboard.py, utils/keyboard.py
│   ├── contact.py ───────▶ utils/clipboard.py, utils/keyboard.py
│   └── moments.py ───────▶ utils/keyboard.py
│
├── atomic/
│   └── tools.py ─────────▶ ui/finder.py, config.py, exceptions.py
│
├── core/
│   └── application.py ───▶ config.py, exceptions.py (pywinauto)
│
├── ui/
│   └── finder.py ────────▶ config.py, exceptions.py
│
└── utils/
    ├── clipboard.py ─────▶ (pyperclip, PIL)
    ├── keyboard.py ──────▶ (pywinauto)
    └── retry.py ─────────▶ (stdlib)
```

---

## 5.1 端到端示例脚本 (example/)

`example/` 目录包含 9 个可独立运行的脚本，连接真实微信桌面端进行端到端测试：

| 脚本 | 功能 | 运行示例 |
|------|------|----------|
| `send_message.py` | 发送文本消息 | `python example/send_message.py 文件传输助手 "你好"` |
| `send_file.py` | 发送图片/文件 | `python example/send_file.py 文件传输助手 photo.png` |
| `get_unread.py` | 扫描未读消息 | `python example/get_unread.py` |
| `get_history.py` | 获取聊天记录 | `python example/get_history.py 文件传输助手 20` |
| `browse_moments.py` | 朋友圈浏览/点赞 | `python example/browse_moments.py --like 3` |
| `group_at.py` | 群聊@成员 | `python example/group_at.py 群名 成员名 "消息"` |
| `search_article.py` | 公众号文章搜索 | `python example/search_article.py 关键词` |
| `get_ui_tree.py` | UIA控件树提取 | `python example/get_ui_tree.py` |
| `full_loop_demo.py` | 闭环引擎完整演示 | `python example/full_loop_demo.py --once` |

> 运行前需确保微信桌面端已登录运行。使用 `python` 或配置好的 Python 环境。

---

## 5.2 单元测试 (tests/)

| 测试文件 | 覆盖模块 | 测试数 |
|----------|----------|--------|
| `test_config.py` | `config.py` | 6 |
| `test_exceptions.py` | `exceptions.py` | 8 |
| `test_retry.py` | `utils/retry.py` | 7 |
| `test_messaging.py` | `skills/messaging.py` | 4 |
| `test_atomic.py` | `atomic/tools.py` | 28 |
| `test_healer.py` | `engine/healer.py` | 18 |
| `test_perceiver.py` | `engine/perceiver.py` | 20 |
| `test_router.py` | `engine/router.py` | 14 |
| `test_skills.py` | `skills/*` 全部技能 | 45 |
| `test_utils.py` | `utils/clipboard.py`, `utils/keyboard.py` | 30 |

运行命令：`python -m pytest tests/ -v`

---

## 6. 扩展指南：新增一个 Tier 1 技能

以新增"撤回消息"技能为例：

### Step 1: 创建技能文件

`src/wechat_auto/skills/recall.py`:

```python
from wechat_auto.skills.base import BaseSkill
from typing import Any

class RecallSkill(BaseSkill):
    name = "recall_message"

    def _run(self, **params) -> Any:
        contact = params.get("contact", "")
        message_index = params.get("message_index", -1)
        return self.recall(contact, message_index)

    def recall(self, contact: str, message_index: int = -1) -> None:
        self._activate()
        self._open_chat(contact)
        # ... 右键消息 → 点击"撤回" ...
```

### Step 2: 注册到 skills/__init__.py

```python
from wechat_auto.skills.recall import RecallSkill
__all__ = [..., "RecallSkill"]
```

### Step 3: 在 AgentLoop 中注册

`engine/loop.py` 的 `_register_skills()` 方法中添加：

```python
from wechat_auto.skills.recall import RecallSkill
skills.append(RecallSkill(app, finder, cfg, session, healer))
```

> **注意**：`_register_skills()` 中注册的技能会自动加入 `SkillRouter` 的路由表。

---

## 7. 项目目录结构（见上）

```
wechat-auto/
├── src/wechat_auto/
│   ├── core/application.py     # 微信连接管理（pywinauto）
│   ├── ui/finder.py           # UIA控件查找与导航
│   ├── config.py              # 配置（窗口标题、延迟、类名等）
│   ├── exceptions.py           # 自定义异常
│   ├── engine/
│   │   ├── loop.py            # AgentLoop 主循环
│   │   ├── perceiver.py       # 未读消息感知
│   │   ├── router.py           # 技能路由（Tier1→Tier2降级）
│   │   └── healer.py           # 环境自愈（独立容错）
│   ├── skills/                # Tier 1: 9个已实现技能
│   ├── atomic/tools.py        # Tier 2: 7个原子工具
│   └── utils/                 # clipboard, keyboard, retry
├── example/                   # 9个端到端示例脚本
├── tests/                     # 单元测试（180+ tests）
├── agents.md                  # 本文档
├── CLAUDE.md                  # 开发环境指南
└── README.md                  # 系统规格说明书
```

### Step 4: 调用

```python
agent.router.route("recall_message", {"contact": "张三", "message_index": -1})
```

---

## 8. 核心设计原则

1. **防混淆导航**：查联系人/群时强制使用通讯录专属搜索框；搜文章/视频时使用全局搜索框。
2. **状态强制归位**：任何技能执行后（无论成功或失败），`BaseSkill.execute()` 的 finally 块必定触发 `reset_ui_environment()`。Healer 各步骤独立容错，单步失败不阻断后续复位。
3. **分级降级**：90% 通用任务通过 Tier 1 瞬间完成（省 Token、高稳定）；10% 边缘场景由 Tier 2 控件字典兜底，确保系统绝不挂起。
4. **联系人搜索优先级**：`MessagingSkill._open_chat()` 先尝试通讯录搜索框精确匹配；若未找到（如系统联系人"文件传输助手"），自动回退全局搜索框。
