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
[ACTION_VERIFICATION_MATRIX.md](../../docs/ACTION_VERIFICATION_MATRIX.md) for actual coverage.
These references must accompany the repository skill; missing references stop UI work.
Offline-only analysis does not require screenshots or UI actions. Static rules never
certify a live recipient; the complete stable-identity send workflow remains WA-005.
