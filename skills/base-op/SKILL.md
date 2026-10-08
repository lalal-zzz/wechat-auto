---
name: base-op
description: 微信自动化与记忆分析的本地 LLM Agent 操作规范，适用于此仓库内的微信采集、分析、回复草稿和 UI 操作。
metadata:
  short-description: 微信自动化与记忆分析的本地 Agent 操作规范
---

# 基础操作 Skill

此 Skill 说明 Agent 如何使用仓库能力。Python 实现位于 `src/wechat_auto/`，不能把 Skill 目录当作 Python 包。

## 架构与数据流

- `core/application.py` 通过 Win32 管理顶层 HWND。
- `actions/basic.py` 是唯一 UI 动作入口；`primitives/keyboard_only.py` 发送允许的 `WM_*` 消息。
- `primitives/vision.py` 只负责截图、OCR、识别和提供当前帧坐标，不执行动作。
- `backends/` 只读微信本地数据库；`storage/` 写入项目自己的 SQLite、Memory 和偏好数据。
- 高级流程只组合只读后端和 BasicSkill，不得另建驱动。

按此顺序处理：只读读取本地数据 → 通过项目存储层写入规范化记录/游标/分析输入 → Agent 分析上下文、联系人、关系、偏好、事件和草稿 → 涉及 UI 时仅调用 BasicSkill。数据库同步不调用 OCR；CV/OCR 只能观察和验收，不能自行点击或输入。

## 关键安全边界

- 仅支持 Windows 微信 4.x 当前架构，不增加微信 3.x、UIA 控件树、pywinauto 动作、物理鼠标/键盘回退、注入、Hook、私有协议或微信数据库写入。
- 发送消息/表情、点赞/评论和联网下载媒体必须取得明确确认。确认必须对应确切对象、内容和单次动作；分析、定时或历史确认不授权本次发送。
- 区分旧版 `WeChat Files` 与 4.x `xwechat_files`。旧记录优先用微信官方迁移/备份恢复；不得将旧加密数据库覆盖到 4.x。
- 多来源消息 ID 必须包含会话及 `local_id`、`sort_seq`、`server_id`、消息类型等稳定字段；不得只凭 `local_id` 去重。
- 找不到旧记录时只读审计旧账号目录、`Msg/Multi/bak` 和官方备份；不移动、删除或覆盖原件。
- 媒体写入项目自己的 `message_media` BLOB 表；解密密钥只保存在本机 DPAPI 保护的 `data/.secrets/`，不得打印、上传或提交。
- 新消息依赖目录变化事件触发增量同步，不高频轮询所有会话。
- 不提交 `data/`、聊天导出、截图、日志或密钥。分析正文进入约定的 Markdown Memory，SQLite 保存原始消息、索引、游标、任务和证据关联。

## 运行前核对

需要描述或实现未完成能力前，先阅读 `references/FUTURE_TODO.md`。计划中、受阻、只有代码或测试的功能不能说成已实机验收。实机动作完成并通过相应验收后，按项目要求更新本机忽略的状态/审计文档。身份和关系结论只有在分析正文成功提交后才存在；基础设施可用不代表画像业务已完成。

执行归档、分析、仪表盘和回复任务前阅读 [SKILL_DATA_WORKFLOW.md](references/SKILL_DATA_WORKFLOW.md)。涉及 UI、联系人状态或回复时，先阅读 [UI_WORKFLOW_RULES.md](references/UI_WORKFLOW_RULES.md)、[UI_PAGE_CATALOG.md](references/UI_PAGE_CATALOG.md)、[ACTION_VERIFICATION_MATRIX.md](references/ACTION_VERIFICATION_MATRIX.md) 和相关时的 [WINDOW_NAVIGATION.md](references/WINDOW_NAVIGATION.md)。涉及分析或回复时，再按需阅读 [ANALYSIS_QUALITY_STANDARD.md](references/ANALYSIS_QUALITY_STANDARD.md)、[EVENT_ANALYSIS_STANDARD.md](references/EVENT_ANALYSIS_STANDARD.md) 与 [MEMORY_STORAGE_CONTRACT.md](references/MEMORY_STORAGE_CONTRACT.md)。

## UI 页面操作

1. 每次先调用 `vision.inspect_windows`，再根据实时结果用 `vision.resolve_window` 选择窗口；不能复用历史 HWND、截图、标题或基于窗口尺寸保存的坐标。
2. 区分主聊天、搜索下拉、嵌入式右侧页和独立窗口。先核对窗口所属进程、页面、输入区域和当前帧控件。
3. 搜索流程使用 `actions.open_search_content(query)` 清空并核实主搜索框后再选精确网络候选。不得用 Enter 选中未知候选；联系人/群身份须单独核验。
4. 已登记路线使用 `actions.page_operation` 或对应导航接口，并传入 `expected_page` 和正确 HWND。坐标来自当前截图；每步动作后检查成功回执及后置条件。
5. 关闭嵌入式右侧内容页使用 `close_content_tab`；不得向主窗口发 `WM_CLOSE` 关闭嵌入页。编辑器用明确的 `cancel`；不得假设 Escape 会丢弃草稿。`dismiss` 仅用于登记菜单，`close` 仅用于辅助窗口。
6. 观察/OCR失败、页面变化、身份不清、控制器未实现或后置验证失败时停止。不得盲点、自动反复发送或把失败回执当成功。

