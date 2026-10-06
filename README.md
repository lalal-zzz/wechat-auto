# WeChat Auto — Windows WeChat Automation, MCP & AI Memory

**English** | [简体中文](README.zh-CN.md)

WeChat Auto is a local Windows WeChat 4.x / Weixin automation and conversation-memory project for LLM agents. It connects read-only chat archives, contact profiles, WeChat Moments, PaddleOCR mobile, traditional computer vision, Win32 HWND actions, SQLite, compact Markdown memory and a Model Context Protocol (MCP) server.

The goal is evidence-backed chat history analysis, monthly summaries, person and relationship timelines, incremental long-term agent memory and confirmed reply drafts. It provides foundations for an AI WeChat assistant and chatbot; the complete recipient-safe automatic reply workflow remains under development.

**Project:** `0.8.1` · Windows WeChat 4.x · Local stdio MCP and repository Skills.

## Project overview

| Area | Implementation |
|---|---|
| Desktop automation | Single BasicSkill action entry, Win32 window management, HWND message clicks, scrolling, keys and text input |
| OCR and page recognition | Lazy PaddleOCR mobile / optional RapidOCR, bounded text recognition, CV dividers, search fields, composers and embedded content tabs |
| Chat archives and media | Source-aware message IDs, local SQLite archives, media BLOBs, resumable import and incremental synchronization foundations |
| Contact identity | Stable username/wxid; separate alias, nickname and remark; profile snapshots, absence and restoration tracking |
| WeChat Moments | Content/media metadata adapters and profile-change evidence; availability depends on the actual readable source |
| Long-term memory | Short Claims, Events, evidence references, versions, dependencies and cursors in SQLite; complete current/historical Markdown summaries |
| Analysis workflows | Monthly conversation jobs, cross-month summaries, long-running events, person/scenario analysis and incremental invalidation |
| Agent integration | Local stdio MCP, task-specific context compression, on-demand evidence retrieval and 12 repository Skills |
| Reply assistance | Conversation-specific style/context, reply drafts and confirmation infrastructure; full recipient/status/result gates pending |
| Visualization | Local offline HTML dashboard and PNG / Mermaid timeline export infrastructure |

Implementation does not imply live-device certification. Person or relationship conclusions exist only after an external agent successfully submits an analysis version.

**Contact and Moments collection:** local cache refresh plus a resumable, identity-checked
per-contact album loading queue. Directional contact removal, blacklist/blocking,
restoration and Moments access observations retain evidence history. Memory schema 3
migrates from 1/2. Collection is limited by client visibility and supported controls;
neither path guarantees complete server history. See the [Moments skill collection workflow](skills/wechat-profile-moments/references/CONTACT_COLLECTION.md).

**Window navigation and recovery:** process-bound HWND inventory, layered page recognition,
current-frame OpenCV/OCR targets and verified routes. Contact selection stays beneath the
personal Contacts header, excluding New Friends and mixed search. Failed sidebar detection
recalculates, then offers guarded Agent screenshot review through BasicSkill.
See the [navigation skill window workflow](skills/wechat-ui-navigation/references/WINDOW_NAVIGATION.md).

Profile enrichment saves explicit signature, region, source and other visible fields,
preserving earlier values when a field is missing. Exact local cache-media archiving and
confirmed single-item remote downloads validate files and store BLOBs. These tools do
not guarantee complete remote history. See [Moments archive](docs/MOMENTS_ARCHIVE.md).

## Architecture and storage

```text
Read-only WeChat data / local media / HWND screenshots
                         ↓
              Archive and normalize identities
                         ↓
                 wechat_memory.sqlite3
     Claims / Events / evidence refs / versions / dependencies / cursors
                         ↓
             Compact complete Markdown memory
                current.md + historical versions
                         ↓
              MCP retrieval and context trimming
                         ↓
              External agent analysis / reply draft
                         ↓
                  Per-action confirmation
                         ↓
              BasicSkill → HWND → verification
```

| Layer | Responsibility |
|---|---|
| Original source / local archive | Full messages, local media, Moments content and profile snapshots |
| wechat_memory.sqlite3 | Queryable short conclusions, identity mappings, evidence relations, versions and job state |
| Markdown | Compact complete analysis text for people and agents, with readable historical versions |
| MCP | Relevant context first; expand evidence only when requested |

Full analysis reports are not hidden in nested database JSON. Monthly partitions do not truncate long-running events. Changed inputs invalidate affected months and downstream summaries; older successful versions remain readable. Self and other people are analyzed separately across private chats, work groups and other scenarios.

```text
data/
├── wechat_memory.sqlite3
└── memory/
    ├── conversations/{conversation_id}/
    │   ├── current.md
    │   ├── versions/
    │   └── months/{YYYY-MM}/
    │       ├── current.md
    │       └── versions/
    └── people/{person_id}/
        ├── current.md
        └── versions/
```

