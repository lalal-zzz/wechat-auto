---
name: wechat-profile-moments
description: Process profile and Moments deltas as time-stamped evidence for person memory with conservative inference and resumable failures.
---

# Profile and Moments

## Procedure

For per-person UI loading and coverage, read
[CONTACT_COLLECTION.md](../../docs/CONTACT_COLLECTION.md). Run the local path first;
then queue stable person IDs with `sync.enqueue_moments_contacts`, inspect
`sync.moments_queue`, and call `sync.load_contact_moments` only with the UI runtime.
This tool loads one person's visible album and reopens the local DB afterward.
An all-contact queue contains candidates, not certified current friends.
Retain local_db and ui_load observations separately; an empty cache never means no posts.
Missing or ambiguous current-frame controls or identity stop actions.
Fixed layout profiles are not supported.

First read [WINDOW_NAVIGATION.md](../../docs/WINDOW_NAVIGATION.md). Resolve the
main/profile/personal-album HWND independently. `actions.ensure_contacts_section`
must locate the exact personal 联系人 group; choose rows only below its header.
Do not enter 新的朋友 or fall back to mixed search. For failed navigation, inspect
the receipt, recalculate from a fresh frame, and use guarded `vision.prepare_review`
→ `actions.apply_review` if needed. Missing exact alias stops personal loading.
Use runtime verification; a recognized page does not certify personal-album collection.

For a user-authorized all-contact refresh, read
[MOMENTS_ARCHIVE.md](../../docs/MOMENTS_ARCHIVE.md) and run
`scripts/sync_all_contacts_moments.py` from the repository root. This archives
all locally readable contact-linked Moments and produces a private media manifest;
it does not download remote media or certify current friendship. Do not infer
removal from local_type or overwrite old archive records outside the source scope.

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
- Inspect coverage stop_reason: page_budget=partial, unchanged text=stalled,
  visible permission text=restricted, exceptions=failed. None proves full history.
- A navigation failure stops the batch; do not advance to another person on an unknown page.
- A running queue entry after a crash needs explicit `sync.recover_moments_contact`
  after checking the old process ended. Failed entries require explicit rerun.
- If requires_navigation_restore is true, restore/verify the page before another person.
- Remote media downloading is separate from UI loading and still needs per-item confirmation.

## Version rules

Snapshots are append-only and keyed by field hash/source time. Identical input is a no-op. Parser changes alter the fingerprint; incompatible interpretations trigger an affected-person rebuild.

Implementation 0.8.1 uses Memory schema 3 (additive migration from 1/2) and page
action protocol 4. Navigation coordinates come from current-frame OpenCV, never size-keyed profiles. Coverage history is append-only; repeated content creates no
duplicate profile snapshots/analysis versions. Never reinterpret older partial
coverage as complete when a collector version changes.

## Shared UI and recipient contract

Before UI navigation, recipient selection, removal auditing, or reply dispatch, read
[UI_WORKFLOW_RULES.md](../../docs/UI_WORKFLOW_RULES.md). Use its search-state table,
stable-identity checks, missing/removal distinctions, and failure stop conditions.
Read [UI_PAGE_CATALOG.md](../../docs/UI_PAGE_CATALOG.md) for page descriptions and
[ACTION_VERIFICATION_MATRIX.md](../../docs/ACTION_VERIFICATION_MATRIX.md) for verification requirements.
These references must accompany the repository skill; missing references stop UI work.
Offline-only analysis does not require screenshots or UI actions. Static rules never
certify a live recipient; the complete stable-identity send workflow remains WA-005.

Sidebar navigation may retry at most twice with a complete fresh observation. Unknown pages, ambiguous controls, menus, closing and external actions do not retry. WM message delivery is not proof of a successful transition; abort collection when verification fails.

## Profile enrichment and media / 0.8.1

After stable identity proof, call `sync.capture_contact_profile` to save explicit
visible fields before personal-album entry. The loading queue passes the stable
wxid automatically. Require exact archived alias and the same captured profile
frame; missing/ambiguous labels remain unobserved and cannot clear prior fields.
Signature, region, contact source, added time and common groups retain provenance;
new profile snapshots feed the shared Memory index. A failed UI lookup saves no
guessed-person profile. Text-only fields do not certify avatar or gender icons.

Run `scripts/archive_local_moments_media.py --manifest ...` for exact local cache
hits. It never networks or fuzzy-matches by size. For a remote item, show its exact
author/post/type/ordinal locally, then invoke `scripts/download_moments_item.py`
with that reviewed item_id and --confirm only after explicit approval for that
item. Changes to the media fingerprint invalidate approval. Do not transfer
confirmation to another item or automatically retry HTTP/format failures.
Read MOMENTS_ARCHIVE.md for private receipts and the actual tested boundary.

## 数据更新与 Skill 联动

执行前读取共用的
[数据新鲜度与联动规则](../../docs/SKILL_DATA_WORKFLOW.md)，先确定历史快照、当前
状态、回复或 UI 模式。联动由当前 Agent 读取相关 SKILL.md 并执行其工具流程，
不是自动派生代理、创建定时任务或扩大授权。

“当前资料/动态”先完成 sync.contacts_moments_local；本地 cached_only 不能称
远程完整覆盖。需要加载指定个人相册时联动
[wechat-ui-navigation](../wechat-ui-navigation/SKILL.md)，身份有歧义先联动
[wechat-identity-audit](../wechat-identity-audit/SKILL.md)。
资料补采绑定稳定 wxid 和精确 alias；UI 加载结束重新读库，再由
[wechat-sync](../wechat-sync/SKILL.md) 索引新快照/动态。
变更证据交给 [wechat-person-analysis](../wechat-person-analysis/SKILL.md)，涉及长期
事件再交给 [wechat-timeline](../wechat-timeline/SKILL.md)。未变化字段不触发重复版本。
受限/停滞/部分加载交接真实覆盖；缺签名不清空，无法导航停止当前人和批次。
媒体下载另走逐项确认，分析任务不自动下载照片或视频。
