"""Traditional visual control observations; these functions never act."""
from __future__ import annotations


class NavigationControlError(RuntimeError):
    """A current-frame navigation control could not be uniquely located."""


def composer_send_enabled(image, send_box: dict) -> bool | None:
    """Observe the current green Send backing; missing pixels are unknown."""
    import numpy as np
    from PIL import Image

    if not isinstance(image, Image.Image):
        return None
    try:
        x, y, w, h = (int(send_box[k]) for k in ('x', 'y', 'w', 'h'))
    except (KeyError, TypeError, ValueError):
        return None
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > image.width or y+h > image.height:
        return None
    pixels = np.asarray(image.crop((x, y, x+w, y+h)).convert('RGB')).astype(float)
    green = ((pixels[:, :, 1] > 100) & (pixels[:, :, 1] > pixels[:, :, 0]*1.25)
             & (pixels[:, :, 1] > pixels[:, :, 2]*1.15))
    return bool(green.mean() > .05)


def is_empty_composer_placeholder(image, body_boxes: list[dict], send_box: dict) -> bool:
    """Recognize one known low-contrast guide, never arbitrary composer text."""
    import numpy as np
    from PIL import Image

    from wechat_auto.primitives.vision import normalize_text

    if (not isinstance(image, Image.Image) or not body_boxes
            or normalize_text(''.join(b['text'] for b in body_boxes)) != '按住鼠标语音输入文字'):
        return False

    def patch(box):
        x, y, w, h = (int(box[k]) for k in ('x', 'y', 'w', 'h'))
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > image.width or y+h > image.height:
            return None
        return np.asarray(image.crop((x, y, x+w, y+h)).convert('RGB')).astype(float)

    for box in [*body_boxes, send_box]:
        pixels = patch(box)
        if pixels is None:
            return False
        # An enabled Send button has a green backing, including its text box.
        green = ((pixels[:, :, 1] > 100) & (pixels[:, :, 1] > pixels[:, :, 0]*1.25)
                 & (pixels[:, :, 1] > pixels[:, :, 2]*1.15))
        if green.mean() > .05:
            return False
        background = np.median(pixels.reshape(-1, 3), axis=0)
        contrast = np.max(np.abs(pixels-background), axis=2)
        ink = contrast[contrast > 25]
        if not ink.size or np.percentile(ink, 95) > 140:
            return False
    return True


def find_private_chat_profile_avatar(image, boxes: list, state: dict, query: str) -> dict:
    """Find the unique member avatar above its exact name in chat details."""
    import cv2
    import numpy as np

    from wechat_auto.primitives.vision import normalize_text

    geometry = state.get('geometry', {})
    panel = geometry.get('right_panel_candidate')
    if not panel or state.get('composer', {}).get('state') not in {'present', 'candidate'}:
        raise NavigationControlError('Private chat details geometry absent')
    panel_boxes = [b for b in boxes if b['x'] > panel['x']]
    labels = {normalize_text(b['text']) for b in panel_boxes}
    if not {'查找聊天内容', '消息免打扰', '置顶聊天'} <= labels:
        raise NavigationControlError('Private chat details anchors absent')
    names = [b for b in panel_boxes if normalize_text(b['text']) == normalize_text(query)]
    if len(names) != 1:
        raise NavigationControlError('Unique exact private member name absent')
    name = names[0]
    gray = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 30, 80)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if (x <= panel['x'] or not .85 < w / h < 1.15
                or not name['h'] * 1.5 < h < name['h'] * 4
                or not 0 <= name['y'] - (y + h) < name['h']
                or abs(x + w / 2 - (name['x'] + name['w'] / 2)) > name['h']
                or abs(cv2.contourArea(contour)) / (w * h) < .65):
            continue
        if not any(abs(x-c['x']) < 4 and abs(y-c['y']) < 4 for c in candidates):
            candidates.append({'x': x, 'y': y, 'w': w, 'h': h})
    if len(candidates) != 1:
        raise NavigationControlError('Private member avatar absent or ambiguous')
    c = candidates[0]
    return {**c, 'window_fraction': [(c['x']+c['w']/2)/image.width,
                                     (c['y']+c['h']/2)/image.height],
            'method': 'opencv_square_and_exact_member_ocr'}


