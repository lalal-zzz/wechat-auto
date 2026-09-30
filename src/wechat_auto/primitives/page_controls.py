"""Traditional visual control observations; these functions never act."""
from __future__ import annotations


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
