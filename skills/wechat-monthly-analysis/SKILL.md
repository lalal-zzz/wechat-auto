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
6. Submit claims, phases, evidence references, fingerprint, template version, and `expected_parent` through `analysis.submit`.
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
[ACTION_VERIFICATION_MATRIX.md](../../docs/ACTION_VERIFICATION_MATRIX.md) for actual coverage.
These references must accompany the repository skill; missing references stop UI work.
Offline-only analysis does not require screenshots or UI actions. Static rules never
certify a live recipient; the complete stable-identity send workflow remains WA-005.
