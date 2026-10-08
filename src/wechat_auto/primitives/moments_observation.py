"""Read-only album section observations; never infer item identity or act."""
from __future__ import annotations

import hashlib
import re


def parse_album_visibility_hint(text: str) -> tuple[str, str]:
    """Parse only an explicit album visibility footer, never infer access."""
    text = re.sub(r'\s+', '', text)
    periods = {'三天': 'three_days', '3天': 'three_days', '一个月': 'one_month',
               '1个月': 'one_month', '半年': 'six_months', '六个月': 'six_months', '6个月': 'six_months'}
    match = re.fullmatch(r'(?:朋友|对方)?(?:仅展示|只展示|仅显示|只显示|仅可查看|仅可见|只可见)'
                         r'(?:最近|近)?(三天|3天|一个月|1个月|半年|六个月|6个月)(?:的)?(?:朋友圈|动态)?', text)
    return (periods[match[1]], text) if match else ('unknown', '')


def has_calendar_rows(texts: list[str]) -> bool:
    """Recognize calendar layout, without assigning publication dates."""
    joined = any(re.fullmatch(r'(?:0[1-9]|[12]\d|3[01])(?:0?[1-9]|1[0-2])月', t) for t in texts)
    separated = (any(re.fullmatch(r'(?:\d{4}年)?(?:0?[1-9]|1[0-2])月', t) for t in texts)
                 and any(re.fullmatch(r'(?:0?[1-9]|[12]\d|3[01])', t) for t in texts))
    return joined or separated


def observe_album_sections(image, boxes: list[dict], state: dict) -> dict:
    embedded = any(p.get('key') == 'moments_person' and p.get('presentation') == 'embedded_right_tab'
                   for p in state.get('panels', []))
    width, height = image.size
    bounds = list(state['region_bounds']['right_content']) if embedded else [0, 0, 1, 1]
    if embedded:
        bounds[1] = state['region_bounds']['right_panel_header'][3]
        bounds[3] = 1
    scoped = [b for b in boxes if b.get('score', 0) >= .65 and
              bounds[0] <= (b['x']+b['w']/2)/width <= bounds[2] and
              bounds[1] <= (b['y']+b['h']/2)/height <= bounds[3]]
    left_column = bounds[0] + (bounds[2]-bounds[0])*.25
    dates = [re.sub(r'\s+', '', b['text']) for b in scoped if b['x']/width <= left_column]
    pinned = '置顶' in dates
    calendar = has_calendar_rows(dates)
    window, hint = 'unknown', ''
    for b in scoped:
        period, footer = parse_album_visibility_hint(b['text'])
        if footer:
            window, hint = period, footer
    sections = [
        {'section': 'pinned', 'status': 'observed' if pinned else 'unknown',
         'visibility_window': 'unknown', 'visibility_hint': ''},
        {'section': 'regular', 'status': 'restricted' if hint else 'observed' if calendar else 'unknown',
         'visibility_window': window, 'visibility_hint': hint},
    ]
    # Photo grids may change while all OCR labels stay identical. Compare the
    # current album pane, excluding central contacts/profile and tab chrome.
    crop = image.crop(tuple(round(v*(width if i % 2 == 0 else height)) for i, v in enumerate(bounds)))
    pixels = bytes(v//16 for v in crop.convert('L').resize((48, 48)).getdata())
    return {'sections': sections, 'content_fingerprint': hashlib.sha256(pixels).hexdigest(),
            'body_bounds': bounds, 'access_denied': any(re.sub(r'\s+', '', b['text']) in
                {'不让你看', '朋友不让你看朋友圈', '对方不让你看朋友圈'} for b in scoped)}


def merge_album_sections(current: dict[str, dict], incoming: list[dict]) -> None:
    """Keep earlier pinned observations after that section scrolls out of view."""
    for item in incoming:
        name = item['section']
        if name not in current or item['status'] != 'unknown':
            # A later date row does not clear a previously observed time limit.
            if current.get(name, {}).get('visibility_window', 'unknown') != 'unknown' and item['visibility_window'] == 'unknown':
                item = {**item, 'visibility_window': current[name]['visibility_window'],
                        'visibility_hint': current[name]['visibility_hint'], 'status': 'restricted'}
            current[name] = dict(item)
