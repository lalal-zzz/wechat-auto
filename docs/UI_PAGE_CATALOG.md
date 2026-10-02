# 微信界面枚举与识别覆盖

更新时间：2026-10-01。页面目录版本：3。目录源为 `src/wechat_auto/primitives/page_catalog.py`，项目页面编号源为 `actions/semantics.py`。

## 使用规则

- 页面名称是项目自己的语义，不是微信暴露的控件 ID。
- 一帧返回底层 page、page_candidates、panels、overlays 和 content_windows；辅助窗口另行采样。主窗右侧标签不能抹掉中央聊天状态，独立弹窗也不能当成主窗内容。
- 同一种内容可为中央嵌入、右侧标签或独立窗口。catalog 的 presentations 声明候选形态，实际需结合 HWND 与当前截图识别。
- 多数规则识别使用多个独立文字组；同一组中的词是备选，组与组必须全部满足。输出保留候选，不自动点击。
- 目录共 49 类；本机实际采样覆盖 16 类页面状态，其他界面与环境仍待验收。实机动作结果见 [ACTION_VERIFICATION_MATRIX.md](ACTION_VERIFICATION_MATRIX.md)。
- 群聊身份需要用稳定 @chatroom ID 校验，不能仅靠标题或人数识别。
- template_required 表示已枚举但尚无可靠文字规则，需边缘/图标模板、窗口类型及当前帧布局测量。
- 浅色、深色、DPI 和尺寸变化是每种页面都要覆盖的验证维度。

## 全量目录

