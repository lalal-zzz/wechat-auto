"""Single low-level action skill for Weixin 4.x.

Invariant: every UI mutation is delivered through the Weixin HWND route (the
top-level window or its unique visible MMUI render child). OCR is only an
observer: it verifies a result or supplies a replacement coordinate. It never
performs the click itself.
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
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
            "reset_search_popup": self.reset_search_popup,
            "select_search_result": self.select_search_result,
            "verify_searched_contact_alias": self.verify_searched_contact_alias,
            "close_private_chat_details": self.close_private_chat_details,
            "send_current_verified_text": self.send_current_verified_text,
            "open_search_content": self.open_search_content,
            "prepare_text": self.prepare_text,
            "cancel_prepared_text": self.cancel_prepared_text,
            "delete_verified_text": self.delete_verified_text,
            "send_text": self.send_text,
            "prepare_mention": self.prepare_mention,
            "send_mention": self.send_mention,
            "prepare_quote": self.prepare_quote,
            "send_quote": self.send_quote,
            "copy_message": self.copy_message,
            "copy_text_draft_identity": self.copy_text_draft_identity,
            "prepare_profile_observation": self.prepare_profile_observation,
            "capture_visible_signature": self.capture_visible_signature,
            "capture_contact_profile": self.capture_contact_profile,
            "click": self.click,
            "right_click": self.right_click,
            "scroll": self.scroll,
            "press_key": self.press_key,
            "prepare_file": self.prepare_file,
            "hover_attachment_card": self.hover_attachment_card,
            "open_attachment_context_menu": self.open_attachment_context_menu,
            "copy_attachment_identity": self.copy_attachment_identity,
            "cancel_verified_attachment": self.cancel_verified_attachment,
            "open_composer_context_menu": self.open_composer_context_menu,
            "dismiss_composer_context_menu": self.dismiss_composer_context_menu,
            "send_file": self.send_file,
            "prepare_image": self.prepare_image,
            "cancel_verified_image": self.cancel_verified_image,
            "copy_image_identity": self.copy_image_identity,
            "send_image": self.send_image,
            "open_emoji": self.open_emoji,
            "open_emoji_favorites": self.open_emoji_favorites,
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
                     'open_contacts', 'open_chats', 'open_discover', 'open_main_menu', 'open_emoji_panel'},
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
        attempted_routes = set()
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
            edge = (source['hwnd'], next(iter(keys)), route[0])
            if edge in attempted_routes:
                return stopped('route_no_progress')
            attempted_routes.add(edge)
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
        self.reset_search_popup()
        from wechat_auto.utils.screenshot import ScreenshotHelper

        self._activate()
        search_scope = self._app.describe_window(self._app.handle)
        image = ScreenshotHelper().capture_visible_window(self._app.handle)
        if image is None:
            raise RuntimeError("Visible foreground search window capture unavailable")
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
        if existing == normalize_text(query):
            self.keyboard_only.click_window_fraction((field['x']+field['w']*.4)/image.width,
                                                       (field['y']+field['h']/2)/image.height)
            time.sleep(self._config.action_delay+.5)
            return self._receipt('prepare_search', verified_by='visible_search_field_ocr',
                                 selection_required=True, sent=False, input_dispatched=True)
        driver = self.keyboard_only
        if existing and existing != "搜索":
            clear = find_search_clear(image, field)
            if len(clear) != 1:
                raise RuntimeError("Search clear control is absent or ambiguous")
            driver.click_window_fraction(clear[0][0] / image.width, clear[0][1] / image.height)
            time.sleep(self._config.action_delay)
            visible = ScreenshotHelper().capture_visible_window(self._app.handle)
            if visible is None or visible.size != image.size:
                raise RuntimeError('Visible search frame changed; typing stopped')
            empty = field_text(self.vision.recognize_image(visible.crop((region[0],region[1],
                region[0]+region[2],region[1]+region[3])), region=region, window_size=image.size))
            if empty != "搜索":
                raise RuntimeError("Search field did not clear; typing stopped")
        driver.click_window_fraction((field["x"] + field["w"] * .4) / image.width,
                                     (field["y"] + field["h"] / 2) / image.height)
        with driver.foreground_lease():
            self._verify_search_input_focus(field, image.size, search_scope)
            driver._type_text(query)
            time.sleep(self._config.action_delay + .5)
        visible = ScreenshotHelper().capture_visible_window(self._app.handle)
        if visible is None or visible.size != image.size:
            raise RuntimeError('Visible search frame changed; no result selected')
        observed = self.vision.recognize_image(visible.crop((region[0],region[1],
            region[0]+region[2],region[1]+region[3])), region=region, window_size=image.size)
        joined = field_text(observed)
        verification = 'visible_search_field_ocr'
        if normalize_text(query) != joined:
            if not self._search_popup_echo_matches(query):
                raise RuntimeError("Search query was not verified; no result selected")
            verification = 'owned_search_popup_query_echo'
        return self._receipt("prepare_search", verified_by=verification,
                             selection_required=True, sent=False,
                             focus_verified_by='win32_caret_in_current_search_field')

    def _verify_search_input_focus(self, field: dict, size: tuple, scope: dict) -> None:
        """Require a current search frame and a public caret before typing."""
        from wechat_auto.primitives.page_geometry import observe_geometry
        from wechat_auto.utils.screenshot import ScreenshotHelper

        if self._app.describe_window(self._app.handle) != scope:
            raise RuntimeError('Search window changed; typing stopped')
        image = ScreenshotHelper().capture_visible_window(self._app.handle)
        if image is None or image.size != size:
            raise RuntimeError('Visible search frame changed; typing stopped')
        fields = observe_geometry(image).get('search_field_candidates', [])
        if len(fields) != 1 or any(abs(fields[0][k] - field[k]) > 3 for k in ('x', 'y', 'w', 'h')):
            raise RuntimeError('Search field changed; typing stopped')
        caret = self._app.focused_caret_rect()
        current = fields[0]
        if (not isinstance(caret, (list, tuple)) or len(caret) != 4
                or not current['x'] < caret[0] < caret[2] < current['x'] + current['w']
                or not current['y'] < caret[1] < caret[3] < current['y'] + current['h']
                or self._app.describe_window(self._app.handle) != scope):
            raise RuntimeError('Search input focus not verified; typing stopped')

    def reset_search_popup(self) -> dict:
        """Dismiss only a recognized owned search popup before a new query."""
        windows = self.inspect_windows()
        auxiliary = [w for w in windows if not w['is_main']]
        if not auxiliary:
            return self._receipt('reset_search_popup', success=True, input_dispatched=False, sent=False)
        if (len(auxiliary) != 1 or auxiliary[0].get('status') != 'recognized'
                or auxiliary[0].get('owner_hwnd') != self._app.handle
                or not {'search', 'search_suggestions'} & {s['page'] for s in auxiliary[0]['surfaces']}):
            raise RuntimeError('Only one recognized owned search popup may be reset')
        handle = auxiliary[0]['hwnd']
        self.keyboard_only.press_key('escape')
        time.sleep(self._config.action_delay + .5)
        if any(w['hwnd'] == handle for w in self._app.list_windows()):
            raise RuntimeError('Search popup did not dismiss; no new query typed')
        return self._receipt('reset_search_popup', success=True, sent=False,
                             verified_by='owned_search_popup_disappeared')

    def _search_popup_echo_matches(self, query: str) -> bool:
        """Read the literal first network suggestion, never choose that item."""
        from wechat_auto.primitives.vision import (
            VisionAutomation,
            normalize_text,
            parse_search_sections,
        )

        auxiliary = [w for w in self._app.list_windows() if not w['is_main']]
        if (len(auxiliary) != 1 or auxiliary[0]['owner_hwnd'] != self._app.handle
                or 'ToolSaveBits' not in auxiliary[0]['class']):
            return False
        observer = VisionAutomation(self._app.for_window(auxiliary[0]['hwnd']), self._config)
        observation = observer.observe_page()
        if not observation.get('ok'):
            return False
        blocks = [s for s in parse_search_sections(observation['boxes']) if s['section'] == 'web']
        if len(blocks) != 1 or not blocks[0]['items']:
            return False
        first = min(blocks[0]['items'], key=lambda b: (b['y'], b['x']))
        return first.get('score', 0) >= .65 and normalize_text(first['text']) == normalize_text(query)

    def _visible_search_query_matches(self, query: str) -> bool:
        """Recheck the current visible field when web suggestions are offscreen."""
        from wechat_auto.primitives.page_geometry import observe_geometry
        from wechat_auto.primitives.vision import normalize_text
        from wechat_auto.utils.screenshot import ScreenshotHelper

        image = ScreenshotHelper().capture_visible_window(self._app.handle)
        if image is None:
            return False
        fields = observe_geometry(image).get('search_field_candidates',[])
        if len(fields) != 1:
            return False
        field = fields[0]
        region = (field['x']+int(field['w']*.13),field['y'],int(field['w']*.75),field['h'])
        boxes = self.vision.recognize_image(image.crop((region[0],region[1],
            region[0]+region[2],region[1]+region[3])),region=region,window_size=image.size)
        text = ''.join(normalize_text(b['text']) for b in boxes if b.get('score',0) >= .65
                       and field['x']+field['w']*.08 < b['x']+b['w']/2 < field['x']+field['w']*.88)
        return text == normalize_text(query)

    def select_search_result(self, query: str, *, section: str, username: str,
                             result_name: str | None = None) -> dict:
        """Select one exact owned-popup result; never a web/history candidate."""
        from wechat_auto.primitives.vision import (
            VisionAutomation,
            normalize_text,
            scoped_search_matches,
        )

        if section not in {'contact', 'function'} or not username:
            raise ValueError('Stable identity and contact/function section required')
        system = section == 'function' and username == 'filehelper' and query == '文件传输助手'
        if section == 'function' and not system:
            raise ValueError('Only the built-in FileHelper function is supported')
        name = result_name or query
        if system and name != query:
            raise ValueError('Built-in function name must match its query')
        self._recipient_lease = None
        self._pending_recipient = None
        windows = self._app.list_windows()
        auxiliary = [w for w in windows if not w['is_main']]
        if (len(auxiliary) != 1 or auxiliary[0]['owner_hwnd'] != self._app.handle
                or 'ToolSaveBits' not in auxiliary[0]['class']):
            raise RuntimeError('Unique owned search popup required')
        target = self._app.for_window(auxiliary[0]['hwnd'])
        observer = VisionAutomation(target, self._config)
        observation = observer.observe_page()
        if not observation.get('ok') or not (self._visible_search_query_matches(query)
                                             or self._search_popup_echo_matches(query)):
            raise RuntimeError('Current search query not verified')
        matches, _ = scoped_search_matches(observation['boxes'], name, section)
        if len(matches) != 1:
            raise RuntimeError('Exact result in the requested section absent or ambiguous')
        metadata = self._app.describe_window(target.handle)
        if any(metadata[k] != auxiliary[0][k] for k in ('pid','rect','client_rect','dpi','owner_hwnd')):
            raise StaleFrameError('Search popup changed before selection')
        child = BasicSkill(target, self._config, self._session)
        child.keyboard_only.foreground_mode = 'never'
        child.keyboard_only.click_window_fraction(*self._box_center_fraction(matches[0], tuple(observation['state']['size'])))
        time.sleep(self._config.action_delay + .5)
        after = self.vision.observe_page(visible=True)
        state = after.get('state', {})
        header = [b for b in state.get('regions', {}).get('conversation_header', [])
                  if normalize_text(b['text']) == normalize_text(name)]
        if (not after.get('ok') or len(header) != 1
                or state.get('composer',{}).get('state') != 'present'
                or any(not w['is_main'] for w in self._app.list_windows())):
            raise RuntimeError('Search result did not open a uniquely verified chat')
        if system:
            self._recipient_lease = {'username':username, 'query':query,
                                    'metadata':self._app.describe_window(self._app.handle),
                                    'verification':'built_in_function_section_and_chat'}
        else:
            self._pending_recipient = {'username':username, 'query':name,
                                       'metadata':self._app.describe_window(self._app.handle)}
        return self._receipt('select_search_result', success=True, sent=False,
                             identity_verified=system, alias_verification_required=not system,
                             verified_by='exact_scoped_search_and_chat')

    def verify_searched_contact_alias(self, expected_alias: str) -> dict:
        """Open the searched chat's profile, verify alias, then return to that chat."""
        from wechat_auto.primitives.vision import normalize_text

        pending = getattr(self, '_pending_recipient', None)
        if not pending or not expected_alias or pending['username'].endswith('@chatroom'):
            raise PermissionError('Searched private contact and archived alias required')
        current = self._app.describe_window(self._app.handle)
        if any(current[k] != pending['metadata'][k] for k in ('hwnd','pid','rect','client_rect','dpi')):
            raise StaleFrameError('Searched contact window changed before profile verification')
        auxiliary = [w for w in self._app.list_windows() if not w['is_main']]
        if auxiliary:
            return self._finish_searched_contact_alias(expected_alias,pending,auxiliary)
        self._activate()
        observation = self.vision.observe_page(visible=True)
        state = observation.get('state',{})
        titles = [observation['boxes'][b['box_index']] for b in state.get('regions',{}).get('conversation_header',[])
                  if normalize_text(b['text']) == normalize_text(pending['query'])]
        if not observation.get('ok') or len(titles) != 1 or state.get('composer',{}).get('state') not in {'present','candidate'}:
            raise RuntimeError('Searched conversation not currently verified')
        from wechat_auto.primitives.page_controls import (
            find_private_chat_profile_avatar,
        )
        panel = state.get('geometry',{}).get('right_panel_candidate')
        if not panel:
            self.keyboard_only.click_window_fraction(*self._box_center_fraction(titles[0],tuple(state['size'])))
            time.sleep(self._config.action_delay + .5)
            observation = self.vision.observe_page(visible=True)
            state = observation.get('state',{})
        if not observation.get('ok'):
            raise RuntimeError('Chat details observation failed')
        panel = state.get('geometry',{}).get('right_panel_candidate')
        if panel:
            anchors = [b for b in observation['boxes']
                       if b['x'] > panel['x'] and normalize_text(b['text']) == '查找聊天内容']
            if len(anchors) == 1:
                image = self.vision._last_observed_image
                region = (panel['x'],0,image.width-panel['x'],anchors[0]['y'])
                observation['boxes'] = [b for b in observation['boxes']
                                        if not (b['x'] > panel['x'] and b['y'] < anchors[0]['y'])]
                observation['boxes'] += self.vision.recognize_image(
                    image.crop((region[0],0,image.width,region[3])),
                    region=region,window_size=image.size,upscale=2)
        avatar = find_private_chat_profile_avatar(self.vision._last_observed_image,
                                                  observation['boxes'],state,pending['query'])
        self.keyboard_only.click_window_fraction(*avatar['window_fraction'])
        time.sleep(self._config.action_delay + .5)
        auxiliary = [w for w in self._app.list_windows() if not w['is_main']]
        return self._finish_searched_contact_alias(expected_alias,pending,auxiliary)

    def _finish_searched_contact_alias(self, expected_alias: str, pending: dict,
                                      auxiliary: list) -> dict:
        from wechat_auto.primitives.vision import VisionAutomation, normalize_text

        if (len(auxiliary) != 1 or auxiliary[0]['pid'] != pending['metadata']['pid']
                or auxiliary[0]['owner_hwnd'] not in {0,self._app.handle}
                or 'ToolSaveBits' not in auxiliary[0]['class']):
            raise RuntimeError('Unique same-process profile card did not open')
        target = self._app.for_window(auxiliary[0]['hwnd'])
        observer = VisionAutomation(target,self._config)
        profile = observer.observe_page()
        if not profile.get('ok') or profile['state']['page'] != 'contact_profile':
            raise RuntimeError('Current profile card page not recognized')
        if any(normalize_text(b['text']) in {'添加到通讯录','添加朋友'} for b in profile['boxes']):
            raise PermissionError('Contact state does not permit this send')
        self._verify_contact_alias(expected_alias,observer=observer)
        closed = self.page_operation('close', hwnd=target.handle,
                                      expected_page='contact_profile',max_attempts=1)
        if not closed['success']:
            raise RuntimeError('Verified profile card did not close')
        restored = self.close_private_chat_details(pending['query'])
        if not restored['success']:
            raise RuntimeError('Verified contact details did not close')
        returned = self.vision.observe_page(visible=True)
        titles = [b for b in returned.get('state',{}).get('regions',{}).get('conversation_header',[])
                  if normalize_text(b['text']) == normalize_text(pending['query'])]
        if not returned.get('ok') or len(titles) != 1 or any(not w['is_main'] for w in self._app.list_windows()):
            raise RuntimeError('Verified contact chat did not resume')
        self._recipient_lease = {**pending,'metadata':self._app.describe_window(self._app.handle),
                                'verification':'contact_section_profile_alias_and_same_chat'}
        self._pending_recipient = None
        return self._receipt('verify_searched_contact_alias',success=True,sent=False,
                             identity_verified=True,verified_by='exact_profile_alias_and_same_chat')

    def close_private_chat_details(self, query: str) -> dict:
        """Close only the current private details panel through its title toggle."""
        from wechat_auto.primitives.vision import normalize_text

        if any(not w['is_main'] for w in self._app.list_windows()):
            raise RuntimeError('Auxiliary window blocks details close')
        self._activate()
        observed = self.vision.observe_page(visible=True)
        state = observed.get('state',{})
        panel = state.get('geometry',{}).get('right_panel_candidate')
        if not observed.get('ok') or not panel:
            raise RuntimeError('Current private details panel unavailable')
        labels = {normalize_text(b['text']) for b in observed['boxes'] if b['x'] > panel['x']}
        if not {'查找聊天内容','消息免打扰','置顶聊天'} <= labels:
            raise RuntimeError('Current private details panel anchors absent')
        titles = [observed['boxes'][b['box_index']] for b in state['regions']['conversation_header']
                  if normalize_text(b['text']) == normalize_text(query)]
        if len(titles) != 1:
            raise RuntimeError('Exact chat title unavailable')
        self.keyboard_only.click_window_fraction(*self._box_center_fraction(titles[0],tuple(state['size'])))
        time.sleep(self._config.action_delay + .5)
        after = self.vision.observe_page(visible=True)
        success = (after.get('ok') and not after['state']['geometry'].get('right_panel_candidate')
                   and after['state']['composer']['state'] == 'present')
        return self._receipt('close_private_chat_details',success=bool(success),sent=False,
                             verified_by='details_disappeared_and_composer_observed')

    def _checked_recipient_composer(self, lease: dict, *, allowed_popup: dict | None = None,
                                    expected_image: Path | None = None):
        """Observe the same verified recipient and one current text composer."""
        from wechat_auto.primitives.vision import normalize_text

        metadata = self._app.describe_window(self._app.handle)
        auxiliary = [w for w in self._app.list_windows() if not w['is_main']]
        popup_matches = (allowed_popup is not None and len(auxiliary) == 1
                         and all(auxiliary[0][k] == allowed_popup[k] for k in (
                             'hwnd', 'pid', 'class', 'owner_hwnd', 'rect', 'client_rect', 'dpi')))
        if (any(metadata[k] != lease['metadata'][k] for k in ('hwnd','pid','rect','client_rect','dpi'))
                or auxiliary and not popup_matches or allowed_popup is not None and not popup_matches):
            raise RuntimeError('Recipient window changed or auxiliary window appeared')
        # PrintWindow sees the underlying editor without this separately owned
        # native menu. Every other caller still requires a visible foreground frame.
        observation = self.vision.observe_page(visible=allowed_popup is None)
        state = observation.get('state', {})
        titles = [b for b in state.get('regions',{}).get('conversation_header', [])
                  if normalize_text(b['text']) == normalize_text(lease['query'])]
        candidates = state.get('geometry',{}).get('composer_candidates', [])
        if (not observation.get('ok') or len(titles) != 1 or state.get('overlays')
                or state.get('panels') or state.get('content_windows')
                or state.get('composer',{}).get('state') != 'present' or len(candidates) != 1):
            raise RuntimeError('Current recipient/header/composer not verified')
        send_labels = [b for b in observation['boxes'] if normalize_text(b['text']) in {
            '发送','发送(S)','发送（S）'} and b['y'] >= candidates[0]['y']
            and b['x']+b['w']/2 > candidates[0]['x']+candidates[0]['w']*.7]
        if len(send_labels) != 1:
            raise RuntimeError('Composer action row absent or ambiguous')
        action_top = send_labels[0]['y'] - send_labels[0]['h']*.25
        body_boxes = [observation['boxes'][b['box_index']] for b in sorted(state['regions']['composer'],key=lambda b:(
            observation['boxes'][b['box_index']]['y'],observation['boxes'][b['box_index']]['x']))
            if (observation['boxes'][b['box_index']]['y']
                + observation['boxes'][b['box_index']]['h']/2) < action_top]
        body = ''.join(b['text'] for b in body_boxes)
        from wechat_auto.primitives.page_controls import (
            composer_send_enabled,
            is_empty_composer_placeholder,
        )

        if is_empty_composer_placeholder(getattr(self.vision, '_last_observed_image', None),
                                         body_boxes, send_labels[0]):
            body = ''
            body_boxes = []
        if expected_image is not None:
            from wechat_auto.primitives.image_preview import find_image_preview

            observation['_image_preview'] = find_image_preview(
                self.vision._last_observed_image, candidates[0], expected_image)
        if expected_image is None and not normalize_text(body) and composer_send_enabled(
                getattr(self.vision, '_last_observed_image', None), send_labels[0]) is not False:
            raise RuntimeError('Empty OCR does not prove an empty composer; Send enabled or pixels unavailable')
        observation['_composer_body_boxes'] = body_boxes
        return observation, normalize_text(body), candidates[0]

    def send_current_verified_text(self, text: str, *, confirm: bool = False,
                                   use_existing_draft: bool = False,
                                   before_dispatch: Callable[[], None] | None = None) -> dict:
        """Send once after exact recipient/draft checks; observe the outgoing result."""
        from wechat_auto.primitives.vision import normalize_text

        if not confirm:
            raise PermissionError('Sending requires explicit confirmation')
        if not text or any(ord(c) < 32 for c in text):
            raise ValueError('A nonempty printable confirmed body is required')
        lease = getattr(self, '_recipient_lease', None)
        if not lease:
            raise PermissionError('Verified stable recipient lease required')
        def checked():
            return self._checked_recipient_composer(lease)
        self._activate()
        before, body, frame = checked()
        previous_matches = sum(normalize_text(b['text']) == normalize_text(text)
                               for b in before['boxes'] if b['y'] < frame['y']
                               and b['x']+b['w']/2 > before['state']['size'][0]*.6)
        size = before['state']['size']
        if use_existing_draft:
            if body != normalize_text(text):
                raise RuntimeError('Existing draft does not match confirmed body; no send dispatched')
            draft, body, draft_frame = checked()
        else:
            if body:
                raise RuntimeError('Existing draft present; no typing or sending')
            self.keyboard_only.click_window_fraction((frame['x']+frame['w']/2)/size[0],
                                                     (frame['y']+frame['h']*.3)/size[1])
            self.keyboard_only._type_text(text)
            time.sleep(self._config.action_delay + .5)
            draft, body, draft_frame = checked()
        if body != normalize_text(text):
            raise RuntimeError('Confirmed draft text not exactly observed; no send dispatched')
        if before_dispatch is not None:
            self._recipient_lease = None
            before_dispatch()
            draft, body, current_frame = checked()
            if (body != normalize_text(text) or current_frame != draft_frame
                    or draft['state']['size'] != size):
                raise RuntimeError('Draft or composer changed during dispatch checks; no send dispatched')
        send = [b for b in draft['boxes'] if normalize_text(b['text']) in {'发送','发送(S)','发送（S）'}
                and b['y'] >= draft_frame['y'] and b.get('score',0) >= .65]
        if len(send) != 1:
            raise RuntimeError('Unique current Send button not observed; no send dispatched')
        self._recipient_lease = None
        try:
            self.keyboard_only.click_window_fraction(*self._box_center_fraction(send[0],tuple(size)))
            time.sleep(self._config.action_delay + .8)
            after = self.vision.observe_page(visible=True)
            state = after.get('state',{})
            remaining = [b for b in state.get('regions',{}).get('composer',[]) if normalize_text(b['text']) == normalize_text(text)]
            outgoing = [b for b in after.get('boxes',[]) if normalize_text(b['text']) == normalize_text(text)
                        and b['x']+b['w']/2 > size[0]*.6 and b['y'] < frame['y']]
            import numpy as np

            image = getattr(self.vision, '_last_observed_image', None)
            green_outgoing = []
            for box in outgoing:
                if image is None:
                    continue
                pixels = np.asarray(image.crop((box['x'],box['y'],box['x']+box['w'],box['y']+box['h'])))
                if pixels.size and ((pixels[:,:,1] > 100) & (pixels[:,:,1] > pixels[:,:,0].astype(float)*1.25)
                                    & (pixels[:,:,1] > pixels[:,:,2].astype(float)*1.15)).mean() >= .2:
                    green_outgoing.append(box)
            failure = any('发送失败' in b['text'] or '消息已发出，但被对方拒收' in b['text']
                          for b in after.get('boxes',[]))
            metadata = self._app.describe_window(self._app.handle)
            same_recipient = (
                all(metadata[k] == lease['metadata'][k] for k in ('hwnd','pid','rect','client_rect','dpi'))
                and not any(not w['is_main'] for w in self._app.list_windows())
                and state.get('size') == size
                and not state.get('overlays')
                and state.get('composer',{}).get('state') == 'present'
                and sum(normalize_text(b['text']) == normalize_text(lease['query'])
                        for b in state.get('regions',{}).get('conversation_header', [])) == 1
            )
            verified = (after.get('ok') and same_recipient and not remaining
                        and len(green_outgoing) > previous_matches and not failure)
            return self._receipt('send_current_verified_text', success=bool(verified), dispatched=True,
                                 sent=bool(verified), delivery_verified=False, automatic_retry=False,
                                 verified_by='outgoing_text_and_cleared_draft' if verified else 'result_unknown')
        except Exception as exc:
            # Dispatch may already have reached the HWND. Preserve uncertainty
            # even when the subsequent screenshot/OCR or driver receipt fails.
            return self._receipt('send_current_verified_text', success=False, dispatched=True,
                                 sent=False, delivery_verified=False, automatic_retry=False,
                                 verified_by='result_unknown', error_type=type(exc).__name__)

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
        # An already visible, unobstructed chat needs no sidebar click. Unread
        # badges can obscure that glyph; this observation proves only the page,
        # never the recipient identity or permission to type/send.
        state = before['state']
        if (operation == 'open_chats' and target.handle == self._app.handle
                and source in spec.targets and page_keys(state) == {source}
                and not state.get('panels') and not state.get('overlays')
                and not state.get('content_windows')
                and all(w['is_main'] for w in windows_before)):
            return self._receipt(
                'page_operation', operation=operation, success=True,
                verified_by='current_unobstructed_target_page',
                source_page=source, after_pages=[source],
                input_dispatched=False, already_at_target=True, sent=False,
            )
        skill = self if target.handle == self._app.handle else BasicSkill(
            target, self._config, self._session)
        # Popup activation dismisses Qt menus; preserve their current focus.
        driver = skill.keyboard_only
        old_mode = driver.foreground_mode
        if target.handle != self._app.handle:
            driver.foreground_mode = "never"
        elif operation in {"open_main_menu", "open_moments"}:
            # Menus dismiss and Moments activation can be lost when focus
            # returns before Qt finishes opening the content. Keep it foreground.
            driver.foreground_mode = "leave"
        point = None
        used_layout = "observed_frame"
        try:
            if spec.method in {"ocr", "ocr_cancel", "profile_album"}:
                boxes = [b for b in before["boxes"] if b.get("score", 0) >= .65
                         and re.sub(r"\s+", "", b.get("text", "")) in spec.anchors]
                # Discover labels must be in the navigation list, not body text.
                if source in {"discover", "moments_feed", "channels", "web_search", "mini_program_list"}:
                    bounds = before["state"]["region_bounds"]["conversation_list"]
                    width, _height = before["state"]["size"]
                    boxes = [b for b in boxes if bounds[0] <= (b["x"] + b["w"] / 2) / width <= bounds[2]]
                if len(boxes) != 1:
                    raise RuntimeError("Page control absent or ambiguous; action stopped")
                if spec.method == 'profile_album':
                    from wechat_auto.primitives.page_controls import (
                        find_contact_album_entry,
                    )
                    image = observer.capture()
                    if image is None or tuple(image.size) != tuple(before['state']['size']):
                        raise StaleFrameError('Profile changed before album control observation')
                    split = before['state']['geometry'].get('right_panel_candidate')
                    control = find_contact_album_entry(image, boxes[0], right=split['x'] if split else None)
                    point = tuple(control['window_fraction'])
                    used_layout = control['method']
                else:
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

    def scroll(self, x: float, y: float, notches: int, *, embedded_content: bool = False) -> dict:
        self.keyboard_only.wheel_window_fraction(x, y, notches, embedded_content=embedded_content)
        return self._receipt("scroll", point=(x, y), notches=notches,
                             embedded_content=embedded_content)

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
                             profiles_database: str = 'data/wechat_contact_profiles.sqlite3',
                             max_contact_scroll_pages: int = 30) -> dict:
        """Verified profile → personal album → bounded HWND scrolling.

        Stable local identity must be resolved by the caller. Only the profile's
        exact visible alias authenticates entry; a title/name alone never does.
        Screen stability means stalled, not a complete server download.
        """
        from wechat_auto.actions.pages import page_keys
        from wechat_auto.primitives.moments_observation import merge_album_sections
        from wechat_auto.primitives.vision import VisionAutomation
        if not expected_alias or not 1 <= max_pages <= 30 or not 1 <= max_contact_scroll_pages <= 30:
            raise ValueError('Visible alias and bounded page count are required')
        for window in self.inspect_windows():
            if window.get('status') != 'recognized':
                raise RuntimeError('Window observation unavailable before personal album selection')
            if any(s['page'] == 'moments_person' for s in window['surfaces']):
                raise RuntimeError('Close the previous personal album before selecting another contact')
        navigation = self.page_operation('open_contacts')
        if not navigation['success']:
            raise RuntimeError('Contacts navigation failed')
        self.open_contact_profile(contact, expected_alias, navigate=False,
                                  max_contact_scroll_pages=max_contact_scroll_pages)
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
        sections = {}
        status, reason = 'partial', 'page_budget'
        for _ in range(max_pages):
            observation = observer.observe_page()
            if not observation.get('ok') or 'moments_person' not in page_keys(observation['state']):
                raise RuntimeError('Personal Moments page changed during loading')
            visible = observation.get('album_observation')
            if not visible:
                raise RuntimeError('Personal album section observation unavailable')
            merge_album_sections(sections, visible['sections'])
            if visible['access_denied']:
                status, reason = 'restricted', 'visible_access_restriction'
                break
            fingerprint = visible['content_fingerprint']
            repeated = repeated + 1 if fingerprint == previous else 0
            previous = fingerprint
            if repeated >= 2:
                status, reason = 'stalled', 'unchanged_album_frame'
                break
            # The personal album is the verified content window; never scroll
            # the main chat/list when album ownership is ambiguous.
            left, top, right, bottom = visible['body_bounds']
            skill.scroll((left+right)/2, top+(bottom-top)*.7, 4,
                         embedded_content=album['target']['presentation'] == 'embedded_right_tab')
            pages += 1
            time.sleep(max(1., self._config.scroll_delay))
        final = observer.observe_page()
        if not final.get('ok') or 'moments_person' not in page_keys(final['state']):
            raise RuntimeError('Personal Moments page changed after the final scroll')
        if final.get('album_observation'):
            merge_album_sections(sections, final['album_observation']['sections'])
            if final['album_observation']['access_denied']:
                status, reason = 'restricted', 'visible_access_restriction'
        evidence = observer.shot('moments', 'personal-load-final')
        closed = False
        if target.handle != self._app.handle:
            closed = self.page_operation('close', hwnd=target.handle,
                                         expected_page='moments_person')['success']
        elif album['target']['presentation'] == 'embedded_right_tab':
            closed = self.page_operation('close_content_tab', hwnd=target.handle,
                                         expected_page='moments_person')['success']
        return self._receipt('load_contact_moments', success=True, sent=False,
                             coverage_status=status, stop_reason=reason, pages=pages,
                             evidence_ref=evidence or '', verified_by='exact_profile_alias_then_personal_page',
                             requires_navigation_restore=not closed,
                             album_hwnd=target.handle, album_presentation=album['target']['presentation'],
                             profile_capture=profile_capture,
                             section_coverage=list(sections.values()),
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
        observation = self.vision.observe_page()
        if not observation.get('ok'):
            raise RuntimeError('Contact section observation unavailable')
        state, boxes = observation['state'], observation['boxes']
        section = state.get('contact_section')
        if section is None:
            section = {'ok': False, 'error': 'contacts_page_not_observed'}
        return {'section': section, 'state': state,
                'boxes': boxes, 'size': tuple(state['size'])}

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
        """Prepare only in the current stable recipient's verified empty composer.

        ``contact`` is the verified local username, not a search/display name.
        This method never navigates, replaces an existing draft, or sends.
        """
        from wechat_auto.primitives.vision import normalize_text

        lease = getattr(self, '_recipient_lease', None)
        if not lease or lease.get('username') != contact:
            raise PermissionError('Stable contact must match the current verified recipient')
        if not text or any(ord(c) < 32 for c in text):
            raise ValueError('A nonempty printable draft body is required')
        self._activate()
        before, body, frame = self._checked_recipient_composer(lease)
        if body:
            raise RuntimeError('Existing draft present; no typing')
        size = before['state']['size']
        self.keyboard_only.click_window_fraction((frame['x']+frame['w']/2)/size[0],
                                                 (frame['y']+frame['h']*.3)/size[1])
        self.keyboard_only._type_text(text)
        time.sleep(self._config.action_delay + .5)
        _, body, current_frame = self._checked_recipient_composer(lease)
        verified = body == normalize_text(text)
        fingerprint = self._composer_fingerprint(current_frame) if verified else None
        self._prepared_text_lease = ({'recipient': lease, 'body': body,
                                     'frame': current_frame.copy(), 'fingerprint': fingerprint,
                                     'original_text': text,
                                     'expires_at': time.monotonic() + 120}
                                    if fingerprint else None)
        return self._receipt('prepare_text', success=verified, prepared=verified,
                             input_dispatched=True, sent=False,
                             cancellation_available=bool(fingerprint),
                             verified_by='verified_recipient_and_draft_ocr' if verified else 'draft_not_verified')

    def _composer_fingerprint(self, frame: dict) -> str | None:
        """Keep a private in-memory exact frame digest; never guess unseen edits."""
        import hashlib

        from PIL import Image

        image = getattr(self.vision, '_last_observed_image', None)
        if not isinstance(image, Image.Image):
            return None
        x, y, w, h = (int(frame[k]) for k in ('x', 'y', 'w', 'h'))
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x+w > image.width or y+h > image.height:
            return None
        return hashlib.sha256(image.crop((x, y, x+w, y+h)).convert('RGB').tobytes()).hexdigest()

    def cancel_prepared_text(self, contact: str) -> dict:
        """Clear only this instance's own unchanged, observed draft, once.

        Exact pixels are deliberately conservative: even a caret-only change
        can refuse cancellation. Refusal never authorizes a raw clear fallback.
        """
        draft = getattr(self, '_prepared_text_lease', None)
        lease = getattr(self, '_recipient_lease', None)
        if (not draft or lease is not draft['recipient'] or lease.get('username') != contact
                or time.monotonic() > draft['expires_at']):
            raise PermissionError('Current owned draft lease required')
        self._activate()
        observation, body, frame = self._checked_recipient_composer(lease)
        if (body != draft['body'] or frame != draft['frame']
                or self._composer_fingerprint(frame) != draft['fingerprint']):
            raise RuntimeError('Prepared draft changed; no cancellation dispatched')
        original = draft.get('original_text')
        if not isinstance(original, str) or not 1 <= len(original.encode('utf-16-le')) // 2 <= 10000:
            raise RuntimeError('Bounded original draft text required')
        from wechat_auto.primitives.attachment_observer import has_card_sized_rectangle

        image = getattr(self.vision, '_last_observed_image', None)
        boxes = sorted(observation.get('_composer_body_boxes', []), key=lambda box: (box['y'], box['x']))
        if image is None or has_card_sized_rectangle(image, frame, 45) or not boxes:
            raise RuntimeError('Exact text-only draft end unavailable')
        self._prepared_text_lease = None
        size = observation['state']['size']
        last = boxes[-1]
        end = (min(frame['x']+frame['w']-1, last['x']+last['w']+last['h']*.15)/size[0],
               (last['y']+last['h']/2)/size[1])
        clear_dispatched = False
        try:
            self.keyboard_only.click_window_fraction(*end)
            # Recheck after focus before issuing any destructive editor keys.
            _, current_body, current_frame = self._checked_recipient_composer(lease)
            if (current_body != body or current_frame != frame
                    or time.monotonic() > draft['expires_at']
                    or self._composer_fingerprint(frame) != draft['fingerprint']):
                return self._receipt('cancel_prepared_text', success=False, cancelled=False,
                                     sent=False, clear_dispatched=False,
                                     verified_by='draft_changed_after_focus', automatic_retry=False)
            with self.keyboard_only.foreground_lease():
                clear_dispatched = True
                self.keyboard_only.erase_backward(len(original.encode('utf-16-le')) // 2)
            time.sleep(self._config.action_delay + .5)
            _, remaining, _ = self._checked_recipient_composer(lease)
            return self._receipt('cancel_prepared_text', success=not remaining,
                                 cancelled=not remaining, clear_dispatched=True, sent=False,
                                 verified_by='empty_composer_observed' if not remaining else 'result_unknown',
                                 automatic_retry=False)
        except Exception as exc:
            return self._receipt('cancel_prepared_text', success=False, cancelled=False,
                                 sent=False, clear_dispatched=clear_dispatched,
                                 verified_by='result_unknown', automatic_retry=False,
                                 error_type=type(exc).__name__)

    def send_text(self, contact: str, text: str, *, confirm: bool = False,
                  before_dispatch: Callable[[], None] | None = None) -> dict:
        if not confirm:
            raise PermissionError("Sending requires confirm=True")
        lease = getattr(self, '_recipient_lease', None)
        if not lease or lease.get('username') != contact:
            raise PermissionError('Stable contact must match the current verified recipient')
        if before_dispatch is None:
            return self.send_current_verified_text(text, confirm=True)
        return self.send_current_verified_text(text, confirm=True, before_dispatch=before_dispatch)

    def prepare_mention(self, contact: str, member: str, text: str = "") -> dict:
        """Prepare only plain draft text; a verified mention chip is not supported."""
        if not member.strip():
            raise ValueError("member must not be empty")
        lease = getattr(self, '_recipient_lease', None)
        if not lease or lease.get('username') != contact or not contact.endswith('@chatroom'):
            raise PermissionError('Stable verified group recipient required')
        # prepare_text checks the current recipient and an empty composer before
        # any input, then reads the exact body back. Never accept suggestions by
        # Enter: without an observed popup that key could send the draft.
        result = self.prepare_text(contact, f"@{member}" + (f" {text}" if text else ""))
        result.update(action='prepare_mention', member=member, text=text, sent=False,
                      mention_verified=False, selection_required=True)
        return result

    def send_mention(self, contact: str, member: str, text: str = "", *,
                     confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Mention send requires confirm=True")
        if not member.strip():
            raise ValueError("member must not be empty")
        raise PermissionError('Verified group/member selection and mention chip required; no send dispatched')

    def prepare_quote(self, contact: str, message: tuple[float, float],
                      quote_menu: tuple[float, float] | None = None, text: str = "") -> dict:
        """Legacy bare points do not prove a current message or quote target."""
        raise PermissionError('Current-frame message identity and quote preview required; no quote action dispatched')

    def send_quote(self, contact: str, message: tuple[float, float],
                   quote_menu: tuple[float, float] | None = None, text: str = "", *,
                   confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Quote reply requires confirm=True")
        if not text.strip():
            raise ValueError("text must not be empty")
        # No prepared quote identity exists yet. A boolean confirmation cannot
        # authenticate an arbitrary message/menu coordinate or a quote chip.
        raise PermissionError('Current-frame message identity and quote preview required; no send dispatched')

    def copy_message(self, message: tuple[float, float], *, contact: str | None = None,
                     copy_menu: tuple[float, float] | None = None) -> dict:
        """Copy one observed message via WeChat's normal context menu.

        Clipboard contents may be private: this method never reads or returns
        them. A caller can supply a freshly observed menu point, or opt
        into OCR observation for a unique ``复制`` menu label.
        """
        navigation = self.open_chat(contact) if contact else None
        if contact and navigation.get('opened') is not True:
            raise ChatNotFoundError('chat_not_opened_or_verified')
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
        if navigation.get('opened') is not True:
            raise ChatNotFoundError('chat_not_opened_or_verified')
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

    def open_composer_context_menu(self, contact: str, *, expected_text: str | None = None) -> dict:
        """Open an empty editor or an explicitly matched text draft's menu."""
        from wechat_auto.primitives.vision import normalize_text

        lease = getattr(self, '_recipient_lease', None)
        if not lease or lease.get('username') != contact:
            raise PermissionError('Stable contact must match the current verified recipient')
        self._activate()
        observation, body, frame = self._checked_recipient_composer(lease)
        if expected_text is not None:
            if not expected_text.strip() or body != normalize_text(expected_text):
                raise RuntimeError('Draft differs from expected text; no composer menu opened')
        elif body:
            raise RuntimeError('Existing draft present; no composer menu opened')
        self._composer_menu_origin = None
        width, height = observation['state']['size']
        boxes = observation.get('_composer_body_boxes', [])
        if expected_text is not None:
            if not boxes:
                raise RuntimeError('Current text position unavailable; no composer menu opened')
            point = self._box_center_fraction(boxes[0], (width, height))
        else:
            point = ((frame['x']+frame['w']/2)/width, (frame['y']+frame['h']*.3)/height)
        self.keyboard_only.right_click_window_fraction(*point)
        self._composer_menu_origin = {'recipient': lease, 'created_at': time.monotonic()}
        time.sleep(self._config.click_delay + .5)
        return self._receipt('open_composer_context_menu', sent=False, input_dispatched=True,
                             success=False, verified_by='menu_observation_required')

    def copy_text_draft_identity(self, contact: str, text: str) -> dict:
        """Prove literal draft text through HWND selection and native Copy."""
        import hashlib
        from uuid import uuid4

        import win32clipboard
        from PIL import Image

        from wechat_auto.primitives.attachment_observer import has_card_sized_rectangle
        from wechat_auto.primitives.vision import normalize_text
        from wechat_auto.utils.screenshot import ScreenshotHelper

        if not text or any(ord(c) < 32 for c in text):
            raise ValueError('Exact printable text required')
        lease = getattr(self, '_recipient_lease', None)
        if not lease or lease.get('username') != contact:
            raise PermissionError('Verified stable recipient required')
        self._activate()

        def checked(popup=None):
            observation, body, frame = self._checked_recipient_composer(lease, allowed_popup=popup)
            image = getattr(self.vision, '_last_observed_image', None)
            if (body != normalize_text(text) or not isinstance(image, Image.Image)
                    or has_card_sized_rectangle(image, frame, 45)):
                raise RuntimeError('Exact text-only draft not verified; no Copy dispatched')
            return observation, frame

        before, frame = checked()
        boxes = sorted(before.get('_composer_body_boxes', []), key=lambda b: (b['y'], b['x']))
        if not boxes:
            raise RuntimeError('Current text selection bounds unavailable')
        width, height = before['state']['size']
        first, last = boxes[0], boxes[-1]
        start = (max(frame['x'] + 2, first['x'] - first['h'] * .5) / width,
                 (first['y'] + first['h'] / 2) / height)
        end = ((frame['x'] + frame['w'] - 3) / width,
               (last['y'] + last['h'] / 2) / height)
        ClipboardHelper.set_text('wechat-auto-text-copy-' + uuid4().hex)
        sequence = win32clipboard.GetClipboardSequenceNumber()
        self.keyboard_only.drag_window_fraction(start, end)
        labels = {'复制', '复制(ctrl+c)', '复制ctrl+c', '复制（ctrl+c）'}
        started = time.monotonic()
        self.open_composer_context_menu(contact, expected_text=text)
        current, target, menu, observation = self._consume_composer_context_menu()
        if current is not lease or checked(menu)[1] != frame:
            raise StaleFrameError('Text recipient or composer changed')
        matches = [b for b in observation.get('boxes', []) if b.get('score', 0) >= .65
                   and normalize_text(b['text']).casefold() in labels]
        size = observation.get('state', {}).get('size')
        if (len(matches) != 1 or size != [menu['rect'][2]-menu['rect'][0],
                                         menu['rect'][3]-menu['rect'][1]]):
            raise RuntimeError('Exact native text menu control unavailable')
        image = ScreenshotHelper().capture_window(menu['hwnd'])
        if (image is None or not observation.get('_menu_frame_sha256')
                or hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()
                != observation['_menu_frame_sha256']):
            raise StaleFrameError('Native text menu pixels changed')
        if (time.monotonic() - started > 120 or self._recipient_lease is not lease
                or win32clipboard.GetClipboardSequenceNumber() != sequence
                or self._app.describe_window(menu['hwnd']) != menu):
            raise StaleFrameError('Text menu or clipboard changed before dispatch')
        child = BasicSkill(target, self._config, self._session)
        child.keyboard_only.foreground_mode = 'never'
        child.keyboard_only.click_window_fraction(*self._box_center_fraction(matches[0], tuple(size)))
        time.sleep(self._config.action_delay + .5)
        copied_sequence = win32clipboard.GetClipboardSequenceNumber()
        literal_match = copied_sequence != sequence and ClipboardHelper.get_text() == text
        _, current_frame = checked()
        verified = (literal_match and current_frame == frame
                    and win32clipboard.GetClipboardSequenceNumber() == copied_sequence)
        return self._receipt('copy_text_draft_identity', success=bool(verified),
                             identity_verified=bool(verified), sent=False,
                             deletion_dispatched=False, automatic_retry=False,
                             verified_by='native_literal_text_copy' if verified else 'literal_text_not_verified')

    def delete_verified_text(self, contact: str, text: str, *, confirm_discard: bool = False) -> dict:
        """Delete an explicitly approved exact draft through native editor characters."""
        from wechat_auto.primitives.attachment_observer import has_card_sized_rectangle
        from wechat_auto.primitives.vision import normalize_text

        if not confirm_discard:
            raise PermissionError('Deleting the current draft requires explicit confirmation')
        lease = getattr(self, '_recipient_lease', None)
        if not lease or lease.get('username') != contact or not text.strip():
            raise PermissionError('Verified recipient and exact nonempty draft required')
        expected = normalize_text(text)
        observation, body, frame = self._checked_recipient_composer(lease)
        if body != expected:
            raise RuntimeError('Draft differs from explicitly approved text; no deletion')
        image = getattr(self.vision, '_last_observed_image', None)
        if image is None or has_card_sized_rectangle(image, frame, 45):
            raise RuntimeError('Non-text draft content cannot be discarded as text')
        boxes = sorted(observation.get('_composer_body_boxes', []), key=lambda box: (box['y'], box['x']))
        if not boxes:
            raise RuntimeError('Exact draft text position unavailable')
        width, height = observation['state']['size']
        last = boxes[-1]
        end = (min(frame['x']+frame['w']-1, last['x']+last['w']+last['h']*.15)/width,
               (last['y']+last['h']/2)/height)
        self.keyboard_only.click_window_fraction(*end)
        _, current_body, current_frame = self._checked_recipient_composer(lease)
        if current_body != expected or current_frame != frame:
            raise RuntimeError('Draft changed after focus; no deletion')
        self._prepared_text_lease = None
        self.keyboard_only.erase_backward(len(text.encode('utf-16-le')) // 2)
        time.sleep(self._config.action_delay + .5)
        _, remaining, _ = self._checked_recipient_composer(lease)
        return self._receipt('delete_verified_text', success=not remaining, deleted=not remaining,
                             delete_dispatched=True, sent=False, automatic_retry=False,
                             verified_by='empty_composer_observed' if not remaining else 'result_unknown')

    def _consume_composer_context_menu(self, *, expected_origin_id: str | None = None):
        from wechat_auto.primitives.vision import VisionAutomation, normalize_text

        origin = getattr(self, '_composer_menu_origin', None)
        self._composer_menu_origin = None
        lease = getattr(self, '_recipient_lease', None)
        if (not origin or lease is not origin['recipient']
                or time.monotonic()-origin['created_at'] > 120):
            raise PermissionError('Current composer menu origin required')
        if expected_origin_id is not None and origin.get('origin_id') != expected_origin_id:
            raise PermissionError('Composer menu origin was replaced')
        main = self._app.describe_window(self._app.handle)
        if any(main[k] != lease['metadata'][k] for k in ('hwnd', 'pid', 'rect', 'client_rect', 'dpi')):
            raise RuntimeError('Composer owner changed; no dismissal dispatched')
        auxiliary = [w for w in self._app.list_windows() if not w['is_main']]
        if (len(auxiliary) != 1 or auxiliary[0]['pid'] != main['pid']
                or auxiliary[0]['owner_hwnd'] != self._app.handle
                or 'ToolSaveBits' not in auxiliary[0]['class']):
            raise RuntimeError('Unique owned composer menu unavailable')
        before = auxiliary[0]
        target = self._app.for_window(before['hwnd'])
        observer = VisionAutomation(target, self._config)
        observation = observer.observe_page()
        from PIL import Image

        image = getattr(observer, '_last_observed_image', None)
        if isinstance(image, Image.Image):
            import hashlib

            observation['_menu_frame_sha256'] = hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()
        labels = {normalize_text(b['text']).casefold() for b in observation.get('boxes', [])}
        paste = {'粘贴', '粘贴(ctrl+v)', '粘贴（ctrl+v）', '粘贴ctrl+v'}
        editing = {'全选', '全选(ctrl+a)', '全选ctrl+a', '剪切', '复制', '边写边译'}
        image_menu = (origin.get('kind') == 'image_preview'
                      and {'剪切', '复制', '编辑'} <= labels
                      and any(label.rstrip('.。…') == '另存为' for label in labels))
        if not observation.get('ok') or not (image_menu or (labels & paste and labels & editing)):
            raise RuntimeError('Composer menu anchors absent; no dismissal dispatched')
        after = self._app.describe_window(before['hwnd'])
        if any(before[k] != after[k] for k in ('hwnd', 'pid', 'rect', 'client_rect', 'dpi', 'owner_hwnd', 'class')):
            raise StaleFrameError('Composer menu changed during observation')
        return lease, target, before, observation

    def dismiss_composer_context_menu(self) -> dict:
        """Dismiss only this instance's newly opened, observed editor menu."""
        _, target, before, _ = self._consume_composer_context_menu()
        child = BasicSkill(target, self._config, self._session)
        child.keyboard_only.foreground_mode = 'never'
        child.keyboard_only.press_key('escape')
        time.sleep(self._config.click_delay + .5)
        dismissed = all(w['hwnd'] != before['hwnd'] for w in self._app.list_windows())
        return self._receipt('dismiss_composer_context_menu', success=dismissed, sent=False,
                             input_dispatched=True, verified_by='owned_menu_disappeared' if dismissed else 'result_unknown')

    def _paste_attachment_via_menu(self, lease: dict, path: str, clipboard_matches) -> None:
        """Select only this newly opened editor menu's exact Paste, once."""
        from wechat_auto.primitives.vision import normalize_text

        self.open_composer_context_menu(lease['username'])
        current_lease, target, menu, observation = self._consume_composer_context_menu()
        if current_lease is not lease:
            raise RuntimeError('Recipient changed; no paste dispatched')
        _, body, _ = self._checked_recipient_composer(lease, allowed_popup=menu)
        if body:
            raise RuntimeError('Draft changed while opening menu; no attachment pasted')
        matches = [b for b in observation.get('boxes', []) if b.get('score', 0) >= .65
                   and normalize_text(b['text']).casefold() in {
                       '粘贴', '粘贴(ctrl+v)', '粘贴（ctrl+v）', '粘贴ctrl+v'}]
        size = observation.get('state', {}).get('size')
        if (len(matches) != 1 or size != [menu['rect'][2]-menu['rect'][0],
                                         menu['rect'][3]-menu['rect'][1]]):
            raise RuntimeError('Exact current Paste control absent or ambiguous')
        if not clipboard_matches(path):
            raise RuntimeError('Attachment clipboard payload changed; no attachment pasted')
        fresh = self._app.describe_window(menu['hwnd'])
        if any(fresh[k] != menu[k] for k in ('hwnd', 'pid', 'class', 'owner_hwnd', 'rect', 'client_rect', 'dpi')):
            raise StaleFrameError('Composer menu changed before paste')
        child = BasicSkill(target, self._config, self._session)
        child.keyboard_only.foreground_mode = 'never'
        child.keyboard_only.click_window_fraction(*self._box_center_fraction(matches[0], tuple(size)))

    def _current_attachment_card(self, contact: str, path: str, *, allowed_popup: dict | None = None):
        """Return only a current-frame candidate, never a send authorization."""
        from wechat_auto.primitives.attachment_observer import find_file_card

        lease = getattr(self, '_recipient_lease', None)
        if not lease or lease.get('username') != contact:
            raise PermissionError('Stable contact must match the current verified recipient')
        payload = Path(path).resolve(strict=True)
        if not payload.is_file():
            raise ValueError('Expected a local file')
        self._activate()
        observation, _, frame = (self._checked_recipient_composer(lease) if allowed_popup is None
                                  else self._checked_recipient_composer(lease, allowed_popup=allowed_popup))
        card = find_file_card(self.vision._last_observed_image, observation['boxes'], frame,
                              payload.name, payload.stat().st_size)
        current = self._app.describe_window(self._app.handle)
        if any(current[k] != lease['metadata'][k] for k in ('hwnd', 'pid', 'rect', 'client_rect', 'dpi')):
            raise StaleFrameError('Attachment window changed before observation action')
        return card, lease

    def hover_attachment_card(self, contact: str, path: str) -> dict:
        """Observe one current file-card candidate and request its tooltip only."""
        card, _ = self._current_attachment_card(contact, path)
        self.keyboard_only.hover_window_fraction(*card['window_fraction'])
        time.sleep(self._config.action_delay + 1)
        return self._receipt('hover_attachment_card', sent=False, input_dispatched=True,
                             success=False, identity_verified=False, candidate=card,
                             verified_by='tooltip_observation_required')

    def open_attachment_context_menu(self, contact: str, path: str) -> dict:
        """Open a candidate card's menu without selecting any command."""
        from uuid import uuid4

        card, lease = self._current_attachment_card(contact, path)
        self._composer_menu_origin = None
        self.keyboard_only.right_click_window_fraction(*card['window_fraction'])
        origin_id = uuid4().hex
        self._composer_menu_origin = {'recipient': lease, 'created_at': time.monotonic(),
                                      'kind': 'attachment_card', 'candidate': card, 'origin_id': origin_id}
        time.sleep(self._config.click_delay + .5)
        return self._receipt('open_attachment_context_menu', sent=False, input_dispatched=True,
                             success=False, identity_verified=False, candidate=card,
                             menu_origin_id=origin_id,
                             verified_by='menu_observation_required')

    def copy_attachment_identity(self, contact: str, path: str) -> dict:
        """Read an unsent card through native Copy; never Cut/Delete/Send."""
        from uuid import uuid4

        import win32clipboard

        from wechat_auto.primitives.vision import normalize_text

        payload = Path(path).resolve(strict=True)
        expected_size = payload.stat().st_size
        expected_hash = ClipboardHelper.file_sha256(payload)
        self._attachment_identity_lease = None
        self._current_attachment_card(contact, str(payload))
        ClipboardHelper.set_text('wechat-auto-copy-check-' + uuid4().hex)
        sequence = win32clipboard.GetClipboardSequenceNumber()
        opened = self.open_attachment_context_menu(contact, str(payload))
        origin = self._composer_menu_origin
        if (not origin or origin.get('kind') != 'attachment_card'
                or not opened.get('menu_origin_id') or opened['menu_origin_id'] != origin.get('origin_id')):
            raise PermissionError('Attachment card menu origin required')
        lease, target, menu, observation = self._consume_composer_context_menu(expected_origin_id=opened['menu_origin_id'])
        card, current_lease = self._current_attachment_card(contact, str(payload), allowed_popup=menu)
        if current_lease is not lease or card['box'] != origin['candidate']['box']:
            raise StaleFrameError('Attachment card changed while observing its menu')
        labels = {normalize_text(b['text']).casefold() for b in observation.get('boxes', [])}
        if not {'剪切', '复制', '粘贴', '删除'} <= labels:
            raise RuntimeError('Attachment selection menu anchors absent; no Copy dispatched')
        copy = [b for b in observation.get('boxes', []) if b.get('score', 0) >= .65
                and normalize_text(b['text']).casefold() in {'复制', '复制(ctrl+c)', '复制ctrl+c'}]
        size = observation.get('state', {}).get('size')
        if len(copy) != 1 or size != [menu['rect'][2]-menu['rect'][0], menu['rect'][3]-menu['rect'][1]]:
            raise RuntimeError('Exact Copy control absent or ambiguous')
        if win32clipboard.GetClipboardSequenceNumber() != sequence:
            raise RuntimeError('Clipboard changed while observing Copy; no Copy dispatched')
        if time.monotonic()-origin['created_at'] > 120:
            raise PermissionError('Attachment Copy origin expired')
        fresh = self._app.describe_window(menu['hwnd'])
        if any(fresh[k] != menu[k] for k in ('hwnd', 'pid', 'class', 'owner_hwnd', 'rect', 'client_rect', 'dpi')):
            raise StaleFrameError('Attachment menu changed before Copy')
        child = BasicSkill(target, self._config, self._session)
        child.keyboard_only.foreground_mode = 'never'
        child.keyboard_only.click_window_fraction(*self._box_center_fraction(copy[0], tuple(size)))
        time.sleep(self._config.action_delay + .5)
        try:
            verified = (win32clipboard.GetClipboardSequenceNumber() != sequence
                        and ClipboardHelper.copied_file_matches(payload.name, expected_size, expected_hash)
                        and payload.stat().st_size == expected_size
                        and ClipboardHelper.file_sha256(payload) == expected_hash)
        except Exception as exc:
            return self._receipt('copy_attachment_identity', success=False, identity_verified=False,
                                 sent=False, dispatched=True, automatic_retry=False,
                                 verified_by='clipboard_result_unknown', error_type=type(exc).__name__)
        if verified:
            try:
                current_card, current_lease = self._current_attachment_card(contact, str(payload))
                rect = dict(zip(('x', 'y', 'w', 'h'), card['box'], strict=True))
                digest = self._composer_fingerprint(rect)
                verified = current_lease is lease and current_card['box'] == card['box'] and bool(digest)
            except Exception as exc:
                return self._receipt('copy_attachment_identity', success=False, identity_verified=False,
                                     sent=False, dispatched=True, automatic_retry=False,
                                     verified_by='clipboard_result_unknown', error_type=type(exc).__name__)
            if verified:
                self._attachment_identity_lease = {'recipient': lease, 'path': str(payload),
                                                   'sha256': expected_hash, 'size': expected_size,
                                                   'card': card, 'card_digest': digest,
                                                   'created_at': time.monotonic()}
        return self._receipt('copy_attachment_identity', success=bool(verified),
                             identity_verified=bool(verified), sent=False, dispatched=True,
                             automatic_retry=False, verified_by='copied_file_full_name_and_sha256'
                             if verified else 'clipboard_file_identity_not_verified')

    def cancel_verified_attachment(self, contact: str, path: str, *, confirm_discard: bool = False) -> dict:
        """Remove only one freshly verified unsent card; never clear the editor."""
        from wechat_auto.primitives.attachment_observer import (
            has_card_sized_rectangle,
            text_outside_card,
        )
        from wechat_auto.primitives.vision import normalize_text

        if not confirm_discard:
            raise PermissionError('Explicit discard of this verified draft attachment required')
        identity = getattr(self, '_attachment_identity_lease', None)
        lease = getattr(self, '_recipient_lease', None)
        if (not identity or lease is not identity['recipient'] or lease.get('username') != contact
                or time.monotonic()-identity['created_at'] > 120
                or Path(path).resolve(strict=True) != Path(identity['path'])):
            raise PermissionError('Current verified attachment identity required')
        self._attachment_identity_lease = None
        payload = Path(identity['path'])
        if payload.stat().st_size != identity['size'] or ClipboardHelper.file_sha256(payload) != identity['sha256']:
            raise RuntimeError('Verified source changed; no draft cancellation dispatched')
        card, current_lease = self._current_attachment_card(contact, str(payload))
        if current_lease is not lease or card['box'] != identity['card']['box']:
            raise StaleFrameError('Verified attachment card changed')
        observation, _, _ = self._checked_recipient_composer(lease)
        outside = text_outside_card(observation['_composer_body_boxes'], card['box'])
        if outside:
            raise RuntimeError('Other draft text present; no attachment cancellation dispatched')
        rect = dict(zip(('x', 'y', 'w', 'h'), card['box'], strict=True))
        digest = self._composer_fingerprint(rect)
        if not digest or digest != identity.get('card_digest'):
            raise StaleFrameError('Attachment card differs from the verified identity frame')
        opened = self.open_attachment_context_menu(contact, str(payload))
        if not opened.get('menu_origin_id'):
            raise PermissionError('Draft cancellation menu origin missing')
        current_lease, target, menu, menu_observation = self._consume_composer_context_menu(expected_origin_id=opened['menu_origin_id'])
        current_card, _ = self._current_attachment_card(contact, str(payload), allowed_popup=menu)
        current_observation, _, _ = self._checked_recipient_composer(lease, allowed_popup=menu)
        labels = {normalize_text(b['text']) for b in menu_observation.get('boxes', [])}
        changes = {
            'recipient': current_lease is not lease,
            'card_geometry': current_card['box'] != card['box'],
            'card_pixels': self._composer_fingerprint(rect) != digest,
            'other_text': text_outside_card(current_observation['_composer_body_boxes'], card['box']) != outside,
            'menu_anchors': not {'剪切', '复制', '粘贴', '删除'} <= labels,
            'expired': time.monotonic()-identity['created_at'] > 120,
        }
        if any(changes.values()):
            raise StaleFrameError('Draft cancellation blocked: ' + ','.join(k for k, changed in changes.items() if changed))
        buttons = [b for b in menu_observation.get('boxes', [])
                   if normalize_text(b['text']) == '删除' and b.get('score', 0) >= .65]
        size = menu_observation.get('state', {}).get('size')
        if len(buttons) != 1 or size != [menu['rect'][2]-menu['rect'][0], menu['rect'][3]-menu['rect'][1]]:
            raise RuntimeError('Exact draft removal control unavailable')
        fresh = self._app.describe_window(menu['hwnd'])
        if any(fresh[k] != menu[k] for k in ('hwnd', 'pid', 'class', 'owner_hwnd', 'rect', 'client_rect', 'dpi')):
            raise StaleFrameError('Attachment menu changed before draft cancellation')
        if payload.stat().st_size != identity['size'] or ClipboardHelper.file_sha256(payload) != identity['sha256']:
            raise RuntimeError('Verified source changed before draft cancellation')
        child = BasicSkill(target, self._config, self._session)
        child.keyboard_only.foreground_mode = 'never'
        try:
            child.keyboard_only.click_window_fraction(*self._box_center_fraction(buttons[0], tuple(size)))
            time.sleep(self._config.action_delay + .5)
            after, _, frame = self._checked_recipient_composer(lease)
            remaining = has_card_sized_rectangle(self.vision._last_observed_image, frame, card['box'][3]*.6)
            preserved = text_outside_card(after['_composer_body_boxes'], [0, 0, 0, 0]) == outside
            source_ok = payload.stat().st_size == identity['size'] and ClipboardHelper.file_sha256(payload) == identity['sha256']
            verified = not remaining and preserved and source_ok
            return self._receipt('cancel_verified_attachment', success=verified, cancelled=verified,
                                 dispatched=True, sent=False, automatic_retry=False,
                                 verified_by='card_absent_other_text_and_source_preserved' if verified else 'result_unknown')
        except Exception as exc:
            return self._receipt('cancel_verified_attachment', success=False, cancelled=False,
                                 dispatched=True, sent=False, automatic_retry=False,
                                 verified_by='result_unknown', error_type=type(exc).__name__)

    def _prepare_clipboard_payload(self, contact: str, setter, value: str, *, clipboard_matches) -> dict:
        lease = getattr(self, '_recipient_lease', None)
        if not lease or lease.get('username') != contact:
            raise PermissionError('Stable contact must match the current verified recipient')
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"Expected a file: {path}")
        self._activate()
        _, body, _ = self._checked_recipient_composer(lease)
        if body:
            raise RuntimeError('Existing draft present; no attachment pasted')
        setter(str(path))
        # Clipboard conversion may be slow. Observe again before touching the
        # editor; a previous successful identity check cannot authorize a new page.
        observation, body, frame = self._checked_recipient_composer(lease)
        if body:
            raise RuntimeError('Existing draft appeared; no attachment pasted')
        width, height = observation['state']['size']
        self.keyboard_only.click_window_fraction((frame['x']+frame['w']/2)/width,
                                                 (frame['y']+frame['h']*.3)/height)
        _, body, _ = self._checked_recipient_composer(lease)
        if body:
            raise RuntimeError('Draft changed after focus; no attachment pasted')
        if not clipboard_matches(str(path)):
            raise RuntimeError('Attachment clipboard payload changed; no attachment pasted')
        self._paste_attachment_via_menu(lease, str(path), clipboard_matches)
        return {"transport": "hwnd", "path": str(path), "sent": False,
                "paste_method": "owned_composer_menu",
                "input_dispatched": True, "prepared": False,
                "verified_by": "attachment_preview_not_verified"}

    def prepare_file(self, contact: str, path: str) -> dict:
        self._attachment_identity_lease = None
        payload = Path(path).expanduser().resolve(strict=True)
        if not payload.is_file():
            raise ValueError('Expected a local file')
        expected_size = payload.stat().st_size
        expected_hash = ClipboardHelper.file_sha256(payload)
        recipient = getattr(self, '_recipient_lease', None)
        result = self._prepare_clipboard_payload(
            contact, lambda value: ClipboardHelper.set_files([value]), str(payload),
            clipboard_matches=lambda value: ClipboardHelper.files_match([value]),
        )
        result.update(action='prepare_file', success=False, identity_verified=False,
                      automatic_retry=False)
        try:
            if (payload.stat().st_size != expected_size
                    or ClipboardHelper.file_sha256(payload) != expected_hash):
                raise RuntimeError('Source changed during attachment preparation')
            copied = self.copy_attachment_identity(contact, str(payload))
            identity = getattr(self, '_attachment_identity_lease', None)
            verified = bool(copied.get('identity_verified') and identity
                            and identity.get('recipient') is recipient
                            and getattr(self, '_recipient_lease', None) is recipient
                            and identity.get('path') == str(payload)
                            and identity.get('size') == expected_size
                            and identity.get('sha256') == expected_hash
                            and identity.get('card_digest')
                            and 0 <= time.monotonic()-identity['created_at'] <= 120
                            and payload.stat().st_size == expected_size
                            and ClipboardHelper.file_sha256(payload) == expected_hash)
            if verified:
                result.update(prepared=True, success=True, identity_verified=True,
                              verified_by='prepared_file_full_identity_and_current_card')
            else:
                self._attachment_identity_lease = None
        except Exception as exc:
            self._attachment_identity_lease = None
            result['error_type'] = type(exc).__name__
        return result

    def send_file(self, contact: str, path: str, *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("File send requires confirm=True")
        # Preparation is independently useful, but its receipt cannot release
        # the old blind Enter path. Submission needs its own current-frame
        # payload/recipient check and an observable outgoing-file verifier.
        raise PermissionError('Current file submission and result verification required; no send dispatched')

    def prepare_image(self, contact: str, path: str) -> dict:
        payload = Path(path).expanduser().resolve(strict=True)
        original_hash = ClipboardHelper.file_sha256(payload)
        recipient = getattr(self, '_recipient_lease', None)
        result = self._prepare_clipboard_payload(contact, ClipboardHelper.set_image, str(payload),
                                                 clipboard_matches=ClipboardHelper.image_matches)
        result.update(action='prepare_image', success=False, prepared=False,
                      identity_verified=False, automatic_retry=False)
        try:
            if ClipboardHelper.file_sha256(payload) != original_hash:
                raise RuntimeError('Image source changed during preparation')
            copied = self.copy_image_identity(contact, str(payload))
            if (copied.get('success') and copied.get('identity_verified')
                    and getattr(self, '_recipient_lease', None) is recipient
                    and ClipboardHelper.file_sha256(payload) == original_hash):
                result.update(success=True, prepared=True, identity_verified=True,
                              verified_by='native_copied_image_pixels_and_current_preview')
            else:
                result.update(verification_stage=copied.get('failed_stage'),
                              error_type=copied.get('error_type'))
        except Exception as exc:
            result['error_type'] = type(exc).__name__
        return result

    def copy_image_identity(self, contact: str, path: str) -> dict:
        """Observe one image through native Copy without removing or sending it."""
        return self._image_draft_operation(contact, path, discard=False)

    def cancel_verified_image(self, contact: str, path: str, *, confirm_discard: bool = False) -> dict:
        """Discard one exact image draft only after native Copy proves its pixels."""
        if not confirm_discard:
            raise PermissionError('Explicit image draft discard required')
        return self._image_draft_operation(contact, path, discard=True)

    def _image_draft_operation(self, contact: str, path: str, *, discard: bool) -> dict:
        from uuid import uuid4

        import win32clipboard

        from wechat_auto.primitives.attachment_observer import text_outside_card
        from wechat_auto.primitives.vision import normalize_text

        lease = getattr(self, '_recipient_lease', None)
        if not lease or lease.get('username') != contact:
            raise PermissionError('Current verified recipient required')
        payload = Path(path).resolve(strict=True)
        source_hash = ClipboardHelper.file_sha256(payload)
        action = 'cancel_verified_image' if discard else 'copy_image_identity'
        dispatched = False
        copy_dispatched = False
        identity_verified = False
        stage = 'observe_image'

        def checked(popup=None):
            observation, _, frame = self._checked_recipient_composer(
                lease, allowed_popup=popup, expected_image=payload)
            candidate = observation['_image_preview']
            if text_outside_card(observation['_composer_body_boxes'], candidate['box']):
                raise RuntimeError('Other draft text present')
            if ClipboardHelper.file_sha256(payload) != source_hash:
                raise RuntimeError('Source image changed')
            return observation, frame, candidate

        def content_digest(candidate):
            x, y, w, h = candidate['box']
            return self._composer_fingerprint({'x': x+5, 'y': y+5, 'w': w-10, 'h': h-10})

        def command(label, sequence, guard=None):
            nonlocal dispatched, copy_dispatched, stage
            stage = 'copy_menu' if label == '复制' else 'cut_menu'
            _, frame, candidate = checked()
            if guard and (frame != guard[0] or candidate['box'] != guard[1]
                          or content_digest(candidate) != guard[2]):
                raise StaleFrameError('Image changed before menu')
            self.keyboard_only.right_click_window_fraction(*candidate['window_fraction'])
            time.sleep(self._config.action_delay + .5)
            origin_id = uuid4().hex
            self._composer_menu_origin = {'recipient': lease, 'created_at': time.monotonic(),
                                         'origin_id': origin_id, 'kind': 'image_preview'}
            current, target, menu, observed = self._consume_composer_context_menu(
                expected_origin_id=origin_id)
            _, current_frame, current_candidate = checked(menu)
            labels = {normalize_text(b['text']) for b in observed.get('boxes', [])}
            image_menu = ({'剪切', '复制', '编辑'} <= labels
                          and any(item.rstrip('.。…') == '另存为' for item in labels))
            selection_menu = {'剪切', '复制', '粘贴', '删除'} <= labels
            if current is not lease or not (image_menu or selection_menu):
                raise RuntimeError('Exact image selection menu unavailable')
            if current_frame != frame or current_candidate['box'] != candidate['box']:
                raise StaleFrameError('Image geometry changed under menu')
            if guard and content_digest(current_candidate) != guard[2]:
                raise StaleFrameError('Image pixels changed under menu')
            buttons = [b for b in observed['boxes'] if normalize_text(b['text']) == label
                       and b.get('score', 0) >= .65]
            size = observed.get('state', {}).get('size')
            fresh = self._app.describe_window(menu['hwnd'])
            if (len(buttons) != 1 or size != [menu['rect'][2]-menu['rect'][0],
                                             menu['rect'][3]-menu['rect'][1]]
                    or any(fresh[k] != menu[k] for k in (
                        'hwnd', 'pid', 'class', 'owner_hwnd', 'rect', 'client_rect', 'dpi'))
                    or win32clipboard.GetClipboardSequenceNumber() != sequence
                    or ClipboardHelper.file_sha256(payload) != source_hash):
                raise StaleFrameError('Image menu or clipboard/source changed')
            child = BasicSkill(target, self._config, self._session)
            child.keyboard_only.foreground_mode = 'never'
            if label == '剪切':
                dispatched = True
            else:
                copy_dispatched = True
            child.keyboard_only.click_window_fraction(*self._box_center_fraction(buttons[0], tuple(size)))
            time.sleep(self._config.action_delay + .5)

        try:
            checked()
            ClipboardHelper.set_text('wechat-auto-image-copy-' + uuid4().hex)
            sequence = win32clipboard.GetClipboardSequenceNumber()
            command('复制', sequence)
            stage = 'native_copy_pixels'
            if (win32clipboard.GetClipboardSequenceNumber() == sequence
                    or not ClipboardHelper.copied_image_matches(str(payload))):
                raise RuntimeError('Copied image pixels do not match source')
            identity_verified = True
            sequence = win32clipboard.GetClipboardSequenceNumber()
            _, frame, candidate = checked()
            digest = content_digest(candidate)
            if not digest:
                raise RuntimeError('Image frame digest unavailable')
            if not discard:
                if win32clipboard.GetClipboardSequenceNumber() != sequence:
                    raise RuntimeError('Image clipboard changed during final observation')
                return self._receipt(action, success=True, identity_verified=True,
                                     dispatched=True, copy_dispatched=True, sent=False, automatic_retry=False,
                                     verified_by='native_copied_image_pixels_and_current_preview')
            command('剪切', sequence, (frame, candidate['box'], digest))
            stage = 'verify_empty_composer'
            _, remaining, _ = self._checked_recipient_composer(lease)
            verified = (not remaining and ClipboardHelper.file_sha256(payload) == source_hash
                        and ClipboardHelper.copied_image_matches(str(payload)))
            return self._receipt(action, success=verified, cancelled=verified,
                                 dispatched=dispatched, identity_verified=True, sent=False,
                                 automatic_retry=False, verified_by='copied_pixels_and_empty_composer_source_preserved'
                                 if verified else 'result_unknown')
        except Exception as exc:
            return self._receipt(action, success=False, cancelled=False,
                                 dispatched=dispatched if discard else copy_dispatched,
                                 copy_dispatched=copy_dispatched, identity_verified=identity_verified, sent=False,
                                 automatic_retry=False, failed_stage=stage, error_type=type(exc).__name__,
                                 verified_by='result_unknown' if dispatched else 'image_discard_not_dispatched')

    def send_image(self, contact: str, path: str, *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Image send requires confirm=True")
        raise PermissionError('Current image preview and result verification required; no send dispatched')

    def open_emoji(self) -> dict:
        return self.page_operation('open_emoji_panel')

    def open_emoji_favorites(self) -> dict:
        """Open the favorites tab by its current public glyph; never send a cell."""
        from wechat_auto.primitives.page_controls import (
            emoji_favorites_selected,
            find_emoji_favorites_control,
        )
        from wechat_auto.primitives.vision import VisionAutomation

        windows=[w for w in self._app.list_windows() if not w['is_main']]
        metadata=self._app.describe_window(self._app.handle)
        if (len(windows)!=1 or windows[0]['pid']!=metadata['pid']
                or windows[0]['owner_hwnd'] not in {0,self._app.handle}
                or 'ToolSaveBits' not in windows[0]['class']):
            raise RuntimeError('Unique same-process emoji popup required')
        target=self._app.for_window(windows[0]['hwnd'])
        observer=VisionAutomation(target,self._config)
        before=observer.observe_page()
        if not before.get('ok') or not any(p['key']=='emoji_panel' for p in before['state']['panels']):
            raise RuntimeError('Current native emoji popup not recognized')
        heart=find_emoji_favorites_control(observer._last_observed_image)
        if not emoji_favorites_selected(observer._last_observed_image,heart):
            current=self._app.describe_window(target.handle)
            if any(current[k]!=windows[0][k] for k in ('hwnd','pid','rect','client_rect','dpi')):
                raise StaleFrameError('Emoji popup changed before tab selection')
            child=BasicSkill(target,self._config,self._session)
            child.keyboard_only.foreground_mode='never'
            child.keyboard_only.click_window_fraction(*heart['window_fraction'])
            time.sleep(self._config.action_delay+.5)
        after=observer.observe_page()
        selected=(after.get('ok') and emoji_favorites_selected(observer._last_observed_image,
                  find_emoji_favorites_control(observer._last_observed_image)))
        return self._receipt('open_emoji_favorites',success=bool(selected),sent=False,
                             verified_by='current_heart_tab_backplate',automatic_retry=False)

    def send_sticker(self, cell: tuple[float, float], *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError("Sticker send requires confirm=True")
        raise RuntimeError('Sticker sending requires current-frame asset matching; raw cell coordinates are not accepted')

    def send_sticker_by_id(self, contact: str, sticker_id: str, catalog_path: str,
                           *, confirm: bool = False) -> dict:
        if not confirm:
            raise PermissionError('Sticker send requires confirm=True')
        raise RuntimeError('Stored sticker cell coordinates were removed; identify the asset in the current panel')

    def open_moments(self) -> dict:
        return {**self.navigate_page('moments_feed'), 'action': 'open_moments'}

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
