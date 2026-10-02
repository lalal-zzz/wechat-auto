---
name: wechat-conversation-summary
description: Build a compact cross-month conversation memory with relationship stages, unresolved commitments, and a continuous versioned timeline.
---

# Conversation Summary

Run after affected monthly jobs finish.

## Procedure

1. Claim the conversation job and load current months with `analysis.get_conversation_input`.
2. Inspect linked events before joining phases across months.
3. Write one complete view covering relationship overview, important people, long events, communication evolution, contextual styles, topics, commitments, stages, and timeline.
4. Use supported dates/ranges and retain month-only precision when necessary.
5. Submit with the current parent version and complete evidence set, then complete the job.

## Failure handling

- Missing month: state the coverage gap and keep affected conclusions uncertain.
- Similar events without continuity evidence: keep them separate.
- Contradictory months: preserve both interpretations and expand evidence only if needed.
- Submit conflict/write failure: keep prior current version and retry from fresh inputs.

## Version rules

Track the actual monthly input versions and submit their referenced evidence with the template version. The backend fingerprint does not automatically certify monthly dependency readiness. Unchanged inputs should create no version. Never edit files under `versions/`.

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

先检查目标会话哪些月份受影响；必要时联动
[wechat-sync](../wechat-sync/SKILL.md) 和
[wechat-monthly-analysis](../wechat-monthly-analysis/SKILL.md)。相关月份全部成功后
才生成“当前”汇总。月份文件存在或 pending 列表为空不代表依赖已就绪。
固定历史请求可以使用指定版本，明确缺失月份，不自动扩大采集范围。
提交时使用实际月份证据与父版本，不仅凭标题或文件时间判断输入改变。
成功后将会话版本交给 [wechat-person-analysis](../wechat-person-analysis/SKILL.md)，
事件演化交给 [wechat-timeline](../wechat-timeline/SKILL.md)。
上游失败保留上一完整会话 Memory，不让旧汇总覆盖已成功的新月份。
