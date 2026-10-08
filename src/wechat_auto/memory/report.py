"""Full offline reading view of intact formal Markdown analysis versions.

Unlike the structured dashboard this view never caps the number of paragraphs,
claims or months. It does not generate or certify conclusions.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from html import escape
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from wechat_auto.memory.dashboard import DashboardBuilder
from wechat_auto.memory.markdown import MarkdownMemory
from wechat_auto.memory.report_visuals import render_visuals


_ICON_PATHS = {
    "search": '<circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 5 5"/>',
    "x": '<path d="m6 6 12 12M18 6 6 18"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
    "printer": '<path d="M6 8V3h12v5M6 17H4V9h16v8h-2M6 14h12v7H6z"/><path d="M17 11h.1"/>',
    "person": '<circle cx="12" cy="8" r="3.2"/><path d="M5.5 20v-1.4a6.5 6.5 0 0 1 13 0V20"/>',
    "relation": '<circle cx="7" cy="8" r="2.5"/><circle cx="17" cy="8" r="2.5"/><path d="M2.8 19v-1.1a4.2 4.2 0 0 1 6.7-3.3M21.2 19v-1.1a4.2 4.2 0 0 0-6.7-3.3M9 12h6"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="16" rx="2"/><path d="M7.5 3v4M16.5 3v4M3.5 10h17M8 14h2m4 0h2m-8 3h2"/>',
    "heart": '<path d="M20.2 8.6c0 4.4-8.2 10.2-8.2 10.2S3.8 13 3.8 8.6a4.1 4.1 0 0 1 7.2-2.7 4.1 4.1 0 0 1 7.2 2.7Z"/>',
    "message": '<path d="M20 11.3a7.5 7.5 0 0 1-7.8 7.2 8 8 0 0 1-3.6-.8L4 19l1.3-3.9A6.8 6.8 0 0 1 4 11.3 7.5 7.5 0 0 1 12.2 4 7.5 7.5 0 0 1 20 11.3Z"/><path d="M8 11h.1M12 11h.1M16 11h.1"/>',
    "spark": '<path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3ZM19 15l1 2.5 2.5 1-2.5 1L19 22l-1-2.5-2.5-1 2.5-1L19 15Z"/>',
    "chart": '<path d="M4 19V5m0 14h17M8 15l3-4 3 2 5-7"/><circle cx="8" cy="15" r="1"/><circle cx="11" cy="11" r="1"/><circle cx="14" cy="13" r="1"/><circle cx="19" cy="6" r="1"/>',
    "book": '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21V5.5ZM4 17a2.5 2.5 0 0 1 2.5-2.5H20"/><path d="M8 7h8m-8 3h6"/>',
    "flower": '<path d="M12 12c-4-1-5.5-5-3-7 2-1 3.5 1 3 7Zm0 0c1-4 5-5.5 7-3 1 2-1 3.5-7 3Zm0 0c4 1 5.5 5 3 7-2 1-3.5-1-3-7Zm0 0c-1 4-5 5.5-7 3-1-2 1-3.5 7-3Z"/><circle cx="12" cy="12" r="1.5"/>',
}


def _chapter_icon(title: str) -> tuple[str, str]:
    text = title.lower()
    if any(word in text for word in ("人际", "关系", "家人", "朋友", "同事", "联系人")):
        kind = "relation"
    elif any(word in text for word in ("时间", "事件", "经历", "计划", "日常", "阶段", "约定")):
        kind = "calendar"
    elif any(word in text for word in ("兴趣", "偏好", "喜好", "喜欢", "爱好", "活动")):
        kind = "heart"
    elif any(word in text for word in ("情绪", "冲突", "边界", "沟通", "表达", "回应", "互动")):
        kind = "message"
    elif any(word in text for word in ("变化", "成长", "演化", "趋势", "长期")):
        kind = "flower"
    elif any(word in text for word in ("性格", "人格", "自我", "人物", "个性", "价值")):
        kind = "person"
    elif any(word in text for word in ("分析", "证据", "覆盖", "资料", "数据", "范围")):
        kind = "chart"
    elif any(word in text for word in ("学习", "工作", "生活", "经历", "回顾")):
        kind = "book"
    else:
        kind = "spark"
    svg = f'<svg viewBox="0 0 24 24" aria-hidden="true">{_ICON_PATHS[kind]}</svg>'
    return kind, svg


def _icon(name: str, class_name: str = "") -> str:
    return (f'<svg class="{class_name}" viewBox="0 0 24 24" aria-hidden="true">'
            f'{_ICON_PATHS[name]}</svg>')


def render_markdown(text: str) -> str:
    """Render the analysis Markdown subset with all source HTML escaped.

    No image/remote fetch, executable markup, or untrusted link is emitted.
    Unsupported Markdown remains readable text, never silently discarded.
    """
    def inline(value):
        value = escape(value)
        value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
        value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
        return re.sub(r"(\[20\d{2}-\d{2}[^\]\n]*\])", r'<span class="source-ref">\1</span>', value)

    lines = text.splitlines()
    blocks, paragraph, items = [], [], []
    in_code, code = False, []
    open_chapter = False
    chapter_number = 0

    def flush():
        if paragraph:
            # Reflow at sentence boundaries without summarizing or losing words.
            rendered = []
            for line in paragraph:
                sentences = re.findall(r'.+?(?:[。！？](?:[”’])?|$)', line)
                chunks, pending = [], ""
                for sentence in sentences:
                    if pending and len(pending) + len(sentence) > 150:
                        chunks.append(pending)
                        pending = ""
                    pending += sentence
                if pending:
                    if chunks and re.fullmatch(r'(?:\[[^\]]+\])+', pending):
                        chunks[-1] += pending
                    else:
                        chunks.append(pending)
                rendered.extend('<p class="reading-chunk">' + inline(chunk) + '</p>' for chunk in chunks)
            blocks.append('<div class="piece prose-block">' + ''.join(rendered) + '</div>')
            paragraph.clear()
        if items:
            blocks.append('<ul class="piece">' + "".join("<li>" + inline(x) + "</li>" for x in items) + "</ul>")
            items.clear()

    index = 0
    if lines and lines[0].strip() == "---":
        try:
            end = lines.index("---", 1)
        except ValueError:
            end = -1
        if end > 0:
            blocks.append('<details class="piece metadata"><summary>分析元数据</summary><pre>' +
                          escape("\n".join(lines[1:end])) + "</pre></details>")
            index = end + 1
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.startswith("```"):
            flush()
            if in_code:
                blocks.append('<pre class="piece">' + escape("\n".join(code)) + "</pre>")
                code = []
            in_code = not in_code
        elif in_code:
            code.append(line)
        elif not line.strip():
            flush()
        elif re.match(r"^#{1,6}\s", line):
            flush()
            match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if len(match[1]) == 2:
                if open_chapter:
                    blocks.append("</div></details>")
                chapter_number += 1
                kind, icon = _chapter_icon(match[2])
                blocks.append(f'<details class="chapter piece" data-kind="{kind}"><summary>'
                              f'<span class="chapter-number">{chapter_number:02d}</span>'
                              f'<span class="chapter-icon">{icon}</span>'
                              f'<span class="chapter-title">{inline(match[2])}</span>'
                              '</summary><div class="chapter-body">')
                open_chapter = True
                continue
            level = min(len(match[1]) + 1, 6)
            blocks.append(f'<h{level} class="piece">{inline(match[2])}</h{level}>')
        elif line.lstrip().startswith("|"):
            flush()
            rows = [line]
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                rows.append(lines[index])
                index += 1
            rendered = []
            for n, row in enumerate(rows):
                cells = row.strip().strip("|").split("|")
                if all(re.fullmatch(r"\s*:?-+:?\s*", c) for c in cells):
                    continue
                tag = "th" if n == 0 else "td"
                rendered.append("<tr>" + "".join(f"<{tag}>{inline(c.strip())}</{tag}>" for c in cells) + "</tr>")
            blocks.append('<div class="piece table"><table>' + "".join(rendered) + "</table></div>")
        elif re.match(r"^\s*(?:[-*]|\d+[.)])\s", line):
            if paragraph:
                flush()
            items.append(re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", line))
        else:
            if items:
                flush()
            paragraph.append(line)
    flush()
    if code:
        blocks.append('<pre class="piece">' + escape("\n".join(code)) + "</pre>")
    if open_chapter:
        blocks.append("</div></details>")
    return "\n".join(blocks)


class FullReportBuilder(DashboardBuilder):
    def build(self, *, person_id: str | None = None, conversation_id: str | None = None,
              accepted_versions: dict[tuple[str, str, str], int] | None = None,
              source_months: list[str] | None = None, visuals: dict | None = None) -> str:
        """Optional exact reviewed-version allowlist excludes old unreviewed reports.

        Acceptance comes from the coordinator's review receipt, never inferred
        from file existence, headings, input traversal, or a template label.
        """
        if not person_id and not conversation_id:
            raise ValueError("a scoped person or conversation is required")
        directory = self._directory(person_id, conversation_id)
        context = self._context(person_id, conversation_id, directory)
        if accepted_versions is not None:
            wanted = {("conversation", row["conversation_id"]) for row in context["conversations"]}
            if person_id and not conversation_id:
                wanted.add(("person", person_id))
            actual_versions = {(v["scope_type"], v["scope_id"], v["period"]): int(v["version"])
                               for v in context["source_versions"]}
            for key, expected in accepted_versions.items():
                if key[:2] in wanted and actual_versions.get(key) != expected:
                    raise ValueError("accepted version is no longer current in the selected report scope")
        sections, monthly_sections, month_index, toc, included_months, omitted = [], defaultdict(list), defaultdict(list), [], set(), []
        formal_sources = {}
        for version in context["source_versions"]:
            key = (version["scope_type"], version["scope_id"], version["period"])
            if (accepted_versions is not None and
                    accepted_versions.get(key) != int(version["version"])):
                omitted.append(version["period"] or version["scope_type"])
                continue
            if version["report"]["status"] != "verified":
                if accepted_versions is not None:
                    raise ValueError("reviewed formal Markdown path/hash is not intact; prior HTML retained")
                omitted.append(version["period"] or version["scope_type"])
                continue
            path = (self.memory_root / {"conversation": "conversations", "person": "people"}[key[0]] / key[1])
            if key[2]:
                path = path / "months" / key[2]
            path = path / "versions" / f"v{int(version['version']):06d}.md"
            body = path.read_bytes()
            if hashlib.sha256(body).hexdigest() != version["content_hash"]:
                raise RuntimeError("formal Markdown changed during report generation")
            formal_sources[key] = (int(version["version"]), version["content_hash"], body.decode("utf-8"))
            label = (key[2] + " 月度详析" if key[2] else
                     ("人物综合" if key[0] == "person" else "跨月会话综合"))
            anchor = f"report-{len(sections) + sum(len(rows) for rows in monthly_sections.values()) + 1}"
            toc.append(f'<a href="#{anchor}">{escape(label)}</a>')
            href = quote(Path(os.path.relpath(path, directory)).as_posix(), safe="/.")
            content = (f'<div class="version">版本 {version["version"]} · '
                       f'<a href="{href}">模型 Markdown</a></div>' +
                       render_markdown(body.decode("utf-8")))
            if key[2]:
                # Keep every monthly analysis available, but let the reader choose
                # which month to open instead of forcing a 28-month scroll.
                month_index[key[2][:4]].append(f'<a class="month-chip" data-period="{escape(key[2])}" href="#{anchor}">'
                                                f'<span>{escape(key[2][5:])}</span><small>月</small></a>')
                monthly_sections[key[2][:4]].append(
                    f'<section id="{anchor}" data-period="{escape(key[2])}" class="report month-report"><details class="month-card piece"><summary>'
                    f'<span class="month-mark">{_icon("calendar")}<b>{escape(key[2][5:])}</b></span>'
                    f'<span class="month-label"><strong>{escape(label)}</strong>'
                    f'<small>完整月度分析 · 点击展开</small></span>'
                    f'<span class="month-chevron" aria-hidden="true">＋</span></summary>'
                    f'<div class="month-content">{content}</div></details></section>')
            else:
                sections.append(f'<section id="{anchor}" class="report integrated-report"><h2>{escape(label)}</h2>' +
                                content + "</section>")
            if key[2]:
                included_months.add(key[2])
        visual_html = ""
        if visuals:
            graphic = render_visuals(visuals, formal_sources)
            if graphic:
                visual_html = graphic
                toc.insert(0, '<a href="#visual-overview">图解总览</a>')
        missing = sorted(set(source_months or []) - included_months)
        title = context["scope"]["title"] + " · 全历史聊天关系报告"
        note = ("本页展示协调者已独立复核的指定版本。" if accepted_versions is not None else
                "本页展示正式库当前版本；语义质量尚未由本页面认证。")
        note += f" 已展示 {len(included_months)} 个月度正文。"
        if missing:
            note += " 待完成月份：" + "、".join(missing) + "。全历史综合尚未完成。"
        if omitted:
            note += " 有旧版或校验未通过正文未纳入本次报告。"
        if context["dirty_nodes"]:
            note += " 相关下游存在待更新节点。"
        generated = datetime.now(timezone.utc).astimezone(
            timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M 北京时间")
        assets = Path(__file__).resolve().parents[3] / "skills" / "wechat-dashboard" / "assets"
        style = (assets / "report.css").read_text(encoding="utf-8")
        script = (assets / "report.js").read_text(encoding="utf-8")
        month_count = len(included_months)
        month_index_html = "".join(
            f'<div class="year-index"><h3>{_icon("calendar", "year-icon")}<span>{escape(year)}</span>'
            f'<small>{len(months)} 个月</small></h3>'
            f'<div class="month-grid">{"".join(months)}</div></div>'
            for year, months in sorted(month_index.items()))
        monthly_html = "".join(
            f'<section class="year-group"><h2>{_icon("calendar", "year-icon")}<span>{escape(year)}</span>'
            f'<small>YEAR FILE　/　{len(months)} 个月度记录</small></h2>'
            f'<div class="year-month-list">{"".join(months)}</div></section>'
            for year, months in sorted(monthly_sections.items()))
        period_explorer = (
            '<section class="period-explorer" aria-label="历史时间导航"><div class="explorer-heading">'
            '<span><small>TIME EXPLORER</small><strong>沿时间阅读</strong></span>'
            '<p>选择年份浏览月份，点击时间格打开对应月报。</p></div>'
            '<div class="year-filters" role="group" aria-label="月份年份筛选">'
            '<button type="button" data-year="all" aria-pressed="true">全部</button>' +
            "".join(f'<button type="button" data-year="{escape(year)}" aria-pressed="false">{escape(year)}</button>'
                    for year in sorted(month_index)) + '</div><div class="period-track">' +
            "".join(month for months in month_index.values() for month in months) +
            '</div><p class="period-selection" role="status">选择一个月份查看详细记录</p></section>')
        template = (assets / "report-template.html").read_text(encoding="utf-8-sig")
        replacements = {
            "DOCUMENT_TITLE": escape(title),
            "SCOPE_DISPLAY_NAME": escape(context["scope"]["title"]),
            "MONTH_COUNT": str(month_count),
            "MONTH_COUNT_PADDED": f"{month_count:02d}",
            "INTEGRATED_COUNT": f"{len(sections):02d}",
            "COVERAGE_LABEL": "全量" if not missing else "部分",
            "GENERATED_AT": generated,
            "REPORT_NOTE": escape(note),
            "ICON_CALENDAR": _icon("calendar"),
            "ICON_BOOK": _icon("book"),
            "ICON_SPARK": _icon("spark"),
            "ICON_SEARCH": _icon("search", "tool-icon"),
            "ICON_CLOSE": _icon("x", "tool-icon"),
            "ICON_LAYERS": _icon("layers", "tool-icon"),
            "ICON_PRINT": _icon("printer", "tool-icon"),
            "ICON_CHART": _icon("chart"),
            "TABLE_OF_CONTENTS": "".join(toc),
            "YEAR_MONTH_INDEX": month_index_html,
            "PERIOD_EXPLORER": period_explorer,
            "INTEGRATED_REPORTS": "".join(sections),
            "VISUAL_REPORT": visual_html,
            "YEARLY_MONTH_REPORTS": monthly_html,
            "INLINE_CSS": style,
            "INLINE_JS": script,
        }
        html = template
        for token, value in replacements.items():
            html = html.replace("{{" + token + "}}", value)
        if re.search(r"\{\{[A-Z_]+\}\}", html):
            raise RuntimeError("HTML template contains an unresolved placeholder")
        path = directory / "report.html"
        MarkdownMemory._atomic_write(path, html)
        return str(path)
