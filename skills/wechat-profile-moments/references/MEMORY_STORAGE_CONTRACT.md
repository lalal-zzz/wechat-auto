# 分析存储与来源契约

契约版本：1。每个分析 Skill 开始执行前读取本文，解析实际项目根目录和已配置
MCP 路径。所有相对路径以项目根目录为基准；不得以终端当前目录、姓名或临时
测试目录临时决定正式输出位置。

## 正式输出唯一位置

未显式配置其他工作区时使用：

| 内容 | 固定位置 |
|---|---|
| 结构化 Memory SQLite | `data/wechat_memory.sqlite3` |
| Markdown 根目录 | `data/memory/` |
| 私聊或群聊月度正文 | `data/memory/conversations/{conversation_id}/months/{YYYY-MM}/current.md` |
| 私聊或群聊跨月正文 | `data/memory/conversations/{conversation_id}/current.md` |
| 人物综合正文（self/contact/group_member） | `data/memory/people/{person_id}/current.md` |
| 关系正文（需要时） | `data/memory/relationships/{relationship_id}/current.md` |
| 完整历史版本 | 同作用域目录的 `versions/v000001.md` 等，由提交接口维护 |
| 分析索引 | `data/memory/index.md`，只放对象、来源范围、状态和正文链接 |
| 生成图表 | `data/memory/dashboard/`；记录对象和上游成功版本 |
| 未完成候选/阅读进度 | `data/work/analysis/{run_id}/`；不是正式 Memory，不直接用于回复 |

ID 来自同一个 Memory SQLite，不能在测试库和正式库之间假定 person_id/
conversation_id 相同。群消息按群会话输出月度/汇总；相关成员在人物目录聚合。
没有为 self 另建一套独立画像；会话里的 self 风格留在该会话 Memory。
不为同一份分析另外生成 personality.md/preferences.md/events.md 或 Claim YAML。

如已显式配置 memory_db / memory_root，使用那一对路径，并将解析后的路径写到
本地来源清单；不得默认库写 Claim、另一根目录写正文。切换路径按迁移/重建处理，
保留旧库与版本，不复制 current.md 冒充已提交的完整版本关系。
正式分析不写入 `data/analysis_tests/`；该目录仅保存旧测试和隔离验收产物。

## 原始来源与固定清单

原始消息、资料、朋友圈和媒体仍保存在各自归档库；结构化 Memory 不复制大段
报告或整份消息。不要因文件名有 complete/full 就假定完整或最新。
执行时核对实际范围，记录到固定本地 `data/analysis_sources.json`：

- 解析后的项目根、memory_db、memory_root；
- 明确选定的 history_db、profiles_db、moments_db，以及各自真实来源覆盖；
- 本次稳定对象/范围、历史快照或当前状态模式、语义模板、缺口；
- run_id 和对应工作目录，避免每次新建一个随意命名的输出位置。

清单不包含消息正文、密钥、签名URL或嵌套分析结果。禁止把多个历史库直接当成
重复独立证据；需要合并时使用稳定复合消息ID，记录来源审计并保留原档。

SQLite 职责：短 Claim/状态/证据关系、Event/阶段、身份/成员关联、版本/依赖、
覆盖/水位、任务/修正。完整分析正文写 Markdown；Evidence 按来源库动态展开。
事件详述在月份及会话 current.md 内保存，跨月正文保留连续阶段与重要过程，
SQLite 仅存短事件/阶段和相关 Claim 索引。依照 EVENT_ANALYSIS_STANDARD.md，
不另建逐事件报告；当前事件标量版本与完整 Markdown 历史版本不能混为一谈。
约定词义/暗号同样在会话 current.md 的“约定表达与语境”中详述，短结论用现有
claims 表的 conversation_expression 类型及证据关联保存；不另建任意词典文件，
不把会话专属词义复制为全局人物事实。实际 schema 尚无专门词典表。
阅读进度如当前 schema 尚无分块语义游标，先放固定工作目录中一份可续跑进度，
不伪造数据库已有该能力，也不将暂存分析 JSON 当正式人物画像。

## 写入、验收与恢复

1. 提交前核对输出数据库和根目录，查询正式库里的身份、当前版本与真实来源。
2. 未验收正文先留在固定工作目录。正式结果用 `analysis.submit` 及实际
   expected_parent 写入，版本路径由 MarkdownMemory 决定，不手动编辑 versions/。
3. 验证数据库记录的 markdown_path 属于配置的 memory_root、当前完整版本
   可读、证据指向选定来源；成功后再更新索引、完成任务和交接。
4. 路径不匹配、身份映射失败或父版本冲突时停止该提交，重载正确范围；不改到
   一个新目录绕过冲突。失败留候选/进度及上一成功版本，不能覆盖为完成。
5. 原始归档不因分析修正而改写。旧测试结果作为历史参考，不作为原始证据或
   直接导入的正式人物结论。整个 data/ 保持 Git 忽略，不上传私有分析。

本文是 Skill 存储契约；当前任意参数 create_server/CLI 不会自动强制这些位置，
执行 Agent 须核验。运行时路径绑定及语义阅读进度门禁仍需单独实现与验收。

## 语音原件与转写的同源保存

原语音保存在所选消息归档库 message_media 的 BLOB 中，转写保存在同库 voice_transcriptions。两者通过原消息稳定 message_id 关联；转写记录版本、引擎/模型来源、audio_sha256、时间片段、识别分数和状态，用户更正保留新版本。消息的原始 XML 不替换，转写文本不另存一套人物 Memory。

月度输入及证据读取返回最新 transcription；正式月报仍写 Markdown，引用对应原消息和必要的转写片段。语音尚未归档或转写时明确标示缺口，不写成已分析。配置归档路径的分析服务会将相关转写修订纳入输入指纹；其他自建调用必须核对其实际 history_path 配置，不能假定仅消息 ID 不变就代表内容未变。
