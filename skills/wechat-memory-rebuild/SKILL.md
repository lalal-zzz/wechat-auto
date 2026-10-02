---
name: wechat-memory-rebuild
description: Rebuild only affected WeChat memories after incompatible templates, backfills, identity corrections, or damaged analysis while preserving prior versions.
---

# WeChat Memory Rebuild

Use rebuild for incompatible templates, large historical backfills, merge/split decisions, rejected foundational links, or corruption. Normal deltas use incremental analysis.

## Procedure

1. Record the rebuild reason, affected scope, current versions, schema/application versions, and evidence range.
2. Traverse dependency edges to identify the minimal affected months, conversations, events, people, relationships, and charts.
3. Recompute bottom-up from raw evidence references.
4. Submit complete Markdown views with explicit parent versions and a new template/input fingerprint.
5. Verify every previous full Markdown version remains readable before clearing dirty nodes.

## Failure handling

- Unsupported schema: stop before writes and run a documented migration.
- Missing evidence: keep old current version, record the gap, and leave rebuild pending.
- Mid-run failure: completed nodes remain versioned; resume remaining jobs idempotently.
- Parent conflict: reload and recompute that node.
- Validation failure: never promote the candidate current file.

## Version rules

Never rewrite raw archives, historical Markdown, or superseded claims/events. Schema migrations and semantic template revisions are separate version axes. Rollback selects a prior complete view; it does not erase later audit history.

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

固定历史重建使用指定证据范围；要重建“当前”状态时先联动
[wechat-sync](../wechat-sync/SKILL.md)。身份修正先由
[wechat-identity-audit](../wechat-identity-audit/SKILL.md) 完成确认。
按受影响依赖依次联动 [wechat-monthly-analysis](../wechat-monthly-analysis/SKILL.md)、
[wechat-conversation-summary](../wechat-conversation-summary/SKILL.md)、
[wechat-person-analysis](../wechat-person-analysis/SKILL.md)、
[wechat-timeline](../wechat-timeline/SKILL.md)，成功后再交给
[wechat-dashboard](../wechat-dashboard/SKILL.md)。正常新消息不默认完整重建。
交接原因、范围、来源水位与旧/新完整版本。某节点失败保留其上一成功版本，
已完成节点不重跑，不提前声称所有 dirty 节点已经清除。
