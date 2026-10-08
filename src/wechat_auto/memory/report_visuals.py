"""Offline infographics from reviewed display specs bound to formal prose."""
from __future__ import annotations

from collections import defaultdict
from html import escape
from datetime import date
import calendar
import re


def _time_range_chart(items: list[dict]) -> str:
    """Plot only display dates already bound to prose; no inferred event duration."""
    spans = []
    for item in items:
        label = str(item.get("date", ""))
        exact = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[至—–~](\d{2})|[至—–~](\d{4})-(\d{2})-(\d{2}))?", label)
        month = re.fullmatch(r"(\d{4})-(\d{2})", label)
        if exact:
            start = date(*map(int, exact.group(1, 2, 3)))
            end = (date(start.year, start.month, int(exact[4])) if exact[4] else
                   date(*map(int, exact.group(5, 6, 7))) if exact[5] else start)
            precision = "day"
        elif month:
            year, number = map(int, month.groups())
            start, end = date(year, number, 1), date(year, number, calendar.monthrange(year, number)[1])
            precision = "month"
        else:
            continue
        if end < start:
            raise ValueError("timeline date range ends before it starts")
        spans.append((item, start, end, precision))
    if not spans:
        return ""
    first, last = min(s[1] for s in spans), max(s[2] for s in spans)
    days = max((last-first).days, 1)
    width, left, extent = 960, 255, 660
    height = 65 + 48 * len(spans)
    rows = []
    for i, (item, start, end, precision) in enumerate(spans):
        y = 48 + i * 48
        x = left + (start-first).days/days*extent
        span_width = (end-start).days/days*extent
        label = escape(str(item["label"]))
        title = escape(str(item.get("date", "")) + " · " + str(item["label"]))
        glyph = (f'<rect class="time-band {precision}" x="{x:.2f}" y="{y-6}" width="{max(span_width, 6):.2f}" height="12" rx="4"/>'
                 if start != end else f'<circle class="time-point" cx="{x:.2f}" cy="{y}" r="5"/>')
        rows.append(f'<g><title>{title}</title><text x="8" y="{y+4}">{label}</text>'
                    f'<line class="time-lane" x1="{left}" y1="{y}" x2="{left+extent}" y2="{y}"/>' + glyph +
                    f'<text class="time-caption" x="{left}" y="{y+20}">{escape(str(item.get("date", "")))}</text></g>')
    ticks = []
    for year in range(first.year, last.year+1):
        tick = max(first, date(year, 1, 1))
        x = left + (tick-first).days/days*extent
        ticks.append(f'<text class="time-year" x="{x:.2f}" y="18">{year}</text>')
    return ('<div class="time-range-scroll"><svg class="time-range-chart" role="img" '
            f'aria-label="按真实时间比例排列的节点和日期范围" viewBox="0 0 {width} {height}">' +
            ''.join(ticks + rows) + '</svg></div><p class="visual-legend">圆点为明确日期；短条为原文日期范围；虚线条为仅明确到月份的日期窗口，不表示事件持续整月。</p>')


