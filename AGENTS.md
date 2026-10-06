# WeChat Auto 当前开发约束

本项目只支持 Windows 微信 4.x 当前架构，不保留微信 3.x、UIA 控件树或旧复合技能兼容。

## 架构

- `core/application.py`：纯 Win32 查找、激活和管理顶层 HWND。
- `actions/basic.py`：唯一 UI 动作入口。
- `primitives/keyboard_only.py`：通过 `WM_*` 消息执行点击、右键、滚轮、按键和输入。
- `primitives/vision.py`：只截图、OCR、识别和返回替代坐标，不执行动作。
- `backends/`：只读微信本地数据库。
- `storage/`：项目自己的离线 SQLite、表情语义和偏好目录。
- `actions/composite.py`：未来高级流程接口，暂不提供具体自动回复实现。

## 共用页面、搜索与收件人规则

- 所有 Skill 涉及 UI、联系人状态或回复时，先读取各自目录 `references/` 内随包提供的
  `UI_WORKFLOW_RULES.md`；页面类型和验收分别读取本 Skill 的
  `UI_PAGE_CATALOG.md`、`ACTION_VERIFICATION_MATRIX.md`。执行规则由相关 Skill 的
  `SKILL.md` 与 `references/` 维护；共用规则变更须同步实际依赖它的 Skill 随包文档。
  不再以 `docs/` 作为 Skill 执行规则的维护来源。
- 私聊优先通讯录定位→资料身份核验→进入聊天。通讯录搜索也可能是混合分区弹窗，
  只接受联系人分区精确候选；网络搜索、历史消息和同名群不能充当收件人。
- `username/wxid` 是本地身份，公开微信号是 `alias`，二者不能混作同一字段。
  标题、昵称或头像匹配不能单独证明稳定身份；缺少可核对字段必须停止。
- 一次 UI 搜索失败不证明删除。只有完整、不同的快照参与缺席分析；区分 missing、
  inferred_removed、confirmed_removed。保留历史，不自动加回好友或发消息探测关系。
- 发送前重新核验收件人、页面、输入区域与确切正文；确认令牌不能替代身份核验。
  基础 `send_text`/`open_chat` 接口不代表完整稳定身份链路已验收，未完成项见 WA-005。
- 静态 Markdown 是共用规则，不能当成动态坐标。窗口尺寸相同也可能发生内部布局变化。
- 窗口角色、分层页面、目标选择与恢复读取当前 Skill 的 `references/WINDOW_NAVIGATION.md`。
  联系人导航只在个人“联系人”分组下查找，先确认展开；不得点击“新的朋友”、企业联系人、
  公众号/服务号或自动转到混合搜索。无法定位时保存新截图，交给 Agent 复核。
- Agent 的图片框也必须经 BasicSkill 执行：绑定当前 HWND、页面、帧与短期单次 review；
  变化后重新测算。复核不允许发送、删除、下载或绕过公开微信号身份核验。

## 人员信息、Memory 与性格演化系统

这是所有分析功能共用的设计约束。当前已有资料、归档、紧凑 Markdown 版本、结构化
Claim/Event 与分析任务基础设施；具体人物结论需要外部 Agent 成功提交分析版本，
不能把基础设施实现当作全部人员分析与演化业务已完成。

### 1. 分析对象

统一使用 `Person` 概念，至少区分：

- `self`：当前微信账号本人，分析重点是自我表达、行为模式、决策、情绪、关系和成长。
- `contact`：联系人，分析重点是可观察的沟通方式、偏好、边界和关系变化。
- `group_member`：群成员，分析重点是特定群中的角色、活跃方式和互动关系。

同一个人必须使用稳定的 `person_id` 关联，不能只使用昵称。昵称、备注名、群昵称和微信号必须分别保存。

### 2. 个人资料字段

资料层必须区分当前值、历史值和来源，至少支持：

```text
wechat_id / wxid
alias
nickname
original_name
remark
display_name
nickname_prefix / nickname_core / nickname_suffix
group_display_name
real_name
gender
signature
avatar
background_image
first_seen_at
last_seen_at
last_profile_update_at
source
raw_profile
```

字段含义必须保持清晰：

- `original_name`：对方原始昵称或首次发现的名称。
- `nickname`：当前微信昵称。
- `remark`：用户为联系人设置的备注。
- `group_display_name`：联系人在特定群中的群昵称。
- `display_name`：当前场景用于展示的名称，优先级通常为 `remark`、`nickname`、`original_name`、`wechat_id`。
- 昵称前缀、主体和后缀应可拆分，不能把完整昵称当成唯一字段。

### 3. Markdown 是分析正文

