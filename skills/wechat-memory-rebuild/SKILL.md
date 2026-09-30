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
[ACTION_VERIFICATION_MATRIX.md](../../docs/ACTION_VERIFICATION_MATRIX.md) for actual coverage.
These references must accompany the repository skill; missing references stop UI work.
Offline-only analysis does not require screenshots or UI actions. Static rules never
certify a live recipient; the complete stable-identity send workflow remains WA-005.
