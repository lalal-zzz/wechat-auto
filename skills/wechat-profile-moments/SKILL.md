---
name: wechat-profile-moments
description: 将资料和朋友圈变化整理为带时间来源的人物证据；谨慎推断，失败后可续做。
---

# 资料与朋友圈

此 Skill 为人物分析提供资料快照和朋友圈证据，不能代替私聊/共同群分析，也不能只凭头像生成全局画像。分享一条朋友圈不自动表示赞同或实际到场。资料变化只有在身份、时间和内容均可核对时才能与聊天变化对齐；无关会话不因资料更新而强制重建。

## 存储与证据

先阅读 [MEMORY_STORAGE_CONTRACT.md](references/MEMORY_STORAGE_CONTRACT.md)、[ANALYSIS_QUALITY_STANDARD.md](references/ANALYSIS_QUALITY_STANDARD.md) 和 [CONTACT_COLLECTION.md](references/CONTACT_COLLECTION.md)。结构化数据写入配置的 `data/wechat_memory.sqlite3`；分析正文写入 `data/memory/people/{person_id}/current.md`，历史版本由提交接口维护。未验收候选与阅读进度只放在 `data/work/analysis/{run_id}/`。显式自定义存储位置时，将解析后的路径写入 `data/analysis_sources.json`。

交接稳定 `person_id`、快照/帖子来源引用、实际可读取内容、字段变化、发布时间、观察时间及覆盖情况。资料和朋友圈事实标为 `observed`，推断须有多条相互独立证据，并保留反例；不要把帖子主题直接归为兴趣、态度或活动参与事实。

## 采集步骤

1. 先完成本地采集与索引，再根据目标人物的缺口决定是否需要 UI 加载。
2. 相册覆盖读取 [CONTACT_COLLECTION.md](references/CONTACT_COLLECTION.md)。使用 `sync.enqueue_moments_contacts`、`sync.moments_queue` 和 UI runtime 的 `sync.load_contact_moments` 处理稳定人物 ID。该操作只加载当前可见相册，结束后重新读取本地库；`local_db` 和 `ui_load` 覆盖分开记录。空缓存不代表没有动态；全联系人队列只是候选列表，不是当前好友认证。
   置顶与普通动态分别交接 `sections`；普通可见期限不套用到置顶，最早缓存日期不证明普通历史完整。区域观察不等于逐条置顶归属已核验；缺少证据保持 unknown。
3. UI 操作前阅读 [WINDOW_NAVIGATION.md](references/WINDOW_NAVIGATION.md)。分别确认主窗口、资料窗口和个人相册 HWND。调用 `actions.ensure_contacts_section` 定位个人“联系人”分组，只选其标题下精确条目；不得进入“新的朋友”或混合搜索。导航失败时读取回执，以新帧重新计算目标；必要时使用 `vision.prepare_review` → `actions.apply_review`。缺少精确 alias、窗口身份或当前帧时停止。静态页面识别不证明相册采集成功。
4. 用户明确要求刷新全部联系人的可读本地动态时，阅读 [MOMENTS_ARCHIVE.md](references/MOMENTS_ARCHIVE.md)，再从仓库根目录运行 `scripts/sync_all_contacts_moments.py`。该脚本只处理本地可读数据并生成本地媒体清单，不联网下载，也不证明当前好友关系。不得因 `local_type` 推断删除或越过来源范围改写归档。
5. 调用 `sync.index_archives`，只处理新快照/动态影响的人物。比较前后快照；未变化字段不新增快照或分析事件。需要比对时使用内容 hash。
6. 仅当时间与身份可靠时，才把资料变化与会话时间线对齐。缺少资料字段代表 `unknown`，不代表已删除。

## 资料补采与媒体

