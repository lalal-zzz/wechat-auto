# 窗口、页面、导航与图片复核

版本：0.8.0。窗口观察器 1、页面目录 3、页面动作协议 4；Memory schema 3、MCP 协议 2 不变。

## 实现链路

```text
绑定运行中的微信主 HWND 与连接时 PID
  → 枚举同进程的可见顶层窗口
  → 每个 HWND 独立截图、CV/OCR、识别前后几何/归属检查
  → 窗口角色 + 分层页面 + 控件定位实现范围
  → 唯一目标选择 / 有界导航路由
  → BasicSkill → 同一个 HWND 驱动
  → 再识别所有窗口，核验结果
  → 失败：重新测算 → 当前图片交给 Agent 复核 → 单次执行 → 再核验
```

识别器没有输入方法。账号/收件人身份和“这是通讯录/相册窗口”是不同证明。
主 HWND 被其他进程复用时拒绝继续，要求重新连接。微信数据库仍只读。
连接时使用当前微信主窗的 Win32 框架样式区分同类 Qt 辅助窗，不按标题或面积选择；
最小化主窗仍须绑定主 HWND。多个主窗候选必须停止，不能自行取最大窗口。
无标题的滚动个人相册须同时有左侧年份/月日列和明确可见范围页脚，且无聊天输入区
或竞争的主页面；页面识别不证明联系人身份。侧栏轮廓匹配须有高分且明显领先，
真实重复或接近候选仍拒绝，不能按固定位置取第一个。


## 窗口与页面分别保存

| 观察项 | 用途 |
|---|---|
| hwnd/pid/class/owner_hwnd | 当前窗口与进程/拥有者关联，不依赖私人的窗口标题 |
| rect/client_rect/dpi/enabled/minimized | 坐标转换、变更和模态禁用检查 |
| role | main_client、menu_window、editor_window、dialog_window、content_window、unknown_window |
| surfaces | 一个 HWND 中的 base/panel/overlay/window 页面候选及呈现位置 |
| presentation | embedded_main、embedded_panel、embedded_right_tab、embedded_overlay、auxiliary_window、auxiliary_popup |
| composer_present/right_panel_present | 聊天输入区和右侧内容的观察，不能替代身份认证 |
| operations | 可尝试的注册语义动作、定位器是否实现、主窗关闭禁令 |

例：主窗同时有聊天输入框和右侧搜一搜，仍只有一个 HWND、两个 surface。
独立相册是另一 HWND。不能把右侧网页输入框当成聊天输入框，也不能用两个相册
的列表顺序选择人。不存在目标时返回 target_page_not_found，多个目标返回
ambiguous_target_window；可用 presentation 和当前 hwnd 明确选择。

默认紧凑检查不返回原始 OCR、昵称、微信号、聊天文字或窗口标题。
`vision.observe_windows` 仍是需要时才使用的详细证据接口。

## API

| 工具 | 行为 |
|---|---|
| vision.inspect_windows | 新截图生成紧凑窗口/页面/动作清单，无动作 |
| vision.resolve_window(page,presentation,hwnd) | 唯一目标选择，无动作，不认证联系人 |
| actions.navigate_page(page,max_steps) | 默认最多 6 步，每步重选窗口、定位和验证，首个失败即停止 |
| actions.restore_main_window(max_steps) | 只关闭已知只读辅助内容、解除已知菜单；不会关闭主客户端或丢弃编辑器 |
| actions.ensure_contacts_section | 确认个人联系人标题/展开箭头，必要时只展开这个分组 |
| vision.prepare_review(operation,hwnd,expected_alias) | 保存当前私有图片与 120 秒、单次的复核计划，不输入 |
| actions.apply_review(review_id,box,source_page) | 验证 Agent 的像素框后执行一次限定只读导航并验证结果 |

页面路由是可执行框架，49 类目录不意味着所有控件均已实现或实测。
无定位器的步骤返回 operation_control_unimplemented；没有声明路线返回 route_unavailable。
只有聊天/通讯录/发现的幂等导航允许默认两次、最多三次重算。菜单切换、关闭和对外
动作不会自动重复。已知编辑器/评论/发布窗口需要用户明确处理，不自动按 Escape 丢草稿。

## 联系人分组

真实左侧树包含新的朋友、公众号/服务号、企业微信联系人、个人联系人等不同分组。
`observe_contact_section` 在当前测量的列表区域找精确“联系人”标题（允许计数），
再用当前箭头的形状区别展开/折叠。成员范围从这个标题下方开始，止于下一类别。

不能用“新的朋友”下的一项证明好友，不能选同名公众号或企业联系人。
个人资料/朋友圈入口取消了混合搜索自动兜底。列表未找到或同名多个就停止，
保存当前图交给 Agent 复核。列表扫描有页数预算；标题滚出视图时仅在已有分组
范围、同一页面/尺寸且没有其他分组信号时继续，无法确认则停止。

