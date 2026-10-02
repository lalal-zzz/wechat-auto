# 微信页面视觉观察

## 原则

完整页面枚举、子状态矩阵、规则覆盖和实机验证状态见 [UI_PAGE_CATALOG.md](UI_PAGE_CATALOG.md)。
当前共 49 类：页面 ID 固定，观察结果区分底层页面、面板、弹窗和独立内容窗口。

传统 CV 识别结构，OCR 读取内容。结构观察与内容识别来自同一帧截图；不执行点击、输入或发送。

- 使用局部灰度差、长分隔线、对比度增强和矩形轮廓寻找导航栏、会话列表、右侧内容栏及输入区边框。
- 从背景亮度观察 dark / light / mixed，而不是绑定一组固定 RGB 颜色。
- 从实际分隔线调整 OCR 区域；未检测到分隔线时使用宽松比例范围。
- 空白输入框只有几何边框时报告 candidate，发送控件等文本出现后才补充 present 证据。
- OCR 识别联系人、群聊、聊天记录、公众号、视频号等文字标记。公众号/视频号内容区可与聊天输入区同时存在。
- 单个边框不证明它就是输入框；无文字也不能证明控件不存在。证据不足保持 unknown，结果不授权动作。

## 安装与运行

OCR 配置使用 PaddleOCR 与 PaddlePaddle CPU，模型为 `PP-OCRv5_mobile_det` 和 `PP-OCRv5_mobile_rec`，模型由本机缓存管理。Windows CPU 关闭 MKL-DNN，RGB 截图转换为 Paddle 的 BGR ndarray。

```powershell
python -m pip install -r requirements-ocr.txt
python scripts\recognize_wechat_page.py
# 离线重放本地截图
python scripts\recognize_wechat_page.py --image data\ocr\latest\capture.png --output data\ocr\replay
# 显式使用轻量后备进行诊断
python scripts\recognize_wechat_page.py --engine rapid
# 只识别区域结构，不加载 OCR
python scripts\recognize_wechat_page.py --geometry-only --output data\ocr\geometry
```

首次加载下载官方模型；后续识别使用模型缓存。预览输出保存到 `data/ocr/`，包含私人页面数据，不进入 Git。控制台只显示计数和状态，不打印正文或联系人。

## 输出

每次生成 `capture.png`、`result.json` 和离线 `index.html`。网页在截图上覆盖文字框，悬停查看文字和置信度。JSON 返回：

| 字段 | 内容 |
|---|---|
| boxes | OCR 文字、置信度、像素框、窗口图像比例 |
| page | 当前页面推断；未知时为 unknown |
| page_id / page_candidates | 稳定页面 ID 和竞争的底层页面候选 |
| panels / overlays / content_windows | 同一帧的侧栏、弹窗和独立内容页候选 |
| geometry | 明暗观察、长分隔线、输入框和右栏几何候选 |
| chat_area / composer | 聊天和输入区证据 |
| right_panel / content_view | 右栏及中央公众号、视频号或搜索内容证据 |
| search_results | 搜索分区标记 |
| region_bounds / regions | 当前观察区域和对应文字框索引 |

这些坐标是截图坐标，后续动作仍交给 BasicSkill 转换到 HWND 客户区，不可直接执行。

## 接口和失败

`VisionAutomation.observe_page(include_ocr=True)` 返回单帧观察；真实运行时 MCP 条件注册 `vision.observe_page`。传入 false 时只执行传统 CV，不加载模型。截图失败返回 `window_capture_unavailable`，OCR 推理失败返回 `ocr_infrastructure_failure` 和异常类型。命令行严格执行所选 OCR 引擎，错误以失败退出，不能把失败解释为无聊天框。

## 窗口与动作规则

右侧标签栏操作路由到嵌入窗口，不能用关闭主窗代替关闭标签。
关闭叉号从当前帧 CV 检测；页面观察器版本为 5。目录与动作支持范围见
[UI_PAGE_CATALOG.md](UI_PAGE_CATALOG.md)、[ACTION_VERIFICATION_MATRIX.md](ACTION_VERIFICATION_MATRIX.md)。

## 实机审计入口

```powershell
python scripts\audit_wechat_pages.py --output data\ui_audit\manual
```

审计器从 stdin 逐行读取 JSON，支持 capture、navigation、search、search_content、
page_operation 与 quit。原图、完整 OCR 和错误详情只保存到本机 data/；查询词不输出到审计 stdout。
命令失败也采样页面并记录失败类型；回执 success=false 不算成功。
管道 JSON 使用 UTF-8；Windows ANSI 编码会破坏中文查询，因此审计器对管道 stdin
显式使用 UTF-8。搜索 OCR 只读取文字区域，排除放大镜、清空和麦克风图标。
所有 UI 动作仍经 BasicSkill；媒体下载、发送和真实资料修改不在本次采样范围。