| ID | 界面 | 层 | 上级 | 识别方式 | 必需文字组（组间 AND，组内 OR） | 实机状态 |
|---|---|---|---|---|---|---|
| 1 | 登录/扫码 (`login`) | base | - | anchor_rule | 扫码登录/扫描二维码；微信/登录 | 待实机截图与验收 |
| 2 | 锁定 (`locked`) | overlay | - | anchor_rule | 微信已锁定/已锁定；解锁/在手机上解锁 | 待实机截图与验收 |
| 3 | 网络/连接异常 (`connection_error`) | overlay | - | anchor_rule | 连接已断开/网络连接异常；重试/重新连接 | 待实机截图与验收 |
| 10 | 主界面未选会话 (`main_without_selected_chat`) | base | - | runtime_fusion | 需要结构/身份/模板补充 | 待实机截图与验收 |
| 11 | 聊天 (`chat`) | base | - | runtime_fusion | 需要结构/身份/模板补充 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 12 | 群聊 (`group_chat`) | base | chat | stable_identity_required | 需要结构/身份/模板补充 | 待实机截图与验收 |
| 13 | 本地搜索结果 (`search`) | panel | - | anchor_rule | 联系人/群聊；聊天记录/搜索结果/服务号/功能/最近使用过的小程序 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 14 | 聊天记录检索 (`chat_history`) | panel | chat | anchor_rule | 聊天记录；全部/图片与视频/文件/日期 | 待实机截图与验收 |
| 15 | 消息右键菜单 (`message_menu`) | overlay | chat | anchor_rule | 复制；引用/转发/多选 | 待实机截图与验收 |
| 16 | 表情面板 (`emoji_panel`) | panel | chat | template_required | 需要结构/身份/模板补充 | 待实机截图与验收 |
| 17 | 图片/视频查看器 (`media_viewer`) | window | chat | template_required | 需要结构/身份/模板补充 | 待实机截图与验收 |
| 18 | 文件预览 (`file_preview`) | window | chat | template_required | 需要结构/身份/模板补充 | 待实机截图与验收 |
| 19 | 发现 (`discover`) | base | - | anchor_rule | 发现；朋友圈/视频号/搜一搜 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 20 | 通讯录 (`contacts`) | base | - | anchor_rule | 通讯录/通讯录管理；新的朋友/群聊/标签 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 21 | 联系人资料 (`contact_profile`) | base | contacts | anchor_rule | 微信号/微信号:；发消息/设置备注和标签/音视频通话 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 22 | 联系人更多菜单 (`contact_more`) | overlay | contact_profile | anchor_rule | 删除联系人；推荐给朋友/把他推荐给朋友/设置朋友权限/投诉/举报 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 23 | 备注编辑 (`contact_remark`) | overlay | contact_profile | anchor_rule | 设置备注和标签/备注；完成/保存 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 24 | 朋友权限 (`contact_permissions`) | overlay | contact_profile | anchor_rule | 朋友权限；仅聊天/聊天、朋友圈、微信运动等 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 25 | 标签编辑 (`contact_tags`) | overlay | contact_profile | anchor_rule | 标签/设置标签；新建标签/添加标签 | 待实机截图与验收 |
| 26 | 新的朋友 (`new_friends`) | base | contacts | anchor_rule | 新的朋友；接受/添加朋友/已添加 | 待实机截图与验收 |
| 27 | 私聊信息侧栏 (`chat_details`) | panel | chat | anchor_rule | 聊天信息/聊天详情；消息免打扰/置顶聊天/查找聊天记录 | 待实机截图与验收 |
| 30 | 群聊列表 (`group_list`) | base | contacts | template_required | 需要结构/身份/模板补充 | 待实机截图与验收 |
| 31 | 群资料/管理 (`group_details`) | panel | group_chat | anchor_rule | 群聊名称；群公告/群管理/我在本群的昵称 | 待实机截图与验收 |
| 32 | 群成员 (`group_members`) | panel | group_details | anchor_rule | 群成员/查看全部群成员；搜索/添加成员 | 待实机截图与验收 |
| 33 | 群公告 (`group_announcement`) | overlay | group_details | anchor_rule | 群公告；发布/编辑/完成 | 待实机截图与验收 |
| 34 | 群名称编辑 (`group_name`) | overlay | group_details | anchor_rule | 群聊名称；保存/完成 | 待实机截图与验收 |
| 35 | 邀请群成员 (`group_invite`) | overlay | group_details | anchor_rule | 选择联系人；确定/邀请 | 待实机截图与验收 |
| 40 | 朋友圈信息流 (`moments_feed`) | base | - | anchor_rule | 朋友圈；朋友的新动态/今天/昨天/赞/评论 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 41 | 个人朋友圈/相册 (`moments_person`) | base | contact_profile | anchor_rule | 相册/个人相册；今天/昨天/朋友圈 | 待实机截图与验收 |
| 42 | 单条朋友圈详情 (`moments_detail`) | window | moments_feed | template_required | 需要结构/身份/模板补充 | 待实机截图与验收 |
| 43 | 朋友圈评论输入 (`moments_comment`) | overlay | moments_detail | anchor_rule | 评论；取消/发表 | 待实机截图与验收 |
| 44 | 发布朋友圈 (`moments_publish`) | window | moments_feed | anchor_rule | 发表朋友圈/发布朋友圈；发表/谁可以看/所在位置 | 待实机截图与验收 |
| 45 | 朋友圈点赞评论菜单 (`moments_menu`) | overlay | moments_feed | anchor_rule | 赞/取消赞；评论 | 待实机截图与验收 |
| 50 | 公众号列表 (`official_accounts`) | base | - | anchor_rule | 公众号/订阅号 | 待实机截图与验收 |
| 51 | 公众号文章 (`article`) | panel | official_accounts | anchor_rule | 阅读原文；阅读/赞/在看 | 待实机截图与验收 |
| 52 | 视频号 (`channels`) | window | - | anchor_rule | 视频号；推荐/关注/朋友 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 53 | 视频号直播 (`channels_live`) | window | channels | anchor_rule | 直播；直播中/进入直播间/观看 | 待实机截图与验收 |
| 54 | 搜一搜 (`web_search`) | panel | - | anchor_rule | 搜一搜；搜索/全部/文章 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 55 | 小程序 (`mini_program`) | window | - | template_required | 需要结构/身份/模板补充 | 待实机截图与验收 |
| 60 | 设置 (`settings`) | window | - | anchor_rule | 设置/账号与存储；账号设置/通用设置/消息通知/通用 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 61 | 文件传输助手 (`file_transfer`) | base | chat | anchor_rule | 文件传输助手 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 62 | 收藏 (`favorites`) | base | - | anchor_rule | 收藏；全部/笔记/链接/文件 | 待实机截图与验收 |
| 63 | 主菜单 (`main_menu`) | overlay | - | anchor_rule | 设置；收藏/锁定/备份与恢复/迁移与备份 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 64 | 小程序列表 (`mini_program_list`) | base | discover | anchor_rule | 小程序；最近使用/我的小程序 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 65 | 网络搜索建议 (`search_suggestions`) | panel | search | anchor_rule | 搜索网络结果 | 4.1.15.9 深色/144 DPI 已采样；其他环境待验收 |
| 70 | 语音/视频通话 (`call`) | window | chat | anchor_rule | 挂断/接听；视频通话/语音通话/拒绝 | 待实机截图与验收 |
| 90 | 确认弹窗 (`confirm_dialog`) | overlay | - | anchor_rule | 取消；确定/删除/确认 | 待实机截图与验收 |
| 91 | 文件选择器 (`file_picker`) | window | chat | anchor_rule | 文件名/文件名:；打开/保存 | 待实机截图与验收 |
| 92 | 错误提示 (`error_dialog`) | overlay | - | anchor_rule | 操作失败/加载失败/无法打开；确定/重试/关闭 | 待实机截图与验收 |