稳定身份核验后，调用 `sync.capture_contact_profile` 保存资料页明确可见字段；保存对象须绑定稳定 wxid 和精确 alias。缺失或歧义字段记为未观察，不清除已有资料。签名、地区、联系人来源、添加时间和共同群须保留来源；仅文字字段不能证明头像或性别图标含义。UI 查找失败时不得保存猜测到的人物档案。

本地媒体可用 `scripts/archive_local_moments_media.py --manifest ...` 匹配精确缓存；不联网，也不按文件大小模糊匹配。远程媒体必须逐项向用户展示作者、动态、类型和序号，并取得该条目的明确确认后，才可调用 `scripts/download_moments_item.py`，使用已复核的 `item_id` 与 `--confirm`。媒体指纹变化会使确认失效。不得把确认转给别的项目，也不得自动重试网络或格式错误。具体采集边界见 [MOMENTS_ARCHIVE.md](references/MOMENTS_ARCHIVE.md)。

## 失败处理

- 可选字段缺失：保留 unknown，不表示删除。
- 媒体损坏：保留元数据，标记不可用。
- 远程媒体：保持待处理，直到逐项确认。
- 联系人重新出现：记录恢复事实，不删除缺席历史。
- 来源冲突：分别保留各来源说法，不静默覆盖。
- 相册 `stop_reason` 为 `page_budget`、`unchanged_album_frame`、整体拒绝访问提示或异常时，分别记录 partial、stalled、restricted 或 failed；它们都不能证明已读完整。普通区域的期限提示仅保存分区限制，不升级为整体拒绝访问。
- 导航失败时停止当前人和批次，不能带着未知页面继续下一个人。
- 崩溃后仍为 running 的队列项，须先确认旧进程结束，再显式调用 `sync.recover_moments_contact`；失败项也须显式重跑。
- `requires_navigation_restore=true` 时，恢复并验证页面后才处理下一个人。

## UI 与数据联动

涉及 UI、联系人状态或回复时，按仓库规则阅读 [UI_WORKFLOW_RULES.md](references/UI_WORKFLOW_RULES.md)、[UI_PAGE_CATALOG.md](references/UI_PAGE_CATALOG.md) 和 [ACTION_VERIFICATION_MATRIX.md](references/ACTION_VERIFICATION_MATRIX.md)。执行前也阅读[数据新鲜度与联动规则](references/SKILL_DATA_WORKFLOW.md)。

当前资料和朋友圈先调用 `sync.contacts_moments_local`；需要加载指定相册时联动 wechat-ui-navigation，身份有歧义时联动 wechat-identity-audit。UI 加载后重新读库，再由 wechat-sync 索引。变更证据交给 wechat-person-analysis，长期事件再交给 wechat-timeline。每次交接说明身份、来源范围、覆盖、水位、成功输出和缺口。此流程不授权自动下载；导航受限或停滞时停止，不清空旧字段，也不把部分覆盖说成完整。

## UI 排错与实测规划

遇到搜索、资料入口、输入区、发送结果或表情定位问题时，读取随包的
[UI_FAILURE_RECOVERY.md](references/UI_FAILURE_RECOVERY.md)。按其中的问题/处理表区分
已实现处理与剩余缺口，保留首次失败回执；发送 unknown 仅增加只读复核证据，不自动重发。
用户要求 OpenCV + OCR 全流程实测时，正常步骤不依赖 Agent 看图，失败后才图片排错。
具体账号、正文、截图与运行流水只存本机忽略的台账，不写入 Skill。

## 随包资源范围

执行规则、参考文档与模板只读取本 Skill 目录中的 `references/`、`assets/` 和已提供的 `scripts/`，相对路径从本 Skill 目录解析。不能跨目录借用另一个 Skill 的参考资源；缺少必需随包资源时报告缺失，维护时补齐本目录副本。其他 Skill 名称仅表示流程职责与上下游，不代替本目录资源。项目运行接口、正式数据路径与项目命令是运行依赖，不是外部指令来源；不为打包复制私人数据。
