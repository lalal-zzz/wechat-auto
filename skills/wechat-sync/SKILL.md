---
name: wechat-sync
description: 增量归档本地微信消息、资料、群和朋友圈，维护游标、来源审计与安全恢复。
---

# 微信数据同步

在分析前、收到目录变化通知后，或来源水位落后时运行。只通过只读后端读取微信；写入范围仅限项目自己的数据库和归档。

## 执行步骤

1. 调用 `status.summary`，确认当前应用、Memory schema 和 MCP 工具契约状态。
2. 检查已配置来源是否可用，区分微信 4.x `xwechat_files` 与旧版目录。
3. 先更新所需来源归档，再调用 `sync.index_archives`。索引已有归档不等于从微信采集了最新数据。
4. 检查回执中的来源覆盖和索引变化；输入未变时不得重复添加证据引用或分析任务。
5. 完整导入、迁移、媒体补齐后，记录来源范围、时间范围、行数、失败数和缺口，并更新 `docs/PROJECT_STATE.md` 与 `docs/HISTORY_SOURCE_AUDIT.md`。

## 语音归档与本地转写

语音采用程序自身的本地 ASR，不依赖微信界面“转文字”。归档交接包含同一稳定消息 ID 下的原语音和转写文字；缺少音频、未转写、识别失败分别记录，不能把语音 XML 或占位符当成已读内容。

导出记录丢失 server_id/local_id 时，使用 `--message-source <local_original_export_db>` 按同一会话、sort_seq、create_time 和原始正文精确恢复身份；修复来源及正文 hash 保存在 voice_message_links，原始消息不改写。时间相同或音频长度相近只能作为候选，不能独立绑定。无法唯一恢复时标为未匹配，不直接宣称音频已丢失。

项目运行入口为 `scripts/transcribe_voice.py`。`--media-db` 指定已解密本地语音分片，按会话和 server_id 只读提取 VoiceInfo，音频写入项目归档库的 message_media BLOB，不按 local_id 单独关联。`--model-path` 指定现存本地 faster-whisper 模型，使用 pilk 将 SILK 解码后识别；可选依赖在 `requirements-speech.txt`。不自动下载模型，不上传私人音频，不写微信来源库。

```powershell
python scripts/transcribe_voice.py --history-db data/wechat_history_complete.sqlite3 --conversation-id <conversation_id> --media-db <local_decrypted_media_db> --model-path <local_model_directory> --limit 100
```

MCP 监控配置 `--voice-model-path <local_model_directory>` 后，将本地模型传给增量归档入口。语音识别环境须先安装 speech 依赖；Conda/系统库发生冲突时使用隔离环境，不用允许重复 OpenMP 的开关掩盖冲突。历史批次可加 `--progress` 查看计数；失败/空文本存入 voice_transcription_attempts，默认跳过，明确复核后用 `--retry-failed` 重试。

已有音频 BLOB 时可省略 `--media-db`。每批已有转写跳过，重复运行继续处理剩余音频。调用前核对会话身份、归档库和模型目录；缺少依赖/模型/音频时交接具体缺口。HistoryStore 配置 voice_model_path 时，save_messages 会在同一归档流程中处理新保存的语音并附带转写；sync_when_notified 与 archive_all_history 支持传入同一配置。未配置模型的普通保存仍只归档，不隐式联网获取模型。历史补齐通过上述脚本执行，再交给分析。微信已存在的结果可以导入作为历史来源，但不作为这条流程的依赖或默认识别引擎。

转写写入同一归档库 voice_transcriptions，保留 message_id、版本、引擎、模型来源、audio_sha256、时间片段和识别分数。机器结果标记 transcribed_unreviewed，用户更正优先，不覆盖原始 XML 或旧转写版本。它属于派生消息证据，不是人物分析正文。

历史批量转写可使用 `--workers 4` 并行推理；根据本机资源调整，允许 1～8 个工作线程。只有主线程写入项目 SQLite。转写成功、空文本和技术失败分别计数；已处理批次可增量续跑，不能把空文本或未匹配音频算作成功。

