"""Extract explicit profile labels from one verified frame; never perform actions."""
from __future__ import annotations

import re

LABELS = {'昵称': 'nickname', '微信号': 'alias', '地区': 'region', '备注': 'remark',
          '个性签名': 'signature', '签名': 'signature', '来源': 'contact_source',
          '添加时间': 'added_at', '共同群聊': 'common_groups', '标签': 'tags', '性别': 'gender'}


def extract_profile_fields(boxes: list[dict], size: tuple[int, int], bounds: list[float]) -> dict:
    width, height = size
    selected = [b for b in boxes if b.get('score', 0) >= .75 and
                bounds[0] <= (b['x'] + b['w'] / 2) / width <= bounds[2] and
                bounds[1] <= (b['y'] + b['h'] / 2) / height <= bounds[3]]
    values: dict[str, list[str]] = {}
    for label, field in LABELS.items():
        for b in selected:
            text = str(b.get('text', '')).strip()
            match = re.fullmatch(re.escape(label) + r'\s*[:：]\s*(.+)', text)
            value = match.group(1).strip() if match else None
            if text == label or text in {label + ':', label + '：'}:
                row = [v for v in selected if v is not b and v['x'] >= b['x'] + b['w'] and
                       abs((v['y'] + v['h']/2) - (b['y'] + b['h']/2)) <= max(b['h'], v['h']) * .5]
                # Multiple boxes can be unrelated controls; do not join them speculatively.
                if len(row) == 1:
                    value = str(row[0]['text']).strip()
            if value and value not in LABELS and value not in {'发消息', '朋友圈', '更多信息'}:
                values.setdefault(field, []).append(value)
    fields = {k: v[0] for k, v in values.items() if len(v) == 1}
    return {'fields': fields, 'ambiguous_fields': sorted(k for k, v in values.items() if len(v) > 1),
            'unobserved_fields': sorted(set(LABELS.values()) - set(fields))}
