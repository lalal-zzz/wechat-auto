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

The fingerprint includes monthly version IDs and template version. Unchanged dependencies create no version. Never edit files under `versions/`.

## Shared UI and recipient contract

Before UI navigation, recipient selection, removal auditing, or reply dispatch, read
[UI_WORKFLOW_RULES.md](../../docs/UI_WORKFLOW_RULES.md). Use its search-state table,
stable-identity checks, missing/removal distinctions, and failure stop conditions.
Read [UI_PAGE_CATALOG.md](../../docs/UI_PAGE_CATALOG.md) for page descriptions and
[ACTION_VERIFICATION_MATRIX.md](../../docs/ACTION_VERIFICATION_MATRIX.md) for actual coverage.
These references must accompany the repository skill; missing references stop UI work.
Offline-only analysis does not require screenshots or UI actions. Static rules never
certify a live recipient; the complete stable-identity send workflow remains WA-005.
