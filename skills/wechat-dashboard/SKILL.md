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
[ACTION_VERIFICATION_MATRIX.md](../../docs/ACTION_VERIFICATION_MATRIX.md) for actual coverage.
These references must accompany the repository skill; missing references stop UI work.
Offline-only analysis does not require screenshots or UI actions. Static rules never
certify a live recipient; the complete stable-identity send workflow remains WA-005.
