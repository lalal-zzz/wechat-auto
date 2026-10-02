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

Track conversation versions, profile/Moments coverage, and user corrections in the input handoff. The current submission backend computes its fingerprint from evidence IDs, template and supported corrections; do not claim it automatically verifies every upstream version or source watermark. A nickname-only change updates profile history without forcing a personality change. Never diagnose illness or state MBTI as fact.

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

当前画像先联动 [wechat-sync](../wechat-sync/SKILL.md)，核对相关会话、资料与
朋友圈来源覆盖。需补采资料/相册时联动
[wechat-profile-moments](../wechat-profile-moments/SKILL.md)；身份问题先联动
[wechat-identity-audit](../wechat-identity-audit/SKILL.md)。
受影响会话先完成 [wechat-conversation-summary](../wechat-conversation-summary/SKILL.md)。
analysis.get_person_input 不是完整资料/朋友圈原文接口，需要时用 evidence 工具
展开已有引用；拿不到来源就标缺口，不假装这些输入已自动提供。
按各私聊/群聊场景及 self 分别分析，交接人物版本、来源覆盖与未解决冲突给
[wechat-timeline](../wechat-timeline/SKILL.md) 和 [wechat-dashboard](../wechat-dashboard/SKILL.md)。
回复只需相关短 Claim，不将全人物档案交给每次草稿。
