"""Generate a self-contained offline memory dashboard."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import quote

from wechat_auto.memory.store import MemoryStore
from wechat_auto.version import __version__

_ASSETS = Path(__file__).resolve().parents[3] / "skills" / "wechat-dashboard" / "assets"


class DashboardBuilder:
    def __init__(self, store: MemoryStore, output_root: str | Path, *,
                 memory_root: str | Path | None = None):
        self.store = store
        self.output_root = Path(output_root).expanduser().resolve()
        self.memory_root = (Path(memory_root).expanduser().resolve() if memory_root
                            else self.output_root.parent)

    def _directory(self, person_id: str | None, conversation_id: str | None) -> Path:
        directory = self.output_root
        for kind, value in (("people", person_id), ("conversations", conversation_id)):
            if value:
                if value in {".", ".."} or any(ch in value for ch in '<>:"/\\|?*'):
                    raise ValueError("unsafe dashboard scope identifier")
                directory /= kind
                directory /= value
        resolved = directory.resolve()
        if not resolved.is_relative_to(self.output_root):
            raise ValueError("dashboard scope escapes output root")
        return resolved

    def _report(self, version: dict, directory: Path) -> dict:
        """Link only the recorded, intact version inside the configured Memory root."""
        plural = {"person": "people", "conversation": "conversations"}.get(version["scope_type"])
        if not plural:
            return {"status": "unsupported_scope"}
        base = self.memory_root / plural / version["scope_id"]
        if version["period"]:
            base /= "months"
            base /= version["period"]
        expected = base / "versions" / f"v{int(version['version']):06d}.md"
        path = Path(version["markdown_path"]).expanduser().resolve()
        if not path.is_relative_to(self.memory_root) or path != expected.resolve():
            return {"status": "unsafe_path"}
        if not path.is_file():
            return {"status": "missing"}
        if hashlib.sha256(path.read_bytes()).hexdigest() != version["content_hash"]:
            return {"status": "content_mismatch"}
        relative = Path(os.path.relpath(path, directory)).as_posix()
        return {"status": "verified", "href": quote(relative, safe="/.")}

    def _context(self, person_id: str | None, conversation_id: str | None,
                 directory: Path) -> dict:
        # Structured metadata only. Markdown is linked for reading, never parsed
        # into claims, coverage, or a second source of machine-readable memory.
        with self.store.transaction() as connection:
            person_row = (connection.execute("SELECT * FROM people WHERE person_id=?", (person_id,)).fetchone()
                          if person_id else None)
            if person_id and person_row is None:
                raise ValueError("dashboard person not found")
            conversation = self.store.get_conversation(conversation_id) if conversation_id else None
            if conversation_id and conversation is None:
                raise ValueError("dashboard conversation not found")
            related = (self.store.person_conversations(person_id) if person_id
                       else ([conversation] if conversation else self.store.list_conversations()))
            if conversation_id:
                related = [row for row in related if row["conversation_id"] == conversation_id]
                if person_id and not related:
                    raise ValueError("person is not linked to the requested conversation")
            # Membership history may contain multiple rows for one conversation.
            conversations = list({row["conversation_id"]: row for row in related}.values())
            scopes = [("conversation", row["conversation_id"]) for row in conversations]
            if person_id and not conversation_id:
                scopes.append(("person", person_id))
            if not person_id and not conversation_id:
                scopes.extend(("person", row["person_id"]) for row in self.store.list_people())
            versions, coverage, dirty = [], [], []
            for scope_type, scope_id in scopes:
                versions.extend(dict(row) for row in connection.execute(
                    "SELECT * FROM analysis_versions WHERE scope_type=? AND scope_id=? "
                    "AND status='current' ORDER BY period,version", (scope_type, scope_id)))
                coverage.extend(dict(row) for row in connection.execute(
                    "SELECT * FROM analysis_coverage WHERE scope_type=? AND scope_id=? ORDER BY period",
                    (scope_type, scope_id)))
                dirty.extend(dict(row) for row in connection.execute(
                    "SELECT * FROM dirty_nodes WHERE node_type=? AND node_id=?", (scope_type, scope_id)))
                if scope_type == "conversation":
                    prefix = scope_id + ":"
                    dirty.extend(dict(row) for row in connection.execute(
                        "SELECT * FROM dirty_nodes WHERE node_type='conversation_month' "
                        "AND substr(node_id,1,?)=?", (len(prefix), prefix)))
            profile_rows = ([dict(row) for row in connection.execute(
                "SELECT observed_at,source FROM profile_snapshot_refs WHERE person_id=? ORDER BY observed_at",
                (person_id,))] if person_id else [])
            moments_rows = ([dict(row) for row in connection.execute(
                "SELECT * FROM moments_coverage WHERE person_id=?", (person_id,))] if person_id else [])
            people = {row["person_id"]: {"display_name": row["display_name"], "person_type": row["person_type"]}
                      for row in connection.execute("SELECT person_id,display_name,person_type FROM people")}
        # Private direct chats often have no title in the archive database.
        # Use the stable linked contact identity for display instead of exposing
        # the storage fallback "未命名会话" to the reader.
        direct_names = {}
        for row in conversations:
            if row["conversation_type"] != "direct":
                continue
            linked = connection.execute("""
                SELECT DISTINCT p.person_id,p.person_type,p.display_name
                FROM conversation_members cm JOIN people p ON p.person_id=cm.person_id
                WHERE cm.conversation_id=? AND (cm.valid_to IS NULL OR cm.valid_to='')
            """, (row["conversation_id"],)).fetchall()
            contacts = {member["person_id"]: member["display_name"].strip()
                        for member in linked if member["person_type"] == "contact"
                        and member["display_name"].strip()}
            if len(contacts) == 1:
                direct_names[row["conversation_id"]] = next(iter(contacts.values()))
        names = {
            row["conversation_id"]: (row["title"].strip() or direct_names.get(row["conversation_id"])
                or ("未命名私聊" if row["conversation_type"] == "direct" else "未命名群聊"))
            for row in conversations
        }
        source_versions = []
        for row in versions:
            source_versions.append({key: row[key] for key in (
                "scope_type", "scope_id", "period", "version", "parent_version", "created_at", "status",
                "input_fingerprint", "content_hash")})
            source_versions[-1]["label"] = (people.get(row["scope_id"], {}).get("display_name") or "未命名人物"
                                            if row["scope_type"] == "person"
                                            else names.get(row["scope_id"], "未命名会话"))
            source_versions[-1]["report"] = self._report(row, directory)
        title = (dict(person_row).get("display_name") or "未命名人物" if person_row else
                 (conversation["title"].strip() or direct_names.get(conversation_id)
                  or ("未命名私聊" if conversation["conversation_type"] == "direct" else "未命名群聊")
                  if conversation else "全部记忆"))
        return {"scope": {"title": title, "person_id": person_id, "conversation_id": conversation_id,
                          "kind": "person" if person_id else "conversation" if conversation_id else "all",
                          "conversation_title": names.get(conversation_id, "") if conversation else "",
                          "person_type": person_row["person_type"] if person_row else None},
                "people": people, "conversations": conversations, "source_versions": source_versions,
                "coverage": coverage, "dirty_nodes": dirty, "profile_observations": profile_rows,
                "moments_coverage": moments_rows}

    def build(self, *, person_id: str | None = None,
              conversation_id: str | None = None) -> str:
        directory = self._directory(person_id, conversation_id)
        context = self._context(person_id, conversation_id, directory)
        claims = self.store.search_claims(person_id=person_id,
                                          conversation_id=conversation_id,
                                          statuses=("confirmed", "observed", "inferred", "unknown"), limit=500)
        events = [self.store.get_event(row["event_id"]) for row in self.store.list_events(
            person_id=person_id, conversation_id=conversation_id, limit=500)]
        if person_id or conversation_id:
            visible_people = {person_id} if person_id else set()
            for claim in claims:
                visible_people.update((claim["subject_person_id"], claim["object_person_id"]))
            for event in events:
                visible_people.update(event["people"])
            context["people"] = {key: value for key, value in context["people"].items() if key in visible_people}
        metadata = {"generator": __version__, "template_version": "dashboard-ui-v2",
                    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "person_id": person_id, "conversation_id": conversation_id,
                    "source_versions": context["source_versions"], "display_limit": 500,
                    "display_limit_reached": {"claims": len(claims) == 500, "events": len(events) == 500},
                    "freshness": "stale" if context["dirty_nodes"] else "unknown",
                    "semantic_quality": "not_certified", "media_content_coverage": "unknown"}
        payload = json.dumps({"claims": claims, "events": events, "metadata": metadata,
                              **context}, ensure_ascii=False)
        # A JSON script block must not be terminable by text from a chat or a name.
        payload = payload.translate(str.maketrans({"<": "\\u003c", ">": "\\u003e", "&": "\\u0026",
                                                  "\u2028": "\\u2028", "\u2029": "\\u2029"}))
        html = Template((_ASSETS / "dashboard.html").read_text(encoding="utf-8")).substitute(
            page_title=escape(context["scope"]["title"] + " · 记忆与变化"), payload=payload,
            style=(_ASSETS / "dashboard.css").read_text(encoding="utf-8"),
            script=(_ASSETS / "dashboard.js").read_text(encoding="utf-8"))
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "index.html"
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
        path = self._directory(person_id, conversation_id) / "timeline.mmd"
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
        directory = self._directory(person_id, conversation_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "timeline.png"
        image.save(path)
        return str(path)