月度输入和证据上下文会附带最新转写；配置 history_db 的分析服务将相关转写版本计入输入指纹。脚本将新增转写所属月份列为待分析；转写完成不等于月报和 HTML 已更新。成功交接原音频数量、转写成功/未转写数量、变更消息及月份，按本地审计规则记账，再更新月度→会话→人物/关系→报告。

## 失败处理

- 来源缺失或锁定：游标保持不变，待外部条件恢复后再继续。
- 发现旧版数据库：只读审计，并使用微信官方迁移或备份恢复；不得覆盖 4.x 数据库。
- 批次未完整提交：保留最后成功游标，从该处恢复。
- 身份冲突：建立合并候选；不得按展示名称自动合并。
- 媒体读取失败：保留消息元数据并标记媒体待处理；联网下载必须逐项取得明确确认。

## 兼容与历史边界

来源适配逻辑改变时必须使输入指纹反映变化。Memory schema 不兼容时停止写入，先完成受支持的迁移或重建。不得回退游标或改写原始归档。

## UI 与收件人规则

若任务涉及 UI 导航、收件人选择、删除状态审计或回复派发，先阅读 [UI_WORKFLOW_RULES.md](references/UI_WORKFLOW_RULES.md)、[UI_PAGE_CATALOG.md](references/UI_PAGE_CATALOG.md) 和 [ACTION_VERIFICATION_MATRIX.md](references/ACTION_VERIFICATION_MATRIX.md)。按其中规则核对搜索状态、稳定身份、缺席与删除的区别及失败停止条件。纯离线同步不需要截图。静态规则不能证明当前收件人身份；完整发送身份链路仍有 WA-005 未完成项。

## 数据工作流与交接

执行前阅读[数据新鲜度与联动规则](references/SKILL_DATA_WORKFLOW.md)，判断请求是历史快照、当前状态、回复还是 UI 操作。Skill 联动表示当前 Agent 阅读相关 `SKILL.md` 并执行其工具步骤，不代表自动派生 Agent、定时任务或授权扩大。

分析前区分“微信来源→原始归档”和“原始归档→Memory 索引”。聊天增量使用已装配的 `monitor.run_once` 或只读归档流程；资料和朋友圈使用 `sync.contacts_moments_local`。两者成功后再调用 `sync.index_archives`。一次监控不能代替全历史导入。

需要 UI 补采资料时交给 wechat-profile-moments；身份或删除状态不明时交给 wechat-identity-audit。同步回执应交接来源、实际覆盖、水位、缺口和受影响月份。新消息交给 wechat-monthly-analysis，新资料或动态交给 wechat-person-analysis。无增量时不重复触发分析。来源锁定或不可用时不推进水位；已有归档只能作为明确标注截至范围的历史输入。

## UI 排错与实测规划

遇到搜索、资料入口、输入区、发送结果或表情定位问题时，读取随包的
[UI_FAILURE_RECOVERY.md](references/UI_FAILURE_RECOVERY.md)。按其中的问题/处理表区分
已实现处理与剩余缺口，保留首次失败回执；发送 unknown 仅增加只读复核证据，不自动重发。
用户要求 OpenCV + OCR 全流程实测时，正常步骤不依赖 Agent 看图，失败后才图片排错。
具体账号、正文、截图与运行流水只存本机忽略的台账，不写入 Skill。

## 随包资源范围

执行规则、参考文档与模板只读取本 Skill 目录中的 `references/`、`assets/` 和已提供的 `scripts/`，相对路径从本 Skill 目录解析。不能跨目录借用另一个 Skill 的参考资源；缺少必需随包资源时报告缺失，维护时补齐本目录副本。其他 Skill 名称仅表示流程职责与上下游，不代替本目录资源。项目运行接口、正式数据路径与项目命令是运行依赖，不是外部指令来源；不为打包复制私人数据。
