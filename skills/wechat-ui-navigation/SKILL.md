---
name: wechat-ui-navigation
description: 识别当前微信 HWND 与分层页面，选择唯一目标、执行已登记导航并恢复已知只读窗口。联系人或朋友圈 UI 采集前使用；不授权发送、修改设置或下载媒体。
---

# 微信窗口与页面导航

实时 UI 操作前先阅读 [UI_WORKFLOW_RULES.md](references/UI_WORKFLOW_RULES.md)、[UI_PAGE_CATALOG.md](references/UI_PAGE_CATALOG.md)、[ACTION_VERIFICATION_MATRIX.md](references/ACTION_VERIFICATION_MATRIX.md) 和 [WINDOW_NAVIGATION.md](references/WINDOW_NAVIGATION.md)。

## 识别窗口并选择目标

1. 调用 `vision.inspect_windows` 检查当前进程窗口。回执包含 HWND 角色、所有者、几何信息、DPI、可见页面、输入框状态和可用操作；不会返回私有 OCR 内容或窗口标题。窗口未知、过期或不可用时停止。
2. 调用 `vision.resolve_window` 选择目标页面。区分 `embedded_main`、`embedded_right_tab`、`auxiliary_window` 和 `auxiliary_popup`。不得选列表中的第一个候选；多个窗口都匹配时，用当前清单确定目标窗口，否则请用户选择。
3. `action_authorized=false` 和 `identity_verified=false` 是刻意的安全状态。页面识别、标题匹配或当前 HWND 都不能证明联系人身份。须先从本地稳定 ID 确认 `username/wxid`，再核对资料页上精确显示的 alias。

## 导航与恢复

使用 `actions.navigate_page(page, max_steps=6)` 执行已登记路线。每一步都由 BasicSkill 使用当前帧 CV/OCR 坐标执行，之后重新盘点所有窗口。路线遇到首个后置条件失败即停止；Windows 消息返回成功本身不代表页面切换成功。检查每步结果和 `stop_reason`。

仅当任务允许关闭已知菜单或只读辅助内容时调用 `actions.restore_main_window`。它不会关闭主客户端、改设置、选文件或丢弃编辑器/评论/发布草稿。遇到这类编辑器时明确告知用户可用的处理方式；不要反复按 Escape。

## 失败与恢复

恢复顺序是：重新观察当前画面 → 根据新画面重新计算 CV/OCR 目标 → 使用受保护的 Agent 图片复核。侧栏失败回执若有 `visual_review`，应优先使用。否则明确调用 `vision.prepare_review(operation, hwnd, expected_alias)`，查看其本地图片，再把像素坐标 `[x,y,width,height]` 和 `source_page` 交给 `actions.apply_review`。

单次复核计划在 120 秒后失效；若 HWND、PID、几何、DPI、帧或目标变化也会被拒绝。复核不得发送、删除、下载、取消编辑器或执行任意点击。实际动作与结果验证都必须由 BasicSkill 完成。

资料与个人朋友圈采集中的联系人导航调用 `actions.ensure_contacts_section`，只展开个人“联系人”分组，并选择其标题下的精确行。不得进入“新的朋友”、服务号或企业联系人分类，也不得退回混合全局搜索。缺标题、候选行歧义或资料页没有精确 alias 时停止；这不能作为删除好友的证据。

定向发送的收件人直接搜索，按共用规则核对当前查询、联系人分区中的完整名称精确候选，再核验资料 alias 并返回同一聊天；不滚动遍历通讯录。仅页面导航和资料核验不授权发送。排错与实现边界见 [UI_FAILURE_RECOVERY.md](references/UI_FAILURE_RECOVERY.md)。

按回执处理错误：

- `target_page_not_found`：检查加载状态和当前页面；不能据此推断删除。
- `ambiguous_target_window`：根据当前 HWND/展示状态重新选择；不能依赖列表顺序。
- `unrecognized_auxiliary_window` 或 `window_observation_unavailable`：保留本地证据并检查窗口；禁止使用固定坐标回退。
- `blocking_window_requires_handling` 或 `editor_requires_explicit_handling`：说明观察到的阻挡窗口和受支持操作；不得自动取消用户工作。
- `operation_control_unimplemented` 或 `route_unavailable`：说明检测器或路线尚未实现；目录中有页面不代表按钮可用。
- `navigation_postcondition_failed` 或 `restore_postcondition_failed`：停止并保留回执，不得猜测窗口后继续操作。

联系人/会话/发现页导航默认最多基于两次全新观察重试。发送、菜单切换和关闭动作不得自动重试。

## 朋友圈采集交接

导航验证后，按 [CONTACT_COLLECTION.md](references/CONTACT_COLLECTION.md) 执行资料与朋友圈采集。资料窗口和个人相册窗口须分别确认。`local_db` 覆盖与 `ui_load` 覆盖分开记录；相似相册不证明属于同一人。相册为空或加载停滞不代表历史完整或好友已删除。

联网下载媒体是独立操作，必须逐项取得明确确认。打开或滚动相册不授权下载，也不证明所有帖子已缓存。

## 数据工作流与交接

执行前阅读[数据新鲜度与联动规则](references/SKILL_DATA_WORKFLOW.md)，确定请求类型。每一步都重新观察 HWND、页面、控件和窗口几何，不复用其他 Skill 的截图坐标。同步新鲜度不能替代当前帧证明，页面识别也不能替代联系人身份核验。

联系人定位需要稳定身份时联动 wechat-identity-audit；本地映射更新交给 wechat-sync。个人分组和资料身份核验成功后，把当前目标和回执交给 wechat-profile-moments；回复页面核验交给 wechat-reply-monitor，本 Skill 不代其发送。

图片复核只解决白名单导航中的一步定位。帧过期、窗口未知、同名歧义或后置验证失败时停止并交接失败状态；不得继续下一个联系人，也不得把图片坐标视为持续授权。

## 随包资源范围

执行规则、参考文档与模板只读取本 Skill 目录中的 `references/`、`assets/` 和已提供的 `scripts/`，相对路径从本 Skill 目录解析。不能跨目录借用另一个 Skill 的参考资源；缺少必需随包资源时报告缺失，维护时补齐本目录副本。其他 Skill 名称仅表示流程职责与上下游，不代替本目录资源。项目运行接口、正式数据路径与项目命令是运行依赖，不是外部指令来源；不为打包复制私人数据。
