(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("memory-data").textContent);
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
  const text = (id, value) => { $(id).textContent = value; };
  const statuses = {confirmed: "用户已确认", observed: "有直接记录", inferred: "分析推断", unknown: "尚不确定", inactive: "已失效", superseded: "已被修订", completed: "已完成", cancelled: "已取消", pending: "待继续", active: "记录有效", current: "当前版本"};
  const statusClass = value => ["confirmed", "observed", "inferred", "unknown"].includes(value) ? value : "other";
  const badge = value => `<span class="status-badge ${statusClass(value)}">${esc(statuses[value] || "其他状态")}</span>`;
  const dimensions = [
    {id: "facts", label: "事实与日期", types: ["fact", "person_fact", "personal_fact", "identity", "birthday", "milestone", "date", "biography", "life", "career"]},
    {id: "preferences", label: "兴趣与喜好", types: ["preference", "interest", "like", "dislike", "habit", "lifestyle", "taste"]},
    {id: "communication", label: "沟通与表达", types: ["communication", "communication_style", "chat_style", "chat_habit", "interaction", "interaction_rhythm"]},
    {id: "behavior", label: "行为与性格", types: ["personality", "trait", "behavior", "behavior_pattern", "personality_behavior"]},
    {id: "emotion", label: "情绪与恢复", types: ["emotion", "emotional_pattern", "recovery", "support"]},
    {id: "values", label: "价值观与选择", types: ["value", "values", "decision", "goal"]},
    {id: "boundaries", label: "边界与关系", types: ["boundary", "relationship", "relationship_boundary", "role", "group_role"]},
    {id: "expressions", label: "约定表达", types: ["conversation_expression"]},
    {id: "matters", label: "事项与任务", types: ["event", "event_status", "task", "commitment", "topic", "matter"]},
    {id: "other", label: "其他内容", types: []}
  ];
  const dimensionFor = claim => dimensions.find(group => group.types.includes(String(claim.claim_type || "").toLowerCase())) || dimensions[dimensions.length - 1];
  let activeDimension = "all";
  const countFormat = value => new Intl.NumberFormat("zh-CN").format(value);
  const dateLabel = (value, includeTime = false) => {
    if (!value) return "未提供日期";
    const raw = String(value);
    if (/^\d{4}$/.test(raw)) return `${raw}年`;
    if (/^\d{4}-\d{2}$/.test(raw)) return `${raw.slice(0, 4)}年${Number(raw.slice(5, 7))}月`;
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return `${raw.slice(0, 4)}年${Number(raw.slice(5, 7))}月${Number(raw.slice(8, 10))}日`;
    if (/^\d{4}-\d{2}-\d{2}T/.test(raw)) {
      const valueDate = new Date(raw);
      if (!Number.isNaN(valueDate.getTime())) return new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", year: "numeric", month: "long", day: "numeric", ...(includeTime ? {hour: "2-digit", minute: "2-digit", hour12: false} : {})}).format(valueDate);
    }
    return raw;
  };
  const dateRange = (start, end) => start && end ? `${dateLabel(start)} — ${dateLabel(end)}` : start ? `起始日：${dateLabel(start)}；结束日期未提供` : end ? `截至：${dateLabel(end)}；开始日期未提供` : "适用日期未提供";
  const personName = id => id ? data.people[id]?.display_name || (data.people[id]?.person_type === "self" ? "本人" : "未命名人物") : "";
  const conversationName = id => data.conversations.find(row => row.conversation_id === id)?.title || "未命名会话";
  const definitionList = rows => `<dl class="metadata-list">${rows.filter(row => row[1] !== null && row[1] !== undefined && row[1] !== "").map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl>`;
  const empty = (heading, description, canReset = false) => `<div class="empty"><div class="empty-symbol" aria-hidden="true"></div><strong>${esc(heading)}</strong><p>${esc(description)}</p>${canReset ? '<button class="empty-reset" type="button" data-reset>清除筛选</button>' : ""}</div>`;
  const knownVersions = data.metadata.source_versions;
  text("scope-kind", data.scope.kind === "person" ? "人物档案" : data.scope.kind === "conversation" ? "会话档案" : "记忆总览");
  text("page-heading", data.scope.title);
  text("scope-tag", data.scope.conversation_id && data.scope.person_id ? "指定会话中的人物记录" : data.scope.kind === "person" ? (data.scope.person_type === "self" ? "本人的聊天与变化" : "按稳定身份关联") : data.scope.kind === "conversation" ? "这段对话的事情与互动" : "已保存的本地记忆");
  text("scope-description", data.scope.conversation_id && data.scope.person_id ? `限定于「${data.scope.conversation_title || "未命名会话"}」。查看这段对话里的具体事情、表达与变化。` : "从具体事情、表达和偏好开始，保留每个结论的语境与时间。");
  const monthlyCount = knownVersions.filter(version => version.period).length;
  const hasPersonSummary = knownVersions.some(version => version.scope_type === "person" && !version.period);
  const missingConversationCount = data.conversations.filter(conversation => !knownVersions.some(version => version.scope_type === "conversation" && version.scope_id === conversation.conversation_id && !version.period)).length;
  const missingSummaries = [data.scope.kind === "person" && !data.scope.conversation_id && !hasPersonSummary ? "人物综合" : "", missingConversationCount ? (missingConversationCount === data.conversations.length ? "会话汇总" : "部分会话汇总") : ""].filter(Boolean);
  text("analysis-tag", monthlyCount && missingSummaries.length ? `月度已保存 · ${missingSummaries.join("、")}待保存` : knownVersions.length ? "已保存分析 · 覆盖待核验" : "正式分析待保存");
  text("claim-count", countFormat(data.claims.length));
  text("event-count", countFormat(data.events.length));
  text("version-count", countFormat(knownVersions.length));
  text("conversation-count", countFormat(data.conversations.length));
  text("generated-short", `生成于 ${dateLabel(data.metadata.generated_at)} · 北京时间`);
  text("generated-full", `${dateLabel(data.metadata.generated_at, true)} 生成 · 北京时间`);
  const stale = data.metadata.freshness === "stale";
  text("quality-title", stale ? "部分分析有待更新" : knownVersions.length ? "阅读范围与完整度仍需核验" : "完整分析正在积累");
  text("quality-description", (stale ? "本范围有待更新记录，页面保留已保存内容。来源是否最新、全历史语义阅读与媒体解读仍需分别核验。" : "页面展示正式库中已保存的内容；页面生成时间不等于聊天同步时间。尚未验收的候选不会作为正式结论展示，全历史完成状态不能由版本或条数推定。") + (monthlyCount && missingSummaries.length ? ` 当前有 ${monthlyCount} 份月度正式分析，尚无${missingSummaries.join("与")}正式版本。` : ""));
  const sourceRow = (title, state, description) => `<div class="source-row"><div class="source-row-title"><span>${esc(title)}</span><span>${esc(state)}</span></div><p>${esc(description)}</p></div>`;
  const indexedStarts = data.conversations.map(row => row.first_seen_at).filter(Boolean).sort();
  const indexedEnds = data.conversations.map(row => row.last_seen_at).filter(Boolean).sort();
  const indexRange = indexedStarts.length || indexedEnds.length ? dateRange(indexedStarts[0], indexedEnds[indexedEnds.length - 1]) : "未提供索引日期范围";
  $("source-status").innerHTML = [
    sourceRow("聊天来源", data.conversations.length ? `${data.conversations.length} 个关联会话` : "未关联", `${indexRange}。这是会话索引记录范围，不能据此确认所有聊天已归档。`),
    sourceRow("资料观察", data.profile_observations.length ? `${data.profile_observations.length} 条快照索引` : "范围未核验", data.profile_observations.length ? `观察范围：${dateRange(data.profile_observations[0].observed_at, data.profile_observations[data.profile_observations.length - 1].observed_at)}。不代表当前微信资料。` : "本页没有可核对的目标资料观察记录。"),
    sourceRow("朋友圈", data.moments_coverage.length ? "有本地覆盖记录" : "范围未核验", data.moments_coverage.length ? "本地缓存或观察覆盖不代表完整远程历史，具体状态见详情。" : "本页没有可核对的目标朋友圈覆盖记录。"),
    sourceRow("语义阅读", "完整度未认证", "数据库水位与证据数不记录逐块语义阅读；实际完成范围须核对正式正文与阅读验收。"),
    sourceRow("媒体内容", "解读范围未知", "图片、语音、视频及文件的内容是否已解读，不能由本页的文字结论推定。"),
    sourceRow("来源新鲜度", stale ? "存在待更新分析" : "尚未核验", "页面未同步微信。没有按范围成功同步与验收依据时，不能称为实时状态。")
  ].join("");
  const versionKind = version => version.scope_type === "person" ? "人物分析" : version.period ? `${dateLabel(version.period)} · 月度分析` : "会话综合分析";
  const versionDetails = version => `<div class="metadata-record"><strong>${esc(version.label)} · ${esc(versionKind(version))} · 第 ${esc(version.version)} 版</strong>${definitionList([["稳定范围", `${version.scope_type} / ${version.scope_id}`], ["提交时间（北京时间）", dateLabel(version.created_at, true)], ["父版本", version.parent_version ?? "首个版本"], ["输入指纹", version.input_fingerprint], ["正文校验值", version.content_hash], ["正文链接核验", version.report.status === "verified" ? "已核对路径与文件内容" : ({missing: "版本文件缺失", content_mismatch: "版本内容与记录不一致", unsafe_path: "路径不符合正式正文约束"}[version.report.status] || "无法核验")]])}</div>`;
  $("technical-metadata").innerHTML = definitionList([
    ["人物标识", data.scope.person_id], ["会话标识", data.scope.conversation_id], ["生成器版本", data.metadata.generator], ["界面模板", data.metadata.template_version], ["生成时间（UTC）", data.metadata.generated_at], ["每类展示上限", `${data.metadata.display_limit} 条；条数是本页展示量`], ["全历史语义质量", "未认证"], ["来源新鲜度", stale ? "待更新" : "未知"]
  ]) + `<h3>当前成功分析版本</h3>${knownVersions.map(versionDetails).join("") || '<p class="small-note">本范围暂无成功提交版本。</p>'}` +
  `<h3>结构化覆盖记录</h3>${data.coverage.map(row => `<div class="metadata-record">${definitionList([["范围", `${row.scope_type} / ${row.scope_id} / ${row.period || "综合"}`], ["消息水位", row.message_watermark || "未记录"], ["资料水位", row.profile_watermark || "未记录"], ["朋友圈水位", row.moment_watermark || "未记录"], ["关联证据数", row.evidence_count], ["记录更新", dateLabel(row.updated_at, true)]])}</div>`).join("") || '<p class="small-note">暂无结构化覆盖记录。</p>'}` +
  (data.moments_coverage.length ? `<h3>朋友圈覆盖原始状态</h3>${data.moments_coverage.map(row => definitionList(Object.entries(row).filter(([key]) => !["path", "person_id"].includes(key)))).join("")}` : "") +
  (data.dirty_nodes.length ? `<h3>待更新记录</h3>${data.dirty_nodes.map(row => definitionList([["范围", `${row.node_type} / ${row.node_id}`], ["原因", row.reason], ["标记时间", dateLabel(row.dirty_since, true)]])).join("")}` : "");
  const report = version => version.report.status === "verified" ? `<a class="report-link" href="${esc(version.report.href)}"><span>${esc(versionKind(version))}<small>${esc(version.label)} · 第 ${esc(version.version)} 版</small></span><span aria-hidden="true">↗</span></a>` : `<p class="report-unavailable">${esc(versionKind(version))} · 第 ${esc(version.version)} 版：正文未通过本地核验</p>`;
  const summaries = knownVersions.filter(version => !version.period);
  const months = knownVersions.filter(version => version.period);
  $("report-links").innerHTML = summaries.map(report).join("") + (!summaries.length && months.length ? '<p class="report-unavailable">月度正文已可阅读，综合分析正式版本尚未保存。</p>' : "") + (months.length ? `<details class="report-months" ${summaries.length ? "" : "open"}><summary>月度详细分析（${months.length} 份）</summary>${months.map(report).join("")}</details>` : "") || '<p class="report-unavailable">正式正文尚未保存。阅读进度与分析候选仍在工作区中。</p>';
  const filtered = item => {
    const needle = $("query").value.trim().toLocaleLowerCase("zh-CN");
    const chosenStatus = $("status").value;
    const content = `${item.canonical_text || ""} ${item.title || ""} ${item.summary || ""} ${personName(item.subject_person_id)} ${(item.phases || []).map(phase => phase.title || "").join(" ")}`.toLocaleLowerCase("zh-CN");
    return (!needle || content.includes(needle)) && (!chosenStatus || (chosenStatus === "other" ? statusClass(item.status) === "other" : item.status === chosenStatus));
  };
  const claimCard = claim => {
    const subject = personName(claim.subject_person_id), scene = claim.conversation_id ? conversationName(claim.conversation_id) : "";
    return `<article class="claim"><p class="claim-text">${esc(claim.canonical_text)}</p><div class="record-meta">${badge(claim.status)}${subject ? `<span>${esc(subject)}</span>` : ""}${scene ? `<span>${esc(scene)}</span>` : ""}<span>${esc(dateRange(claim.valid_from, claim.valid_to))}</span></div><details class="record-details"><summary>记录信息</summary>${definitionList([["结论标识", claim.claim_id], ["原始类型", claim.claim_type], ["结论版本", claim.current_version], ["依据状态", `${statuses[claim.status] || "其他状态"}（${claim.status}）`], ["置信记录", `${claim.confidence}；分析记录值，未经统计校准`], ["更新日期", dateLabel(claim.updated_at, true)]])}</details></article>`;
  };
  const eventCard = event => {
    const formatted = dateLabel(event.started_at);
    const dateMatch = formatted.match(/^(\d{4})年(.+)$/);
    const dateHtml = dateMatch ? `${esc(dateMatch[1])}年<strong>${esc(dateMatch[2])}</strong>` : esc(formatted);
    return `<article class="event"><div class="event-date">${dateHtml}</div><div class="event-content"><h3 class="event-title">${esc(event.title || "未命名事情")}</h3>${event.summary ? `<p class="event-summary">${esc(event.summary)}</p>` : ""}<div class="record-meta">${badge(event.status)}<span>${esc(dateRange(event.started_at, event.ended_at))}</span></div>${event.phases?.length ? `<ol class="phase-list">${event.phases.map(phase => `<li><span class="phase-date">${esc(dateRange(phase.started_at, phase.ended_at))}</span>${esc(phase.title)}</li>`).join("")}</ol>` : ""}<details class="record-details"><summary>记录信息</summary>${definitionList([["事件标识", event.event_id], ["事件版本", event.current_version], ["记录状态", `${statuses[event.status] || "其他状态"}（${event.status}）`], ["相关人物", (event.people || []).map(personName).join("、")], ["关联结论标识", (event.claims || []).join("、")], ["置信记录", `${event.confidence}；分析记录值，未经统计校准`]])}</details></div></article>`;
  };
  function render() {
    const allClaims = data.claims.filter(filtered);
    const visibleClaims = allClaims.filter(claim => activeDimension === "all" || dimensionFor(claim).id === activeDimension);
    const groups = dimensions.map(group => ({...group, rows: allClaims.filter(claim => dimensionFor(claim).id === group.id)}));
    const buttons = [{id: "all", label: "全部", rows: allClaims}, ...groups.filter(group => group.rows.length || group.id === activeDimension)];
    $("dimensions").innerHTML = buttons.map(group => `<button class="dimension-button" type="button" data-dimension="${group.id}" aria-pressed="${group.id === activeDimension}">${esc(group.label)}<span>${group.rows.length}</span></button>`).join("");
    $("claims").innerHTML = visibleClaims.length ? groups.filter(group => group.rows.length && (activeDimension === "all" || activeDimension === group.id)).map(group => `<section class="claim-group"><h3 class="group-heading">${esc(group.label)}</h3>${group.rows.map(claimCard).join("")}</section>`).join("") : empty(data.claims.length ? "没有找到匹配内容" : "具体的理解，从完整阅读开始", data.claims.length ? "可以换一个关键词、依据状态，或清除维度筛选。" : "本范围还没有已保存的结论。完成阅读、回查和正式提交后，具体事实、偏好与表达会呈现在这里。", data.claims.length > 0);
    if (data.metadata.display_limit_reached.claims) $("claims").innerHTML += '<p class="limit-note">已达到本页 500 条展示上限，搜索仅在本页内容中进行。</p>';
    const events = data.events.filter(filtered).slice().sort((left, right) => (String(left.started_at || "").localeCompare(String(right.started_at || ""))) * ($("event-order").value === "asc" ? 1 : -1));
    $("events").innerHTML = events.length ? events.map(eventCard).join("") : empty(data.events.length ? "没有找到匹配的事情" : "事情进展尚待整理", data.events.length ? "更换关键词或依据状态，可以继续查看已保存事件。" : "有证据的阶段、决定与后续会按真实日期排列；未查明的结果会保留为未知。", data.events.length > 0);
    if (data.metadata.display_limit_reached.events) $("events").innerHTML += '<p class="limit-note">已达到本页 500 条事件展示上限，搜索仅在本页内容中进行。</p>';
    text("visible-claim-count", `${visibleClaims.length} 条内容`);
    text("filter-result", `当前显示 ${visibleClaims.length} 条结论、${events.length} 件事情。维度筛选用于内容与特征；关键词与依据筛选同时作用于事情进展。`);
  }
  function reset() { $("query").value = ""; $("status").value = ""; activeDimension = "all"; render(); }
  $("query").addEventListener("input", render);
  $("status").addEventListener("change", render);
  $("event-order").addEventListener("change", render);
  $("reset-filters").addEventListener("click", reset);
  $("dimensions").addEventListener("click", event => { const button = event.target.closest("[data-dimension]"); if (button) { activeDimension = button.dataset.dimension; render(); } });
  document.addEventListener("click", event => { if (event.target.closest("[data-reset]")) reset(); });
  render();
})();
