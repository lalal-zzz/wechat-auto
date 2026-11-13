# 联系人与朋友圈两路采集

实现版本：0.8.1；Memory schema：3；页面动作协议：4。Windows 微信 4.x。

## 数据库路径

`sync.contacts_moments_local` / `scripts/sync_all_contacts_moments.py` 只读本机
DPAPI 密钥可打开的 contact.db、sns.db。全量读取当前缓存，按稳定 username 关联
人物，变化才写资料快照和动态；归档外的旧记录仍保留。不用未经验证的 local_type
猜好友身份，也不累计删除证据。每个人都写 `local_db/cached_only` 覆盖观察，包括
本轮没有缓存动态的人。没有缓存不等于没有发过朋友圈。

`moments_coverage` 保留每次路径、数量、滚动次数、停止原因、证据引用与时间。
历史覆盖观察会增加，原始内容、资料快照和分析版本不重复增加。

## UI 加载路径

先读取 [UI_WORKFLOW_RULES.md](UI_WORKFLOW_RULES.md)、
[UI_PAGE_CATALOG.md](UI_PAGE_CATALOG.md)、
[ACTION_VERIFICATION_MATRIX.md](ACTION_VERIFICATION_MATRIX.md)。

1. 将稳定 person_id 加入 `sync.enqueue_moments_contacts`；`sync.moments_queue` 查看。
2. `sync.load_contact_moments(person_id, max_pages)` 需要带 UI runtime 的 MCP。
   状态门禁拒绝已知删除、拉黑、推测移除或未知对象；资料必须能关联唯一 wxid 和可见 alias。
   单次快照缺席（missing）仅允许进入个人联系人分组的只读身份复核，必须经当前资料
   alias 精确核验才能进入相册；不清除缺席历史、不恢复好友关系、不放开发送门禁。
3. BasicSkill 使用当前截图 OpenCV 导航图标及个人“联系人”分组下精确候选。
   同名多候选、网络/历史记录候选、缺少 alias、资料不符都停止。
   个人联系人列表扫描默认最多 30 次，使用每帧的分组范围；此预算与相册页数分别计数。
4. 资料中可见微信号必须精确匹配数据库 alias，才允许点击唯一“朋友圈/相册”入口。
   有缩略图时入口来自当前资料标签旁唯一缩略图区域，不把文字标签本身当作可点击入口。
   队列将稳定 wxid 传给资料补采；在进入相册前保存当前可见资料字段与原帧证据。
   已有其他个人相册未关闭时停止；个人相册页面必须被识别，不能用信息流代替。
5. 只通过 BasicSkill/同一 HWND 驱动滚动该窗口。每次滚动前后观察页面。
   默认最多 5 页，上限 30；连续两次相册正文图像指纹不变记 `stalled`，不是完整下载。
   指纹只比较当前相册区域，照片变化但文字相同时继续；滚动点来自当前相册正文范围。
   右侧嵌入相册由 BasicSkill 将滚轮投递到当前点下唯一可见的嵌入渲染 HWND；
   缺失或歧义立即停止，不回退到主窗口滚动聊天或联系人列表。
   明确拒绝访问提示记整体 `restricted`；次数耗尽记 `partial`；页面变化立即停止。
   普通动态的三天、一个月、半年提示只限制普通区域，不能提前停止置顶区域观察。
6. 已验证的独立个人相册用注册关闭动作退出；唯一嵌入个人相册标签使用注册标签关闭动作。
   无法核对返回路径的嵌入页保留页面、
   返回 `requires_navigation_restore=true`，批次停止，不用猜测返回坐标。
7. 加载后重新打开只读数据库副本并同步。不能复用加载前的解密副本。
   微信客户端正常加载可见内容可能产生自身联网请求；本项目不自行下载远程媒体。

```powershell
# 只排队，不操作 UI。全部条目只是候选，不代表全部是当前好友。
python scripts\load_contacts_moments.py --enqueue-all --queue-only
# 从队列处理最多一位，实际 UI 停止条件优先于预算
python scripts\load_contacts_moments.py --max-contacts 1 --max-pages 5
```

可重复 `--person-id` 精确选择对象。队列保留 pending/running/partial/failed；失败不
自动重试，失败后停止整个批次。进程意外结束后的 running 不能自动抢占；确认原
进程已退出后，调用 `sync.recover_moments_contact` 再显式重新运行。

UI 页面加载与归档媒体下载是两回事。远程媒体继续逐项确认，单张下载目前未验收。
权限、删除、拉黑、时间可见范围和服务器限制都可能造成缺口，两路均不能宣称完整历史。

## 删除、拉黑和访问状态

`entities.contact_state` 返回当前状态与完整历史；
`entities.record_contact_state` 保存新的、可追溯的观察，不执行删除/拉黑。

