"""Read-only window/page inventory; replay private audit frames without UI actions.

Default is a live same-process inventory. --replay expects audit JSON/PNG pairs
and recomputes page classification and CV geometry from the recorded frame.
No raw OCR, window titles, aliases or chat text are printed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wechat_auto.actions.basic import BasicSkill
from wechat_auto.config import SessionConfig, WeChatConfig
from wechat_auto.core.application import Application
from wechat_auto.primitives.window_observer import window_summary


def replay(folder: Path) -> list[dict]:
    from PIL import Image

    from wechat_auto.primitives.contact_section import observe_contact_section
    from wechat_auto.primitives.page_controls import observe_tab_closes
    from wechat_auto.primitives.page_geometry import observe_geometry
    from wechat_auto.primitives.page_state import classify_page

    result = []
    for source in sorted(folder.rglob('*.json')):
        frame = source.with_suffix('.png')
        if not frame.exists():
            continue
        record = json.loads(source.read_text(encoding='utf-8'))
        if not {'window', 'boxes'} <= record.keys():
            continue
        with Image.open(frame) as image:
            state = classify_page(record['boxes'], image.size, geometry=observe_geometry(image))
            observe_tab_closes(image, record['boxes'], state)
            if state['page'] in {'contacts', 'contact_profile', 'new_friends'}:
                state['contact_section'] = observe_contact_section(image, record['boxes'], state)
        summary = window_summary(record['window'], {'ok': True, 'state': state})
        result.append({'sample': str(source.relative_to(folder)), **summary})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path)
    parser.add_argument('--geometry-only', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.replay:
        windows = replay(args.replay)
    else:
        config = WeChatConfig(ocr_engine='paddle', ocr_allow_rapid_fallback=False)
        app = Application(config).connect()
        windows = BasicSkill(app, config, SessionConfig()).inspect_windows(include_ocr=not args.geometry_only)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(windows, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'windows': len(windows), 'recognized': sum(w['status'] == 'recognized' for w in windows),
                      'observations': [{key: w.get(key) for key in (
                          'role', 'status', 'page', 'surfaces', 'composer_present', 'right_panel_present')}
                                       for w in windows]}, ensure_ascii=True))


if __name__ == '__main__':
    main()