人员 Memory、资料变化、性格分析和演化结论必须最终写入 Markdown；SQLite 只保存原始消息、媒体、索引、游标、任务状态和证据关联，不把分析正文隐藏在数据库 JSON 中。

建议目录：

```text
data/memory/
├── index.md
├── self/
│   ├── profile.md
│   ├── profile_history.md
│   ├── identity_signals.md
│   ├── personality.md
│   ├── communication.md
│   ├── values.md
│   ├── emotional_patterns.md
│   ├── relationship_patterns.md
│   ├── decision_style.md
│   ├── blind_spots.md
│   ├── goals.md
│   ├── growth.md
│   └── timeline.md
├── contacts/{person_id}/
│   ├── profile.md
│   ├── profile_history.md
│   ├── personality.md
│   ├── communication.md
│   ├── preferences.md
│   ├── relationship.md
│   └── timeline.md
├── groups/{group_id}/
│   ├── profile.md
│   ├── members.md
│   ├── member_roles.md
│   ├── communication_rules.md
│   ├── topics.md
│   └── timeline.md
└── relationships/{relationship_id}.md
```

每份文档必须包含可追踪的元数据，例如 `type`、`target_id`、`updated_at`、`source_range`、`analysis_version`、`confidence` 和 `status`。

### 4. 资料变化是分析信号

个性签名、昵称、头像、背景图、备注和群昵称不只是静态资料，必须形成时间序列：

```text
资料快照
    ↓
字段变化检测
    ↓
身份表达事件
    ↓
与聊天、朋友圈、群行为对齐
    ↓
更新人员 Memory 和演化分析
```

资料本身只能作为观察事实。不得仅凭一次昵称或签名变化断言失恋、抑郁、人格类型或其他心理结论。分析必须区分：

- `confirmed`：用户明确确认。
- `observed`：从资料或行为直接观察到。
- `inferred`：模型根据多条证据推断。
- `unknown`：证据不足，不能判断。

### 5. 自己的分析优先级

自己的人员分析必须是一等功能，不能只分析联系人。至少覆盖：

- 不同场景下的表达方式：私聊、工作群、陌生群、熟人关系、冲突场景。
- 沟通风格、信息处理、计划性、决策和行动模式。
- 情绪触发因素、常见反应和恢复方式。
- 价值观、目标、关系投入方式和边界。
- 反复出现的盲点、行为模式和成长变化。
- 个人资料、签名、昵称和头像变化与聊天行为变化的时间关联。

自己的分析必须允许用户确认、修改和否定。更新优先级为：

```text
用户明确修正 > 用户主动描述 > 长期重复行为 > 短期行为 > 模型推断
```

不得把 MBTI 或其他人格模型作为确定事实，不得进行心理疾病诊断。

### 6. 分析流水线

未来实现应遵循：

```text
只读数据库/事件
    ↓
统一消息、资料和实体规范化
    ↓
资料快照与变化检测
    ↓
按会话、联系人、群组和时间窗口分析
    ↓
生成观察事实、推断、证据和置信度
    ↓
更新 Markdown Memory
    ↓
生成时间线、关系变化和性格演化
    ↓
构造回复上下文或草稿
```

所有结论必须能回溯到消息、资料快照、朋友圈或用户确认；冲突结论不能静默覆盖，必须保留历史并标记有效期或状态。

### 7. 与其他功能的适配

所有功能都应读取统一 Memory，不得各自维护一套人物画像：

```text
聊天归档       → 消息、话题、事件、待办
朋友圈归档     → 兴趣、活动、身份表达变化
表情偏好       → 沟通风格、对象特定表达习惯
群聊分析       → 群规则、成员角色、关系结构
回复草稿       → 联系人/群 Memory、边界、语气和风险
动作执行       → 只调用 BasicSkill，并遵守显式确认
```

### 8. 更新边界

- 自动更新允许写入项目自己的 Markdown Memory 和 SQLite。
- 不得写入微信数据库、微信内存或私有协议。
- 修改微信真实昵称、备注或其他资料必须通过 `BasicSkill` 的明确 UI 动作，并取得用户确认，完成后重新读取验证。
- 发送、表情、点赞、评论和媒体联网下载仍必须显式确认。
- 资料、聊天和分析结果属于私人数据，不得提交 Git、上传或打印敏感内容。

## 硬性规则

