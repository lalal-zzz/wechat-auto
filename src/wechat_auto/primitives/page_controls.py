"""Traditional visual control observations; these functions never act."""
from __future__ import annotations


class NavigationControlError(RuntimeError):
    """A current-frame navigation control could not be uniquely located."""


def find_navigation_control(image, operation: str) -> dict:
    """Match a public icon in the current sidebar, independent of window size.

    Templates encode glyph shapes, never button coordinates. Restrict matching
    to the sidebar measured from this image and reject competing spatial peaks.
    """
    import cv2
    import numpy as np

    from wechat_auto.primitives.navigation_templates import TEMPLATES
    from wechat_auto.primitives.page_geometry import observe_geometry
    if operation not in TEMPLATES:
        raise NavigationControlError('Visual control detector is not implemented for this operation')
    width, height = image.size
    geometry = observe_geometry(image)
    boundaries = [s['x'] for s in geometry['vertical_separators'] if 35 < s['x'] < width * .15]
    if not boundaries:
        raise NavigationControlError('Current sidebar boundary is not detected')
    right = min(boundaries)
    rgb = np.asarray(image.convert('RGB'))[:, :right]
    gray = rgb.mean(axis=2)
    mask = np.uint8(np.abs(gray - np.median(gray)) > 32)
    red = (rgb[:, :, 0].astype(float) > rgb[:, :, 1] * 1.4) & (rgb[:, :, 0].astype(float) > rgb[:, :, 2] * 1.4)
    mask[red] = 0
    template = np.array([[int(v) for v in row] for row in TEMPLATES[operation]], dtype=np.uint8)
    # Selection may fill an icon which is outlined when inactive. Compare
    # silhouettes so color/fill state does not change the semantic target.
    def silhouette(binary):
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        result = np.zeros_like(binary)
        cv2.drawContours(result, contours, -1, 1, cv2.FILLED)
        return result
    mask, template = silhouette(mask), silhouette(template)
    candidates = []
    for scale in np.linspace(.65, 1.6, 39):
        tw, th = round(template.shape[1] * scale), round(template.shape[0] * scale)
        if tw >= right or th >= height:
            continue
        glyph = cv2.resize(template, (tw, th), interpolation=cv2.INTER_NEAREST_EXACT)
        scores = cv2.matchTemplate(mask, glyph, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(scores >= .80)
        for x, y in zip(xs, ys, strict=True):
            candidates.append({'x': float(x + tw / 2), 'y': float(y + th / 2),
                               'score': float(scores[y, x]), 'w': tw, 'h': th})
    candidates.sort(key=lambda c: c['score'], reverse=True)
    unique = []
    for c in candidates:
        if not any(abs(c['x'] - p['x']) < max(c['w'], p['w']) * .6
                   and abs(c['y'] - p['y']) < max(c['h'], p['h']) * .6 for p in unique):
            unique.append(c)
    if len(unique) != 1:
        raise NavigationControlError('Current navigation glyph absent or ambiguous')
    c = unique[0]
    return {**c, 'window_fraction': [c['x'] / width, c['y'] / height],
            'method': 'opencv_multiscale_glyph', 'frame_size': [width, height]}


def find_search_clear(image, field: dict) -> list[tuple[int, int]]:
    import cv2
    import numpy as np

    x, y, w, h = (field[k] for k in ("x", "y", "w", "h"))
    left = x + int(w * .7)
    gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    patch = gray[y:y + h, left:x + w]
    circles = cv2.HoughCircles(patch, cv2.HOUGH_GRADIENT, 1, max(4, h * .2),
                               param1=40, param2=12, minRadius=max(3, int(h * .14)),
                               maxRadius=max(4, int(h * .38)))
    if circles is None:
        return []
    return [(round(left + cx), round(y + cy)) for cx, cy, _radius in circles[0]
            if abs(cy - h / 2) < .15 * h and .3 * h <= x + w - (left + cx) <= .8 * h]


def observe_selected_contacts(image, state: dict) -> None:
    """Observe the current selected Contacts glyph when tree headers scroll away."""
    import numpy as np

    if state.get('page') != 'unknown' or any(state.get(k) for k in ('overlays', 'panels', 'content_windows')):
        return
    try:
        control = find_navigation_control(image, 'open_contacts')
    except NavigationControlError:
        return
    x, y, w, h = (control[k] for k in ('x', 'y', 'w', 'h'))
    patch = np.asarray(image.convert('RGB').crop((round(x-w/2), round(y-h/2),
                                                 round(x+w/2), round(y+h/2)))).astype(float)
    green = (patch[:, :, 1] > 100) & (patch[:, :, 1] > patch[:, :, 0]*1.5) & (patch[:, :, 1] > patch[:, :, 2]*1.2)
    if green.mean() < .15:
        return
    from wechat_auto.actions.semantics import PageId
    state.update(page='contacts', page_id=int(PageId.CONTACTS),
                 selected_navigation={'page': 'contacts', 'verification': 'current_selected_green_glyph',
                                      'control': control})


def find_contact_album_entry(image, label: dict, *, right: int | None = None) -> dict:
    """Find the unique thumbnail strip beside the exact profile Moments label."""
    import cv2
    import numpy as np

    width, height = image.size
    cx = round(label['x'] + label['w'] + label['h']*.2)
    cy = label['y'] + label['h']/2
    top, bottom = max(0, round(cy-label['h']*1.2)), min(height, round(cy+label['h']*1.2))
    right = min(width, right or width)
    if right <= cx or bottom <= top:
        raise NavigationControlError('Personal album thumbnail region unavailable')
    patch = np.asarray(image.convert('RGB'))[top:bottom, cx:right]
    gray = cv2.cvtColor(patch, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 20, 60)
    columns = ((edges > 0).sum(axis=0) >= 3) | (patch.std(axis=(0, 2)) > 18)
    mask = np.uint8(columns)[None, :]*255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((1, max(3, round(label['h']*.3))), dtype='uint8'))
    segments = [cv2.boundingRect(c) for c in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]]
    candidates = [(x, w) for x, _y, w, _h in segments if w >= label['h']*2]
    if len(candidates) != 1:
        raise NavigationControlError('Personal album thumbnail strip absent or ambiguous')
    x, w = candidates[0]
    return {'x': cx+x, 'y': top, 'w': w, 'h': bottom-top,
            'window_fraction': [(cx+x+w/2)/width, cy/height],
            'method': 'current_profile_label_and_thumbnail_texture'}