## Current status

| Status | Scope |
|---|---|
| Implemented foundations | Read-only adapters, archives, media BLOBs, cursors, profile history, Claim/Event memory, Markdown versions, analysis jobs, context tools and draft confirmations |
| Page catalog | 49 page types; enumeration does not mean all pages/actions are verified |
| Integration pending | Stable recipient identity across search variants, missing/deleted-contact gates, full confirmation target binding and send-result verification (`WA-005`) |
| Planned / partial workflows | Fully orchestrated automatic replies, comprehensive analysis templates, public-account information processing and broader action validation |

See [action verification rules](docs/ACTION_VERIFICATION_MATRIX.md) and the [roadmap](docs/FUTURE_TODO.md).

### Recipient search and deleted contacts

Prefer **local stable identity → Contacts → profile verification → chat**. Search can mix contacts, groups, history, service accounts, mini programs and web suggestions, even from Contacts. Never select the first row or authenticate a recipient from a name/avatar alone. Database username/wxid differs from the public WeChat ID/alias in a profile.

No search result does not prove deletion. Missing, inferred removed and confirmed removed are separate states; preserve historical messages and memory. Removing a contact locally, being removed by another person and deleting a chat are different events. Do not send probe messages or automatically add contacts again.

The complete stable-identity send workflow remains `WA-005`. Existing open_chat, send_text and reply confirmation tools do not certify the live recipient. All Skills share the [UI and recipient contract](docs/UI_WORKFLOW_RULES.md).

### Dynamic layouts and OCR

Navigation uses current-frame OpenCV icon matching; size-keyed coordinate profiles
and fixed navigation/row/semantic fallbacks have been removed. See
[dynamic controls](docs/DYNAMIC_UI_CONTROLS.md).

OCR observes text and boxes; it never clicks. Traditional CV observes current dividers, search fields and input frames. BasicSkill delegates actions to the same HWND driver. Right-side content can coexist with the chat composer; closing a tab must not close the main client.

The detector cross-checks dividers against the composer's right edge to distinguish content-card borders. Arbitrary resizing and all page combinations are not certified. See the [OCR guide](docs/PAGE_OCR.md) and [page catalog](docs/UI_PAGE_CATALOG.md).

## Data freshness and Skill handoffs

For current-state tasks, update the relevant WeChat sources before indexing the project
archives. Analyze affected months, then conversation/person memories and events, before
refreshing charts or constructing reply context. Historical tasks can use a stated snapshot.
Each SKILL.md defines its prerequisites and downstream handoff; unchanged inputs skip work.
These are Agent workflow rules, not a completed automatic MCP freshness gate. See the
[shared workflow](docs/SKILL_DATA_WORKFLOW.md) and WA-007 in the roadmap.

## Getting started

Use PowerShell from the repository root and a suitable Windows Python environment. This is currently a src-directory project; set the import path rather than assuming an installable package.

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m pip install -r requirements-mcp.txt
# Optional local database integration:
python -m pip install -r requirements-db.txt
# Optional screenshot OCR:
python -m pip install -r requirements-ocr.txt
```

These files cover their respective integrations, not a finished one-click Windows installer. Win32 integrations also require their Python/runtime dependencies. OCR initialization may download model files; subsequent inference uses the local cache.

### Read-only page inspection

```powershell
python scripts\recognize_wechat_page.py --list-pages
python scripts\recognize_wechat_page.py --geometry-only --output data\ocr\geometry
python scripts\recognize_wechat_page.py --engine paddle --output data\ocr\latest
```

The last two commands capture the current window without clicking or sending. Screenshots, OCR and HTML previews may contain private information and stay in data/.

### Initialize memory and start MCP

To refresh all local non-group contact rows and their readable Moments in one
offline run, use `python scripts\sync_all_contacts_moments.py`. It preserves old
records and creates a private media manifest; it does not download media or prove
current friendship. See [all-contact Moments refresh](docs/MOMENTS_ARCHIVE.md).

Use actual existing project archive paths:

```powershell
python scripts\bootstrap_memory.py `
  --history-db data\wechat_history_complete.sqlite3 `
  --profiles-db data\wechat_contact_profiles.sqlite3 `
  --moments-db data\wechat_moments.sqlite3

python -m wechat_auto.mcp_server `
  --history-db data\wechat_history_complete.sqlite3 `
  --profiles-db data\wechat_contact_profiles.sqlite3 `
  --moments-db data\wechat_moments.sqlite3