| relation | value | 含义 |
|---|---|---|
| local_contact | present / removed / unknown | 本人侧联系人关系 |
| local_block | blocked / unblocked / unknown | 本人是否拉黑对方 |
| peer_contact | removed / unknown | 对方明确删除本人；未发生删除不代表已证实好友 |
| peer_block | blocked / unknown | 对方明确拉黑本人 |
| moments_access | visible / restricted / unavailable / unknown | 朋友圈可见性，不推出好友或拉黑状态 |

每条记录要求稳定 observation_key、person_id、source、evidence_ref。删除/拉黑必须
来自用户明确确认或人工核对的可归因系统信号，并传 confirmed=true；普通 OCR 观察
不能提交这些确定状态。一次搜索失败、仅删除会话、相册空白和权限提示都不能推出删除。
状态重复提交幂等，重复 key 携带不同内容会报错。恢复/解除拉黑追加新记录，不删除旧记录。
资料归档不会自动清除这些状态。身份合并保留并迁移状态/覆盖历史，原队列标记 merged。

缺席规则仍使用独立 presence 状态：三次不同完整快照、至少 24 小时才推测消失。
不完整快照不累计缺席，也不自动恢复；重复快照不增加计数；持续消失继续累计。
不可把包含未知类型的 contact.db 全部条目声明为经过认证的完整好友快照。

MCP 私聊发送入口会拒绝已映射成员的已知删除/拉黑/缺席状态；群中的单个成员拉黑不
阻止整群发送。此检查只补充已有映射，完整收件人稳定身份与结果验证仍是 WA-005。
底层直接 BasicSkill 调用并没有统一 Memory 状态门禁，不能宣称全部发送入口已贯通。

## 迁移与覆盖规则

### 置顶与普通动态

个人相册分为 `pinned` 和 `regular`。置顶内容可早于普通动态的可见期限；不得用
最早置顶日期证明普通历史覆盖，也不得根据已缓存日期反推出当前可见期限。
仅观察到“置顶”标记时记录置顶区域 `observed`，不代表逐条置顶内容已读取或入库。
普通区域的明确期限提示分别记录 `three_days`、`one_month`、`six_months`；无提示为
`unknown`。置顶不继承普通期限，当前可见也不能证明未来始终可见。

`moments_section_coverage` 通过 observation_key 关联每次覆盖观察，分别保存区域、
观察状态、期限与提示。`sync.moments_coverage` 返回每次观察的 `sections`。
schema 3 增量建表保留旧观察；旧缓存及缺少区域证据的记录均为未知，不按日期追补
单条动态的置顶属性。区域限制不写成整体拒绝访问，也不推出删除或拉黑。
滚出置顶区域后保留同次采集中已观察到的标记；停滞仍不能证明两区完整。

历史资料归档索引只登记不完整快照，不参与缺席累计，也不恢复联系人状态。
累积归档、旧资料和未分类 contact.db 条目均不能充当当前完整好友快照。

v1/v2 Memory 打开时执行增量建表迁移到 v3，不重写消息、Claim 或 Markdown。
新增 contact_state_history、moments_coverage、moments_section_coverage、moments_load_queue；不支持的高版本拒绝打开。
正文不写分析 JSON，SQLite 中只留短状态与证据引用。失败仍使用上一成功 Memory 版本。

## 0.8.1 资料补采

`sync.capture_contact_profile(wechat_id, expected_alias, database_path)` 仅观察和保存：
唯一资料 HWND→当前资料页→归档 wxid/alias→同帧精确微信号→显式字段。
支持昵称、备注、地区、个性签名/签名、来源、添加时间、共同群聊、标签及文字性别。
不根据头像/性别图标推断字段，不把无标签的一段文字猜作签名。
字段及公共标签的坐标来自当前帧，拒绝多个同名字段和值候选，排除联系人列表文字。
不存在或不可见的字段保留旧值，空 OCR 不能证明清空；相同观察不新建完整快照。
每字段保存 observed、来源与原截图引用；额外资料字段参与变化历史和 Memory 索引。
本地 DB 空签名不清除 UI 已补采签名。不能声明所有人所有基本信息都可见。

资料可见性与检测器支持决定能采集的字段，不保证所有联系人均提供全部资料。

## 只读资料后端身份与覆盖

DatabaseProfileBackend的公开alias不作为nickname或本地wechat_id回填。多个本地ID字段必须一致；联系人读取即使只有一个搜索候选，也须与请求的稳定username精确匹配，重复精确候选拒绝。本人资料须与已知当前账号ID一致，缺ID或冲突时不归档。适配器返回畸形联系人集合时停止，不能静默丢行后当作完整结果。archive_all_contact_profiles只表示本地缓存读取归档，回执coverage_status=cached_only、server_contacts_complete=false，不用作服务器全量好友或缺席/删除证据。

