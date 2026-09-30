---
name: wechat-person-analysis
description: Build a source-traceable person memory across private chats, groups, profiles, and Moments while preserving scenario differences and corrections.
---

# Person Analysis

Analyze one stable `person_id`; treat `self` as a first-class person.

## Procedure

1. Claim the person job and call `analysis.get_person_input`.
2. Separate private-chat, work-group, friend-group, family-group, and Moments behavior.
3. Apply precedence: user correction, user description, repeated behavior, short-term behavior, model inference.
4. Write a complete view containing profile, traits, scenarios, communication, boundaries, relationships, important matters, changes, timeline, and conflicts.
5. Store short claims/evidence links in SQLite and submit the full view with its parent version.

## Failure handling

- Ambiguous identity: stop aggregation and create/use a merge candidate.
- Sparse evidence: use `unknown` or scoped observations.
- User correction: supersede the inference while preserving history.
- Missing scope: disclose the coverage gap and avoid confidence inflation.

## Version rules

The fingerprint includes conversation versions, profile/Moments watermarks, corrections, and template version. A nickname-only change updates profile history without forcing a personality change. Never diagnose illness or state MBTI as fact.

## Shared UI and recipient contract

Before UI navigation, recipient selection, removal auditing, or reply dispatch, read
[UI_WORKFLOW_RULES.md](../../docs/UI_WORKFLOW_RULES.md). Use its search-state table,
stable-identity checks, missing/removal distinctions, and failure stop conditions.
Read [UI_PAGE_CATALOG.md](../../docs/UI_PAGE_CATALOG.md) for page descriptions and
[ACTION_VERIFICATION_MATRIX.md](../../docs/ACTION_VERIFICATION_MATRIX.md) for actual coverage.
These references must accompany the repository skill; missing references stop UI work.
Offline-only analysis does not require screenshots or UI actions. Static rules never
certify a live recipient; the complete stable-identity send workflow remains WA-005.
