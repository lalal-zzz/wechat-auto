"""Ephemeral, single-use screenshot review plans. This module never executes input."""
from __future__ import annotations

import math
import time
from pathlib import Path
from uuid import uuid4


class VisualReviewStore:
    def __init__(self, directory: Path = Path('data/ui_audit/visual_review')):
        self.directory = directory
        self.requests: dict[str, dict] = {}

    def prepare(self, operation: str, metadata: dict, image, *, expected_alias: str | None = None) -> dict:
        rect = metadata['rect']
        if image.size != (rect[2]-rect[0], rect[3]-rect[1]):
            raise RuntimeError('Review frame geometry does not match its window')
        token = 'vr' + uuid4().hex[:16]
        self.directory.mkdir(parents=True, exist_ok=True)
        path = (self.directory / (token + '.png')).resolve()
        image.save(path)
        if len(self.requests) >= 8:
            self.requests.pop(next(iter(self.requests)))
        self.requests[token] = {'operation': operation, 'metadata': metadata, 'image': image.copy(),
                                'created_at': time.monotonic(), 'expected_alias': expected_alias}
        return {'review_id': token, 'image_path': str(path), 'hwnd': metadata['hwnd'],
                'operation': operation, 'image_size': list(image.size), 'expires_in_seconds': 120,
                'input_dispatched': False, 'proposal_format': '[x,y,width,height] in screenshot pixels'}

    def consume(self, token: str, box: list[float], metadata: dict, image) -> dict:
        import numpy as np

        request = self.requests.pop(token, None)
        if request is None:
            raise RuntimeError('Visual review is unknown or already consumed')
        if time.monotonic() - request['created_at'] > 120:
            raise RuntimeError('Visual review expired; capture the current window again')
        previous = request['metadata']
        if any(metadata[key] != previous[key] for key in (
            'hwnd', 'pid', 'class', 'rect', 'client_rect', 'owner_hwnd', 'dpi', 'enabled', 'visible', 'minimized'
        )) or image.size != request['image'].size:
            raise RuntimeError('Visual review window changed; capture again')
        if len(box) != 4 or not all(math.isfinite(v) for v in box):
            raise ValueError('A finite pixel bounding box is required')
        x, y, w, h = map(round, box)
        width, height = image.size
        if min(w, h) < 5 or x < 0 or y < 0 or x+w > width or y+h > height:
            raise ValueError('Visual proposal is outside the current frame')
        old = np.asarray(request['image'].convert('RGB')).astype('int16')
        new = np.asarray(image.convert('RGB')).astype('int16')
        changed = np.max(np.abs(old-new), axis=2) > 12
        # Allow tiny caret/timestamp noise outside the target, but not a moved
        # target, new panel or changed layout. Blank proposals are not controls.
        if changed.mean() > .02 or changed[y:y+h, x:x+w].mean() > .02:
            raise RuntimeError('Visual review frame changed; capture again')
        if old[y:y+h, x:x+w].std() < 5:
            raise RuntimeError('Visual proposal contains no visible control')
        return {**request, 'box': [x, y, w, h], 'point': [(x+w/2)/width, (y+h/2)/height]}
