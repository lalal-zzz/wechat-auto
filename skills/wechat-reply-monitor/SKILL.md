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
- Stale analysis: apply the shared freshness rules below; keep old Memory as labeled background only when the draft does not require its missing updates.
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
[ACTION_VERIFICATION_MATRIX.md](../../docs/ACTION_VERIFICATION_MATRIX.md) for verification requirements.
These references must accompany the repository skill; missing references stop UI work.
Offline-only analysis does not require screenshots or UI actions. Static rules never
certify a live recipient; the complete stable-identity send workflow remains WA-005.

## 数据更新与 Skill 联动

执行前读取共用的
[数据新鲜度与联动规则](../../docs/SKILL_DATA_WORKFLOW.md)，先确定历史快照、当前
状态、回复或 UI 模式。联动由当前 Agent 读取相关 SKILL.md 并执行其工具流程，
不是自动派生代理、创建定时任务或扩大授权。

先运行当前会话的 monitor.run_once，核对成功读取及实际返回水位；该调用不
代表受影响月度/人物分析已经完成，也不证明所有消息 backlog 已读取到末尾。
若当前读取预算尚未覆盖目标新消息，继续有界同步或停止，不沿用旧消息生成草稿。
相关 Memory 滞后时，只联动 [wechat-monthly-analysis](../wechat-monthly-analysis/SKILL.md)、
[wechat-conversation-summary](../wechat-conversation-summary/SKILL.md) 或
[wechat-person-analysis](../wechat-person-analysis/SKILL.md) 中回复真正需要的范围。
身份/关系状态需复核时联动 [wechat-identity-audit](../wechat-identity-audit/SKILL.md)，
发送前页面核验交给 [wechat-ui-navigation](../wechat-ui-navigation/SKILL.md)。
上游成功后重新构造上下文，绑定目标新消息与分析版本。旧分析仅能作注明滞后的
背景；需要更新的承诺/状态才能正确回复时，先更新，否则停止草稿。
确认前重新核对新消息和对象状态；影响草稿的变化要求重建和新确认。读取失败、
身份不足或页面不符停止，Skill 联动不授权发送或创建定时任务。