## 子状态检查矩阵

| 页面族 | 需要覆盖的子状态 |
|---|---|
| 主界面/聊天 | 未选会话、私聊、群聊、空输入、有草稿、只读系统会话、右栏打开/关闭、引用卡片、艾特选择、搜索覆盖、未读提示 |
| 通讯录 | 列表、搜索结果、联系人详情、自己资料、新朋友、群列表、标签列表、加载中/空列表 |
| 联系人详情 | 有/无公开微信号、有/无备注、更多菜单、备注编辑、权限设置、标签编辑、删除确认、字段不可见 |
| 群管理 | 基础资料、成员列表、公告读取/编辑、群名编辑、邀请成员、非管理员权限、退群确认 |
| 朋友圈 | 信息流、本人/他人相册、单条详情、图文/纯文/视频、点赞评论菜单、评论输入、发表页、空白/权限限制、加载失败 |
| 公众号/视频号 | 左侧列表、中央内容、右侧内容、独立窗口、网页阅读、视频播放、直播、关闭按钮、登录/权限限制 |
| 搜索 | 联系人、群聊、聊天记录、公众号、小程序、搜一搜、无结果、加载中、搜索输入框焦点 |
| 其他窗口 | 图片查看、视频查看、文件预览、文件选择、收藏、设置、通话、锁定、二维码登录、错误提示 |

## 识别与动作验证

1. 为每个页面建立脱敏截图样例；真实私人页面只保存到 `data/ocr/`。
2. 样例标注页面 ID、上级页面、面板/弹窗、微信版本、DPI、窗口大小、主题和预期状态。
3. `recognize_wechat_page.py --image ...` 做离线重放，核对区域和候选；不为采样执行删除或发送。
4. 没有文字的图标和空状态先补本地模板，再注册规则；不得以枚举完成代替识别验收。
5. 页面观察与动作执行分别验收。历史字段 `actions_calibrated=false` 表示目录不提供动作验收证明；不允许恢复固定坐标档案。
6. 独立窗口页面必须捕获其自身 HWND；默认 recognize CLI 仍只截图主窗，audit CLI 和 vision.observe_windows 会逐个捕获同进程辅助窗口。

## 运行接口

```powershell
python scripts\recognize_wechat_page.py --list-pages
python scripts\recognize_wechat_page.py --image data\ocr\latest\capture.png
```

MCP `vision.page_catalog` 不依赖微信运行时；`vision.observe_page` 需要真实 BasicSkill/窗口观察器。新页面只需追加目录和识别规则，不复用已分配 ID。
