# 当前架构

## 动作面

`BasicSkill` 是唯一动作 Skill。其动作全部委托给 `KeyboardOnlyDriver`，后者向微信
顶层 HWND 发送 `WM_LBUTTON*`、`WM_RBUTTON*`、`WM_MOUSEWHEEL`、`WM_KEY*` 和
`WM_CHAR`。不存在 UIA、物理鼠标或物理键盘降级分支。

## 观察面

`VisionAutomation` 使用 Win32 `PrintWindow` 截图和 RapidOCR。它只能返回文字、
红点或坐标，不能点击、输入或滚动。替代坐标由 `BasicSkill` 再交给 HWND 驱动。

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

`CompositeSkill` 目前只是接口。未来自动回复、群上下文分析和朋友圈策略只能组合
只读后端与同一个 `BasicSkill`，不得绕过确认边界或创建第二套 UI 驱动。
