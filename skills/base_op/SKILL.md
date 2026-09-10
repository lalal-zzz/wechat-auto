---
name: base-op
description: Use the local WeChat LLM Agent system for Windows WeChat 4.x chat automation, offline conversation and Moments memory, contact-specific analysis, and confirmed HWND actions. Use when a task involves this repository's WeChat automation or analysis capabilities.
metadata:
  short-description: Local LLM Agent for WeChat automation and memory
---

# base_op Skill

This Skill is the LLM-facing layer of the repository. The implementation code
lives separately under `src/`; do not treat this Skill directory as the Python
package.

## Repository layout

```text
src/                         Python implementation
  wechat_auto/
    core/                    Win32 HWND connection
    actions/basic.py         only UI action entrypoint
    primitives/              HWND actions and OCR observation
    backends/                read-only WeChat database adapters
    storage/                 offline SQLite, memory and preference stores
skills/base_op/SKILL.md      this LLM instruction layer
tests/                       automated tests
data/                        local private databases; never read from Git or commit
```

## Operating model

Use this sequence for repository tasks:

1. Read local memory and database data through the adapters in `src/wechat_auto/backends/`.
2. Persist normalized data, cursors, semantic hints and analysis inputs through `src/wechat_auto/storage/`.
3. Let the LLM analyze context, contacts, relationships, preferences, events and reply candidates.
4. For a UI mutation, call the single `BasicSkill` entrypoint in `src/wechat_auto/actions/basic.py`.
5. Treat OCR as observation and verification only. OCR may return a replacement coordinate; the actual action must still be sent through the top-level HWND driver.
6. Require explicit confirmation before sending messages or stickers, liking/commenting Moments, or downloading remote media.

## Current capabilities

- Open a contact or group chat and prepare/send text.
- Prepare/send files and images.
- HWND click, right-click, scroll and key actions.
- Open the emoji panel and send a previously verified sticker catalog item.
- Read and archive chat history, incremental messages and Moments locally.
- Decode type-47 emoji semantic hints and rank contact-specific sticker preferences.
- Monitor a selected conversation through database change notification and a persistent cursor.

## Important boundaries

- The current target is Windows WeChat `4.1.13.12`, window class `Qt51514QWindowIcon`.
- Do not add UIA, pywinauto action calls, physical mouse/keyboard fallbacks, injection, hooks, private protocol construction, or writes to WeChat's database.
- Do not commit anything under `data/`, chat exports, screenshots, logs or secrets.
- High-level personality, automatic chat, matchmaking, third-party analysis and long-term Memory orchestration are roadmap items; do not claim they are implemented.
- Keep advanced workflows above `BasicSkill`; never create a second UI transport.

## Roadmap context

Future LLM-agent work includes personality and MBTI-style analysis, contact-specific reply style, configurable virtual personas, matchmaking analysis, confirmed Moments actions, analysis of authorized group/contact data, and a source-traceable local Memory system. These are planning directions, not current automatic behavior.

For the full project description and roadmap, read the repository root `README.md`. For module boundaries, read `ARCHITECTURE.md`.
