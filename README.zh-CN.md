# WeChat Auto — Windows 微信自动化、MCP 与 AI 长期记忆

[English](README.md) | **简体中文**

WeChat Auto 是面向 **Windows 微信 4.x / Weixin** 的本地自动化与聊天记忆项目，将只读微信数据、聊天记录归档、联系人资料、朋友圈、PaddleOCR mobile、传统计算机视觉、Win32 HWND 动作、SQLite、Markdown Memory 和 MCP（Model Context Protocol）连接起来。

目标是建立可追溯的聊天分析、月度总结、人物与关系时间线、增量长期记忆和回复草稿工作流。项目已有微信 AI 助手、聊天机器人和自动回复所需的部分基础设施；**完整的稳定收件人核验与自动回复发送链路仍在开发，不能视为无人值守自动聊天已经完成。**

**项目版本：** `0.8.1`；支持 Windows 微信 4.x、本地 stdio MCP 与仓库 Skills。

## 项目总览

| 模块 | 内容 |
|---|---|
| 桌面自动化 | 唯一 BasicSkill 入口，Win32 窗口管理，HWND 消息点击、滚动、按键和输入 |
| OCR 与页面识别 | 懒加载 PaddleOCR mobile，可选 RapidOCR；传统 CV 检测分隔线、搜索框、输入区和嵌入内容标签 |
| 聊天记录与媒体 | 消息归档、跨来源稳定 ID、SQLite 媒体 BLOB、导入与增量同步基础 |
| 联系人与身份 | username/wxid、昵称、备注、公开微信号分开保存；资料快照、缺席与恢复状态 |
| 朋友圈与资料 | 朋友圈正文与媒体元数据适配、签名/头像/昵称变化证据；具体字段取决于可读来源 |
| 长期 Memory | SQLite 保存短 Claim、Event、证据引用、依赖、水位；Markdown 保存完整摘要及历史版本 |
| 分析流水线 | 会话逐月分析任务、跨月汇总、人物场景画像、关系与事件时间线、增量失效传播 |
| Agent 与 MCP | 本地 stdio MCP、按任务裁剪上下文、按需展开证据、12 个仓库 Skills |
| 回复辅助 | 对象特定表达方式、紧凑上下文、草稿与逐次确认；完整身份/状态/结果门禁待贯通 |
| 可视化 | 本地离线 HTML 仪表盘、PNG 与 Mermaid 时间线导出基础 |

“已有实现”不表示全部场景通过实机验证。人物分析需要外部 Agent 成功提交分析版本，不能仅因创建了任务或目录就声称已完成人物画像。

**联系人与朋友圈两路采集：** 本地缓存刷新，以及身份核验后的逐人相册加载队列。
删除、拉黑/黑名单、恢复和朋友圈权限按方向保留证据历史，Memory schema 1/2
增量迁移到 3。采集受客户端可见范围和已实现控件限制，两路都不保证服务器完整历史。
命令、MCP、断点恢复与限制见[联系人两路采集](docs/CONTACT_COLLECTION.md)。

**窗口导航与失败恢复：** 同进程 HWND 盘点、分层页面识别、当前帧 OpenCV/OCR
定位、逐步后置验证。只在个人“联系人”分组下找人，排除“新的朋友”和全局混合搜索。
侧栏定位失败先重算，再交给 Agent 看当前图片，由 BasicSkill 校验后执行。
详见[窗口导航规则](docs/WINDOW_NAVIGATION.md)。

资料补采在身份核验后保存明确可见的签名、地区、来源等字段，缺失不覆盖旧值。
缓存媒体归档和单项确认下载提供格式校验与 BLOB 保存，不保证远程完整历史。
详见[朋友圈归档说明](docs/MOMENTS_ARCHIVE.md)。

## 全链路架构与存储

```text
只读微信数据 / 本地媒体 / HWND 截图
                 ↓
       归档、实体规范化、稳定身份
                 ↓
        wechat_memory.sqlite3
Claim / Event / 证据关系 / 版本 / 依赖 / 水位 / 任务
                 ↓
         紧凑完整 Markdown Memory
         current.md + 历史完整版本
                 ↓
          MCP 检索与上下文裁剪
                 ↓
         外部 Agent 分析 / 回复草稿
                 ↓
              逐次用户确认
                 ↓
        BasicSkill → HWND 动作 → 验证
```

| 层 | 职责 |
|---|---|
| 原始来源 / 本地归档 | 完整消息、媒体、朋友圈和资料快照 |
| wechat_memory.sqlite3 | 可查询短结论、身份、证据引用、结构化状态、版本和任务 |
| Markdown | 人和 Agent 可读的完整高密度分析正文及历史版本 |
| MCP | 返回当前任务相关上下文，需要时再展开证据 |

完整分析报告不隐藏在数据库嵌套 JSON 中。每个会话按自然月处理，跨月事件保持连续。新消息、补入旧消息、朋友圈或资料变化只更新受影响的月份和下游对象；任务失败保留上一成功版本。自己在不同私聊、工作群、朋友群中的表达方式与对方场景表现分别分析。

