---
name: base-op
description: Use the local WeChat LLM Agent system for Windows WeChat 4.x chat automation, offline conversation and Moments memory, contact-specific analysis, and confirmed HWND actions. Use when a task involves this repository's WeChat automation or analysis capabilities.
metadata:
  short-description: Local LLM Agent for WeChat automation and memory
---

# base_op Skill

This Skill is the LLM-facing layer of the repository. The implementation code
lives separately under `src/`; do not treat this Skill directory as the Python
package.

## Repository layout

```text
src/                         Python implementation
  wechat_auto/
    core/                    Win32 HWND connection
    actions/basic.py         only UI action entrypoint
    primitives/              HWND actions and OCR observation
    backends/                read-only WeChat database adapters
    storage/                 offline SQLite, memory and preference stores
skills/base_op/SKILL.md      this LLM instruction layer
tests/                       automated tests
data/                        local private databases; never read from Git or commit
```

## Operating model

Use this sequence for repository tasks:

1. Read local memory and database data through the adapters in `src/wechat_auto/backends/`.
2. Persist normalized data, cursors, semantic hints and analysis inputs through `src/wechat_auto/storage/`.
3. Let the LLM analyze context, contacts, relationships, preferences, events and reply candidates.
4. For a UI mutation, call the single `BasicSkill` entrypoint in `src/wechat_auto/actions/basic.py`.
5. Treat OCR as disabled-by-default observation and verification only. The normal path must use local data and HWND actions; OCR may be enabled only for diagnosis or fallback, and it never performs the action itself.
6. Require explicit confirmation before sending messages or stickers, liking/commenting Moments, or downloading remote media.
7. For history recovery, distinguish legacy `WeChat Files` storage from WeChat 4.x `xwechat_files`. Use official WeChat migration/backup-restore first; never overwrite one encrypted database layout with another.
8. Merge sources with a collision-resistant message identity containing chat, `local_id`, `sort_seq`, `server_id` and/or message type. Never deduplicate by `local_id` alone.
9. Audit old account directories and `Msg/Multi/bak` read-only. Preserve originals and document candidate sources, coverage and gaps in `docs/HISTORY_SOURCE_AUDIT.md`.
10. Keep AES/XOR/media secrets local only, protected with Windows DPAPI under `data/.secrets/`; never print, upload or commit secrets.
11. Persist the continuing problem tree, solution tree, import state, counts and unresolved sources in `docs/PROJECT_PROBLEM_TREE.md`, `docs/PROJECT_SOLUTION_TREE.md` and `docs/PROJECT_STATE.md`.

## Current capabilities

- Open a contact or group chat and prepare/send text.
- Prepare/send a group mention using the HWND action layer.
- Prepare/send files and images.
- HWND click, right-click, scroll and key actions.
- Open the emoji panel and send a previously verified sticker catalog item.
- Read and archive chat history, incremental messages and Moments locally.
- Import full local history into an offline SQLite archive, including media BLOBs, with resumable source auditing and collision-resistant IDs.
- Decode type-47 emoji semantic hints and rank contact-specific sticker preferences.
- Monitor a selected conversation through database change notification and a persistent cursor.
- Personal profile extraction is pending optimization; only fields actually returned by the local DB adapter may be reported.
- Structured local Memory, compact versioned Markdown views, incremental analysis jobs,
  on-demand evidence expansion, and an offline timeline dashboard.
- A local stdio MCP surface for external agents; real sends still require an
  exact single-use confirmation and the shared `BasicSkill` path.

## Unfinished work

Read `docs/FUTURE_TODO.md` before describing or implementing unfinished work. It is the canonical
list of IDs, priorities, dependencies, failure behavior, version targets, and completion criteria.
Do not treat `planned`, `blocked`, code-only, or automated-test-only work as a verified capability.
Update `PROJECT_STATE.md` when an item is completed; change the roadmap status to `verified` only
after its stated real-device checks also pass.

## Important boundaries

- The latest screenshot/navigation audit used Windows WeChat `4.1.15.9`, dark theme,
  144 DPI, window class `Qt51514QWindowIcon`. Other versions/layouts need validation.
- Do not add UIA, pywinauto action calls, physical mouse/keyboard fallbacks, injection, hooks, private protocol construction, or writes to WeChat's database.
- Do not commit anything under `data/`, chat exports, screenshots, logs or secrets.
- Memory/version/task infrastructure is implemented; person or relationship conclusions exist only after a successful analysis version is submitted.
- Keep advanced workflows above `BasicSkill`; never create a second UI transport.

## Page navigation and embedded content