def render_visuals(spec: dict, formal_sources: dict[tuple, tuple[int, str, str]]) -> str:
    """Validate version/hash and exact source excerpts; semantic review is external.

    Each source tuple is (version, content_hash, Markdown text). The display spec
    is a derived view, not another claim store or analysis正文. Missing provenance
    fails the render rather than presenting an unbound graphic as a conclusion.
    """
    bound = []
    for source in spec.get("source_versions", []):
        key = (source["scope_type"], source["scope_id"], source.get("period", ""))
        actual = formal_sources.get(key)
        if not actual or actual[:2] != (int(source["version"]), source["content_hash"]):
            raise ValueError("visual source version/hash is not included in this report")
        bound.append(actual[2])
    if spec.get("panels") and not bound:
        raise ValueError("visuals require formal source bindings")
    panels = []
    status_labels = {"observed": "有原文依据", "inferred": "有证据推断", "unknown": "待核验", "confirmed": "用户确认"}
    owner_icon = ('<svg class="owner-icon" viewBox="0 0 40 40" aria-hidden="true">'
                  '<circle cx="20" cy="12" r="7"/><path d="M7 35v-5a13 13 0 0 1 26 0v5"/></svg>')
    panel_icons = {
        "timeline": '<rect x="3.5" y="5" width="17" height="16" rx="2"/><path d="M7.5 3v4M16.5 3v4M3.5 10h17M8 14h2m4 0h2"/>',
        "activity": '<path d="M4 19V5m0 14h17M8 15l3-4 3 2 5-7"/><circle cx="8" cy="15" r="1"/><circle cx="11" cy="11" r="1"/><circle cx="14" cy="13" r="1"/><circle cx="19" cy="6" r="1"/>',
        "relationships": '<circle cx="7" cy="8" r="2.5"/><circle cx="17" cy="8" r="2.5"/><path d="M2.8 19v-1.1a4.2 4.2 0 0 1 6.7-3.3M21.2 19v-1.1a4.2 4.2 0 0 0-6.7-3.3M9 12h6"/>',
        "compare": '<path d="M4 7h13l-3-3m6 13H7l3 3M16 4l4 3-4 3M8 14l-4 3 4 3"/>',
    }
    status_icons = {
        "observed": '<path d="m5 12 4 4L19 6"/>',
        "inferred": '<path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z"/>',
        "unknown": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.6 2.6 0 1 1 4.6 1.7c-1.1 1.2-2.1 1.4-2.1 3.1m0 3h.1"/>',
        "confirmed": '<path d="M12 3 19 6v5c0 4.6-3 7.7-7 10-4-2.3-7-5.4-7-10V6l7-3Z"/><path d="m9 12 2 2 4-4"/>',
    }
    for panel in spec.get("panels", []):
        kind = panel["type"]
        if kind not in {"timeline", "relationships", "compare", "activity"}:
            raise ValueError("unsupported report graphic")
        items = panel.get("items", [])
        for item in items:
            quote = item.get("source_excerpt", "")
            if not quote or not any(quote in body for body in bound):
                raise ValueError("visual fact has no exact excerpt in its formal Markdown source")
            if item.get("status", "observed") not in status_labels:
                raise ValueError("unknown visual evidence status")

        def card(item):
            state = item.get("status", "observed")
            return (f'<div class="visual-node {state}"><strong>{escape(str(item["label"]))}</strong>'
                    f'<p>{escape(str(item.get("detail", "")))}</p><span class="visual-status">'
                    f'<svg viewBox="0 0 24 24" aria-hidden="true">{status_icons[state]}</svg>'
                    f'{status_labels[state]}</span><details><summary>正文依据</summary><p>'
                    f'{escape(item["source_excerpt"])}</p></details></div>')

        if kind == "timeline":
            content = _time_range_chart(items) + '<p class="visual-legend">左右浏览关键时间节点，点击展开过程与依据。下方卡片间距不表示持续时间。</p><ol class="visual-timeline">' + "".join(
                '<li><div class="visual-date">' + escape(str(item.get("date", "时间未明确"))) +
                '</div><span class="visual-dot" aria-hidden="true"></span><details class="event-fold"><summary>' +
                escape(str(item["label"])) + '</summary>' + card(item) + '</details></li>'
                for item in items) + '</ol>'
        elif kind == "activity":
            values = [item.get('value') for item in items]
            if any(type(value) is not int or value < 0 for value in values):
                raise ValueError('activity counts must be nonnegative integers')
            highest = max(values, default=0) or 1
            # Rotated month labels extend beyond the last bar. Keep them inside
            # the SVG viewBox so the final months remain legible on desktop;
            # narrow screens can scroll this graphic horizontally.
            step = 29
            width = max(620, step * len(items) + 145)
            bars = []
            for index, item in enumerate(items):
                x = 45 + index * step
                height = item['value'] / highest * 170
                bars.append(f'<g class="activity-bar" tabindex="0" role="button" '
                            f'data-period="{escape(str(item["label"]), quote=True)}" '
                            f'data-count="{item["value"]}" aria-label="{escape(str(item["label"]), quote=True)}：{item["value"]}条，打开月报">'
                            f'<title>{escape(str(item["label"]))} · {item["value"]} 条</title>'
                            f'<rect x="{x}" y="{205-height:.2f}" width="22" height="{height:.2f}" rx="3" />'
                            f'<text x="{x+11}" y="{195-height:.2f}" text-anchor="middle">{item["value"]}</text>'
                            f'<text transform="translate({x+11},220) rotate(55)">{escape(str(item["label"]))}</text></g>')
            content = ('<p class="visual-legend">固定来源的消息条数；数量不代表感情、性格或关系质量。</p>'
                       '<p class="chart-readout" role="status">指向柱形查看条数，点击打开当月记录</p>'
                       '<div class="activity-scroll"><svg class="activity-chart" role="group" '
                       f'aria-label="{escape(panel["title"])}" style="min-width:{width}px" viewBox="0 0 {width} 290">'
                       '<defs><linearGradient id="bar-gradient" x1="0" y1="1" x2="0" y2="0">'
                       '<stop offset="0%" stop-color="#236b91"/><stop offset="100%" stop-color="#42d8c0"/>'
                       '</linearGradient></defs>'
                       '<line x1="35" y1="205" x2="' + str(width-15) + '" y2="205" />' +
                       ''.join(bars) + '</svg></div><details><summary>各月数量的正文依据</summary>' +
                       ''.join(card(item) for item in items) + '</details>')
        else:
            groups = defaultdict(list)
            for item in items:
                groups[str(item.get("owner", "归属待核验"))].append(item)
            content = '<div class="visual-groups">' + "".join(
                '<div class="visual-group"><h4>' + owner_icon + escape(owner) + '</h4>' +
                '<div class="visual-branches">' + "".join(card(item) for item in owner_items) +
                '</div></div>' for owner, owner_items in groups.items()) + '</div>'
        panel_icon = '<svg viewBox="0 0 24 24" aria-hidden="true">' + panel_icons[kind] + '</svg>'
        panels.append('<figure data-panel="' + kind + '" class="visual-panel piece"><figcaption><span class="panel-icon ' + kind + '">' +
                      panel_icon + '</span><h3>' + escape(panel["title"]) +
                      '</h3></figcaption>' + content + '</figure>')
    if not panels:
        return ''
    names = {"activity": "消息节奏", "timeline": "时间节点", "relationships": "人际关系", "compare": "偏好与互动"}
    kinds = list(dict.fromkeys(panel["type"] for panel in spec.get("panels", [])))
    tabs = ''.join(f'<button type="button" data-view="{kind}" aria-pressed="{str(i == 0).lower()}">{names[kind]}</button>'
                   for i, kind in enumerate(kinds))
    return ('<section id="visual-overview" class="report graphic-report"><div class="graphic-heading">'
            '<span class="overview-kicker">INTERACTIVE ATLAS</span><h2>把时间与互动展开来看</h2></div>'
            '<div class="chart-tabs" role="group" aria-label="选择图表">' + tabs +
            '</div><div class="graphics-inner">' + "".join(panels) + '</div></section>')
