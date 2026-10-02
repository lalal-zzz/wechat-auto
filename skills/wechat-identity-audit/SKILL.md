---
name: wechat-identity-audit
description: Audit aliases, missing entities, removals, restorations, and merge candidates using stable IDs and versioned snapshots.
---

# WeChat Identity Audit

## Procedure

1. Use wxid/username for people and `@chatroom` for groups; list display fields only as aliases.
2. Compare snapshot versions and record nickname, remark, group-name, signature, and avatar changes without creating a new person.
3. Compare complete, distinct snapshots only. First absence becomes `missing`;
   infer removal only after three snapshots over at least 24 hours. Search
   failure, an incomplete snapshot and deleting a chat are not absence evidence.
4. Require an explicit system signal or user decision for `confirmed_removed`.
5. Create merge candidates for suspected duplicates and call `entities.decide_merge` only after user confirmation.
6. Record restoration when an entity returns; retain all earlier status events.

Read [CONTACT_COLLECTION.md](../../docs/CONTACT_COLLECTION.md) for the directional
state schema. `entities.contact_state` reads history; `entities.record_contact_state`
records reviewed evidence using a unique observation_key and evidence_ref.
Keep local_contact/local_block/peer_contact/peer_block/moments_access separate.
Confirmed deletion/blocking needs user_confirmation or reviewed_system_signal
with confirmed=true; ui_observation may only assert Moments access.
Automatic version-specific DB flag/system-message recognition remains unimplemented.
Mapped private-conversation members have a known-state MCP send guard; full
recipient verification and all BasicSkill entry gates still remain WA-005.
Distinguish removing a contact locally from the other person removing self;
never test either by sending a message or silently adding the contact again.

For UI changes, call `entities.plan_contact_action` with the stable username, confirm its returned
`action_id`, and execute only with the single-use confirmation ID. A visible alias or remark is
never an authorization target.

## Failure handling

- Equal names/different stable IDs: keep separate.
- Stable ID absent: retain a provisional source identity and do not aggregate person analysis.
- Snapshot gap: reset neither counters nor history; mark coverage uncertain.
- Reusing a snapshot ID with changed content is an error, not another observation.
- Incomplete snapshots do not restore missing contacts. Continued complete absence
  counts across successive snapshots even when the previous snapshot was already empty.
- Unblock/restoration is a new sourced observation, never deletion of earlier evidence.
- Do not execute delete/block to test detection. Status recording has no UI side effects.
- Incorrect merge: use a correction/rebuild workflow; never delete evidence.

## Version rules

Identity snapshots and decisions are append-only. Merge/split decisions invalidate affected person, relationship, conversation, and dashboard versions. Algorithm-version changes must not silently reinterpret prior decisions.

0.6.0 / Memory schema 3 adds directional state and collection coverage histories.
Identity merging preserves their evidence history; the old contact's queued UI
entry becomes merged. Schema 1/2 migrate without removing history.

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

“当前联系人状态”先联动 [wechat-sync](../wechat-sync/SKILL.md) 更新相关来源，
再核对快照完整性与独立版本。cached_only 联系人条目不是完整当前好友快照，
一次 UI 查找也不是完整快照，不据此累计缺席或判定删除。
需要资料核验时联动 [wechat-ui-navigation](../wechat-ui-navigation/SKILL.md) 和
[wechat-profile-moments](../wechat-profile-moments/SKILL.md)，但不发送探测消息。
合并/拆分或用户修正需要确认；交接稳定身份映射、范围和证据，不仅交接昵称。
确认的身份修正交给 [wechat-memory-rebuild](../wechat-memory-rebuild/SKILL.md)，
普通资料变化交给 [wechat-person-analysis](../wechat-person-analysis/SKILL.md)。
身份未解决时阻止依赖它的聚合与派发；不自动触发删除、加好友或拉黑。
