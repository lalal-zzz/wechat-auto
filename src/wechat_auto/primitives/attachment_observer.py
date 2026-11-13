"""Read-only candidate location for attachment cards inside the current composer."""
import re


def text_outside_card(boxes: list[dict], card: list[int]) -> str:
    from wechat_auto.primitives.vision import normalize_text

    x, y, w, h = card
    return normalize_text(''.join(b['text'] for b in sorted(boxes, key=lambda b: (b['y'], b['x']))
                                 if not (x <= b['x']+b['w']/2 <= x+w
                                         and y <= b['y']+b['h']/2 <= y+h)))


def has_card_sized_rectangle(image, composer: dict, min_height: float) -> bool:
    """Conservative post-cancel check: any remaining card-sized rectangle blocks success."""
    import cv2
    import numpy as np

    edges = cv2.Canny(np.asarray(image.convert('RGB')), 10, 40)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if (x >= composer['x'] and y >= composer['y']
                and x+w <= composer['x']+composer['w'] and y+h <= composer['y']+composer['h']
                and min_height <= h <= composer['h']*.8 and w >= 2*h
                and abs(cv2.contourArea(contour))/(w*h) >= .8):
            return True
    return False


def file_size_label_matches(text: str, size: int) -> bool:
    """Match a displayed size for candidate location, never exact file identity.

    Scaled labels may use decimal/binary units and rounding/truncation. The
    candidate range deliberately accepts either; native Copy must still prove
    the exact byte count and SHA256 before granting an identity lease.
    """
    from decimal import Decimal

    from wechat_auto.primitives.vision import normalize_text

    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return False
    label = normalize_text(text).casefold()
    match = re.fullmatch(r'(\d{1,18})(?:\.(\d{1,3}))?(b|[kmgt](?:i?b)?)', label)
    if not match:
        return False
    whole, fraction, unit = match.groups()
    if unit == 'b':
        return fraction is None and int(whole) == size
    value = Decimal(whole + ('.' + fraction if fraction else ''))
    if value < 1:
        return False
    quantum = Decimal(1).scaleb(-len(fraction or ''))
    power = 'kmgt'.index(unit[0]) + 1
    for base in ((1024,) if 'i' in unit else (1000, 1024)):
        actual = Decimal(size) / (base ** power)
        if value - quantum/2 <= actual < value + quantum:
            return True
    return False


def find_file_card(image, boxes: list[dict], composer: dict, name: str, size: int) -> dict:
    """Locate one name/size/card candidate; display labels never prove identity."""
    import cv2
    import numpy as np

    from wechat_auto.primitives.vision import normalize_text

    expected = normalize_text(name)

    def name_matches(text):
        text = normalize_text(text).replace('…', '...')
        if text == expected:
            return True
        parts = re.fullmatch(r'(.{3,}?)\.{3}(.{4,})', text)
        return bool(parts and expected.startswith(parts[1]) and expected.endswith(parts[2]))

    def center_inside(box, rect):
        x, y, w, h = rect
        return x <= box['x']+box['w']/2 <= x+w and y <= box['y']+box['h']/2 <= y+h

    region = tuple(composer[k] for k in ('x', 'y', 'w', 'h'))
    names = [b for b in boxes if center_inside(b, region) and name_matches(b['text'])]
    sizes = [b for b in boxes if center_inside(b, region)
             and file_size_label_matches(b['text'], size)]
    edges = cv2.Canny(np.asarray(image.convert('RGB')), 10, 40)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if (x < region[0] or y < region[1] or x+w > region[0]+region[2]
                or y+h > region[1]+region[3] or w < 2*h or h > region[3]*.8
                or abs(cv2.contourArea(contour))/(w*h) < .8):
            continue
        found_names = [b for b in names if center_inside(b, (x, y, w, h))]
        found_sizes = [b for b in sizes if center_inside(b, (x, y, w, h))]
        if len(found_names) != 1 or len(found_sizes) != 1:
            continue
        label, byte_label = found_names[0], found_sizes[0]
        if (byte_label['y'] <= label['y'] or h < label['h']*1.5
                or w < label['w']*1.1):
            continue
        # A selected card has two outlines three pixels apart. Collapse
        # only nearby outlines around the very same OCR name box.
        if not any(c['label'] is label
                   and abs(x-c['box'][0]) < 4 and abs(y-c['box'][1]) < 4
                   and abs((x+w)-(c['box'][0]+c['box'][2])) <= 6
                   and abs((y+h)-(c['box'][1]+c['box'][3])) <= 6 for c in candidates):
            candidates.append({'box': [x, y, w, h], 'label': label,
                               'full_name_visible': normalize_text(label['text']) == expected,
                               'size_display_approximate': normalize_text(byte_label['text']).casefold() != f'{size}b'})
    if len(candidates) != 1:
        raise RuntimeError('File card candidate absent or ambiguous')
    result = candidates[0]
    label = result.pop('label')
    result['window_fraction'] = [(label['x']+label['w']/2)/image.width,
                                 (label['y']+label['h']/2)/image.height]
    result['identity_verified'] = False
    return result
