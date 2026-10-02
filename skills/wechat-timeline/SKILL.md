---
name: wechat-timeline
description: Maintain continuous cross-month event timelines with phases, participants, evidence, alternatives, and append-only versions.
---

# WeChat Timeline

## Procedure

1. Load affected claims and inspect any candidate event with `events.get`.
2. Match continuity using participants, subject, time adjacency, conversation links, and evidence—not topic similarity alone.
3. Extend, shorten, split, or merge phases using actual dates or supported ranges.
4. Preserve participants, linked conversations/claims, confidence, open state, and alternative interpretations.
5. Upsert through `events.upsert`, then refresh dependent conversation/person memories and charts.

## Failure handling

- Ambiguous continuity: keep separate events and record a possible relation.
- Conflicting dates: retain both sourced ranges until resolved.
- Open event without new evidence: keep it open; do not fabricate closure.
- Late historical evidence: update the historical phase and invalidate downstream summaries.
- Missing participant identity: link to provisional evidence, not an unrelated person.

## Version rules

Each semantic event change appends an event version. Month boundaries never create new events by themselves. Merge/split operations preserve predecessor IDs and evidence links so earlier timelines remain reconstructable.

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

最新时间线先确认相关来源已同步、月份/会话/人物结果已成功更新，必要时联动
[wechat-sync](../wechat-sync/SKILL.md)、
[wechat-monthly-analysis](../wechat-monthly-analysis/SKILL.md)、
[wechat-conversation-summary](../wechat-conversation-summary/SKILL.md) 和
[wechat-person-analysis](../wechat-person-analysis/SKILL.md)。只调用当前事件真正依赖的节点。
历史时间线使用指定范围/版本，保留开放事件与缺口，不为闭合时间线猜日期。
事件成功更新后，仅通知受影响会话/人物重新合并，并联动
[wechat-dashboard](../wechat-dashboard/SKILL.md)。用版本/输入检查防止事件→汇总→事件循环。
上游未就绪时保留旧时间线，明确截至范围，不将它标为实时变化图。