def find_navigation_control(image, operation: str) -> dict:
    """Match a public icon in the current sidebar, independent of window size.

    Templates encode glyph shapes, never button coordinates. Restrict matching
    to the sidebar measured from this image and reject competing spatial peaks.
    """
    if operation == 'open_emoji_panel':
        return find_composer_emoji_control(image)
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
    # Remove the entire badge, including its white numeral. Treat occluded
    # pixels as unknown rather than background or evidence of a glyph.
    badge = np.zeros_like(mask)
    contours, _ = cv2.findContours(np.uint8(red), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(badge, contours, -1, 1, cv2.FILLED)
    template = np.array([[int(v) for v in row] for row in TEMPLATES[operation]], dtype=np.uint8)
    # Selection may fill an icon which is outlined when inactive. Compare
    # silhouettes so color/fill state does not change the semantic target.
    def silhouette(binary):
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        result = np.zeros_like(binary)
        cv2.drawContours(result, contours, -1, 1, cv2.FILLED)
        return result
    occluded_mask = silhouette(mask | badge)
    mask, template = silhouette(mask), silhouette(template)
    has_badge = bool(badge.any())
    known = (1 - badge).astype(np.float32)
    visible = (occluded_mask * known).astype(np.float32)

    def match_scores(glyph):
        scores = cv2.matchTemplate(mask, glyph, cv2.TM_CCOEFF_NORMED)
        if has_badge:
            th, tw = glyph.shape
            ones = np.ones((th, tw), np.float32)
            pattern = glyph.astype(np.float32)
            count = cv2.matchTemplate(known, ones, cv2.TM_CCORR)
            ink = cv2.matchTemplate(visible, ones, cv2.TM_CCORR)
            expected = cv2.matchTemplate(known, pattern, cv2.TM_CCORR)
            common = cv2.matchTemplate(visible, pattern, cv2.TM_CCORR)
            safe_count = np.maximum(count, 1)
            variance = (ink - ink * ink / safe_count) * (
                expected - expected * expected / safe_count)
            weighted = np.full_like(scores, -1)
            # At least 75% of the frame and glyph ink must remain visible.
            # An unoccluded rival retains its ordinary score for ambiguity checks.
            eligible = ((count >= tw * th * .75) & (count < tw * th - .5)
                        & (expected >= pattern.sum() * .75) & (variance > 1e-6))
            weighted[eligible] = ((common - ink * expected / safe_count)[eligible]
                                  / np.sqrt(variance[eligible]))
            scores = np.maximum(scores, weighted)
        return scores

    candidates = []
    for scale in np.linspace(.65, 1.6, 39):
        tw, th = round(template.shape[1] * scale), round(template.shape[0] * scale)
        if tw >= right or th >= height:
            continue
        glyph = cv2.resize(template, (tw, th), interpolation=cv2.INTER_NEAREST_EXACT)
        scores = match_scores(glyph)
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
    # Filled silhouettes of a bubble, compass and cube can produce weak
    # cross-matches. Require a strong match and a clear gap to every other
    # spatial peak; two equally plausible icons must still stop navigation.
    if (not unique or unique[0]['score'] < .90
            or len(unique) > 1 and unique[0]['score'] - unique[1]['score'] < .04):
        raise NavigationControlError('Current navigation glyph absent or ambiguous')
    c = unique[0]
    x, y = round(c['x'] - c['w']/2), round(c['y'] - c['h']/2)
    if badge[y:y+c['h'], x:x+c['w']].any():
        # Partial circles can match a bubble. Require the same visible pixels
        # to prefer this semantic glyph over every other supported sidebar icon.
        for name, rows in TEMPLATES.items():
            if name == operation:
                continue
            rival = silhouette(np.array([[int(v) for v in row] for row in rows], dtype=np.uint8))
            for scale in np.linspace(.65, 1.6, 39):
                rw, rh = round(rival.shape[1]*scale), round(rival.shape[0]*scale)
                if rw >= right or rh >= height:
                    continue
                scores = match_scores(cv2.resize(rival, (rw, rh), interpolation=cv2.INTER_NEAREST_EXACT))
                # Compare spatially overlapping candidates, never a different
                # icon elsewhere in the sidebar.
                x0, x1 = max(0, round(c['x']-rw/2-3)), min(scores.shape[1], round(c['x']-rw/2+4))
                y0, y1 = max(0, round(c['y']-rh/2-3)), min(scores.shape[0], round(c['y']-rh/2+4))
                if x1 > x0 and y1 > y0 and scores[y0:y1, x0:x1].max() >= c['score'] - .02:
                    raise NavigationControlError('Current navigation glyph absent or ambiguous')
    return {**c, 'window_fraction': [c['x'] / width, c['y'] / height],
            'method': 'opencv_multiscale_glyph', 'frame_size': [width, height]}


def find_composer_emoji_control(image) -> dict:
    """Match the public smile glyph inside the current composer frame."""
    import cv2
    import numpy as np
    from PIL import Image

    from wechat_auto.primitives.composer_templates import EMOJI_BUTTON
    from wechat_auto.primitives.page_geometry import observe_geometry

    composers = observe_geometry(image).get('composer_candidates',[])
    if len(composers) != 1:
        raise NavigationControlError('Unique composer geometry required for emoji button')
    composer = composers[0]
    x0 = composer['x']
    y0 = composer['y']+composer['h']//2
    gray = cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
    patch = gray[y0:composer['y']+composer['h'],x0:composer['x']+composer['w']]
    mask = np.uint8(np.abs(patch.astype(float)-np.median(patch))>35)
    template = np.array([[int(v) for v in row] for row in EMOJI_BUTTON],dtype=np.uint8)
    candidates = []
    for scale in np.linspace(.6,1.8,49):
        w,h = round(template.shape[1]*scale),round(template.shape[0]*scale)
        if w >= patch.shape[1] or h >= patch.shape[0]:
            continue
        glyphs = [cv2.resize(template,(w,h),interpolation=i)
                  for i in (cv2.INTER_NEAREST_EXACT,cv2.INTER_NEAREST)]
        glyphs.append(np.asarray(Image.fromarray(template).resize((w,h),Image.Resampling.NEAREST)))
        for glyph in glyphs:
            scores = cv2.matchTemplate(mask,glyph,cv2.TM_CCOEFF_NORMED)
            ys,xs = np.where(scores>=.85)
            for x,y in zip(xs,ys,strict=True):
                candidates.append({'x':x0+float(x+w/2),'y':y0+float(y+h/2),
                                   'w':w,'h':h,'score':float(scores[y,x])})
    candidates.sort(key=lambda c:c['score'],reverse=True)
    unique=[]
    for c in candidates:
        if not any(abs(c['x']-p['x'])<max(c['w'],p['w'])*.6
                   and abs(c['y']-p['y'])<max(c['h'],p['h'])*.6 for p in unique):
            unique.append(c)
    if not unique or unique[0]['score']<.90 or len(unique)>1 and unique[0]['score']-unique[1]['score']<.04:
        raise NavigationControlError('Composer emoji glyph absent or ambiguous')
    c=unique[0]
    return {**c,'window_fraction':[c['x']/image.width,c['y']/image.height],
            'method':'opencv_composer_smile_glyph','frame_size':list(image.size)}


def find_emoji_favorites_control(image) -> dict:
    """Match the public heart tab in the current native emoji popup footer."""
    import cv2
    import numpy as np

    from wechat_auto.primitives.composer_templates import EMOJI_FAVORITES_TAB

    gray=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
    y0=int(image.height*.8)
    patch=gray[y0:]
    mask=np.uint8(np.abs(patch.astype(float)-np.median(patch))>35)
    template=np.array([[int(v) for v in row] for row in EMOJI_FAVORITES_TAB],dtype=np.uint8)
    candidates=[]
    for scale in np.linspace(.6,1.8,49):
        w,h=round(template.shape[1]*scale),round(template.shape[0]*scale)
        if w>=patch.shape[1] or h>=patch.shape[0]:
            continue
        glyph=cv2.resize(template,(w,h),interpolation=cv2.INTER_NEAREST_EXACT)
        scores=cv2.matchTemplate(mask,glyph,cv2.TM_CCOEFF_NORMED)
        ys,xs=np.where(scores>=.90)
        for x,y in zip(xs,ys,strict=True):
            candidates.append({'x':float(x+w/2),'y':y0+float(y+h/2),
                               'w':w,'h':h,'score':float(scores[y,x])})
    candidates.sort(key=lambda c:c['score'],reverse=True)
    unique=[]
    for c in candidates:
        if not any(abs(c['x']-p['x'])<max(c['w'],p['w'])*.6
                   and abs(c['y']-p['y'])<max(c['h'],p['h'])*.6 for p in unique):
            unique.append(c)
    if len(unique)!=1:
        raise NavigationControlError('Current emoji favorites heart absent or ambiguous')
    c=unique[0]
    return {**c,'window_fraction':[c['x']/image.width,c['y']/image.height],
            'method':'opencv_emoji_favorites_heart','frame_size':list(image.size)}


def observe_emoji_panel(image,boxes:list,state:dict) -> None:
    """Observe native emoji labels plus the public footer heart, without acting."""
    from wechat_auto.actions.semantics import PageId
    from wechat_auto.primitives.vision import normalize_text

    if state.get('page')!='unknown' or state.get('geometry',{}).get('composer_candidates'):
        return
    labels={normalize_text(b['text']) for b in boxes if b.get('score',0)>=.65}
    try:
        heart=find_emoji_favorites_control(image)
    except NavigationControlError:
        return
    favorites_selected=emoji_favorites_selected(image,heart)
    if not {'最近使用','所有表情'}<=labels and not favorites_selected:
        return
    state.setdefault('panels',[]).append({'key':'emoji_panel','page_id':int(PageId.EMOJI_PANEL),
                                        'layer':'panel','parent':'chat','state':'candidate',
                                        'verification':'native_emoji_labels_and_public_footer_heart',
                                        'action_authorized':False,'favorites_control':heart,
                                        'favorites_selected':favorites_selected})


def emoji_favorites_selected(image,heart:dict) -> bool:
    """Require a contrasting current tab backplate surrounding the heart."""
    import cv2
    import numpy as np

    gray=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
    contours,_=cv2.findContours(cv2.Canny(gray,8,25),cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if (not heart['w']*1.4<w<heart['w']*3 or not heart['h']*1.4<h<heart['h']*3
                or abs(x+w/2-heart['x'])>heart['w']*.25
                or abs(y+h/2-heart['y'])>heart['h']*.25
                or cv2.contourArea(contour)/(w*h)<.8):
            continue
        inside=gray[y+2:y+h-2,x+2:x+w-2]
        outside=gray[max(0,y-8):y-2,x:x+w]
        if outside.size and abs(float(np.median(inside))-float(np.median(outside)))>=8:
            return True
    return False


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


def observe_empty_chat(image, state: dict) -> None:
    """Require the selected Chats glyph AND the public empty-state logo."""
    import cv2
    import numpy as np

    from wechat_auto.actions.semantics import PageId
    from wechat_auto.primitives.empty_chat_logo import EMPTY_CHAT_LOGO

    if (state.get('page') != 'unknown' or state.get('composer', {}).get('geometry_candidates')
            or any(state.get(k) for k in ('overlays', 'panels', 'content_windows'))):
        return
    try:
        control = find_navigation_control(image, 'open_chats')
    except NavigationControlError:
        return
    rgb = np.asarray(image.convert('RGB')).astype(float)
    x, y, w, h = (control[k] for k in ('x', 'y', 'w', 'h'))
    patch = rgb[round(y-h/2):round(y+h/2), round(x-w/2):round(x+w/2)]
    green = ((patch[:, :, 1] > 100) & (patch[:, :, 1] > patch[:, :, 0]*1.5)
             & (patch[:, :, 1] > patch[:, :, 2]*1.2))
    if green.mean() < .15:
        return
    split = state.get('region_bounds', {}).get('conversation_header', [.25])[0]
    gray = rgb[:, round(image.width*split):].mean(axis=2)
    mask = np.uint8(np.abs(gray-np.median(gray)) >= 12)
    template = np.array([[int(v) for v in row] for row in EMPTY_CHAT_LOGO], dtype='uint8')
    hits = []
    for scale in np.linspace(.6, 1.8, 25):
        tw, th = round(template.shape[1]*scale), round(template.shape[0]*scale)
        if tw >= mask.shape[1] or th >= mask.shape[0]:
            continue
        glyph = cv2.resize(template, (tw, th), interpolation=cv2.INTER_NEAREST_EXACT)
        scores = cv2.matchTemplate(mask, glyph, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(scores >= .92)
        for px, py in zip(xs, ys, strict=True):
            hits.append((px+tw/2, py+th/2, tw, th))
    unique = []
    for hit in hits:
        if not any(abs(hit[0]-p[0]) < max(hit[2],p[2])*.6
                   and abs(hit[1]-p[1]) < max(hit[3],p[3])*.6 for p in unique):
            unique.append(hit)
    if len(unique) == 1:
        state.update(page='main_without_selected_chat', page_id=int(PageId.MAIN_EMPTY),
                     selected_navigation={'page': 'chat',
                                          'verification': 'selected_chat_glyph_and_empty_logo',
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
