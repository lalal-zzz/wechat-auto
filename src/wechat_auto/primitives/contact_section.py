"""Observe only the personal Contacts tree, excluding requests and service accounts."""
from __future__ import annotations

import re


def observe_contact_section(image, boxes: list[dict], state: dict) -> dict:
    import cv2
    import numpy as np

    if state.get('page') not in {'contacts', 'contact_profile', 'new_friends'}:
        return {'ok': False, 'error': 'contacts_page_not_observed'}
    bounds = state.get('region_bounds', {}).get('conversation_list')
    if not bounds:
        return {'ok': False, 'error': 'contacts_tree_geometry_unavailable'}
    width, height = image.size
    eligible = [b for b in boxes if b.get('score', 1) >= .65 and
                bounds[0] <= (b['x'] + b['w']/2)/width <= bounds[2] and
                bounds[1] <= (b['y'] + b['h']/2)/height <= bounds[3]]
    headers = [b for b in eligible if re.fullmatch(r'联系人(?:[（(]?\d+[）)]?)?', re.sub(r'\s+', '', b['text']))]
    if len(headers) != 1:
        return {'ok': False, 'error': 'contacts_tree_header_absent_or_ambiguous',
                'header_candidates': len(headers)}
    header = headers[0]
    left = round(bounds[0]*width)
    top = max(0, round(header['y'] - header['h']*.25))
    bottom = min(height, round(header['y'] + header['h']*1.25))
    # OCR may include the chevron's right wing in the heading box. Keep
    # that wing, but only accept contour centers left of the heading.
    right = min(width, round(header['x'] + header['h']*.5))
    if right <= left or bottom <= top:
        return {'ok': False, 'error': 'contacts_expander_unavailable'}
    gray = np.asarray(image.convert('RGB'))[top:bottom, left:right].mean(axis=2)
    binary = (np.abs(gray - np.median(gray)) > 32).astype('uint8')*255
    candidates = []
    for contour in cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, w, h = cv2.boundingRect(contour)
        if left+x+w/2 >= header['x'] or x+w >= binary.shape[1]:
            continue
        if not 7 <= min(w, h) or max(w, h) > header['h']*1.6:
            continue
        mask = binary[y:y+h, x:x+w] != 0
        def span(points):
            return int(points.max() - points.min()) if points.size else 0
        edge_y, edge_x = np.nonzero(mask)
        down = span(edge_x[edge_y < h*.25]) > w*.6 and span(edge_x[edge_y > h*.75]) < w*.5
        across = span(edge_y[edge_x < w*.25]) > h*.6 and span(edge_y[edge_x > w*.75]) < h*.5
        if down != across:
            candidates.append({'state': 'expanded' if down else 'collapsed',
                               'x': left+x+w/2, 'y': top+y+h/2})
    if len(candidates) != 1:
        return {'ok': False, 'error': 'contacts_expander_absent_or_ambiguous', 'header': header}
    end = bounds[3]*height
    # Never carry a person's matching name across another tree category.
    other_headers = {'新的朋友', '公众号、服务号', '公众号', '服务号', '企业微信联系人', '群聊', '标签'}
    for box in eligible:
        label = re.sub(r'\s+', '', box['text'])
        if box['y'] > header['y'] and label in other_headers:
            end = min(end, box['y'])
    return {'ok': True, 'state': candidates[0]['state'], 'header': header,
            'expander_point': [candidates[0]['x']/width, candidates[0]['y']/height],
            'member_bounds': [bounds[0], (header['y']+header['h'])/height, bounds[2], end/height]}
