---
name: wechat-ui-navigation
description: Identify live WeChat HWNDs and layered pages, select an unambiguous target, navigate registered routes and restore known read-only windows. Use before contact or Moments UI collection; it does not authorize sending, changing settings or downloading media.
---

# WeChat windows and navigation

Read [UI_WORKFLOW_RULES.md](../../docs/UI_WORKFLOW_RULES.md),
[UI_PAGE_CATALOG.md](../../docs/UI_PAGE_CATALOG.md),
[ACTION_VERIFICATION_MATRIX.md](../../docs/ACTION_VERIFICATION_MATRIX.md), and
[WINDOW_NAVIGATION.md](../../docs/WINDOW_NAVIGATION.md) before live actions.

## Identify and select

1. Call `vision.inspect_windows` for the current process. It returns HWND roles,
   owner/geometry/DPI, observed surfaces, composer state and operation availability;
   it omits private OCR and titles. Unknown, stale or unavailable windows stop navigation.
2. Select the desired page with `vision.resolve_window`. Distinguish
   embedded_main, embedded_right_tab, auxiliary_window and auxiliary_popup.
   Do not select the first candidate. If multiple windows match, identify the intended
   presentation/HWND from the current inventory or ask the user to choose.
3. `action_authorized=false` and `identity_verified=false` are deliberate. A recognized
   page, matching title or current HWND does not authenticate a contact. Resolve stable
   username/wxid locally, then verify the exact visible alias on the profile.

## Navigate and restore

Use `actions.navigate_page(page, max_steps=6)` to execute a registered route.
Every step uses BasicSkill and fresh CV/OCR coordinates, then inventories all windows
again. The route stops at its first failed postcondition; it does not advance on a
successful Windows message return alone. Inspect the steps and stop_reason.

Use `actions.restore_main_window` only when dismissing known menus and closing
known read-only auxiliary content is within the task. It never closes the main
client, changes settings, chooses a file or discards an editor/comment/publish draft.
Handle such editors explicitly with the user; do not repeatedly press Escape.

## Errors and recovery

The recovery chain is fresh observation → recomputed CV/OCR target → guarded
Agent image review. Failed sidebar receipts include `visual_review` when available.
Otherwise call `vision.prepare_review(operation, hwnd, expected_alias)` explicitly.
View its local image, then submit a pixel `[x,y,width,height]` and `source_page`
with `actions.apply_review`. The single-use plan expires in 120 seconds and rejects
changed HWND/PID/geometry/DPI/frame/target. It cannot send, delete, download, cancel
an editor or execute an arbitrary click. BasicSkill performs and verifies the step.

For Contacts, call `actions.ensure_contacts_section`. Expand only the personal
联系人 header and select exact rows beneath it. Never select 新的朋友, service or
enterprise categories, and never fall back to mixed global search. Missing header,
ambiguous row or absent exact profile alias stops the workflow, not deletion proof.

- target_page_not_found: inspect loading/coverage and current page; not deletion evidence.
- ambiguous_target_window: select a live HWND/presentation; never use list order.
- unrecognized_auxiliary_window or window_observation_unavailable: preserve local
  evidence, inspect that window; no fixed-coordinate fallback.
- blocking_window_requires_handling, editor_requires_explicit_handling: report the
  observed blocker and supported explicit operations. Do not auto-cancel user work.
- operation_control_unimplemented or route_unavailable: report the missing detector/route;
  a catalog entry is not an implemented button.
- navigation_postcondition_failed or restore_postcondition_failed: stop the workflow
  and keep its receipt. Never continue collecting in a guessed window.
- Only contacts/chats/discover navigation may retry, bounded to two fresh observations
  by default. Sending, menu toggles and closing never automatically retry.

## Moments handoff

After window navigation is validated, use the profile/Moments workflow in
[CONTACT_COLLECTION.md](../../docs/CONTACT_COLLECTION.md). The collector now resolves
both the profile window and personal album independently. Keep exact alias proof,
local_db coverage and ui_load coverage separate. Similar albums are not the same person.
An empty/stalled album does not prove complete history or deletion.
Remote media downloading is a separate explicitly confirmed operation. Opening and
scrolling a page does not authorize a download or certify that every post was cached.

## Version contract

Package 0.8.1, window observer 1, page catalog 3, page actions 4.
Read tool versions and operation availability; never reuse historical HWNDs or screenshot
coordinates. Recognition does not certify clicking, and opening an album does not prove
complete remote history. Raw frames and operational records are local-only.

## 数据更新与 Skill 联动

执行前读取共用的
[数据新鲜度与联动规则](../../docs/SKILL_DATA_WORKFLOW.md)，先确定历史快照、当前
状态、回复或 UI 模式。联动由当前 Agent 读取相关 SKILL.md 并执行其工具流程，
不是自动派生代理、创建定时任务或扩大授权。

每一步 UI 操作都重新观察 HWND、页面、控件与几何，不能复用上个 Skill 的
截图坐标。数据同步的新鲜度不能替代当前帧证明，页面识别也不替代联系人身份。
联系人定位前需要稳定身份时联动 [wechat-identity-audit](../wechat-identity-audit/SKILL.md)，
本地映射更新交给 [wechat-sync](../wechat-sync/SKILL.md)。
个人分组/资料身份验证成功后，把当前目标与回执交给
[wechat-profile-moments](../wechat-profile-moments/SKILL.md) 补采资料或加载相册；
回复页面核验只交给 [wechat-reply-monitor](../wechat-reply-monitor/SKILL.md)，不代其发送。
截图复核仅解决白名单导航的一步定位；过期帧、未知窗口、同名歧义或后置失败
停止并交接失败状态，不推进下一联系人，不把图片坐标当成持续授权。