def observe_tab_closes(image, boxes: list[dict], state: dict) -> None:
    """Attach unique diagonal-cross candidates beside each observed tab label."""
    import cv2
    import numpy as np

    gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    width, height = image.size
    for tab in state["right_panel"].get("tabs", []):
        box = boxes[tab["evidence_box_index"]]
        bh = max(12, box["h"])
        # Tabs have a minimum width: short labels leave a larger empty gap.
        left = int(box["x"] + box["w"] + bh * .8)
        right = min(int(width * .96), int(box["x"] + box["w"] + bh * 10))
        top, bottom = max(0, int(box["y"] - bh * .5)), min(height, int(box["y"] + bh * 1.5))
        if right <= left or bottom <= top:
            continue
        patch = gray[top:bottom, left:right]
        contrast = np.abs(patch.astype(np.int16) - int(np.median(patch)))
        mask = np.uint8(contrast >= 25) * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        centers = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if not (.35 * bh <= w <= 1.6 * bh and .35 * bh <= h <= 1.6 * bh
                    and .65 <= w / h <= 1.5):
                continue
            glyph = mask[y:y + h, x:x + w] > 0
            yy, xx = np.mgrid[0:h, 0:w]
            u, v = xx / max(1, w - 1), yy / max(1, h - 1)
            diagonals = (np.abs(u - v) <= .18) | (np.abs(u + v - 1) <= .18)
            inside = glyph[diagonals].sum() / max(1, glyph.sum())
            middle = glyph[int(h * .4):max(int(h * .6), int(h * .4) + 1),
                           int(w * .4):max(int(w * .6), int(w * .4) + 1)]
            if inside >= .85 and middle.any():
                centers.append((left + x + w / 2, top + y + h / 2))
        if len(centers) == 1:
            tab["close_candidate"] = {"x": round(centers[0][0]), "y": round(centers[0][1]),
                                      "window_fraction": [centers[0][0] / width, centers[0][1] / height],
                                      "method": "diagonal_cross_mask"}