群成员只读读取须传稳定@chatroom ID；成员本地ID字段一致且唯一，记录所带群ID必须同属本群。全局nickname与本群group_display_name分别保留；群主标志只接受明确布尔/0/1/true/false，缺值为unknown（None），不按字符串真值推断。ProfileStore的group_member当前值按group_id＋wechat_id隔离，get/changes须显式group_id；history可指定group_id筛选或逐条读取全部原始历史。新快照和变更共用既有历史表，并用群作用域索引关联；旧单成员profiles行不再用作群当前值。初始化以事务序列化并发迁移，旧快照原文保留，只将可核对群/成员ID的旧记录建立legacy_unverified索引；不可核对记录保留原文并记录跳过数量。新观测建立scoped_baseline，后续同群比较才为scoped；不能把旧跨群比较升级为可信变化。save_group_members整批事务，archive_group_members仅归档cached_only并返回server_members_complete=false；空缓存批次不删除旧成员。具体真实来源覆盖、成员有效期和下游分析依赖仍须另行验收。

归档索引读取新的scoped/scoped_baseline群资料，按本地ID复用Person；group_display_name只作为该群context_id下的别名，不能改成全局nickname或覆盖已有联系人展示名。旧profiles群行与legacy_unverified群快照不进入新的可信索引，跳过仍推进输入游标；无作用域旧历史保持原样。资料及快照索引采用原子批次，校验失败须连同人物、别名、引用、dirty和游标回滚。此前已建立的旧索引/分析不会自动撤销或重建，仍需按受影响范围复核；索引成功不代表当前成员新鲜度或人物结论已完成。

资料快照的新证据引用采用profile:<归档路径摘要>:<本地快照ID>:<快照记录摘要>，避免不同归档同号快照合并；记录摘要覆盖正文、主体ID、类型、观察时间、来源及本地编号；解析只接受已配置归档来源且记录哈希一致的绑定引用，失败不回退数字编号。路径变化须重新核对来源/重建对应引用，不按名称猜来源。旧数字引用仅表示指定归档的legacy_local_id查询，不能作为已绑定来源证据；旧引用与结论保留，待受影响范围复核。profile_snapshot_index_v2使用独立游标建立新引用，不覆写旧引用或分析正文。

朋友圈归档通过moment_versions保留每次实际写入的正文/作者/评论/赞及媒体引用元数据，插入和修改与版本在同一事务提交；版本只追加，不原地更新/删除。相同内容不增加版本。旧归档仅建立legacy_baseline当前缓存基线，observed_at为迁移留存时间，不能反推先前修改历史或源读取时间。Memory索引对版本化归档采用moment_version_index独立游标，新增动态及原动态编辑均进入atomic批次，人物/dirty/增量任务/水位整体提交或回滚；无版本表的旧只读源仍用rowid，并明确updates_supported=false。并发连接取得批次锁后才读取水位。moment:<来源摘要>:<版本ID>:<记录摘要>证据只解析配置来源中匹配的不可变记录，旧裸动态ID标legacy_mutable_id；不把当前正文替换为旧证据。旧引用/已发表结论不自动重建；媒体BLOB仍另存且未版本化，真实新鲜度/删除语义/全历史变化和分析正文仍待验收。

MomentStore.save整批事务核对动态ID所绑定作者；已有或同批ID出现不同作者即整批拒绝，不保留半批写入。已知非零发布时间冲突拒绝，未知零时间可补齐，不把布尔或截断小数时间当事实。相同作者正常更新允许，完全相同内容不计重复更新；校验与写入在BEGIN IMMEDIATE内序列化。此不代表已有行更新已触发Memory索引或跨归档证据来源已核验，后续仍须验证相应联动。

人物/身份/会话的first_seen_at与last_seen_at对可比较的显式时区时间及Unix秒/毫秒只扩展最早/最晚边界，SQL更新直接比较当前行，旧观察不能倒退最后时间；相同瞬时保留原表示。无时区、不可解析或已有不可解释边界不猜排序，也不自动重写旧数据；这些字段不能当作来源新鲜度或完整历史覆盖证明。朋友圈索引只为首次发现的人物使用动态昵称作展示回退，已有联系人展示名不被旧动态覆盖；动态昵称按证据引用上下文保留历史别名，并与整批索引一起回滚。

同一稳定本地身份的Person分类按self优先于contact、contact优先于group_member更新，person_id不变；低优先级场景不能降级本人或覆盖已有高优先级展示名，同类资料仍可正常更新。未知输入类型拒绝，旧未知类型保留并要求复核，不自动猜成联系人。此分类优先级不证明当前登录账号、好友状态或用户修正已验收，不授权按昵称/头像合并身份；本人资料的账号核对仍须在上游完成。
