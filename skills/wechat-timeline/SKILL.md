---
name: wechat-timeline
description: 维护跨月事件时间线，记录阶段、参与者、证据、替代解释及可追溯历史。
---

# 微信事件时间线

执行前阅读 [ANALYSIS_QUALITY_STANDARD.md](references/ANALYSIS_QUALITY_STANDARD.md)、[MEMORY_STORAGE_CONTRACT.md](references/MEMORY_STORAGE_CONTRACT.md) 和 [EVENT_ANALYSIS_STANDARD.md](references/EVENT_ANALYSIS_STANDARD.md)。时间线用于索引会话 Memory 中的详细事件正文；几个日期点不能证明事件已完整分析。追踪跨月/跨年开放阶段及后续消息，提供明确连续性证据。区分长期事项、具体事件、阶段、重复发生和因果候选；消息日期与事件日期、计划/截止/实际/回顾日期必须分开。

## 执行步骤

1. 读取受影响 Claim，并通过 `events.get` 检查候选事件。
2. 依据参与者、主题对象、时间邻接、会话关联和原始证据判断连续性；不能仅因主题相似就合并。
3. 依据证据支持的事件日期或范围扩展、缩短、拆分或合并阶段。不要用月初/月末充当事件起止日期。项目、工作、考试和活动分别记录计划、期限和实际日期；相关时核实生日历法，恋爱节点只在适用场景检查。
4. 保留参与者、关联会话/Claim、置信度、开放状态和替代解释。
5. 调用 `events.upsert` 前比较当前语义内容。未变化时不新增版本。提交完整当前阶段集合，包括仍有效的旧阶段，因为 upsert 会替换阶段集合。之后只刷新受影响的会话/人物记忆与图表；检查实际接口支持的状态，不自行发明字段或端点。
6. 对偏好或行为变化，保留旧证据、带日期的变化点、后续持续/反转和反例。只关联相关 Claim；同月出现不代表都与该事件有关。提及频率增加本身不证明行为变化。
7. 区分会话层事件/话题/互动时间线与人物跨来源演化。共同群角色变化、资料和朋友圈观察仅在身份、场景、来源和时间可靠时使用；不得将变化归给所有群成员。

## 失败处理

- 连续性不清楚：事件先分开，记录可能有关联。
- 日期冲突：保留各自有来源的范围，直到能够解决。
- 开放事件无新证据：继续保持开放，不编造结案。
- 新发现的历史证据：更新真实历史阶段，并使依赖该内容的摘要待更新。
- 参与者身份不明：关联临时来源身份，不连接到无关人物。
- 明确日期线索或用户修正推翻模糊范围：回查原消息与回顾证据，改为证据支持的精确结论并保留历史。
- 当前接口不能删除错误关联或维护完整历史阶段关系：说明限制，保留修复候选，不宣称 upsert 已自动修复。

## 历史与数据联动

语义变化时保留可追踪的旧 ID、证据和完整 Markdown 历史；月份边界不产生新事件。当前 `event_versions` 只保存标量快照，不包含完整阶段/关联历史图。运行接口尚不能保证完整的合并/拆分谱系或关联删除；不可安全修正时留下修复候选。

执行前阅读[数据新鲜度与联动规则](references/SKILL_DATA_WORKFLOW.md)。当前时间线先核实相关来源及月度/会话/人物结果已成功更新；按需联动 wechat-sync、wechat-monthly-analysis、wechat-conversation-summary 和 wechat-person-analysis，只运行事件真正依赖的节点。固定历史请求使用指定范围并标明缺口。

事件成功更新后，仅通知受影响会话/人物重新合并，再按需联动 wechat-dashboard。使用实际输入和成功输出避免“事件→汇总→事件”循环。上游未就绪时保留旧时间线并标注截至范围，不称实时状态。

涉及 UI、联系人状态或回复时，先读 [UI_WORKFLOW_RULES.md](references/UI_WORKFLOW_RULES.md)、[UI_PAGE_CATALOG.md](references/UI_PAGE_CATALOG.md) 和 [ACTION_VERIFICATION_MATRIX.md](references/ACTION_VERIFICATION_MATRIX.md)。离线事件分析不需要 UI。

## 完整阅读与交付

如用户明确授权全历史多 Agent 阅读，遵循[分析质量标准](references/ANALYSIS_QUALITY_STANDARD.md)的动态分片、独立月份/主体复核和串行提交要求，使用[共享分片交接格式](references/monthly-handoff.md)。按真实消息跨度、记录数和可读字符数安排分片；规划不证明实际阅读，也不授权启动代理。

核对 `speaker`、`actor`、`fact_owner`、`relation_owner` 和提及/引用的第三方；保留 self 与联系人各自社会关系，不能把第三方事实、偏好或安排归给讲述人。详细 HTML 只能渲染同源成功正文。覆盖不全、主体不明、缺少独立复核或上游失败时停止全面交付，保留上一成功版和候选。

## UI 排错与实测规划

遇到搜索、资料入口、输入区、发送结果或表情定位问题时，读取随包的
[UI_FAILURE_RECOVERY.md](references/UI_FAILURE_RECOVERY.md)。按其中的问题/处理表区分
已实现处理与剩余缺口，保留首次失败回执；发送 unknown 仅增加只读复核证据，不自动重发。
用户要求 OpenCV + OCR 全流程实测时，正常步骤不依赖 Agent 看图，失败后才图片排错。
具体账号、正文、截图与运行流水只存本机忽略的台账，不写入 Skill。

## 随包资源范围

执行规则、参考文档与模板只读取本 Skill 目录中的 `references/`、`assets/` 和已提供的 `scripts/`，相对路径从本 Skill 目录解析。不能跨目录借用另一个 Skill 的参考资源；缺少必需随包资源时报告缺失，维护时补齐本目录副本。其他 Skill 名称仅表示流程职责与上下游，不代替本目录资源。项目运行接口、正式数据路径与项目命令是运行依赖，不是外部指令来源；不为打包复制私人数据。