```

Bootstrap indexes evidence and queues jobs; it does not run complete LLM analysis or invent conclusions. Initial selection covers the five highest-volume eligible private chats and five groups across their available months; later work updates affected nodes.

Connect an MCP-capable external agent to the stdio process. The server is model-agnostic; external models have their own data-handling settings. Add `--with-wechat-runtime` only for workflows needing the logged-in client; runtime prerequisites and recipient-safe dispatch validation still apply.

Tool areas: sync.*, entities.*, claims.*, events.*, analysis.*, memory.*, evidence.*, charts.*, monitor.*, reply.*, actions.*, vision.* and status.*. Availability depends on injected backends and runtime components.

## Agent Skills

| Skill | Workflow |
|---|---|
| [base-op](skills/base-op/SKILL.md) | Shared operating model and UI action boundary |
| [wechat-sync](skills/wechat-sync/SKILL.md) | Archive normalization and incremental sync |
| [wechat-monthly-analysis](skills/wechat-monthly-analysis/SKILL.md) | Per-conversation monthly analysis |
| [wechat-conversation-summary](skills/wechat-conversation-summary/SKILL.md) | Cross-month conversation memory |
| [wechat-person-analysis](skills/wechat-person-analysis/SKILL.md) | Self, contacts, group members and scenario analysis |
| [wechat-profile-moments](skills/wechat-profile-moments/SKILL.md) | Profile and Moments evidence updates |
| [wechat-timeline](skills/wechat-timeline/SKILL.md) | Long events and changes over time |
| [wechat-dashboard](skills/wechat-dashboard/SKILL.md) | Offline visualization and exports |
| [wechat-reply-monitor](skills/wechat-reply-monitor/SKILL.md) | One monitor cycle, bounded reply context and confirmation |
| [wechat-identity-audit](skills/wechat-identity-audit/SKILL.md) | Stable identities, absence, restoration and merge review |
| [wechat-ui-navigation](skills/wechat-ui-navigation/SKILL.md) | HWND/page selection, Contacts group, bounded recovery and guarded screenshot review |
| [wechat-memory-rebuild](skills/wechat-memory-rebuild/SKILL.md) | Corrections and dependency-aware rebuilding |

Skills are static Markdown instructions, not autonomous background services. Keep shared repository references available. Inferences need evidence and distinguish observed, confirmed, inferred and unknown; avatars/signatures alone do not justify psychological diagnoses or certain personality labels.

## Development, privacy and action boundaries

```powershell
python -m pytest tests -q
# Recorded project verification command:
python -m pytest tests -q
```

Use File Transfer Assistant for live checks. Opening a chat or preparing a draft does not authorize sending. Sends, stickers, likes, comments, profile mutations and remote-media downloads require explicit confirmation. Actions do not use injection, hooks, WeChat database writes or private messaging protocols. The supported UI architecture excludes WeChat 3.x and UIAutomation control-tree compatibility.

Chat archives, media, screenshots, exports and secrets are private local artifacts. Protect secrets with Windows DPAPI under data/.secrets/; never commit or print them. The project does not claim Tencent endorsement or zero account-enforcement risk.

Repository: src/wechat_auto/ (MCP runtime and supporting implementation), skills/ (instructions), scripts/ (tools), tests/ (regressions), docs/ (contracts and guides), data/ (ignored private artifacts). Operational ledgers and diagnostic records stay local.

## Documentation

- [Architecture](ARCHITECTURE.md) · [Development rules](AGENTS.md) · [Environment](CLAUDE.md)
- [Shared UI / recipient contract](docs/UI_WORKFLOW_RULES.md)
- [Page catalog](docs/UI_PAGE_CATALOG.md) · [OCR guide](docs/PAGE_OCR.md)
- [Action verification rules](docs/ACTION_VERIFICATION_MATRIX.md)
- [Roadmap](docs/FUTURE_TODO.md) · [Search and realtime design](docs/SEARCH_AND_REALTIME_DESIGN.md)

## Keywords and topics

WeChat automation, Weixin automation, Windows WeChat 4.x, WeChat AI assistant, WeChat chatbot foundations, AI-assisted replies, LLM agent, MCP server, Model Context Protocol, agent skills, PaddleOCR, PP-OCRv5 mobile, RapidOCR, OCR, computer vision, Win32, HWND, desktop automation, SQLite, Markdown memory, long-term agent memory, evidence-backed memory, retrieval context, chat history archive, incremental sync, directory change notifications, monthly conversation analysis, contact identity, wxid, group chat analysis, WeChat Moments, profile snapshots, relationship timeline, event timeline, communication style, self analysis, emoji semantics, sticker preferences, offline dashboard, local-first data, Windows DPAPI, confirmed actions.

中文检索词：微信自动化、微信 AI 助手、微信聊天机器人基础、微信 MCP、微信 OCR、聊天记录归档、月度聊天分析、联系人画像、群聊分析、朋友圈归档、人物记忆、关系时间线、增量分析、自动回复草稿、本地 SQLite、Markdown Memory。
