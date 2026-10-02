---
name: wechat-sync
description: Incrementally index local WeChat message, profile, group, and Moments archives with persistent cursors, source auditing, and safe recovery.
---

# WeChat Sync

Use before analysis, after a directory-change notification, or when a source watermark is behind. Read WeChat through read-only backends and write only project databases.

## Procedure

1. Call `status.summary` and record application, Memory schema, and MCP protocol versions.
2. Verify configured sources exist and distinguish WeChat 4.x `xwechat_files` from legacy data.
3. Update the required source archives first using the available read-only source workflow; only then call `sync.index_archives`. Indexing existing archives is not live acquisition.
4. Check the returned source coverage and index deltas. Validate idempotency when relevant; unchanged input must add no references or jobs.
5. Record full imports, migrations, media completion, ranges, failures, and gaps in the two audit documents.

## Failure handling

- Missing or locked source: leave cursors unchanged and retry after the external condition changes.
- Legacy database: audit read-only and use official migration/restore; never overwrite a 4.x database.
- Partial batch: preserve the last committed cursor and resume from it.
- Identity collision: create a merge candidate; never merge equal display names automatically.
- Media failure: keep message metadata and mark media pending. Remote download requires confirmation.

## Version rules

Adapter changes require an input-fingerprint change. A Memory schema mismatch stops sync until a compatible migration or rebuild exists. Never silently downgrade cursors or rewrite raw archives.

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

分析前区分“微信来源→原始归档”和“原始归档→Memory 索引”。
聊天增量使用已装配的 monitor.run_once/只读归档流程；资料与朋友圈使用
sync.contacts_moments_local。这些成功后才运行 sync.index_archives。
历史导入按原始来源范围处理，不能用一次监控代替全历史同步。
资料需要 UI 补采时交给 [wechat-profile-moments](../wechat-profile-moments/SKILL.md)，
身份/删除状态不明时交给 [wechat-identity-audit](../wechat-identity-audit/SKILL.md)。
交接来源回执、水位、缺口及受影响月份；新消息交给
[wechat-monthly-analysis](../wechat-monthly-analysis/SKILL.md)，新资料/动态交给
[wechat-person-analysis](../wechat-person-analysis/SKILL.md)。无增量不重复触发分析。
源锁定/不可用时不推进水位；已有归档可作为注明截至范围的历史输入。