Read `docs/ACTION_VERIFICATION_MATRIX.md` for tested transitions and
`docs/UI_PAGE_CATALOG.md` for page variants. Enumerated does not mean verified.

1. Observe `vision.observe_windows` before choosing a window. The main frame does
   not contain independent Qt popup HWNDs; reject a foreign process/window.
2. Distinguish the base chat, search dropdown, embedded right content tab, and
   independent window. A chat composer can coexist with a right search pane.
3. Use `actions.open_search_content(query)` to clear and verify the main search
   field, then select its exact network suggestion. Never use Enter to select an
   unknown result; resolve contact/group identity separately.
4. For one registered navigation step, call `actions.page_operation` with
   `expected_page` and the correct HWND. Fixed points require exact version,
   dimensions, DPI and theme; missing calibration stops the action.
5. Close an embedded right tab with `close_content_tab`. Its cross is a same-frame
   OCR/CV observation; BasicSkill routes the click to the embedded Chromium child.
   Never send WM_CLOSE to the main window to close a pane.
6. For editors, use `cancel`; Escape was ineffective in the sampled remark editor.
   Use `dismiss` only for registered menus, and `close` only for auxiliary windows.
7. Require `success=true` and a verified postcondition before the next step.
   Failure receipts are not success. Stop on ambiguity, OCR/capture failure,
   changed page or unsupported tabs. No automatic blind clicks or repeated sends.

`actions.plan_page_route` returns a declared route, not calibration certification.
`actions.page_capabilities` separates navigation from confirmed mutations. Sending,
editing real profiles, likes, comments and downloads keep their dedicated confirmation
flow; they are not enabled by generic page navigation.

## Failure handling

- Read/archive failures never fall back to writing WeChat databases or using private protocols.
- OCR/layout mismatch returns a failed observation or receipt; recalibrate before another coordinate action.
- Analysis failure keeps the last successful complete Markdown and leaves a resumable job.
- Identity ambiguity stops aggregation or action until a stable ID or confirmed merge resolves it.
- Sending, sticker, like, comment, and remote-media failures are never retried automatically; a new attempt needs new confirmation.
- Never log private content, profile data, media keys, or DPAPI secrets while diagnosing.

## Version contract

- Package version comes only from `src/wechat_auto/version.py`; documentation mirrors it.
- `MEMORY_SCHEMA_VERSION` controls SQLite compatibility. Stop on unsupported versions.
- `MCP_PROTOCOL_VERSION` identifies tool contract changes; inspect `status.summary` before workflows.
- `CONTACT_ACTION_PROTOCOL_VERSION` versions project-owned page/element IDs and action-plan fields.
- Analysis template version and input fingerprint control semantic rebuilds independently from schema.
- Markdown and event versions are append-only full snapshots; never edit history in place.
- Layout profiles bind WeChat version, client size, DPI, and theme; mismatch blocks coordinate actions.

## Contact actions

Resolve a contact with `entities.plan_contact_action(username, action, value)` using its exact
internal `username/wxid`. Treat alias, nickname, and remark only as UI navigation attributes.
For a mutation, show the stored plan, call `actions.confirm_contact(action_id)`, then pass only its
`action_id` and single-use `confirmation_id` to `actions.execute_contact`. Semantic IDs such as
`21.09:more` and `22.03:delete_contact` are project-owned identifiers whose coordinates must exist
in the active layout profile. Missing calibration is a hard failure. `set_remark` and
`delete_contact` require confirmation bound to the full stored plan; resync profiles after a
successful UI action before updating Memory.

## Roadmap context

Use the exact work IDs in `docs/FUTURE_TODO.md`. Personality and relationship templates are
`WA-404`; reply policy is `WA-403`; Moments is `WA-304`; public-account processing is `WA-402`.
These remain unavailable until their completion criteria are met.

For the product overview read `README.md`; for module boundaries read `ARCHITECTURE.md`.

## Shared UI and recipient contract

Before UI navigation, recipient selection, removal auditing, or reply dispatch, read
[UI_WORKFLOW_RULES.md](../../docs/UI_WORKFLOW_RULES.md). Use its search-state table,
stable-identity checks, missing/removal distinctions, and failure stop conditions.
Read [UI_PAGE_CATALOG.md](../../docs/UI_PAGE_CATALOG.md) for page descriptions and
[ACTION_VERIFICATION_MATRIX.md](../../docs/ACTION_VERIFICATION_MATRIX.md) for actual coverage.
These references must accompany the repository skill; missing references stop UI work.
Offline-only analysis does not require screenshots or UI actions. Static rules never
certify a live recipient; the complete stable-identity send workflow remains WA-005.
