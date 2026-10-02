---
name: wechat-monthly-analysis
description: Analyze one conversation month into claims, events, coverage, and a compact full Markdown version with safe incremental recovery.
---

# Monthly Conversation Analysis

Process one `conversation_id + YYYY-MM` job. A month partitions input; it does not truncate an event.

## Procedure

1. Claim one job with `analysis.claim_job`; do not process a job already running elsewhere.
2. Read bounded pages with `analysis.get_month_input` until `next_after_id` is empty.
3. Read the previous current month and version.
4. Separate confirmed statements, observations, multi-evidence inferences, and unknowns.
5. Produce a complete Markdown view with overview, events, commitments, relationship and communication changes, and open events.
6. Submit claims, events, evidence references, actual coverage, template version, and `expected_parent` through `analysis.submit`; the backend computes its input fingerprint.
7. Complete the job only after SQLite and Markdown writes succeed.

## Failure handling

- Parent conflict: discard output, reload current inputs, and recompute.
- Missing evidence page: retain the prior Memory and leave a resumable failure.
- Invalid date: preserve unknown precision; never invent a day.
- Conflicting conclusions: keep both with validity/status.
- Unchanged fingerprint: accept the no-op and create no version.

## Version rules

Every semantic change creates a full version; delta Markdown is forbidden. Incompatible template changes trigger rebuild. Superseded claims/events remain historical.

## Shared UI and recipient contract

Before UI navigation, recipient selection, removal auditing, or reply dispatch, read
[UI_WORKFLOW_RULES.md](../../docs/UI_WORKFLOW_RULES.md). Use its search-state table,
stable-identity checks, missing/removal distinctions, and failure stop conditions.
Read [UI_PAGE_CATALOG.md](../../docs/UI_PAGE_CATALOG.md) for page descriptions and
[ACTION_VERIFICATION_MATRIX.md](../../docs/ACTION_VERIFICATION_MATRIX.md) for verification requirements.
These references must accompany the repository skill; missing references stop UI work.
Offline-only analysis does not require screenshots or UI actions. Static rules never
certify a live recipient; the complete stable-identity send workflow remains WA-005.

## 数据更新与 Skill 联动

执行前读取共用的
[数据新鲜度与联动规则](../../docs/SKILL_DATA_WORKFLOW.md)，先确定历史快照、当前
状态、回复或 UI 模式。联动由当前 Agent 读取相关 SKILL.md 并执行其工具流程，
不是自动派生代理、创建定时任务或扩大授权。

当前月份或历史补入任务先联动 [wechat-sync](../wechat-sync/SKILL.md)，
确认该会话月份的原始归档已更新；纯历史快照分析则固定证据范围，说明缺口。
领取后核对任务类型、conversation_id 与月份，不处理超出授权范围的下一任务。
读完所有分页，记录实际覆盖，再向 analysis.submit 提交 evidence_ids、coverage、
template_version 和 expected_parent；输入指纹由后端计算。
成功提交并完成该任务后，将月份版本交给
[wechat-conversation-summary](../wechat-conversation-summary/SKILL.md)；长期事件需要
连续性处理时联动 [wechat-timeline](../wechat-timeline/SKILL.md)。
新增旧消息更新其所属历史月份，不使无关月份重跑；未读完或父版本冲突不交接成功。