```text
data/
├── wechat_memory.sqlite3
└── memory/
    ├── conversations/{conversation_id}/
    │   ├── current.md
    │   ├── versions/
    │   └── months/{YYYY-MM}/
    │       ├── current.md
    │       └── versions/
    └── people/{person_id}/
        ├── current.md
        └── versions/
```

## 当前实现与验收边界

| 状态 | 范围 |
|---|---|
| 已有基础实现 | 只读适配、归档、媒体 BLOB、同步游标、资料历史、Claim/Event、Markdown 版本、分析任务、上下文工具与草稿确认 |
| 已枚举页面 | 49 类：聊天、通讯录、资料、菜单、编辑器、朋友圈、视频号、搜索、小程序及独立窗口；枚举不等于全部验收 |
| 正在贯通 | 不同搜索状态下稳定身份定位、消失联系人发送门禁、确认目标完整绑定、发送结果核验（WA-005） |
| 规划或部分实现 | 自动回复完整编排、全面人物分析模板、公众号信息处理与更多实机动作 |

接口验收规则见[动作验证矩阵](docs/ACTION_VERIFICATION_MATRIX.md)，后续工作见[开发路线图](docs/FUTURE_TODO.md)。

### 找联系人、删除状态与发送

私聊优先：**本地稳定身份 → 通讯录 → 联系人候选 → 资料核验 → 进入聊天**。通讯录搜索也可能返回混合弹窗，需要按当前分区区分联系人、群聊、聊天记录、服务号、小程序和网络建议。不能选择第一条，也不能仅凭昵称、头像或标题认证收件人。数据库 username/wxid 与资料卡显示的公开微信号 alias 是不同字段。

搜索不到不等于被删除。一次缺席、推测消失和确认删除分开处理，保留全部历史。自己删除联系人、对方删除自己、只删除聊天会话不能互相推断；不能通过发送消息探测好友关系，也不自动加回联系人。

完整发送链路仍待 **WA-005**。现有 open_chat、send_text 和回复确认工具不单独证明当前 UI 收件人正确。全部 Skills 引用同一份[页面与收件人规则](docs/UI_WORKFLOW_RULES.md)。

### 页面识别与动态布局

导航由当前截图 OpenCV 识别图标并给出坐标，已移除尺寸坐标档案和固定导航/行号/
语义坐标回退。实现说明见[当前帧控件定位](docs/DYNAMIC_UI_CONTROLS.md)。

OCR 只输出文字和框，不能操作窗口；传统 CV 观察分隔线、搜索框和输入区，动作仍由 BasicSkill 交给同一个 HWND 驱动。右侧搜一搜等内容可以和聊天输入区同时存在，关闭嵌入标签不能关闭微信主窗口。

分隔线检测使用聊天输入框右边缘辅助确认，区分网页卡片与窗口布局。这不代表任意窗口大小、所有拖动布局都已通过验证。详见[页面 OCR 说明](docs/PAGE_OCR.md)及[页面目录](docs/UI_PAGE_CATALOG.md)。

## 开始使用

在仓库根目录使用 PowerShell 和合适的 Windows Python 环境。仓库使用 src 布局，下面显式设置导入路径，不假定已经提供可安装的 Python 包。

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m pip install -r requirements-mcp.txt
# 可选：本地数据库适配
python -m pip install -r requirements-db.txt
# 可选：截图 OCR
python -m pip install -r requirements-ocr.txt
```

这些依赖文件对应各自集成，并非完整的一键 Windows 安装器。Win32 集成还需要相应 Python/运行时依赖。OCR 首次初始化可能下载模型，之后从本地缓存推理。

### 只读页面检查

```powershell
python scripts\recognize_wechat_page.py --list-pages
python scripts\recognize_wechat_page.py --geometry-only --output data\ocr\geometry
python scripts\recognize_wechat_page.py --engine paddle --output data\ocr\latest
```

后两条只截取当前微信窗口，不点击、不发送。截图、OCR 文字和本地 HTML 预览可能包含私人信息，只留在 data/。

### 初始化 Memory 与启动 MCP

所有本地非群联系人和可读朋友圈的一次离线刷新可运行
`python scripts\sync_all_contacts_moments.py`，保留旧记录并生成私人媒体清单，
不下载媒体、不证明当前好友关系。详见[全联系人朋友圈刷新](docs/MOMENTS_ARCHIVE.md)。

路径替换为实际存在的项目归档：

```powershell
python scripts\bootstrap_memory.py `
  --history-db data\wechat_history_complete.sqlite3 `
  --profiles-db data\wechat_contact_profiles.sqlite3 `
  --moments-db data\wechat_moments.sqlite3

python -m wechat_auto.mcp_server `
  --history-db data\wechat_history_complete.sqlite3 `
  --profiles-db data\wechat_contact_profiles.sqlite3 `
  --moments-db data\wechat_moments.sqlite3
