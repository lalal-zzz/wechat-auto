"""Generate a self-contained offline memory dashboard."""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

from wechat_auto.memory.store import MemoryStore

_STYLE = """
:root{color-scheme:light dark;font-family:Segoe UI,system-ui,sans-serif}body{margin:0;background:#0f172a;color:#e2e8f0}
header{padding:24px 32px;background:#111827;position:sticky;top:0}main{padding:24px 32px;max-width:1200px;margin:auto}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}.card,.panel{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:16px}.n{font-size:28px;font-weight:700}
.timeline{border-left:2px solid #38bdf8;margin-left:12px;padding-left:24px}.event{position:relative;margin:18px 0}.event:before{content:'';position:absolute;width:12px;height:12px;border-radius:50%;background:#38bdf8;left:-31px;top:5px}
.claim{padding:10px 12px;margin:8px 0;background:#0f172a;border-radius:8px}.meta{color:#94a3b8;font-size:13px}.high{border-left:4px solid #22c55e}.mid{border-left:4px solid #f59e0b}.low{border-left:4px solid #64748b}input,select{padding:8px;border-radius:8px;border:1px solid #475569;background:#0f172a;color:inherit;margin-right:8px}a{color:#7dd3fc}
"""


class DashboardBuilder:
    def __init__(self, store: MemoryStore, output_root: str | Path):
        self.store = store
        self.output_root = Path(output_root).expanduser().resolve()

    def build(self, *, person_id: str | None = None,
              conversation_id: str | None = None) -> str:
        claims = self.store.search_claims(person_id=person_id,
                                          conversation_id=conversation_id, limit=500)
        events = self.store.list_events(person_id=person_id,
                                        conversation_id=conversation_id, limit=500)
        summary = self.store.database_summary()
        payload = json.dumps({"claims": claims, "events": events}, ensure_ascii=False).replace("</", "<\\/")
        cards = "".join(
            f'<div class="card"><div class="n">{value}</div><div>{escape(key)}</div></div>'
            for key, value in summary.items()
        )
        html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>WeChat Memory</title>
<style>{_STYLE}</style></head><body><header><h1>WeChat Memory</h1>
<span class="meta">本地离线视图；证据正文按需通过 MCP 展开</span></header><main>
<section class="cards">{cards}</section><section class="panel" style="margin-top:18px">
<h2>筛选</h2><input id="q" placeholder="搜索结论或事件"><select id="status"><option value="">全部状态</option><option>confirmed</option><option>observed</option><option>inferred</option></select></section>
<section class="panel" style="margin-top:18px"><h2>连续时间线</h2><div id="timeline" class="timeline"></div></section>
<section class="panel" style="margin-top:18px"><h2>结构化记忆</h2><div id="claims"></div></section>
<script id="memory-data" type="application/json">{payload}</script><script>
const data=JSON.parse(document.getElementById('memory-data').textContent),q=document.getElementById('q'),s=document.getElementById('status');
const esc=x=>String(x??'').replace(/[&<>\"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}}[c]));
function render(){{const needle=q.value.toLowerCase(),status=s.value;
 const events=data.events.filter(x=>(!needle||(x.title+' '+x.summary).toLowerCase().includes(needle))&&(!status||x.status===status));
 document.getElementById('timeline').innerHTML=events.map(x=>`<div class="event"><b>${{esc(x.title)}}</b><div class="meta">${{esc(x.started_at||'?')}} → ${{esc(x.ended_at||'至今')}} · ${{esc(x.status)}} · ${{Math.round(x.confidence*100)}}%</div><div>${{esc(x.summary)}}</div></div>`).join('')||'<p class="meta">暂无事件</p>';
 const claims=data.claims.filter(x=>(!needle||x.canonical_text.toLowerCase().includes(needle))&&(!status||x.status===status));
 document.getElementById('claims').innerHTML=claims.map(x=>`<div class="claim ${{x.confidence>=.8?'high':x.confidence>=.55?'mid':'low'}}"><b>[${{esc(x.claim_id)}}]</b> ${{esc(x.canonical_text)}}<div class="meta">${{esc(x.valid_from||'?')}} → ${{esc(x.valid_to||'至今')}} · ${{esc(x.status)}} · ${{Math.round(x.confidence*100)}}%</div></div>`).join('')||'<p class="meta">暂无结论</p>'}}
q.oninput=render;s.onchange=render;render();</script></main></body></html>"""
        self.output_root.mkdir(parents=True, exist_ok=True)
        path = self.output_root / "index.html"
        temp = path.with_suffix(".html.tmp")
        temp.write_text(html, encoding="utf-8", newline="\n")
        temp.replace(path)
        return str(path)

    def export_mermaid(self, *, person_id: str | None = None,
                       conversation_id: str | None = None) -> str:
        events = list(reversed(self.store.list_events(person_id=person_id,
                                                       conversation_id=conversation_id, limit=200)))
        lines = ["timeline", "    title 微信长期事件时间线"]
        for event in events:
            date = str(event.get("started_at") or "时间未知")[:10]
            title = str(event.get("title") or "未命名事件").replace(":", "：").replace("\n", " ")
            lines.append(f"    {date} : {title}")
        path = self.output_root / "timeline.mmd"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    def export_png(self, *, person_id: str | None = None,
                   conversation_id: str | None = None) -> str:
        """Export a readable static timeline without network or browser dependencies."""
        from PIL import Image, ImageDraw, ImageFont

        events = list(reversed(self.store.list_events(person_id=person_id,
                                                       conversation_id=conversation_id, limit=100)))
        width = 1400
        height = max(260, 120 + len(events) * 72)
        image = Image.new("RGB", (width, height), "#0f172a")
        draw = ImageDraw.Draw(image)
        font_path = Path("C:/Windows/Fonts/msyh.ttc")
        font = ImageFont.truetype(str(font_path), 22) if font_path.is_file() else ImageFont.load_default()
        small = ImageFont.truetype(str(font_path), 16) if font_path.is_file() else ImageFont.load_default()
        draw.text((40, 30), "微信长期事件时间线", fill="#e2e8f0", font=font)
        x = 120
        draw.line((x, 90, x, height - 40), fill="#38bdf8", width=4)
        for index, event in enumerate(events):
            y = 110 + index * 72
            draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill="#38bdf8")
            date = str(event.get("started_at") or "时间未知")[:10]
            title = str(event.get("title") or "未命名事件")[:60]
            draw.text((x + 24, y - 20), f"{date}  {title}", fill="#f8fafc", font=font)
            draw.text((x + 24, y + 13),
                      f"{event.get('status', '')} · {round(float(event.get('confidence', 0))*100)}%",
                      fill="#94a3b8", font=small)
        self.output_root.mkdir(parents=True, exist_ok=True)
        path = self.output_root / "timeline.png"
        image.save(path)
        return str(path)