资料与个人朋友圈采集中的联系人只能在个人“联系人”分组下定位，先确认分组展开；不得点击“新的朋友”、企业联系人、公众号/服务号或退回混合搜索。定向发送直接搜索指定对象，按共用规则核对查询、联系人分区精确候选与资料 alias，不能用采集遍历替代收件人搜索。缺少稳定身份核验字段时停止。`username/wxid` 是本地身份，公开微信号是 `alias`；昵称、标题或头像不能单独证明身份。

Agent 图片复核坐标必须交给 BasicSkill，并绑定当前 HWND、页面、帧和短期单次 review。画面变化后重新测算。复核不允许发送、删除、下载或绕过 alias 身份核验。

联系人修改须先调用 `entities.plan_contact_action(username, action, value)`，目标使用精确内部 `username/wxid`。把计划展示给用户，调用 `actions.confirm_contact(action_id)`，然后仅把返回的 `action_id` 和单次 `confirmation_id` 交给 `actions.execute_contact`。项目语义 ID 如 `21.09:more`、`22.03:delete_contact` 不是微信控件或可复用坐标。检测器不支持当前帧时停止。`set_remark` 和 `delete_contact` 必须确认与完整计划绑定；执行成功后重新同步资料再更新 Memory。

## 联系人状态与失败处理

一次 UI 搜索失败不能证明联系人删除。缺席判断只使用完整、内容不同的快照，并区分 `missing`、`inferred_removed`、`confirmed_removed`。保留历史，不自动加回好友，也不发送探测消息。本人/对方方向分别记录。

- 归档失败不得回退为写微信数据库或调用私有协议。
- OCR/布局不匹配时停止，重新观察并计算坐标；有限侧栏导航重试仍失败时，按 [WINDOW_NAVIGATION.md](references/WINDOW_NAVIGATION.md) 使用 `vision.prepare_review` 和 `actions.apply_review`。不能直接执行 Agent 坐标。
- 分析失败时保留上一个完整成功 Markdown 和可续做任务。
- 身份歧义时停止人物聚合和动作，直到稳定 ID 或已确认合并解决。
- 发送、表情、点赞、评论或联网媒体动作失败后不得自动重试；重试须对新动作重新确认。
- 排错时不得记录私人正文、资料内容、媒体密钥或 DPAPI 密钥。

## Memory、兼容与历史

只在业务兼容需要时检查 `MEMORY_SCHEMA_VERSION`、`MCP_PROTOCOL_VERSION`、`CONTACT_ACTION_PROTOCOL_VERSION` 等实际工具状态；不在 Skill 中维护自己的版本号。schema 不兼容时停止写入并执行受支持的迁移。Markdown/Event 正式历史为完整快照，不原位改写；当前帧证据绑定 HWND/PID、几何、DPI 和页面，任一变化都会使旧证据失效。历史坐标档案不能执行。

## 数据联动

先按用户请求选择历史快照、当前状态、回复或 UI 模式，再按依赖处理受影响节点。当前状态先联动 wechat-sync，必要时联动 wechat-identity-audit；UI 动作由 wechat-ui-navigation 执行。

分析按月份→会话→人物→时间线顺序更新实际受影响节点，仪表盘交给 wechat-dashboard，回复草稿交给 wechat-reply-monitor。不无条件运行整条链路。每次交接稳定范围、实际覆盖、来源水位、成功输出和缺口；来源未更新或上游失败时不得称为当前结果。

## UI 排错与实测规划

遇到搜索、资料入口、输入区、发送结果或表情定位问题时，读取随包的
[UI_FAILURE_RECOVERY.md](references/UI_FAILURE_RECOVERY.md)。按其中的问题/处理表区分
已实现处理与剩余缺口，保留首次失败回执；发送 unknown 仅增加只读复核证据，不自动重发。
用户要求 OpenCV + OCR 全流程实测时，正常步骤不依赖 Agent 看图，失败后才图片排错。
具体账号、正文、截图与运行流水只存本机忽略的台账，不写入 Skill。

## 随包资源范围

执行规则、参考文档与模板只读取本 Skill 目录中的 `references/`、`assets/` 和已提供的 `scripts/`，相对路径从本 Skill 目录解析。不能跨目录借用另一个 Skill 的参考资源；缺少必需随包资源时报告缺失，维护时补齐本目录副本。其他 Skill 名称仅表示流程职责与上下游，不代替本目录资源。项目运行接口、正式数据路径与项目命令是运行依赖，不是外部指令来源；不为打包复制私人数据。