联系人/朋友圈两路采集遵循当前 Skill 的 `references/CONTACT_COLLECTION.md`：本地 cached_only 与 UI
partial/restricted/stalled 分开保存。删除/拉黑按本人/对方方向记录；UI 搜索失败、
相册空白和权限提示不能推断好友删除。状态记录不能代替真实操作确认或稳定身份核验。
Memory schema 3 增量迁移保留历史。导航使用当前截图 OpenCV 图标和 OCR 文字框；
禁止按窗口尺寸加载固定坐标档案或恢复旧语义/行号坐标。当前个人相册动作仍需实机验收。

1. 新 UI 动作必须加入 `BasicSkill`，不得创建第二套驱动。
2. OCR 不能点击或输入；它产生的坐标必须交给 HWND 驱动执行。
3. 不注入、Hook、修改微信内存、写微信数据库或模拟私有协议。
4. 发送消息、表情、点赞、评论和媒体联网下载必须显式确认。
5. 新消息使用目录变化事件触发数据库增量同步，不高频轮询全部会话。
6. 高级 Skill 只能组合只读后端和 `BasicSkill`。
7. 旧版微信目录与微信 4.x `xwechat_files` 必须先区分；旧版记录优先通过微信官方“聊天记录迁移/备份与恢复”迁入当前 4.x，再由本项目读取。不得直接把旧版加密 `MSG*.db` 覆盖到 4.x 目录。
8. 合并不同来源时，消息 ID 必须包含会话、`local_id`、`sort_seq`、`server_id` 或消息类型等稳定字段；禁止只用 `local_id` 去重。
9. 找不到更早记录时，先只读审计旧账号目录、`Msg\Multi\bak` 和官方备份；不得删除、移动或覆盖原始源文件。
10. 图片/语音/视频/文件必须写入项目自己的 `message_media` BLOB 表；解密密钥只允许保存在本机 DPAPI 保护的 `data/.secrets/`，不得打印、上传或提交 Git。
11. 完整导入、旧源迁移、媒体补齐和增量同步都必须记录到 `docs/PROJECT_STATE.md` 与 `docs/HISTORY_SOURCE_AUDIT.md`，保留源范围、时间范围、行数、失败数和待办。

## 数据更新与 Skill 联动

- 所有归档、分析、人物画像、时间线、仪表盘和回复 Skill 先读取自身
  `references/SKILL_DATA_WORKFLOW.md` 随包副本，其 SKILL.md 必须写明自己的上游、下游与停止条件。
- 区分来源同步、归档索引、分析更新与 UI 当前帧。`sync.index_archives` 仅索引
  已有归档，不替代微信增量采集；`charts.refresh` 仅生成视图，不执行分析。
- 按用户请求选择历史快照、当前状态、回复或 UI 模式。历史分析说明固定证据范围；
  当前状态先同步相关来源，按月份→会话→人物/事件→图表更新受影响节点。
- 回复先读当前会话增量；身份、状态或相关分析无法核对时明确 unknown/stale，
  不把旧结论称作当前事实。新消息或上下文变化影响草稿时重建并重新确认。
- 联动是当前 Agent 读取其他 Skill 并使用其工具流程，不自动创建子代理、后台
  调度或跨任务消息，也不继承发送、修改资料和下载的确认权限。
- 交接稳定范围、真实覆盖、水位/输入版本、成功输出版本和缺口；相同输入不
  重复触发下游。不新增重复画像或大量结构化文本文件保存同一交接状态。
- Skill 约定不能当作 MCP 已有自动门禁；工具未提供的按范围新鲜度与依赖就绪
  查询不得伪造为已实现，运行时缺口见 WA-007。

## 验证

```powershell
python -m pytest tests -q
```

实机动作测试优先使用“文件传输助手”，默认只打开会话或准备草稿；没有明确确认不得发送。

## 环境与路径可移植性

- README、Skills、公共文档和命令示例使用 `python`，指当前已激活环境中的解释器；
  Windows 用户也可使用 `py -3`。不得写入开发者本机的 Python 绝对路径。
- 开发时先识别当前机器的虚拟环境与可用解释器。执行所需的本机路径只用于当前
  会话或被 Git 忽略的配置，不复制到公开文档、默认配置或源码常量。
- Python 子进程优先使用 `sys.executable`；项目文件使用相对路径或运行时解析的
  项目根目录，不硬编码用户名、盘符、桌面位置、微信账号或自定义安装目录。
- 微信安装路径从用户配置或系统安装目录解析；模型缓存与数据库目录在本机探测。
  不同机器的环境不得依赖某一开发者的目录结构。

## 发布范围

运行状态、来源审计、问题树和解决树仅保存在本机忽略的 docs/ 文件中。
需要记账时创建或更新这些本机文件，不加入 Git。公开文档只保留接口、规则、
使用限制与开发计划；截图、数据库、账号统计和成功/失败流水不随源码发布。
