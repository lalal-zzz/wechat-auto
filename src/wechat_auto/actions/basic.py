"""Single low-level action skill for Weixin 4.x.

Invariant: every UI mutation is delivered through the Weixin HWND route (the
top-level window or its unique visible MMUI render child). OCR is only an
observer: it verifies a result or supplies a replacement coordinate. It never
performs the click itself.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from wechat_auto.actions.base import BaseSkill
from wechat_auto.actions.contracts import ActionReceipt, StaleFrameError
from wechat_auto.exceptions import ChatNotFoundError
from wechat_auto.utils.clipboard import ClipboardHelper


class BasicSkill(BaseSkill):
    """All primitive WeChat UI actions, with confirmation for external acts."""

    name = "basic_action"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if getattr(self._config, "action_driver", "hwnd") != "hwnd":
            raise ValueError("BasicSkill requires action_driver='hwnd'")

    def _receipt(self, action: str, *, point: tuple[float, float] | None = None,
                 verified_by: str = "not_verified", **extra) -> dict:
        result = ActionReceipt(
            action=action, point=point, verified_by=verified_by,
        ).to_dict()
        result.update(extra)
        return result

    def _run(self, **params) -> Any:
        action = params.pop("action", "")
        handlers = {
            "open_chat": self.open_chat,
            "open_visible_chat_row": self.open_visible_chat_row,
            "open_navigation": self.open_navigation,
            "open_chat_by_avatar": self.open_chat_by_avatar,
            "open_contact_profile": self.open_contact_profile,
            "load_contact_moments": self.load_contact_moments,
            "execute_contact_action": self.execute_contact_action,
            "page_operation": self.page_operation,
            "inspect_windows": self.inspect_windows,
            "resolve_target_window": self.resolve_target_window,
            "navigate_page": self.navigate_page,
            "restore_main_window": self.restore_main_window,
            "ensure_contacts_section": self.ensure_contacts_section,
            "prepare_visual_review": self.prepare_visual_review,
            "apply_visual_review": self.apply_visual_review,
            "prepare_search": self.prepare_search,
            "open_search_content": self.open_search_content,
            "prepare_text": self.prepare_text,
            "send_text": self.send_text,
            "prepare_mention": self.prepare_mention,
            "send_mention": self.send_mention,
            "prepare_quote": self.prepare_quote,
            "send_quote": self.send_quote,
            "copy_message": self.copy_message,
            "prepare_profile_observation": self.prepare_profile_observation,
            "capture_visible_signature": self.capture_visible_signature,
            "capture_contact_profile": self.capture_contact_profile,
            "click": self.click,
            "right_click": self.right_click,
            "scroll": self.scroll,
            "press_key": self.press_key,
            "prepare_file": self.prepare_file,
            "send_file": self.send_file,
            "prepare_image": self.prepare_image,
            "send_image": self.send_image,
            "open_emoji": self.open_emoji,
            "send_sticker": self.send_sticker,
            "send_sticker_by_id": self.send_sticker_by_id,
            "open_moments": self.open_moments,
            "like_moment": self.like_moment,
            "comment_moment": self.comment_moment,
        }
        if action not in handlers:
            raise ValueError(f"Unknown basic action: {action}")
        result = handlers[action](**params)
        if isinstance(result, dict) and "receipt_id" not in result:
            receipt = self._receipt(
                str(result.get("action") or action),
                verified_by=str(result.get("verified_by") or "not_verified"),
            )
            receipt.update(result)
            return receipt
        return result

    def click(self, x: float, y: float) -> dict:
        self.keyboard_only.click_window_fraction(x, y)
        return self._receipt("click", point=(x, y))

    def observe_windows(self, *, include_ocr: bool = True) -> list[dict]:
        """Observe every visible client-process top-level window separately."""
        from wechat_auto.primitives.vision import VisionAutomation

        return [{**window, "observation": VisionAutomation(
            self._app.for_window(window["hwnd"]), self._config
        ).observe_page(include_ocr=include_ocr)} for window in self._app.list_windows()]

    def inspect_windows(self, *, include_ocr: bool = True) -> list[dict]:
        """Compact window roles, layered pages and guarded operation inventory."""
        from wechat_auto.actions.pages import OPERATIONS
        from wechat_auto.primitives.window_observer import WindowObserver

        windows = WindowObserver(self._app, self._config).inspect(include_ocr=include_ocr)
        for window in windows:
            surfaces = window.get('surfaces', [])
            keys = {s['page'] for s in surfaces}
            overlays = {s['page'] for s in surfaces if s['layer'] == 'overlay'}
            window['operations'] = [
                {'name': op.name, 'locator': op.method,
                 'locator_implemented': op.method != 'visual_control' or op.name in {
                     'open_contacts', 'open_chats', 'open_discover', 'open_main_menu'},
                 'preconditions_observed': window.get('enabled', True) and
                     window.get('status') == 'recognized' and (not overlays or bool(overlays & set(op.sources))),
                 'main_close_forbidden': op.method == 'wm_close' and window['is_main']}
                for op in OPERATIONS if keys & set(op.sources)]
        return windows

    def resolve_target_window(self, page: str, *, presentation: str | None = None,
                              hwnd: int | None = None) -> dict:
        """Read-only unique selection; it does not certify person/account identity."""
        from wechat_auto.primitives.window_observer import select_surface

        return select_surface(self.inspect_windows(), page, presentation=presentation, hwnd=hwnd)

    def prepare_visual_review(self, operation: str, *, hwnd: int | None = None,
                              expected_alias: str | None = None) -> dict:
        """Save a fresh private frame for an Agent; do not execute its proposal yet."""
        from wechat_auto.actions.visual_review import VisualReviewStore
        from wechat_auto.primitives.vision import VisionAutomation

        allowed = {'open_contacts', 'open_chats', 'open_discover', 'open_main_menu',
                   'open_contact_more', 'open_contact_moments', 'open_settings',
                   'expand_contacts', 'select_contact_row'}
        if operation not in allowed:
            raise ValueError('Only registered read-only review operations are supported')
        if operation in {'select_contact_row', 'open_contact_moments'} and not expected_alias:
            raise ValueError('An exact archived alias is required for personal visual navigation')
        target = self._app.for_window(hwnd) if hwnd is not None else self._app
        metadata = self._app.describe_window(target.handle)
        if not metadata['visible'] or not metadata['enabled'] or metadata['minimized']:
            raise RuntimeError('Review target window is not available')
        observer = self.vision if target.handle == self._app.handle else VisionAutomation(target, self._config)
        image = observer.capture()
        if image is None:
            raise RuntimeError('Review capture unavailable')
        after = self._app.describe_window(target.handle)
        if any(metadata[k] != after[k] for k in ('pid', 'class', 'rect', 'client_rect', 'owner_hwnd', 'dpi')):
            raise RuntimeError('Review window changed while capturing')
        if not hasattr(self, '_visual_review_store'):
            self._visual_review_store = VisualReviewStore()
        return self._visual_review_store.prepare(operation, metadata, image, expected_alias=expected_alias)

    def apply_visual_review(self, review_id: str, box: list[float], source_page: str) -> dict:
        """One guarded read-only proposal, followed by verification; never sends."""
        from wechat_auto.actions.pages import MAIN_PAGES, OPERATIONS, page_keys
        from wechat_auto.primitives.contact_section import observe_contact_section
        from wechat_auto.primitives.page_geometry import observe_geometry
        from wechat_auto.primitives.vision import VisionAutomation

        store = getattr(self, '_visual_review_store', None)
        pending = store.requests.get(review_id) if store else None
        if pending is None:
            raise RuntimeError('Visual review is unknown or already consumed')
        before_windows = self.inspect_windows()
        if any(w.get('blocking') and w['hwnd'] != pending['metadata']['hwnd']
               or not w['is_main'] and w.get('status') != 'recognized'
               for w in before_windows):
            raise RuntimeError('Another auxiliary window must be handled before visual input')
        old_handles = {w['hwnd'] for w in before_windows}
        target = self._app.for_window(pending['metadata']['hwnd'])
        observer = self.vision if target.handle == self._app.handle else VisionAutomation(target, self._config)
        image = observer.capture()
        if image is None:
            raise RuntimeError('Review capture unavailable')
        plan = store.consume(review_id, box, self._app.describe_window(target.handle), image)
        operation = plan['operation']
        observed = observer.observe_page()
        if not observed.get('ok'):
            raise RuntimeError('Current page observation unavailable')
        state = observed['state']
        keys = page_keys(state)
        if state.get('overlays') and source_page not in {s['key'] for s in state['overlays']}:
            raise RuntimeError('Visual proposal cannot click through a blocking overlay')
        # Known destructive labels can never be reinterpreted as navigation.
        px, py, pw, ph = plan['box']
        blocked = {'发送', '发表', '删除', '删除联系人', '退出登录', '拉黑', '确定', '确认', '点赞'}
        if any(re.sub(r'\s+', '', b.get('text', '')) in blocked and
               px <= b['x']+b['w']/2 <= px+pw and py <= b['y']+b['h']/2 <= py+ph
               for b in observed['boxes']):
            raise PermissionError('Visual navigation proposal points to an external/mutating control')
        sidebar = {'open_contacts', 'open_chats', 'open_discover', 'open_main_menu'}
        if operation in sidebar:
            if not plan['metadata']['is_main'] or source_page not in MAIN_PAGES:
                raise RuntimeError('Sidebar review requires the main client page')
            if keys and not keys & set(MAIN_PAGES):
                raise RuntimeError('Current page is not a main navigation page')
            geometry = observe_geometry(image)
            edges = [s['x'] for s in geometry.get('vertical_separators', []) if 35 < s['x'] < image.width*.15]
            if not edges or px+pw > min(edges):
                raise RuntimeError('Sidebar proposal is outside the current measured sidebar')
        elif operation in {'expand_contacts', 'select_contact_row'}:
            section = observe_contact_section(image, observed['boxes'], state)
            if operation == 'expand_contacts':
                header = section.get('header')
                bounds = state.get('region_bounds', {}).get('conversation_list')
                if not header or not bounds:
                    raise RuntimeError('Exact Contacts heading is not verified')
                cx, cy = plan['point'][0]*image.width, plan['point'][1]*image.height
                if not bounds[0]*image.width <= cx <= header['x']+header['w'] or not header['y']-header['h']*.25 <= cy <= header['y']+header['h']*1.25:
                    raise RuntimeError('Proposal is not on the personal Contacts heading')
                if section.get('state') == 'expanded':
                    return self._receipt('apply_visual_review', success=True, operation=operation,
                                         input_dispatched=False, verified_by='contacts_already_expanded')
            else:
                if not section.get('ok') or section['state'] != 'expanded':
                    raise RuntimeError('Personal Contacts member scope is not verified')
                bounds = section['member_bounds']
                if not bounds[0] <= plan['point'][0] <= bounds[2] or not bounds[1] <= plan['point'][1] <= bounds[3]:
                    raise RuntimeError('Proposal is outside personal Contacts; requests are not contacts')
        else:
            spec = next(s for s in OPERATIONS if s.name == operation)
            if source_page not in keys or source_page not in spec.sources:
                raise RuntimeError('Review source page was not verified')
            if operation == 'open_contact_moments':
                self._verify_contact_alias(plan['expected_alias'], observer=observer)
        # Recheck the proposed patch and HWND after slow OCR, before input.
        metadata = self._app.describe_window(target.handle)
        if any(metadata[k] != plan['metadata'][k] for k in ('pid', 'class', 'rect', 'owner_hwnd', 'dpi')):
            raise StaleFrameError('Review target changed before dispatch')
        fresh = observer.capture()
        if fresh is None:
            raise RuntimeError('Review final capture unavailable')
        import numpy as np
        if fresh.size != image.size or np.max(np.abs(np.asarray(fresh.crop((px,py,px+pw,py+ph))).astype('int16') -
                                                    np.asarray(image.crop((px,py,px+pw,py+ph))).astype('int16')), axis=2).mean() > 4:
            raise StaleFrameError('Reviewed control changed before dispatch')
        skill = self if target.handle == self._app.handle else BasicSkill(target, self._config, self._session)
        if skill is not self:
            skill.keyboard_only.foreground_mode = 'never'
        skill.keyboard_only.click_window_fraction(*plan['point'])
        time.sleep(self._config.action_delay + .5)
        if operation == 'expand_contacts':
            post = self._observe_contact_section()['section']
            verified = post.get('ok') and post['state'] == 'expanded'
        elif operation == 'select_contact_row':
            profile = self.resolve_target_window('contact_profile')
            if not profile['ok']:
                verified = False
            else:
                profile_observer = VisionAutomation(self._app.for_window(profile['target']['hwnd']), self._config)
                self._verify_contact_alias(plan['expected_alias'], observer=profile_observer)
                verified = True
        else:
            spec = next(s for s in OPERATIONS if s.name == operation)
            windows = self.inspect_windows()
            verified = any(w['status'] == 'recognized' and
                           (w['hwnd'] == target.handle or w['hwnd'] not in old_handles) and
                           (operation not in sidebar or w['hwnd'] == target.handle) and
                           any(s['page'] in spec.targets and (operation not in sidebar or s['layer'] == 'base' or operation == 'open_main_menu')
                               for s in w['surfaces']) for w in windows)
        return self._receipt('apply_visual_review', success=bool(verified), operation=operation,
                             point=tuple(plan['point']), coordinate_source='agent_reviewed_current_frame',
                             verified_by='post_action_observation' if verified else 'postcondition_failed',
                             sent=False, automatic_retry=False)

    def navigate_page(self, page: str, *, max_steps: int = 6) -> dict:
        """Execute a bounded declared route with fresh window selection each step."""
        from wechat_auto.actions.pages import OPERATIONS, plan_page_route
        from wechat_auto.primitives.window_observer import KNOWN_PAGES, select_surface

        if page not in KNOWN_PAGES or not 1 <= max_steps <= 12:
            raise ValueError('Known page and 1..12 route steps are required')
        steps = []
        def stopped(code):
            return self._receipt('navigate_page', success=False, target_page=page,
                                 stop_reason=code, steps=steps, sent=False, identity_verified=False)

        for index in range(max_steps + 1):
            windows = self.inspect_windows()
            if any(w.get('status') in {'stale', 'unavailable', 'observation_failed'} for w in windows):
                return stopped('window_observation_unavailable')
            if any(not w['is_main'] and w.get('status') == 'unknown' for w in windows):
                return stopped('unrecognized_auxiliary_window')
            selected = select_surface(windows, page)
            blockers = [w for w in windows if w.get('blocking')]
            if selected['ok']:
                target = selected['target']
                if any(w['hwnd'] != target['hwnd'] or target['layer'] != 'overlay'
                       or {s['page'] for s in w['surfaces'] if s['layer'] == 'overlay'} != {page}
                       for w in blockers):
                    return stopped('blocking_window_requires_handling')
                return self._receipt('navigate_page', success=True, target=target, steps=steps,
                                     sent=False, identity_verified=False, verified_by='unique_observed_surface')
            if selected['error'] != 'target_page_not_found':
                return stopped(selected['error'])
            if index == max_steps:
                return stopped('route_step_budget')
            if len(blockers) > 1:
                return stopped('ambiguous_blocking_window')
            sources = blockers or [w for w in windows if w['is_main']]
            if len(sources) != 1 or not sources[0].get('enabled', True):
                return stopped('source_window_unavailable')
            source = sources[0]
            keys = ({s['page'] for s in source['surfaces'] if s['layer'] == 'overlay'}
                    if blockers else {source.get('page', 'unknown')})
            if len(keys) != 1:
                return stopped('ambiguous_source_page')
            try:
                route = plan_page_route(next(iter(keys)), page)
            except (ValueError, RuntimeError):
                return stopped('route_unavailable')
            if not route:
                return stopped('route_unavailable')
            op = next(op for op in OPERATIONS if op.name == route[0])
            if op.method == 'visual_control' and op.name not in {
                'open_contacts', 'open_chats', 'open_discover', 'open_main_menu'
            }:
                return stopped('operation_control_unimplemented')
            try:
                receipt = self.page_operation(op.name, hwnd=source['hwnd'], expected_page=next(iter(keys)))
            except (RuntimeError, PermissionError):
                return stopped('navigation_precondition_or_control_failed')
            steps.append(receipt)
            if not receipt['success']:
                return stopped('navigation_postcondition_failed')
        return stopped('route_step_budget')

    def restore_main_window(self, *, max_steps: int = 6) -> dict:
        """Dismiss known menus/close known read-only auxiliary content, never drafts."""
        from wechat_auto.primitives.window_observer import EDITOR_PAGES, MENU_PAGES

        if not 1 <= max_steps <= 12:
            raise ValueError('Restore steps must be between 1 and 12')
        steps = []
        def result(success, reason):
            return self._receipt('restore_main_window', success=success, stop_reason=reason,
                                 steps=steps, sent=False)

        safe_close = {'settings', 'media_viewer', 'file_preview', 'moments_person',
                      'moments_detail', 'channels', 'mini_program', 'chat_history'}
        for index in range(max_steps + 1):
            windows = self.inspect_windows()
            if any(w.get('status') != 'recognized' for w in windows):
                return result(False, 'unrecognized_or_unavailable_window')
            if any({s['page'] for s in w['surfaces']} & EDITOR_PAGES for w in windows):
                return result(False, 'editor_requires_explicit_handling')
            auxiliary = [w for w in windows if not w['is_main']]
            main = [w for w in windows if w['is_main']]
            if len(main) != 1:
                return result(False, 'main_window_unavailable')
            source = auxiliary[0] if auxiliary else main[0]
            keys = {s['page'] for s in source['surfaces']}
            menus = keys & MENU_PAGES
            if len(menus) == 1 and source.get('blocking'):
                operation, expected = 'dismiss', next(iter(menus))
            elif auxiliary:
                candidates = keys & safe_close
                if len(candidates) != 1:
                    return result(False, 'auxiliary_requires_explicit_handling')
                operation, expected = 'close', next(iter(candidates))
            elif source.get('blocking'):
                return result(False, 'blocking_window_requires_handling')
            elif any(s['presentation'] == 'embedded_right_tab' for s in source['surfaces']):
                operation, expected = 'close_content_tab', None
            else:
                enabled = bool(main[0].get('enabled', True))
                return result(enabled, 'main_window_ready' if enabled else 'main_window_disabled')
            if index == max_steps:
                return result(False, 'restore_step_budget')
            try:
                receipt = self.page_operation(operation, hwnd=source['hwnd'], expected_page=expected)
            except (RuntimeError, PermissionError):
                return result(False, 'restore_precondition_or_control_failed')
            steps.append(receipt)
            if not receipt['success']:
                return result(False, 'restore_postcondition_failed')
        return result(False, 'restore_step_budget')

    def resize_window(self, width: int, height: int) -> dict:
        self._app.resize_window(width, height)
        time.sleep(self._config.action_delay + .5)
        left, top, right, bottom = self._app.get_window_rect()
        return self._receipt("resize_window", verified_by="window_rectangle",
                             requested_size=[width, height], actual_size=[right-left, bottom-top],
                             success=(right-left, bottom-top) == (width, height))

    def drag_divider(self, start: tuple[float, float], end: tuple[float, float]) -> dict:
        """Move only a separator corroborated in the current captured frame."""
        from wechat_auto.primitives.page_geometry import observe_geometry
        image = self.vision.capture()
        if image is None:
            raise RuntimeError("Divider capture unavailable")
        before = observe_geometry(image)
        px, py = start[0] * image.width, start[1] * image.height
        vertical = [s for s in before['vertical_separators']
                    if abs(s['x'] - px) <= 2 and .15 * image.height < py < .7 * image.height]
        horizontal = [c for c in before['composer_candidates']
                      if abs(c['y'] - py) <= 3 and c['x'] + 15 < px < c['x'] + c['w'] - 15]
        if len(vertical) + len(horizontal) != 1:
            raise RuntimeError("Drag start is not a unique current divider")
        self.keyboard_only.drag_window_fraction(start, end)
        after_image = self.vision.capture()
        after = observe_geometry(after_image) if after_image else {}
        if vertical:
            candidates = [s['x'] for s in after.get('vertical_separators', [])
                          if abs(s['x'] - end[0] * image.width) <= 6]
            original = vertical[0]['x']
        else:
            candidates = [c['y'] for c in after.get('composer_candidates', [])
                          if abs(c['y'] - end[1] * image.height) <= 6]
            original = horizontal[0]['y']
        verified = len(candidates) == 1 and abs(candidates[0] - original) >= 5
        return self._receipt("drag_divider", verified_by="divider_geometry" if verified else "postcondition_failed",
                             success=verified, dispatched=True, automatic_retry=False,
                             start=list(start), end=list(end))

    def prepare_search(self, query: str) -> dict:
        """Populate the main search field, verifying its focus without choosing a result."""
        from wechat_auto.primitives.page_controls import find_search_clear
        from wechat_auto.primitives.page_geometry import observe_geometry
        from wechat_auto.primitives.vision import normalize_text

        if not query.strip() or any(ord(c) < 32 for c in query):
            raise ValueError("Search query must be non-empty printable text")
        image = self.vision.capture()
        if image is None:
            raise RuntimeError("Search window capture unavailable")
        fields = observe_geometry(image).get("search_field_candidates", [])
        if len(fields) != 1:
            raise RuntimeError("Search field geometry is absent or ambiguous")
        field = fields[0]
        # Exclude the magnifier as well as the clear/microphone zone. OCR can
        # join the magnifier and placeholder into one text box ("Q 搜索").
        region = (field["x"] + int(field["w"] * .13), field["y"],
                  int(field["w"] * .75), field["h"])
        def field_text(boxes):
            # OCR can turn the microphone/clear icon into a letter. Their
            # rightmost control zone is outside the editable text span.
            return "".join(normalize_text(b.get("text", "")) for b in boxes
                           if field["x"] + field["w"] * .08 < b["x"] + b["w"] / 2
                           < field["x"] + field["w"] * .88)
        prior = self.vision.recognize_image(image.crop((region[0], region[1],
            region[0] + region[2], region[1] + region[3])), region=region, window_size=image.size)
        existing = field_text(prior)
        if not existing:
            raise RuntimeError("Search field text unavailable; typing stopped")
        driver = self.keyboard_only
        if existing and existing != "搜索":
            clear = find_search_clear(image, field)
            if len(clear) != 1:
                raise RuntimeError("Search clear control is absent or ambiguous")
            driver.click_window_fraction(clear[0][0] / image.width, clear[0][1] / image.height)
            time.sleep(self._config.action_delay)
            empty = field_text(self.vision.ocr(region))
            if empty != "搜索":
                raise RuntimeError("Search field did not clear; typing stopped")
        driver.click_window_fraction((field["x"] + field["w"] * .4) / image.width,
                                     (field["y"] + field["h"] / 2) / image.height)
        with driver.foreground_lease():
            driver._type_text(query)
            time.sleep(self._config.action_delay + .5)
        observed = self.vision.ocr(region)
        joined = field_text(observed)
        if normalize_text(query) != joined:
            raise RuntimeError("Search field text was not verified; no result selected")
        return self._receipt("prepare_search", verified_by="search_field_ocr",
                             selection_required=True, sent=False)

    def open_search_content(self, query: str) -> dict:
        """Open the exact verified main-field query in the embedded network pane."""
        from wechat_auto.primitives.vision import VisionAutomation, normalize_text

        self.prepare_search(query)
        choices = []
        for window in self._app.list_windows():
            if window["is_main"] or "ToolSaveBits" not in window["class"]:
                continue
            target = self._app.for_window(window["hwnd"])
            result = VisionAutomation(target, self._config).observe_page()
            if not result.get("ok"):
                continue
            boxes = [b for b in result["boxes"] if b.get("score", 0) >= .65
                     and normalize_text(b.get("text", "")) == "搜索网络结果"]
            for heading in boxes:
                # This heading is inert. The first suggestion below it is the
                # clickable exact query, before expanded/similar suggestions.
                entries = [b for b in result["boxes"] if b.get("score", 0) >= .65
                           and normalize_text(b.get("text", "")) == normalize_text(query)
                           and heading["y"] + heading["h"] < b["y"]
                           < heading["y"] + heading["h"] * 5]
                if entries:
                    box = min(entries, key=lambda b: b["y"])
                    choices.append((target, self._box_center_fraction(box, tuple(result["state"]["size"]))))
        if len(choices) != 1:
            raise RuntimeError("Network search entry absent or ambiguous; no result selected")
        target, point = choices[0]
        skill = BasicSkill(target, self._config, self._session)
        skill.keyboard_only.foreground_mode = "never"
        skill.keyboard_only.click_window_fraction(*point)
        time.sleep(self._config.action_delay + .8)
        result = self.vision.observe_page()
        state = result.get("state", {})
        panel = state.get("right_panel", {})
        verified = result.get("ok") and panel.get("state") == "present" and "search" in panel.get("types", [])
        if verified:
            verified = any(normalize_text(query) in normalize_text(result["boxes"][t["evidence_box_index"]]["text"])
                           for t in panel.get("tabs", []))
        return self._receipt("open_search_content", verified_by="embedded_query_tab_ocr" if verified else "postcondition_failed",
                             success=bool(verified), sent=False, automatic_retry=False)

    def page_operation(self, operation: str, *, hwnd: int | None = None,
                       expected_page: str | None = None, max_attempts: int = 2) -> dict:
        """Recover only idempotent navigation, observing and locating anew each time.

        A failed send, toggle, close or mutation is never retried. Even sidebar
        navigation stops if an unexpected page appeared instead of its source.
        """
        if not 1 <= max_attempts <= 3:
            raise ValueError("Navigation attempts must be between 1 and 3")
        from wechat_auto.primitives.page_controls import NavigationControlError
        recoverable = operation in {"open_contacts", "open_chats", "open_discover"}
        attempts = []
        for _ in range(max_attempts if recoverable else 1):
            try:
                result = self._page_operation_once(operation, hwnd=hwnd, expected_page=expected_page)
            except (StaleFrameError, NavigationControlError) as exc:
                if not recoverable:
                    raise
                code = 'stale_frame' if isinstance(exc, StaleFrameError) else 'control_not_unique'
                result = self._receipt("page_operation", operation=operation, success=False,
                                       verified_by=code, input_dispatched=False)
                attempts.append({"success": False, "error": code, "input_dispatched": False})
                continue
            attempts.append({key: result.get(key) for key in (
                "receipt_id", "point", "success", "source_page", "after_pages", "coordinate_source")})
            if result["success"]:
                break
            # Repeating a known navigation command is safe only while the
            # original page still exists and no new page/window was observed.
            after = set(result.get("after_pages", []))
            if not after or after != {result.get("source_page")}:
                break
        result["attempts"] = attempts
        result["automatic_retry"] = len(attempts) > 1
        result["recovery_policy"] = "fresh_observation_idempotent_navigation" if recoverable else "none"
        if not result['success'] and recoverable:
            try:
                result['visual_review'] = self.prepare_visual_review(operation, hwnd=hwnd)
            except (RuntimeError, PermissionError):
                result['visual_review_available'] = False
        return result

    def _page_operation_once(self, operation: str, *, hwnd: int | None = None,
                             expected_page: str | None = None) -> dict:
        """Execute one registered navigation transition, verifying both ends.

        Mutation operations are deliberately absent: they retain their dedicated
        confirmation APIs. Unknown pages/points and competing controls stop here.
        """
        from wechat_auto.actions.pages import page_keys, resolve_operation
        from wechat_auto.primitives.vision import VisionAutomation

        target = self._app.for_window(hwnd) if hwnd is not None else self._app
        observer = self.vision if target.handle == self._app.handle else VisionAutomation(target, self._config)
        before = observer.observe_page()
        if not before.get("ok"):
            raise RuntimeError("Page observation unavailable; action stopped")
        if expected_page and expected_page not in page_keys(before["state"]):
            raise RuntimeError("Expected page does not match current window")
        spec, source = resolve_operation(operation, before["state"])
        if operation == "close_content_tab":
            panel = before["state"]["right_panel"]
            if panel["state"] != "present" or not panel.get("embedded") or len(panel.get("tabs", [])) != 1:
                raise RuntimeError("Embedded content tab is absent or ambiguous")
            embedded = {p["key"] for p in before["state"].get("panels", [])
                        if p.get("presentation") == "embedded_right_tab" and p["key"] in spec.sources}
            if len(embedded) != 1:
                raise RuntimeError("Embedded content page is absent or ambiguous")
            source = next(iter(embedded))
        windows_before = self._app.list_windows()
        # The main PrintWindow frame does not contain independent Qt popups.
        if target.handle == self._app.handle:
            for window in windows_before:
                if not window["is_main"] and "ToolSaveBits" in window["class"]:
                    raise RuntimeError("An auxiliary popup must be handled before main navigation")
        if spec.method == "wm_close" and target.handle == self._app.handle:
            raise PermissionError("Use navigation to leave an embedded page; main client cannot be closed")
        skill = self if target.handle == self._app.handle else BasicSkill(
            target, self._config, self._session)
        # Popup activation dismisses Qt menus; preserve their current focus.
        driver = skill.keyboard_only
        old_mode = driver.foreground_mode
        if target.handle != self._app.handle:
            driver.foreground_mode = "never"
        elif operation == "open_main_menu":
            # Returning focus to another application immediately dismisses
            # this menu. Keep the client foreground until it is handled.
            driver.foreground_mode = "leave"
        point = None
        used_layout = "observed_frame"
        try:
            if spec.method in {"ocr", "ocr_cancel"}:
                boxes = [b for b in before["boxes"] if b.get("score", 0) >= .65
                         and re.sub(r"\s+", "", b.get("text", "")) in spec.anchors]
                # Discover labels must be in the navigation list, not body text.
                if source in {"discover", "moments_feed", "channels", "web_search", "mini_program_list"}:
                    bounds = before["state"]["region_bounds"]["conversation_list"]
                    width, _height = before["state"]["size"]
                    boxes = [b for b in boxes if bounds[0] <= (b["x"] + b["w"] / 2) / width <= bounds[2]]
                if len(boxes) != 1:
                    raise RuntimeError("Page control absent or ambiguous; action stopped")
                point = self._box_center_fraction(boxes[0], tuple(before["state"]["size"]))
                driver.click_window_fraction(*point)
            elif spec.method == "visual_control":
                from wechat_auto.primitives.page_controls import find_navigation_control
                image = observer.capture()
                if image is None:
                    raise RuntimeError('Control capture unavailable; action stopped')
                if tuple(image.size) != tuple(before['state']['size']):
                    raise StaleFrameError('Window changed during control observation; reobserve')
                control = find_navigation_control(image, operation)
                point = tuple(control['window_fraction'])
                used_layout = control['method']
                metadata = target.window_metadata()
                if tuple(metadata[k] for k in ('width', 'height')) != image.size:
                    raise StaleFrameError('Window resized before click; reobserve')
                driver.click_window_fraction(*point)
            elif spec.method == "tab_close":
                candidate = before["state"]["right_panel"]["tabs"][0].get("close_candidate")
                if not candidate:
                    raise RuntimeError("Tab close glyph is absent or ambiguous")
                point = tuple(candidate["window_fraction"])
                driver.click_content_fraction(*point)
            elif spec.method == "escape":
                driver.press_key("escape")
            elif spec.method == "wm_close":
                driver.close_window()
            else:
                raise RuntimeError("Page operation is not implemented")
            time.sleep(self._config.action_delay + .5)
        finally:
            driver.foreground_mode = old_mode
        windows_after = self._app.list_windows()
        visible = {w["hwnd"] for w in windows_after}
        if spec.method in {"ocr_cancel", "escape", "wm_close"}:
            verified = target.handle not in visible
            after_keys = []
            if not verified:
                after = observer.observe_page()
                after_keys = sorted(page_keys(after.get("state", {})))
                verified = bool(after.get("ok") and source not in after_keys)
        else:
            verified = False
            after_keys = []
            # Check main target plus newly created auxiliary windows. Existing
            # unrelated windows must not satisfy this operation's postcondition.
            old_handles = {w["hwnd"] for w in windows_before}
            for window in windows_after:
                if window["hwnd"] != target.handle and window["hwnd"] in old_handles:
                    continue
                post = VisionAutomation(self._app.for_window(window["hwnd"]), self._config).observe_page()
                keys = page_keys(post.get("state", {}))
                after_keys.extend(sorted(keys))
                target_keys = ({post.get('state', {}).get('page')} if operation in {
                    'open_contacts', 'open_chats', 'open_discover'} else keys)
                same_navigation_window = operation not in {'open_contacts', 'open_chats', 'open_discover'} or window['hwnd'] == target.handle
                if (post.get("ok") and same_navigation_window and target_keys & set(spec.targets)
                        and (not spec.require_source_exit or source not in keys)):
                    verified = True
        return self._receipt("page_operation", point=point,
                             verified_by="post_action_page_observation" if verified else "postcondition_failed",
                             operation=operation, source_page=source, after_pages=after_keys,
                             hwnd=target.handle, success=verified, automatic_retry=False,
                             coordinate_source=used_layout,
                             observer_version=before["state"].get("observer_version"),
                             catalog_version=before["state"].get("catalog_version"))

    def _semantic_click(self, page: int, element: int) -> tuple[float, float]:
        raise RuntimeError('Fixed semantic coordinates were removed; this control needs a current-frame detector')

    @staticmethod
    def _require_contact_confirmation(username: str, action: str, *, confirm: bool,
                                      confirmation_target: str) -> None:
        if not confirm or confirmation_target != username:
            raise PermissionError(
                f"{action} requires explicit confirmation bound to {username!r}"
            )

    def execute_contact_action(self, *, username: str, contact_action: str, ui_query: str,
                               visible_wechat_id: str = "", value: str = "",
                               confirm: bool = False,
                               confirmation_target: str = "") -> dict:
        """Execute a DB-resolved contact plan through observed semantic IDs.

        ``username`` is the stable target. ``ui_query`` and visible ID are only
        navigation/verification attributes and never become identity keys.
        """
        from wechat_auto.actions.semantics import PageId

        action = contact_action
        if action not in {"open_contact", "set_remark", "delete_contact"}:
            raise ValueError(f"Unsupported contact action: {action}")
        if not username or username.endswith("@chatroom"):
            raise ValueError("A non-group stable username is required")
        opened = self.open_contact_profile(
            ui_query, expected_wechat_id=visible_wechat_id or None,
        )
        if action == "open_contact":
            return self._receipt(
                action, verified_by=opened["verified_by"], username=username,
                semantic_target="21", sent=False,
            )

        self._require_contact_confirmation(
            username, action, confirm=confirm, confirmation_target=confirmation_target,
        )
        if action == "set_remark":
            if not value.strip():
                raise ValueError("set_remark requires a non-empty value")
            self._semantic_click(PageId.CONTACT_PROFILE, 3)
            self._semantic_click(PageId.CONTACT_REMARK, 1)
            self.keyboard_only._select_all_clear()
            self.keyboard_only._type_text(value)
            self._semantic_click(PageId.CONTACT_REMARK, 2)
            time.sleep(self._config.action_delay + .5)
            observed = "".join(str(box.get("text", "")) for box in self.vision.ocr())
            if value not in observed:
                raise RuntimeError("Remark UI action completed but post-action OCR did not verify it")
            return self._receipt(
                action, verified_by="profile_ocr_after_write", username=username,
                semantic_target="21.03", value=value, requires_database_resync=True,
            )

        self._semantic_click(PageId.CONTACT_PROFILE, 9)
        self._semantic_click(PageId.CONTACT_MORE, 3)
        self._semantic_click(PageId.CONFIRM_DIALOG, 2)
        return self._receipt(
            action, verified_by="confirmation_dialog_action", username=username,
            semantic_target="22.03", requires_database_resync=True,
        )

    def scroll(self, x: float, y: float, notches: int) -> dict:
        self.keyboard_only.wheel_window_fraction(x, y, notches)
        return self._receipt("scroll", point=(x, y), notches=notches)

    def right_click(self, x: float, y: float) -> dict:
        self.keyboard_only.right_click_window_fraction(x, y)
        return self._receipt("right_click", point=(x, y))

    def press_key(self, key: str) -> dict:
        self.keyboard_only.press_key(key)
        return self._receipt("press_key", key=key.lower())

    def open_navigation(self, page: str, *, attempts: int = 1) -> dict:
        if page not in {'chats', 'contacts'} or attempts != 1:
            raise ValueError('Use chats/contacts with one observed action; retries require fresh observation')
        result = self.page_operation('open_' + page)
        if not result['success']:
            raise RuntimeError('Current-frame navigation postcondition failed')
        return {**result, 'page': page, 'ocr_used': True, 'attempts': 1}

    def open_chat_by_avatar(self, avatar: bytes, *, verified_match: dict | None = None) -> dict:
        """Open a visible recent chat by a unique local avatar match, no OCR."""
        page = self.open_navigation("chats")
        match = verified_match or self.vision.find_avatar(avatar)
        if match is None:
            raise ChatNotFoundError("Unique visible avatar was not found")
        if (match.get("ocr_used") is not False or match.get("score", 0) < .72
                or match.get("margin", 0) < .025):
            raise ChatNotFoundError("Avatar match did not meet the verified threshold")
        # The avatar itself is drawn by MMUI and may not accept background
        # window messages; the text area in the same verified row does.
        self.keyboard_only.click_window_fraction_sync(match['x'], match["y"])
        time.sleep(self._config.action_delay + .5)
        return {"action": "open_chat_by_avatar", "transport": "hwnd",
                "navigation": page, "verified_by": "local_avatar_template",
                "ocr_used": False, "match_score": match["score"],
                "match_margin": match["margin"]}

    def open_visible_chat_row(self, row_index: int = 0) -> dict:
        raise RuntimeError('Fixed row-index coordinates were removed; resolve the target from the current frame')

    def _title_matches(self, text: str) -> bool:
        from wechat_auto.primitives.vision import normalize_text
        # The optional search/detail pane occupies the right third of wide
        # Weixin windows.  The conversation title starts near x=.24.
        boxes = self.vision.ocr(self.vision.region_of(.23, .04, .66, .12))
        joined = "".join(normalize_text(b.get("text", "")) for b in sorted(boxes, key=lambda b: (b["y"], b["x"])))
        alias = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9.]", "", normalize_text(text))
        return bool(alias and alias in joined)

    def verify_open_chat(self, contact: str) -> dict:
        """Observe whether *contact* is the currently open conversation."""
        if not getattr(self._config, "ocr_verify_enabled", False):
            return {"verified": False, "reason": "ocr_verification_disabled"}
        return {
            "verified": self._title_matches(contact),
            "reason": "title_ocr",
            "screenshot": self.vision.shot("basic", "open-chat-verify"),
        }

    def _choose_context_menu_item(self, keyword: str) -> tuple[float, float]:
        """Return one OCR-observed context-menu item as a window fraction.

        OCR remains an observer; the returned coordinate is clicked only via
        ``KeyboardOnlyDriver``.  Ambiguous menus are rejected rather than
        guessed.
        """
        if not getattr(self._config, "ocr_verify_enabled", False):
            raise RuntimeError("OCR verification must be enabled for menu text location")
        from wechat_auto.primitives.vision import match_boxes

        boxes = match_boxes(self.vision.ocr(), keyword, exact=True)
        if len(boxes) != 1:
            raise RuntimeError(f"Context-menu item {keyword!r} is ambiguous or absent ({len(boxes)})")
        box = boxes[0]
        width, height = self.vision.size()
        if width <= 0 or height <= 0:
            raise RuntimeError("Cannot determine WeChat window size for menu action")
        return ((box["x"] + box["w"] / 2) / width,
                (box["y"] + box["h"] / 2) / height)

    def open_chat(self, contact: str, *, target_kind: str = "contact",
                  scene: str | None = None, ui_query: str | None = None) -> dict:
        if not contact:
            raise ValueError("contact must not be empty")
        if target_kind not in {"contact", "group"}:
            raise ValueError("target_kind must be 'contact' or 'group'")
        scene = scene or {"contact": "contacts", "group": "groups"}[target_kind]
        if scene not in {"contacts", "groups", "main"}:
            raise ValueError("scene must be contacts, groups or main")
        actual_query = (ui_query or contact).strip()
        self._activate()
        if scene in {"contacts", "groups"}:
            self.open_navigation("contacts")
        self.prepare_search(actual_query)
        time.sleep(self._config.action_delay + .5)
        if not getattr(self._config, "ocr_verify_enabled", False):
            return {"action": "prepare_chat_search", "transport": "hwnd",
                    "opened": False, "selection_required": True,
                    "verified_by": "not_verified", "ocr_used": False}
        return self._open_chat_ocr_fallback(
            contact, target_kind=target_kind, ui_query=actual_query,
        )

    def _open_chat_ocr_fallback(self, contact: str, *, target_kind: str = "contact",
                                ui_query: str | None = None) -> dict:
        from wechat_auto.primitives.vision import normalize_text, parse_search_sections
        driver = self.keyboard_only
        alias = normalize_text(ui_query or contact)
        # Safety gate: if the query is absent from the actual search box, the
        # focused editor may be the current chat. Never press Enter or click a
        # result in that state.
        search_box = self.vision.region_of(.05, .035, .23, .11)
        search_text = "".join(normalize_text(b.get("text", ""))
                              for b in self.vision.ocr(search_box))
        if not alias or alias not in search_text:
            raise ChatNotFoundError("search_focus_not_verified")
        boxes = self.vision.ocr(self.vision.region_of(.05, .09, .42, .72))
        sections = parse_search_sections(boxes)
        candidates = [box for section in sections if section["section"] == target_kind
                      for box in section["items"]
                      if alias in normalize_text(box.get("text", ""))]
        if len(candidates) != 1:
            raise ChatNotFoundError(f"search_result_unavailable:{target_kind}:{len(candidates)}")
        box = candidates[0]
        width, height = self.vision.size()
        driver.click_window_fraction((box["x"] + box["w"] / 2) / width,
                                     (box["y"] + box["h"] / 2) / height)
        time.sleep(self._config.action_delay + .5)
        if not self._title_matches(contact):
            raise ChatNotFoundError("opened_title_not_verified")
        return {"action": "open_chat", "transport": "hwnd", "verified_by": "ocr",
                "opened": True, "ocr_used": True,
                "fallback": "verified_section_coordinate"}

    @staticmethod
    def _box_center_fraction(box: dict, size: tuple[int, int]) -> tuple[float, float]:
        width, height = size
        if width <= 0 or height <= 0:
            raise RuntimeError("Cannot determine WeChat window size")
        return ((box["x"] + box["w"] / 2) / width,
                (box["y"] + box["h"] / 2) / height)

    def _verify_contact_alias(self, expected_wechat_id: str | None, *, observer=None) -> None:
        from wechat_auto.primitives.vision import normalize_text
        profile_boxes = (observer or self.vision).ocr()
        profile_text = "".join(normalize_text(item.get("text", "")) for item in profile_boxes)
        if "微信号" not in profile_text:
            raise ChatNotFoundError("Contact profile was not verified")
        if expected_wechat_id:
            expected = normalize_text(expected_wechat_id)
            values = []
            for label in profile_boxes:
                text = normalize_text(label.get('text', ''))
                if not text.startswith('微信号'):
                    continue
                suffix = text[len('微信号'):].lstrip(':：')
                if suffix:
                    values.append(suffix)
                else:
                    values.extend(normalize_text(item.get('text', '')) for item in profile_boxes
                                  if item['x'] >= label['x'] + label['w']
                                  and abs(item['y'] + item['h']/2 - label['y'] - label['h']/2)
                                  <= max(item['h'], label['h']) * .5)
            if len(values) != 1 or values[0] != expected:
                raise ChatNotFoundError("Visible WeChat id did not match the archived contact")

    def load_contact_moments(self, contact: str, expected_alias: str, *, max_pages: int = 5,
                             wechat_id: str | None = None,
                             profiles_database: str = 'data/wechat_contact_profiles.sqlite3') -> dict:
        """Verified profile → personal album → bounded HWND scrolling.

        Stable local identity must be resolved by the caller. Only the profile's
        exact visible alias authenticates entry; a title/name alone never does.
        Screen stability means stalled, not a complete server download.
        """
        import hashlib

        from wechat_auto.actions.pages import page_keys
        from wechat_auto.primitives.vision import VisionAutomation
        if not expected_alias or not 1 <= max_pages <= 30:
            raise ValueError('Visible alias and bounded page count are required')
        for window in self.inspect_windows():
            if window.get('status') != 'recognized':
                raise RuntimeError('Window observation unavailable before personal album selection')
            if any(s['page'] == 'moments_person' for s in window['surfaces']):
                raise RuntimeError('Close the previous personal album before selecting another contact')
        navigation = self.page_operation('open_contacts')
        if not navigation['success']:
            raise RuntimeError('Contacts navigation failed')
        self.open_contact_profile(contact, expected_alias, navigate=False)
        profile = self.resolve_target_window('contact_profile')
        if not profile['ok']:
            raise RuntimeError('Contact profile window absent or ambiguous')
        profile_target = self._app.for_window(profile['target']['hwnd'])
        self._verify_contact_alias(expected_alias, observer=VisionAutomation(profile_target, self._config))
        profile_capture = (self.capture_contact_profile(wechat_id, expected_alias, profiles_database)
                           if wechat_id else None)
        opened = self.page_operation('open_contact_moments', hwnd=profile_target.handle,
                                     expected_page='contact_profile')
        if not opened['success']:
            raise RuntimeError('Personal Moments page not verified')
        album = self.resolve_target_window('moments_person')
        if not album['ok']:
            raise RuntimeError('Personal Moments window absent or ambiguous')
        target = self._app.for_window(album['target']['hwnd'])
        observer = VisionAutomation(target, self._config, shot_dir=self._session.screenshot_dir)
        skill = self if target.handle == self._app.handle else BasicSkill(target, self._config, self._session)
        previous, repeated, pages = '', 0, 0
        status, reason = 'partial', 'page_budget'
        for _ in range(max_pages):
            observation = observer.observe_page()
            if not observation.get('ok') or 'moments_person' not in page_keys(observation['state']):
                raise RuntimeError('Personal Moments page changed during loading')
            texts = [re.sub(r'\s+', '', b.get('text', '')) for b in observation['boxes']]
            if any('仅展示最近' in t or '不让你看' in t for t in texts):
                status, reason = 'restricted', 'visible_access_restriction'
                break
            fingerprint = hashlib.sha256('\n'.join(texts).encode()).hexdigest()
            repeated = repeated + 1 if fingerprint == previous else 0
            previous = fingerprint
            if repeated >= 2:
                status, reason = 'stalled', 'unchanged_visible_text'
                break
            # The personal album is the verified content window; never scroll
            # the main chat/list when album ownership is ambiguous.
            skill.scroll(.75, .7, 4)
            pages += 1
            time.sleep(max(1., self._config.scroll_delay))
        final = observer.observe_page()
        if not final.get('ok') or 'moments_person' not in page_keys(final['state']):
            raise RuntimeError('Personal Moments page changed after the final scroll')
        evidence = observer.shot('moments', 'personal-load-final')
        closed = False
        if target.handle != self._app.handle:
            closed = self.page_operation('close', hwnd=target.handle,
                                         expected_page='moments_person')['success']
        return self._receipt('load_contact_moments', success=True, sent=False,
                             coverage_status=status, stop_reason=reason, pages=pages,
                             evidence_ref=evidence or '', verified_by='exact_profile_alias_then_personal_page',
                             requires_navigation_restore=not closed,
                             album_hwnd=target.handle, album_presentation=album['target']['presentation'],
                             profile_capture=profile_capture,
                             server_history_complete=False, automatic_retry=False)

    def _open_and_verify_contact_box(self, box: dict, expected_wechat_id: str | None) -> dict:
        """Open one OCR-confirmed Contacts-list row and verify its profile."""
        point = self._box_center_fraction(box, self.vision.size())
        self.keyboard_only.click_window_fraction(*point)
        time.sleep(self._config.action_delay + .7)
        self._verify_contact_alias(expected_wechat_id)
        return {"action": "open_contact_profile", "transport": "hwnd",
                "verified_by": "contacts_page_and_profile_ocr", "ocr_used": True,
                "result_point": list(point), "sent": False}

    def _observe_contact_section(self) -> dict:
        from wechat_auto.primitives.contact_section import observe_contact_section
        from wechat_auto.primitives.page_geometry import observe_geometry
        from wechat_auto.primitives.page_state import classify_page

        image = self.vision.capture()
        if image is None:
            raise RuntimeError('Contact section capture unavailable')
        boxes = self.vision.recognize_image(image)
        state = classify_page(boxes, image.size, geometry=observe_geometry(image))
        return {'section': observe_contact_section(image, boxes, state), 'state': state,
                'boxes': boxes, 'size': image.size}

    def ensure_contacts_section(self) -> dict:
        """Expand only the exact personal Contacts heading, never New Friends."""
        observed = self._observe_contact_section()
        section = observed['section']
        if not section['ok']:
            raise RuntimeError(section['error'])
        if section['state'] == 'collapsed':
            self.keyboard_only.click_window_fraction(*section['expander_point'])
            time.sleep(self._config.action_delay + .5)
            observed = self._observe_contact_section()
            section = observed['section']
        if not section.get('ok') or section.get('state') != 'expanded':
            raise RuntimeError('Personal Contacts section did not expand')
        self._contacts_section_lease = {
            'hwnd': self._app.handle, 'size': observed['size'],
            'bounds': section['member_bounds'],
        }
        return self._receipt('ensure_contacts_section', success=True, sent=False,
                             verified_by='exact_contacts_header_and_current_chevron',
                             member_bounds=section['member_bounds'])

    def open_contact_profile(self, contact: str, expected_wechat_id: str | None = None,
                             *, max_contact_scroll_pages: int = 12, navigate: bool = True) -> dict:
        """Open one exact contact from the Contacts page, never global content.

        OCR observes the Contacts marker and supplies the exact result
        coordinate.  The resulting click is still dispatched exclusively by
        the HWND driver.  Ambiguous or unverified results are rejected.
        """
        if not contact:
            raise ValueError("contact must not be empty")
        from wechat_auto.primitives.vision import normalize_text

        driver = self.keyboard_only
        page_boxes: list[dict] = []
        if navigate:
            self.open_navigation('contacts')
        self.ensure_contacts_section()
        page_boxes = self.vision.ocr()

        # A visible exact row is safer than driving a search box and avoids
        # crossing into chat, article or service-account result categories.
        query = normalize_text(contact)
        def visible_matches(items: list[dict]) -> list[dict]:
            width, height, bounds = self._contact_list_bounds()
            return [box for box in items
                    if bounds[0] <= (box['x'] + box['w']/2) / width <= bounds[2]
                    and bounds[1] <= (box['y'] + box['h']/2) / height <= bounds[3]
                    and normalize_text(box.get("text", "")) == query]

        visible = visible_matches(page_boxes)
        if len(visible) == 1:
            return self._open_and_verify_contact_box(visible[0], expected_wechat_id)
        if len(visible) > 1:
            raise ChatNotFoundError("Visible Contacts-list result is ambiguous")
        if max_contact_scroll_pages < 0:
            raise ValueError("max_contact_scroll_pages must not be negative")
        for _ in range(max_contact_scroll_pages):
            _width, _height, bounds = self._contact_list_bounds()
            driver.wheel_window_fraction((bounds[0] + bounds[2]) / 2,
                                         bounds[1] + (bounds[3] - bounds[1]) * .7, 6)
            time.sleep(self._config.scroll_delay)
            visible = visible_matches(self.vision.ocr())
            if len(visible) == 1:
                return self._open_and_verify_contact_box(visible[0], expected_wechat_id)
            if len(visible) > 1:
                raise ChatNotFoundError("Visible Contacts-list result is ambiguous")

        self.vision.shot('profile', 'contact-list-target-not-found')
        raise ChatNotFoundError('Target not found under personal Contacts; visual review required')

    def _contact_list_bounds(self):
        observed = self._observe_contact_section()
        section, state = observed['section'], observed['state']
        if section.get('ok') and section['state'] == 'expanded':
            self._contacts_section_lease = {'hwnd': self._app.handle, 'size': observed['size'],
                                            'bounds': section['member_bounds']}
            return *observed['size'], section['member_bounds']
        # When our own scroll moved the heading offscreen, keep only the
        # measured list body if no other category became visible. A new page,
        # collapse, resize or category invalidates the lease.
        lease = getattr(self, '_contacts_section_lease', None)
        forbidden = {'新的朋友', '企业微信联系人', '公众号、服务号', '公众号', '服务号', '群聊', '标签'}
        if (lease and lease['hwnd'] == self._app.handle and lease['size'] == observed['size']
                and state.get('page') in {'contacts', 'contact_profile'}
                and section.get('error') == 'contacts_tree_header_absent_or_ambiguous'
                and section.get('header_candidates') == 0
                and not any(re.sub(r'\s+', '', b['text']) in forbidden for b in observed['boxes'])):
            bounds = state['region_bounds']['conversation_list']
            return *observed['size'], bounds
        self._contacts_section_lease = None
        raise RuntimeError('Personal Contacts list scope is not verified')

    def _focus_input(self) -> None:
        observation = self.vision.observe_page()
        state = observation.get('state', {})
        candidates = state.get('geometry', {}).get('composer_candidates', [])
        if not observation.get('ok') or state.get('composer', {}).get('state') != 'present' or len(candidates) != 1:
            raise RuntimeError('Current-frame chat input absent or ambiguous')
        frame = candidates[0]
        width, height = state['size']
        self.keyboard_only.click_window_fraction((frame['x'] + frame['w'] / 2) / width,
                                                 (frame['y'] + frame['h'] * .3) / height)

    def prepare_text(self, contact: str, text: str) -> dict:
        navigation = self.open_chat(contact)
        if navigation.get('opened') is not True:
            raise ChatNotFoundError('chat_not_opened_or_verified')
        self._focus_input()
        self.keyboard_only._type_text(text)
        return {"action": "prepare_text", "transport": "hwnd", "navigation": navigation,
                "sent": False}

    def send_text(self, contact: str, text: str, *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Sending requires confirm=True")
        result = self.prepare_text(contact, text)
        self.keyboard_only._enter()
        result.update(action="send_text", sent=True)
        return result

    def prepare_mention(self, contact: str, member: str, text: str = "") -> dict:
        """Prepare a group @ draft through the focused WeChat editor.

        WeChat may require selecting the popup suggestion to turn the typed
        label into a real mention.  This method intentionally leaves that
        selection visible for confirmation instead of guessing a menu point.
        """
        if not member.strip():
            raise ValueError("member must not be empty")
        navigation = self.open_chat(contact)
        self._focus_input()
        self.keyboard_only._type_text(f"@{member}")
        if text:
            self.keyboard_only._type_text(f" {text}")
        return {"action": "prepare_mention", "transport": "hwnd", "navigation": navigation,
                "member": member, "text": text, "sent": False,
                "selection_required": True}

    def send_mention(self, contact: str, member: str, text: str = "", *,
                     confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Mention send requires confirm=True")
        navigation = self.open_chat(contact)
        self._focus_input()
        self.keyboard_only._type_text(f"@{member}")
        # In WeChat's group editor, Enter accepts the highlighted @ suggestion.
        # If no suggestion is shown, the explicit-confirmation boundary still
        # prevents this path from running accidentally.
        self.keyboard_only._enter()
        if text:
            self.keyboard_only._type_text(text)
        self.keyboard_only._enter()
        result = {"action": "send_mention", "transport": "hwnd", "navigation": navigation,
                  "member": member, "text": text, "sent": True,
                  "suggestion_selected_by": "enter"}
        return result

    def prepare_quote(self, contact: str, message: tuple[float, float],
                      quote_menu: tuple[float, float] | None = None, text: str = "") -> dict:
        """Open the context menu and prepare a reply using current-frame points.

        Caller points must be freshly observed; no stored calibration is loaded.
        This method itself only dispatches HWND messages.
        """
        navigation = self.open_chat(contact)
        self.right_click(*message)
        time.sleep(self._config.click_delay)
        if quote_menu is None:
            quote_menu = self._choose_context_menu_item(self._config.kw_quote)
        self.click(*quote_menu)
        if text:
            self._focus_input()
            self.keyboard_only._type_text(text)
        return {"action": "prepare_quote", "transport": "hwnd", "navigation": navigation,
                "message_point": list(message), "quote_menu": list(quote_menu),
                "text": text, "sent": False}

    def send_quote(self, contact: str, message: tuple[float, float],
                   quote_menu: tuple[float, float] | None = None, text: str = "", *,
                   confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Quote reply requires confirm=True")
        if not text.strip():
            raise ValueError("text must not be empty")
        result = self.prepare_quote(contact, message, quote_menu, text)
        self.keyboard_only._enter()
        result.update(action="send_quote", sent=True)
        return result

    def copy_message(self, message: tuple[float, float], *, contact: str | None = None,
                     copy_menu: tuple[float, float] | None = None) -> dict:
        """Copy one observed message via WeChat's normal context menu.

        Clipboard contents may be private: this method never reads or returns
        them. A caller can supply a freshly observed menu point, or opt
        into OCR observation for a unique ``复制`` menu label.
        """
        navigation = self.open_chat(contact) if contact else None
        self.right_click(*message)
        time.sleep(self._config.click_delay)
        if copy_menu is None:
            copy_menu = self._choose_context_menu_item(self._config.kw_copy_msg)
        self.click(*copy_menu)
        return {"action": "copy_message", "transport": "hwnd", "navigation": navigation,
                "message_point": list(message), "copy_menu": list(copy_menu),
                "clipboard_read": False}

    def prepare_profile_observation(self, contact: str,
                                    profile_entry: tuple[float, float] | None = None,
                                    expected_wechat_id: str | None = None) -> dict:
        """Open a chat and its currently observed profile entry; never sends."""
        if profile_entry is None:
            return self.open_contact_profile(contact, expected_wechat_id)
        navigation = self.open_chat(contact)
        self.click(*profile_entry)
        time.sleep(self._config.action_delay)
        return {"action": "prepare_profile_observation", "transport": "hwnd",
                "navigation": navigation, "profile_entry": list(profile_entry), "sent": False}

    def capture_contact_profile(self, wechat_id: str, expected_alias: str, database_path: str) -> dict:
        """Archive explicit fields from a uniquely selected, identity-verified profile."""
        from wechat_auto.primitives.profile_fields import extract_profile_fields
        from wechat_auto.primitives.vision import VisionAutomation
        from wechat_auto.storage import ProfileStore

        selected = self.resolve_target_window('contact_profile')
        if not selected['ok']:
            raise RuntimeError('Profile window absent or ambiguous')
        target = self._app.for_window(selected['target']['hwnd'])
        observer = self.vision if target.handle == self._app.handle else VisionAutomation(target, self._config)
        image = observer.capture()
        if image is None:
            raise RuntimeError('Profile capture unavailable')
        from wechat_auto.primitives.page_geometry import observe_geometry
        from wechat_auto.primitives.page_state import classify_page
        boxes = observer.recognize_image(image)
        observation = {'ok': True, 'boxes': boxes,
                       'state': classify_page(boxes, image.size, geometry=observe_geometry(image))}
        if not observation.get('ok') or observation['state'].get('page') != 'contact_profile':
            raise RuntimeError('Profile page changed before enrichment')
        with ProfileStore(database_path) as store:
            current = store.get(wechat_id)
            if not current or not expected_alias or current.get('alias') != expected_alias:
                raise RuntimeError('Stable archived identity and exact alias required')
            self._verify_contact_alias(expected_alias, observer=observer)
            state = observation['state']
            bounds = [state['region_bounds']['conversation_list'][2], 0., 1., 1.] if target.handle == self._app.handle else [0., 0., 1., 1.]
            extracted = extract_profile_fields(observation['boxes'], tuple(state['size']), bounds)
            if extracted['fields'].get('alias') != expected_alias:
                raise RuntimeError('Same-frame profile alias not verified')
            from pathlib import Path
            from uuid import uuid4
            folder = Path('data/ui_audit/profiles')
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / (uuid4().hex + '.png')
            image.save(path)
            evidence = str(path.resolve())
            result = store.record_ui_observation(wechat_id, extracted['fields'], evidence_ref=evidence)
        return self._receipt('capture_contact_profile', success=True, sent=False, input_dispatched=False,
                             observed_fields=sorted(extracted['fields']), changed_fields=result['changed_fields'],
                             unobserved_fields=extracted['unobserved_fields'], ambiguous_fields=extracted['ambiguous_fields'],
                             evidence_ref=evidence, identity_verified=True)

    def capture_visible_signature(self, wechat_id: str, database_path: str) -> dict:
        """OCR a visible profile card and save only an explicit signature value.

        This method does not navigate or click.  It intentionally refuses to
        infer a signature from arbitrary chat text, so a failed OCR pass cannot
        erase a previously observed value.
        """
        if not getattr(self._config, "ocr_verify_enabled", False):
            raise RuntimeError("OCR verification must be enabled for profile observation")
        from wechat_auto.primitives.vision import normalize_text
        from wechat_auto.storage import ProfileStore

        boxes = self.vision.ocr()
        signature = None
        for box in boxes:
            text = str(box.get("text", "")).strip()
            compact = normalize_text(text)
            if "个性签名" not in compact:
                continue
            remainder = compact.split("个性签名", 1)[1].lstrip(":：")
            if remainder:
                signature = remainder
                break
        with ProfileStore(database_path) as store:
            result = store.record_signature_observation(wechat_id, signature)
        return {"action": "capture_visible_signature", "transport": "none",
                "signature_observed": result["observed"], "status": result["status"],
                "changed_fields": result["changed_fields"]}

    def _prepare_clipboard_payload(self, contact: str, setter, value: str) -> dict:
        navigation = self.open_chat(contact)
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"Expected a file: {path}")
        setter(str(path))
        self._focus_input()
        self.keyboard_only._paste()
        return {"transport": "hwnd", "navigation": navigation,
                "path": str(path), "sent": False}

    def prepare_file(self, contact: str, path: str) -> dict:
        result = self._prepare_clipboard_payload(
            contact, lambda value: ClipboardHelper.set_files([value]), path
        )
        result["action"] = "prepare_file"
        return result

    def send_file(self, contact: str, path: str, *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("File send requires confirm=True")
        result = self.prepare_file(contact, path)
        self.keyboard_only._enter()
        result.update(action="send_file", sent=True)
        return result

    def prepare_image(self, contact: str, path: str) -> dict:
        result = self._prepare_clipboard_payload(contact, ClipboardHelper.set_image, path)
        result["action"] = "prepare_image"
        return result

    def send_image(self, contact: str, path: str, *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Image send requires confirm=True")
        result = self.prepare_image(contact, path)
        self.keyboard_only._enter()
        result.update(action="send_image", sent=True)
        return result

    def open_emoji(self) -> dict:
        return self.page_operation('open_emoji_panel')

    def send_sticker(self, cell: tuple[float, float], *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Sticker send requires confirm=True")
        self.open_emoji()
        time.sleep(self._config.action_delay)
        self.click(*cell)
        return {"action": "send_sticker", "transport": "hwnd", "sent": True}

    def send_sticker_by_id(self, contact: str, sticker_id: str, catalog_path: str,
                           *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError('Sticker send requires confirm=True')
        raise RuntimeError('Stored sticker cell coordinates were removed; identify the asset in the current panel')

    def open_moments(self) -> dict:
        result = self.page_operation('open_discover')
        if not result['success']:
            raise RuntimeError('Discover navigation failed')
        return self.page_operation('open_moments')

    def like_moment(self, menu: tuple[float, float], like: tuple[float, float], *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Like requires confirm=True")
        self.click(*menu)
        time.sleep(self._config.click_delay)
        self.click(*like)
        return {"action": "like_moment", "transport": "hwnd", "dispatched": True}

    def comment_moment(self, menu: tuple[float, float], comment_button: tuple[float, float],
                       input_box: tuple[float, float], text: str, *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Comment requires confirm=True")
        for point in (menu, comment_button, input_box):
            self.click(*point)
            time.sleep(self._config.click_delay)
        self.keyboard_only._type_text(text)
        self.keyboard_only._enter()
        return {"action": "comment_moment", "transport": "hwnd", "dispatched": True}
