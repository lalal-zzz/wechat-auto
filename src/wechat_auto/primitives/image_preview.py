"""Read-only image-draft candidate matching; native Copy must prove identity."""
from pathlib import Path


def find_image_preview(image, composer: dict, path: str | Path) -> dict:
    import cv2
    import numpy as np
    from PIL import Image

    with Image.open(path) as source:
        source = np.asarray(source.convert('RGB'))
    if float(source.std(axis=(0, 1)).mean()) < 8:
        raise RuntimeError('Image lacks a distinctive preview pattern')
    x, y, w, h = (int(composer[k]) for k in ('x', 'y', 'w', 'h'))
    pixels = np.asarray(image.convert('RGB'))[y:y+h, x:x+w]
    ratio = source.shape[0] / source.shape[1]
    maximum = min(512, w-2, int((h*.8)/ratio))
    if maximum < 24:
        raise RuntimeError('Image preview region too small')
    step = max(1, maximum//40)
    scores = {}
    matches = []
    def check(width):
        if width in scores or not 24 <= width <= maximum:
            return
        height = max(1, round(width*ratio))
        template = cv2.resize(source, (width, height), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(pixels, template, cv2.TM_CCOEFF_NORMED)
        scores[width] = float(result.max())
        ys, xs = np.where(result >= .96)
        if len(xs) > 100:
            raise RuntimeError('Image preview candidate ambiguous')
        for px, py in zip(xs, ys, strict=True):
            matches.append((float(result[py, px]), int(px), int(py), width, height))
    for width in range(24, maximum+1, step):
        check(width)
    for width in sorted(scores, key=scores.get, reverse=True)[:3]:
        for nearby in range(width-step, width+step+1):
            check(nearby)
    unique = []
    for score, px, py, width, height in sorted(matches, reverse=True):
        if not any(abs(px-u[1]) < max(width, u[3])*.1
                   and abs(py-u[2]) < max(height, u[4])*.1 for u in unique):
            unique.append((score, px, py, width, height))
    if len(unique) != 1:
        raise RuntimeError('Image preview candidate absent or ambiguous')
    score, px, py, width, height = unique[0]
    return {'box': [x+px, y+py, width, height], 'score': score,
            'window_fraction': [(x+px+width/2)/image.width, (y+py+height/2)/image.height],
            'identity_verified': False}
