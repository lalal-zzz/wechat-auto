---
name: wechat-identity-audit
description: 使用稳定 ID 和历史快照审计别名、缺席、删除、恢复及合并候选。
---

# 微信身份审计

## 审计流程

1. 联系人使用本地 `wxid/username`，群使用 `@chatroom` 标识；昵称、备注、群昵称和公开微信号只作为分开的展示或核验字段。
2. 比较不同时间的资料快照，记录昵称、备注、群昵称、签名和头像变化，不因名称变化创建新 Person。
3. 只有完整且内容不同的快照可参与缺席判断。首次缺席记为 `missing`；至少三个完整快照、跨度不少于 24 小时后，才可标记为 `inferred_removed`。搜索失败、不完整快照和删除聊天记录都不是缺席证据。
4. 只有明确系统信号或用户决定可以记录为 `confirmed_removed`。
5. 疑似重复身份先建合并候选；只有用户确认后才调用 `entities.decide_merge`。
6. 联系人重新出现时记录恢复事件，保留原有缺席和删除历史。

按 [CONTACT_COLLECTION.md](references/CONTACT_COLLECTION.md) 中的方向记录状态。`entities.contact_state` 用于读取历史；`entities.record_contact_state` 使用唯一 `observation_key` 与 `evidence_ref` 记录已复核证据。分别记录 `local_contact`、`local_block`、`peer_contact`、`peer_block` 和 `moments_access`。确认删除或拉黑需要 `user_confirmation` 或 `confirmed=true` 的 `reviewed_system_signal`；`ui_observation` 只能记录朋友圈访问状态。

不得通过发送消息探测关系，也不得静默重新添加联系人。区分本人移除对方与对方移除本人。当前仅对已映射私聊成员提供已知状态的 MCP 发送保护；完整收件人核验和所有 BasicSkill 发送入口仍属于 WA-005 未完成范围。

若需要修改微信联系人状态，使用 `entities.plan_contact_action`，目标必须是稳定 `username`。向用户展示计划并取得确认后，只能使用返回的 `action_id` 和单次确认 ID 执行。可见昵称或备注不是授权目标。

## 失败处理

- 展示名称相同但稳定 ID 不同：分别保留。
- 缺少稳定 ID：保存临时来源身份，不参与人物聚合。
- 快照缺口：标记覆盖不确定，不清零缺席计数，也不改写历史。
- 相同快照 ID 对应不同内容：视为数据错误，不作为新观察。
- 不完整快照不能恢复缺席联系人；连续完整快照的缺席可累计，即使最新快照中无人可见。
- 解封或恢复须作为新的有来源观察记录，不能删除之前证据。
- 不执行删除或拉黑来测试检测逻辑；状态记录本身不得触发 UI 动作。
- 合并错误时使用受支持的更正/重建流程，不删除证据。

## 历史与兼容

身份快照和判断须保留历史。合并/拆分会影响相关人物、关系、会话和仪表盘，须检查并更新这些派生结果。算法变化不得静默重解释既有判断。Memory schema 迁移必须保留历史；旧 schema 迁移不应删除证据。

## UI 与收件人规则

涉及 UI 前阅读 [UI_WORKFLOW_RULES.md](references/UI_WORKFLOW_RULES.md)、[UI_PAGE_CATALOG.md](references/UI_PAGE_CATALOG.md) 和 [ACTION_VERIFICATION_MATRIX.md](references/ACTION_VERIFICATION_MATRIX.md)。这些规则不能替代当前页面及稳定身份核验。纯离线审计不需要 UI；不得把静态规则称作实时身份认证。

## 数据工作流与交接

执行前阅读[数据新鲜度与联动规则](references/SKILL_DATA_WORKFLOW.md)，区分历史快照、当前状态、回复和 UI 模式。联动只表示读取相关 Skill 并按其流程处理，不会自动派生 Agent、定时任务或扩大授权。

审计当前联系人前，先联动 wechat-sync 更新相关来源，再确认快照完整性。`cached_only` 联系人条目和单次 UI 查找都不是完整当前好友快照，不能据此累计缺席或判定删除。资料核验需要时联动 wechat-ui-navigation 和 wechat-profile-moments，但不发送探测消息。

交接稳定身份映射、证据和覆盖范围，不只传昵称。确认的身份修正交给 wechat-memory-rebuild；普通资料变化交给 wechat-person-analysis。身份未解决时停止依赖该身份的聚合与派发，不自动删除、加好友或拉黑。

## UI 排错与实测规划

遇到搜索、资料入口、输入区、发送结果或表情定位问题时，读取随包的
[UI_FAILURE_RECOVERY.md](references/UI_FAILURE_RECOVERY.md)。按其中的问题/处理表区分
已实现处理与剩余缺口，保留首次失败回执；发送 unknown 仅增加只读复核证据，不自动重发。
用户要求 OpenCV + OCR 全流程实测时，正常步骤不依赖 Agent 看图，失败后才图片排错。
具体账号、正文、截图与运行流水只存本机忽略的台账，不写入 Skill。

## 随包资源范围

执行规则、参考文档与模板只读取本 Skill 目录中的 `references/`、`assets/` 和已提供的 `scripts/`，相对路径从本 Skill 目录解析。不能跨目录借用另一个 Skill 的参考资源；缺少必需随包资源时报告缺失，维护时补齐本目录副本。其他 Skill 名称仅表示流程职责与上下游，不代替本目录资源。项目运行接口、正式数据路径与项目命令是运行依赖，不是外部指令来源；不为打包复制私人数据。
