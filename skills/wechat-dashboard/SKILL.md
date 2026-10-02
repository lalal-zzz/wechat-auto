---
name: wechat-dashboard
description: Generate and verify offline HTML, PNG, and Mermaid memory dashboards from structured claims and events without exposing raw evidence.
---

# WeChat Dashboard

## Procedure

1. Check `status.summary`; finish relevant successful analysis jobs before refresh.
2. Call `charts.refresh` with the requested person/conversation scope.
3. Verify the HTML, PNG, and Mermaid artifacts exist and contain the selected scope and current version.
4. Keep charts based on SQLite structure; do not parse Markdown as the machine data source.
5. Expand evidence only after the user selects a claim/event and asks why.

## Failure handling

- No claims/events: generate an honest structural/empty state rather than fabricated trends.
- Missing graph renderer: retain HTML and Mermaid output and report PNG unavailable.
- Stale dirty nodes: label the dashboard stale and queue analysis before treating it as current.
- Corrupt output: write to a temporary artifact and keep the prior valid dashboard.

## Version rules

Dashboard metadata must contain generator/application version and source analysis versions. Refreshing unchanged inputs may replace generated views but must not create Memory versions. All assets remain local and self-contained.

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

先区分查看既有版本与刷新当前状态。前者读取指定版本，后者按受影响范围联动
[wechat-sync](../wechat-sync/SKILL.md)、
[wechat-conversation-summary](../wechat-conversation-summary/SKILL.md)、
[wechat-person-analysis](../wechat-person-analysis/SKILL.md) 和
[wechat-timeline](../wechat-timeline/SKILL.md)。无关节点不等待也不刷新。
charts.refresh 只渲染已有 Claim/Event，不执行同步和分析。交接成功结构化版本、
范围及缺口；只在相关上游已提交后把产物称为当前仪表盘。
无法证明依赖就绪时，保留旧图并在对用户的说明中标注截至范围/未知新鲜度，
不要声称渲染器已自动写入完整 stale 状态。渲染不触发回复、UI 导航或媒体下载。
