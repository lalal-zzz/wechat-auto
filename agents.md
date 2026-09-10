# WeChat Auto 当前开发约束

本项目只支持 Windows 微信 4.x 当前架构，不保留微信 3.x、UIA 控件树或旧复合技能兼容。

## 架构

- `core/application.py`：纯 Win32 查找、激活和管理顶层 HWND。
- `skills/basic.py`：唯一 UI 动作入口。
- `primitives/keyboard_only.py`：通过 `WM_*` 消息执行点击、右键、滚轮、按键和输入。
- `primitives/vision.py`：只截图、OCR、识别和返回替代坐标，不执行动作。
- `backends/`：只读微信本地数据库。
- `storage/`：项目自己的离线 SQLite、表情语义和偏好目录。
- `skills/composite.py`：未来高级流程接口，暂不提供具体自动回复实现。

## 硬性规则

1. 新 UI 动作必须加入 `BasicSkill`，不得创建第二套驱动。
2. OCR 不能点击或输入；它产生的坐标必须交给 HWND 驱动执行。
3. 不注入、Hook、修改微信内存、写微信数据库或模拟私有协议。
4. 发送消息、表情、点赞、评论和媒体联网下载必须显式确认。
5. 新消息使用目录变化事件触发数据库增量同步，不高频轮询全部会话。
6. 高级 Skill 只能组合只读后端和 `BasicSkill`。

## 验证

```powershell
python -m pytest tests -q
```

实机动作测试优先使用“文件传输助手”，默认只打开会话或准备草稿；没有明确确认不得发送。
