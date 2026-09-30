---
name: wechat-reply-monitor
description: Run one persistent-cursor message-monitor cycle, construct bounded reply context, and enforce exact single-use confirmation before sending.
---

# WeChat Reply Monitor

An external scheduler invokes one cycle at a time.

## Procedure

1. Call `monitor.run_once`; it reads from the saved cursor, archives the delta, dirties affected months, and returns compact context.
2. If no inbound messages exist, create no draft and advance only the valid watermark.
3. Build from current message, current conversation Memory, open commitments, recent events, relevant person claims, and the user's style in this conversation.
4. Save with `reply.create_draft` and show the exact text.
5. Before approval, follow the shared recipient contract: audit current status,
   resolve the stable recipient, and verify the contact profile and chat identity.
   A missing, removed, unknown, ambiguous, or name-only target stops dispatch.
   The full runtime identity/status gate is pending WA-005; do not describe the
   existing send tool as certifying the recipient.
6. After explicit approval and verified recipient support, call `reply.confirm`,
   then `reply.send_confirmed` with unchanged conversation, recipient and text.
7. Verify the action receipt; submitting a key event does not prove delivery.

## Failure handling

- Cursor/read failure: do not advance the cursor.
- Stale analysis: use the last successful complete version and disclose reduced context.
- Edited/expired/already-used confirmation: reject and request a new confirmation.
- Action failure: mark dispatch failed; never reuse its token or auto-retry sending.
- Ambiguous chat identity: stop before drafting/sending.
- Search no-result/history-only/network-only: stop dispatch, retain history;
  do not mark the person deleted or send a probe message.

## Version rules

Drafts bind conversation ID, exact text, creation time, and context version. Schedule, whitelist, past approval, or `confirm=True` never authorizes a new send. Each external send requires a fresh single-use confirmation.

## Shared UI and recipient contract

Before UI navigation, recipient selection, removal auditing, or reply dispatch, read
[UI_WORKFLOW_RULES.md](../../docs/UI_WORKFLOW_RULES.md). Use its search-state table,
stable-identity checks, missing/removal distinctions, and failure stop conditions.
Read [UI_PAGE_CATALOG.md](../../docs/UI_PAGE_CATALOG.md) for page descriptions and
[ACTION_VERIFICATION_MATRIX.md](../../docs/ACTION_VERIFICATION_MATRIX.md) for actual coverage.
These references must accompany the repository skill; missing references stop UI work.
Offline-only analysis does not require screenshots or UI actions. Static rules never
certify a live recipient; the complete stable-identity send workflow remains WA-005.
