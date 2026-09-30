---
name: wechat-profile-moments
description: Process profile and Moments deltas as time-stamped evidence for person memory with conservative inference and resumable failures.
---

# Profile and Moments

## Procedure

1. Run `sync.index_archives` and select only people dirtied by new snapshots or Moments.
2. Record profile and post changes as `observed` evidence with source time.
3. Compare hashes to the previous snapshot; unchanged values create no event/version.
4. Align changes with conversation timelines only when timestamps and identity are reliable.
5. Create an inference only when multiple independent signals support it.

## Failure handling

- Missing optional field means unknown, not deletion.
- Broken media keeps metadata and is marked unavailable.
- Remote media remains pending until explicit confirmation.
- Reappearance creates a restoration event and preserves missing history.
- Conflicting sources remain source-scoped.

## Version rules

Snapshots are append-only and keyed by field hash/source time. Identical input is a no-op. Parser changes alter the fingerprint; incompatible interpretations trigger an affected-person rebuild.

## Shared UI and recipient contract

Before UI navigation, recipient selection, removal auditing, or reply dispatch, read
[UI_WORKFLOW_RULES.md](../../docs/UI_WORKFLOW_RULES.md). Use its search-state table,
stable-identity checks, missing/removal distinctions, and failure stop conditions.
Read [UI_PAGE_CATALOG.md](../../docs/UI_PAGE_CATALOG.md) for page descriptions and
[ACTION_VERIFICATION_MATRIX.md](../../docs/ACTION_VERIFICATION_MATRIX.md) for actual coverage.
These references must accompany the repository skill; missing references stop UI work.
Offline-only analysis does not require screenshots or UI actions. Static rules never
certify a live recipient; the complete stable-identity send workflow remains WA-005.
