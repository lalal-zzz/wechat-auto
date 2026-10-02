# 朋友圈内容与媒体归档

本地只读缓存与个人相册 UI 加载是两条采集路径，均受客户端缓存、权限和可见时间范围限制。
接口与逐人加载规则见 [CONTACT_COLLECTION.md](CONTACT_COLLECTION.md)。

## 本地内容刷新

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
python scripts\sync_all_contacts_moments.py
```

使用本机 DPAPI 保护的既有密钥，只读 contact.db 和 sns.db；不扫描微信内存、
不写微信数据库、不联网下载媒体。读取全部本地非群身份条目和可关联动态，
按稳定 username 归档。未分类的系统/服务/历史条目不能据此认证为当前好友。
相同资料与动态不重复生成分析输入；原归档的范围外记录继续保留。

每次运行把 summary.json 和 media_manifest.jsonl 保存到忽略的 data/。
私人作者、正文、URL 与媒体标识不打印到终端，也不提交 Git。
新增证据进入统一 Memory 的 dirty/分析队列；分析正文由外部 Agent 提交。

## 本地媒体归档

```powershell
python scripts\archive_local_moments_media.py --manifest data\moments_full_refresh\<run>\media_manifest.jsonl
```

只读本地 Sns 缓存，匹配完整哈希或“两位目录+三十位文件名”重建哈希。
不按文件大小或短前缀猜媒体归属。准确命中后验证图片格式或视频容器，
写入项目 moments SQLite 的 message_media BLOB 表，并保留内容 SHA256 与来源。
未命中、重复候选、格式不符分别记录，不引入自动联网回退。

## 逐项确认下载

```powershell
# 只查看单项计划，不联网
python scripts\download_moments_item.py --manifest <manifest> --item-id <item_id>
# 用户核对并明确批准此项后
python scripts\download_moments_item.py --manifest <manifest> --item-id <item_id> --confirm
```

先向用户展示该项作者、动态、媒体种类与序号。确认只作用于这一项，不能转移到
其他媒体。item_id 绑定动态、种类、序号和原媒体字段；内容或 URL 被修改则拒绝。
单次请求有超时和大小限制，下载后校验格式并保存 BLOB。HTTP 状态和安全失败码
写入本机回执，不输出私人 URL，不自动重试。缺少 URL 保持 unavailable。

一次文件下载成功不等于全部联系人完整历史已归档。UI 加载、内容入库和媒体
落库分别记录覆盖状态。全量资料刷新不替代逐项远程下载确认。
