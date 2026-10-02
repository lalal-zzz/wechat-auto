# 当前架构

## 动作面

`BasicSkill` 是唯一动作 Skill。其动作全部委托给 `KeyboardOnlyDriver`，后者向微信
顶层 HWND 发送 `WM_LBUTTON*`、`WM_RBUTTON*`、`WM_MOUSEWHEEL`、`WM_KEY*` 和
`WM_CHAR`。不存在 UIA、物理鼠标或物理键盘降级分支。

联系人动作以 `username/wxid` 为目标。数据库解析器生成版本化动作计划；自绘页面使用
项目自有语义 ID（如 `21.09:more`、`22.03:delete_contact`）。计划先持久化并绑定
单次确认令牌，`BasicSkill` 只执行已确认且未被修改的计划。
坐标由当前截图的 OpenCV/OCR 产生；不加载尺寸坐标档案。不支持的控件、多个候选或身份不唯一时停止执行。

## 观察面

`VisionAutomation` 使用 Win32 `PrintWindow` 截图，按需加载 PaddleOCR mobile，
并可使用 RapidOCR 本地后备。它只能返回文字、红点或坐标，不能点击、输入或滚动。
替代坐标由 `BasicSkill` 再交给 HWND 驱动。

`WindowObserver` 将同进程主窗、菜单、编辑器和辅助内容窗与分层页面结合；窗口身份、
页面识别和联系人身份各自核验。路由每步重新选择唯一 HWND、重算控件并验证结果。
个人联系人定位限定在“联系人”分组下；不使用“新的朋友”或全局混合搜索回退。
最终图片复核采用短期单次计划，Agent 只提交当前图片控件框，BasicSkill 校验帧、
窗口和允许操作后派发 WM_*；详情见 [WINDOW_NAVIGATION.md](docs/WINDOW_NAVIGATION.md)。

## 数据面

- `DatabaseConversationBackend`：历史、上下文和事件触发的增量消息。
- `DatabaseMomentsBackend`：朋友圈内容与媒体清单。
- `HistoryStore` / `MomentStore`：离线 SQLite。
- `emoji_semantics`：解码 type-47 表情 XML 中的多语言提示。
- `StickerPreferenceAnalyzer`：按会话、频率、时间和意图排序表情候选。
- `StickerCatalog`：将稳定表情 ID 映射到经过验证的面板位置。

## 表情发送闭环

```text
指定会话历史 → md5/product_id + 中文含义 → 偏好候选
→ 已验证 StickerCatalog → 窗口尺寸校验 → 明确确认 → HWND 点击发送
```

如果本地元数据没有含义，则先检查本地缓存；本地没有素材时，联网下载必须先询问。

## 高级能力

`backends/collection_sync.py` 是本地资料/朋友圈刷新实现，CLI 与 MCP 共用，不自行
联网下载。`memory/collection.py` 保存每人、每路径的覆盖观察和可续跑队列；UI 加载
只调用 BasicSkill.load_contact_moments，再重新打开本地源同步。`memory/contact_state.py`
保存方向明确的删除、拉黑和访问历史，不能用昵称或权限提示推断好友关系。
接口与使用限制见 [CONTACT_COLLECTION.md](docs/CONTACT_COLLECTION.md)。

高级流程由 MCP 工具和仓库 Skills 组合只读后端与同一个 `BasicSkill`，不得绕过
确认边界或创建第二套 UI 驱动。高级能力通过本地 stdio MCP 暴露：

```text
原始归档 → wechat_memory.sqlite3 → 紧凑 Markdown → MCP 上下文裁剪
```

- `memory/store.py`：人物、会话、Claim、Event、证据引用、分析任务、水位和依赖。
- `memory/markdown.py`：当前完整 Memory 和历史完整版本。
- `memory/analysis.py`：输入指纹、增量提交和下游失效传播。
- `memory/indexer.py`：只引用现有消息、资料和朋友圈归档，不复制正文或媒体。
- `mcp_server.py`：供外部 Agent 使用的本地 stdio 工具；发送工具只在注入
  `BasicSkill` 后注册，并要求单次精确确认。

OCR 首选 PaddleOCR mobile 模型，未安装时可配置为使用现有 RapidOCR 本地后备。
无论使用哪个 OCR 引擎，它都只返回观察框和窗口比例坐标。