树标题滚出视图后，当前帧唯一通讯录图标的绿色选中状态可辅助观察页面。
它不能单独授权联系人选择：仍须已有个人分组展开的范围、同一窗口/尺寸及
无其他分组或阻断页面；未选中、重复或缺失图标不补认页面。

打开资料后使用当前可见 alias 精确核验；本地 username/wxid 不能冒充 alias。
朋友圈加载分别解析资料 HWND 与个人相册 HWND，不固定假定都是主窗口。

个人相册也可呈现为资料旁的右侧嵌入标签：保留中央资料页面，结合当前分隔线、
唯一朋友圈标签及相册的置顶/独立月日列观察；标题或昵称仍不能认证身份。
入口检测资料标签旁的唯一缩略图区域；滚动及关闭必须绑定已识别的相册呈现范围。
嵌入相册滚轮通过同一 HWND 驱动投递到当前点下唯一可见的渲染子窗口；正文使用
屏幕坐标的 WM_MOUSEWHEEL，子窗口缺失或歧义即停止，不回退到主窗。
正文可为 Chromium 或原生 MMUI；必须沿实际 GA_PARENT 父链关联唯一标签宿主，
不能只按点包含关系选择覆盖全窗的主 MMUI。Qt 嵌入后保留弹窗样式时，GetParent/
IsChild 不足以证明实际父链；父链断裂、循环或多个正文候选均停止。
封面滚出后仍从当前图像测量低对比度长边界，不能沿用上一帧边界。月日列可由
OCR 分别识别，也可合成“129月”一类文字框；合并框只用于观察日历布局，不直接
转换成发布时间或证明单条动态的置顶归属。

## 图片复核流程

1. 先使用失败回执中的 visual_review；没有计划时调用 vision.prepare_review。
2. Agent 查看返回的本机 image_path，识别目标与 source_page，给出
   `[x,y,width,height]` 像素框，不能直接点击或改变驱动。
3. 调用 actions.apply_review。绑定 PID/HWND/class/owner、窗口/客户区矩形、DPI
   和所审图片；计划 120 秒过期、只能消费一次。窗口或控件改变则重新截图。
4. 允许非目标区域极小的光标/时间噪声，目标框变化或大范围布局变化仍拒绝。
   空白框不是控件；侧栏提案必须在当前测量的侧栏，联系人提案必须在个人分组。
5. 只有有限的只读导航操作：四个侧栏入口、联系人更多/朋友圈、设置入口、
   展开个人联系人和打开个人联系人行。后两种个人身份操作必须绑定归档 alias。
   发送、删除、确定、发表、退出、点赞、任意 click、取消编辑器和下载不可复核执行。
6. 点击后继续核验页面；打开联系人行仍需精确 alias。失败保留失败，不自动复用框或重发。

截图只写入被忽略的 data/ui_audit/visual_review/；接口返回本机路径，不自动上传。
外部 Agent 使用图片由其调用方决定，项目不引入第二套点击器或视觉模型直接执行器。

## 使用入口

MCP 使用 vision.inspect_windows、vision.resolve_window、actions.navigate_page
和 actions.restore_main_window。检查接口返回的控件实现状态与动作前后条件。
页面目录描述识别范围，不代表全部导航流程具备运行时支持。

## 朋友圈后续

先验收：个人分组→唯一联系人→当前 alias→个人相册→有界加载→重新读本地库。
然后才进入远程媒体下载：保留完整原归档和增量水位、URL/媒体哈希清单、断点状态，
逐项确认联网下载并验证文件。空白/停滞/权限限制不等于没有动态或全部历史已下载。
资料、状态、覆盖与媒体接口说明见 CONTACT_COLLECTION.md、MOMENTS_ARCHIVE.md。

## 定向搜索与原生表情弹窗

单联系人发送可直接搜索，资料/朋友圈批量采集仍使用个人联系人分组。
主搜索字段核对可使用前台可见窗口截图，包含独立 popup；该合成图不能用来将 popup 内容识别为主聊天。
各辅助 HWND 仍独立 PrintWindow/OCR，资料卡可为同进程 owner=0 的 Qt ToolSaveBits 窗口，
必须继续核验明确资料页和 alias。搜索 popup 则仍须 owner 对应主 HWND。
资料和表情辅助窗的关闭必须由主 BasicSkill 指定辅助 HWND；绑定辅助窗自身不能解除主窗关闭保护。
表情入口由当前输入区公共笑脸形状定位；默认面板以标签与公共收藏心形识别，收藏以心形和当前选中背板识别。
收藏标签切换与只读关闭均有独立后置条件，不授权选择或发送任一表情格。
