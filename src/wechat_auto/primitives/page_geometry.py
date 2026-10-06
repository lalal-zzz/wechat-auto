"""Theme-independent geometric observations from a single window image."""
from __future__ import annotations


def observe_geometry(image) -> dict:
    """Find long separators and candidate composer frames using local contrast.

    These are geometric candidates, not semantic controls. They never authorize
    actions. Works on both dark and light images without hard-coded RGB colors.
    """
    import cv2
    import numpy as np

    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    if min(height, width) < 100:
        return {"theme": "unknown", "vertical_separators": [], "composer_candidates": [],
                "right_panel_candidate": None, "method": "local_contrast_geometry"}
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    luminance = float(np.median(gray[int(height * .15):int(height * .9),
                                    int(width * .3):int(width * .95)]))
    theme = "dark" if luminance < 90 else "light" if luminance > 165 else "mixed"
    # Long, low-contrast panel boundaries often disappear under standard Canny.
    # Difference coverage detects them without relying on a specific theme.
    differences = np.abs(np.diff(gray.astype(np.int16), axis=1))
    strip = differences[int(height * .15):int(height * .7)]
    # Dark album dividers can have only four levels of luminance contrast
    # after the cover image scrolls away. Still require a long continuous
    # edge, rather than treating text or a short photo border as a divider.
    coverage = (strip >= 4).mean(axis=0)
    indices = np.flatnonzero(coverage >= .70)
    separators = []
    for x in indices:
        if not .04 * width < x < .95 * width:
            continue
        if separators and x - separators[-1]["x"] < max(4, width * .01):
            continue
        separators.append({"x": int(x), "fraction": round(float(x / width), 4),
                           "coverage": round(float(coverage[x]), 3)})
    # Contrast-normalized contours recover empty composer borders in either theme.
    enhanced = cv2.createCLAHE(clipLimit=2, tileGridSize=(8, 8)).apply(gray)
    edges = cv2.Canny(enhanced, 15, 60)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    search_fields = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if (.04 * width < x < .15 * width and .03 * height < y < .10 * height
                and .08 * width < w < .30 * width and .025 * height < h < .055 * height
                and abs(cv2.contourArea(contour)) / (w * h) > .8
                and not any(abs(x - f["x"]) < 5 and abs(y - f["y"]) < 5 for f in search_fields)):
            search_fields.append({"x": x, "y": y, "w": w, "h": h})
        if not (x >= width * .20 and y >= height * .55 and
                w >= width * .30 and h >= height * .12 and y + h >= height * .90):
            continue
        area_ratio = abs(cv2.contourArea(contour)) / (w * h)
        if area_ratio < .80:
            continue
        if any(abs(x - c["x"]) < 5 and abs(y - c["y"]) < 5 for c in candidates):
            continue
        candidates.append({"x": x, "y": y, "w": w, "h": h,
                           "rectangularity": round(float(area_ratio), 3),
                           "window_fraction": [x / width, y / height, w / width, h / height]})
    candidates.sort(key=lambda c: c["w"] * c["h"], reverse=True)
    # Unfocused gray search fields have much lower contrast than the focused
    # green outline. Restrict the sensitive edge pass to the top-left header.
    search_edges = cv2.Canny(gray[:int(height * .14), :int(width * .45)], 8, 25)
    search_edges = cv2.morphologyEx(search_edges, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8))
    search_contours, _ = cv2.findContours(search_edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in search_contours:
        x, y, w, h = cv2.boundingRect(contour)
        if (.04 * width < x < .15 * width and .03 * height < y < .10 * height
                and .08 * width < w < .30 * width and .025 * height < h < .055 * height
                and abs(cv2.contourArea(contour)) / (w * h) > .8
                and not any(abs(x - f["x"]) < 5 and abs(y - f["y"]) < 5 for f in search_fields)):
            search_fields.append({"x": x, "y": y, "w": w, "h": h})
    right_splits = [s for s in separators if .50 <= s["fraction"] <= .88]
    right_panel = right_splits[-1] if right_splits else None
    if candidates:
        # A webpage card can form another long vertical edge inside the pane.
        # The chat composer ends just before the actual panel divider; use
        # that independent frame to disambiguate instead of the last line.
        composer_end = candidates[0]['x'] + candidates[0]['w']
        adjacent = [s for s in right_splits if 0 <= s['x'] - composer_end <= max(32, width * .025)]
        if len(adjacent) == 1:
            right_panel = {**adjacent[0], 'corroborated_by': 'composer_right_edge'}
    # Weixin's selected list rows use the accent color in either theme.
    # These rectangles supply structural corroboration, not standalone pages.
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    accent = cv2.inRange(hsv, np.array([35, 100, 90]), np.array([90, 255, 255]))
    row_contours, _ = cv2.findContours(accent, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    selected_rows = []
    for contour in row_contours:
        x, y, w, h = cv2.boundingRect(contour)
        if (.04 * width < x < .15 * width and .12 * width < w < .35 * width
                and .03 * height < h < .20 * height
                and cv2.contourArea(contour) / (w * h) > .7):
            selected_rows.append({"x": x, "y": y, "w": w, "h": h})
    return {"theme": theme, "median_luminance": round(luminance, 2),
            "selected_list_rows": selected_rows,
            "search_field_candidates": search_fields,
            "vertical_separators": separators, "composer_candidates": candidates,
            "right_panel_candidate": right_panel, "method": "local_contrast_geometry"}