```

初始化索引证据和创建分析任务，不会自动产生人物结论或执行完整 LLM 分析。首次选择有效私聊前五和群聊前五，覆盖它们全部可用月份；后续通过增量依赖只更新受影响对象。

由支持 MCP 的外部 Agent 连接 stdio 进程。服务不绑定特定大模型，外部模型的数据处理方式由其配置决定。需要操作已登录微信时才追加 `--with-wechat-runtime`；运行时工具具有额外依赖，完整稳定收件人发送仍待验收。

工具分组：sync.*、entities.*、claims.*、events.*、analysis.*、memory.*、evidence.*、charts.*、monitor.*、reply.*、actions.*、vision.*、status.*。实际可用工具取决于注入的后端和运行时组件。

## Skills 工作流

| Skill | 用途 |
|---|---|
| [base_op](skills/base_op/SKILL.md) | 共用操作规则与唯一 UI 动作入口 |
| [wechat-sync](skills/wechat-sync/SKILL.md) | 归档规范化、增量同步 |
| [wechat-monthly-analysis](skills/wechat-monthly-analysis/SKILL.md) | 每个会话逐月分析 |
| [wechat-conversation-summary](skills/wechat-conversation-summary/SKILL.md) | 跨月会话完整 Memory |
| [wechat-person-analysis](skills/wechat-person-analysis/SKILL.md) | 本人、联系人、群成员及不同场景分析 |
| [wechat-profile-moments](skills/wechat-profile-moments/SKILL.md) | 资料与朋友圈更新证据 |
| [wechat-timeline](skills/wechat-timeline/SKILL.md) | 长期事件与人物变化时间线 |
| [wechat-dashboard](skills/wechat-dashboard/SKILL.md) | 离线仪表盘与图表导出 |
| [wechat-reply-monitor](skills/wechat-reply-monitor/SKILL.md) | 单次监听、回复上下文与确认规则 |
| [wechat-identity-audit](skills/wechat-identity-audit/SKILL.md) | 稳定身份、缺席、恢复和合并审查 |
| [wechat-ui-navigation](skills/wechat-ui-navigation/SKILL.md) | HWND/页面选择、个人联系人分组、有界恢复、受限图片复核 |
| [wechat-memory-rebuild](skills/wechat-memory-rebuild/SKILL.md) | 用户修正、依赖失效与重建 |

Skills 是静态 Markdown 指令，不会自己变成后台服务；共用引用文件要随仓库提供。分析必须保留证据，区分 observed、confirmed、inferred、unknown；不能仅凭头像、签名或单条朋友圈断言人格、心理状态或进行心理疾病诊断。

## 开发、隐私与动作边界

```powershell
python -m pytest tests -q
# 项目记录的验证命令
python -m pytest tests -q
```

实机动作优先用文件传输助手。打开聊天或准备草稿不授权发送；消息、表情、点赞、评论、真实资料修改和联网媒体下载都需要明确确认。UI 动作不使用注入、Hook、微信数据库写入或私有消息协议。当前架构不保留微信 3.x 和 UIA 控件树兼容。

聊天数据库、媒体、截图、导出和密钥是本机私人数据，不提交或公开输出。密钥存于 DPAPI 保护的 data/.secrets/。项目不声称腾讯官方授权或“零封号风险”。

仓库目录：src/wechat_auto/ MCP 与必要运行实现、skills/ Agent 指令、scripts/ 本地工具、tests/ 回归、docs/ 接口规则与使用说明、data/ 被忽略的私人数据。运行流水与诊断记录仅留本机。

## 文档导航

- [架构](ARCHITECTURE.md) · [开发约束](AGENTS.md) · [环境说明](CLAUDE.md)
- [共用页面与收件人规则](docs/UI_WORKFLOW_RULES.md)
- [页面识别目录](docs/UI_PAGE_CATALOG.md) · [OCR 使用说明](docs/PAGE_OCR.md)
- [动作验证规则](docs/ACTION_VERIFICATION_MATRIX.md)
- [开发路线图](docs/FUTURE_TODO.md) · [搜索与实时消息设计](docs/SEARCH_AND_REALTIME_DESIGN.md)

## 关键词与检索主题

微信自动化、Windows 微信 4.x、微信 AI 助手、微信聊天机器人基础、微信自动回复草稿、微信 MCP 服务、LLM Agent、大模型代理、Agent Skills、PaddleOCR、PP-OCRv5 mobile、RapidOCR、OCR 文字识别、传统计算机视觉、Win32 HWND、桌面自动化、聊天记录归档、微信历史消息、聊天媒体备份、SQLite、本地数据库、Markdown Memory、长期记忆、证据溯源、上下文检索、上下文裁剪、增量同步、目录变化监听、月度聊天分析、跨月事件汇总、联系人稳定身份、wxid、联系人画像、群成员分析、群聊分析、朋友圈归档、资料快照、昵称签名头像变化、关系时间线、人物变化时间线、沟通风格、自我分析、场景画像、表情语义、表情偏好、离线仪表盘、DPAPI、逐次确认。

English topics: WeChat automation, Weixin automation, WeChat AI assistant, MCP server, Model Context Protocol, LLM agent, PaddleOCR, computer vision, Win32, HWND, SQLite, Markdown memory, long-term agent memory, chat history analysis, incremental sync, monthly conversation analysis, contact identity, WeChat Moments, relationship timeline, sticker preferences, offline dashboard, local-first data, confirmed actions.
