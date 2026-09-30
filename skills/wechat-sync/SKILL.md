---
name: wechat-sync
description: Incrementally index local WeChat message, profile, group, and Moments archives with persistent cursors, source auditing, and safe recovery.
---

# WeChat Sync

Use before analysis, after a directory-change notification, or when a source watermark is behind. Read WeChat through read-only backends and write only project databases.

## Procedure

1. Call `status.summary` and record application, Memory schema, and MCP protocol versions.
2. Verify configured sources exist and distinguish WeChat 4.x `xwechat_files` from legacy data.
3. Call `sync.index_archives`; report counts and watermarks without private content.
4. Run it again when validating idempotency: unchanged input must add no references or jobs.
5. Record full imports, migrations, media completion, ranges, failures, and gaps in the two audit documents.

## Failure handling

- Missing or locked source: leave cursors unchanged and retry after the external condition changes.
- Legacy database: audit read-only and use official migration/restore; never overwrite a 4.x database.
- Partial batch: preserve the last committed cursor and resume from it.
- Identity collision: create a merge candidate; never merge equal display names automatically.
- Media failure: keep message metadata and mark media pending. Remote download requires confirmation.

## Version rules

Adapter changes require an input-fingerprint change. A Memory schema mismatch stops sync until a compatible migration or rebuild exists. Never silently downgrade cursors or rewrite raw archives.

## Shared UI and recipient contract

Before UI navigation, recipient selection, removal auditing, or reply dispatch, read
[UI_WORKFLOW_RULES.md](../../docs/UI_WORKFLOW_RULES.md). Use its search-state table,
stable-identity checks, missing/removal distinctions, and failure stop conditions.
Read [UI_PAGE_CATALOG.md](../../docs/UI_PAGE_CATALOG.md) for page descriptions and
[ACTION_VERIFICATION_MATRIX.md](../../docs/ACTION_VERIFICATION_MATRIX.md) for actual coverage.
These references must accompany the repository skill; missing references stop UI work.
Offline-only analysis does not require screenshots or UI actions. Static rules never
certify a live recipient; the complete stable-identity send workflow remains WA-005.
