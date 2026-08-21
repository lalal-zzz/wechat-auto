"""Moments skill - full Moments automation scenarios (Tier 1)."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from pywinauto import Desktop

from wechat_auto.skills.base import BaseSkill
from wechat_auto.exceptions import MomentsError
from wechat_auto.utils.keyboard import KeyboardHelper
from wechat_auto.utils.retry import retry_on_failure

logger = logging.getLogger(__name__)


class MomentsSkill(BaseSkill):
    """Moments (朋友圈) full-scenario automation.

    Tier 1 skill covering:
        - like_moment (implemented)
        - browse / get_my_timeline (implemented)
        - comment_moment (stub)
        - publish_moment (stub)
        - get_friend_moments (stub)
        - get_my_own_moments (stub)
    """

    name = "like_moment"

    def _run(self, **params) -> Any:
        count = params.get("count", 5)
        return self.like_latest(count)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _open_moments(self) -> None:
        """Navigate to the Moments feed and capture the popup window.

        WeChat Moments opens in a standalone top-level window (class SNSWnd
        or similar), NOT embedded in the main window. We click the button
        and then search the Desktop for the newly-appeared Moments window,
        reassigning self._moments_window for all subsequent operations.
        """
        self._moments_window = None
        try:
            # Try finding Moments button by keyword
            moments_btn = self._finder.find_child_by_title(
                self.window,
                self._config.kw_moments,
                timeout=self._config.find_element_timeout,
            )
            self._finder.click(moments_btn)
        except Exception:
            # Fallback: Ctrl+4 shortcut for Moments
            logger.debug("Moments button not found by title, trying Ctrl+4 shortcut.")
            self.window.type_keys("^4")

        # Wait for the Moments window to appear (it may take a moment to load)
        deadline = time.monotonic() + self._config.page_load_timeout
        while time.monotonic() < deadline:
            time.sleep(0.5)
            moments_win = self._find_moments_popup()
            if moments_win:
                self._moments_window = moments_win
                logger.info("Captured Moments popup window.")
                return

        # Fallback: if no separate popup found, use main window
        logger.warning("Moments popup not found; operating on main window.")
        self._moments_window = self.window

    def _find_moments_popup(self):
        """Scan Desktop for the Moments standalone window."""
        try:
            desktop = Desktop(backend=self._config.backend)
            for win in desktop.windows():
                try:
                    cls = win.class_name()
                    title = win.window_text()
                    if any(k in cls for k in ("SNSWnd", "TopStory", "SnsTimeline")) or \
                       self._config.kw_moments in title or "朋友圈" in title:
                        return win
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _get_active_window(self):
        """Return the Moments window if open, otherwise the main window."""
        return getattr(self, "_moments_window", None) or self.window

    # ------------------------------------------------------------------
    # Implemented: Like / Unlike
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=2, delay=1.0)
    def like_latest(self, count: int = 5) -> int:
        """Like the latest N Moments posts.

        Args:
            count: Number of posts to like.

        Returns:
            Number of likes actually given.
        """
        logger.info("Liking up to %d Moments posts.", count)
        self._activate()
        self._open_moments()
        time.sleep(self._config.action_delay)

        liked = 0
        for i in range(count):
            success = self._like_post_at_index(i)
            if success:
                liked += 1
            time.sleep(self._config.scroll_delay)

        logger.info("Liked %d / %d posts.", liked, count)
        return liked

    @retry_on_failure(max_retries=2, delay=1.0)
    def unlike(self, post_index: int = 0) -> None:
        """Remove like from a post.

        Args:
            post_index: Index of the post in visible list (0 = topmost).
        """
        logger.info("Unliking Moments post at index %d", post_index)
        self._activate()
        self._open_moments()
        time.sleep(self._config.action_delay)
        self._unlike_post_at_index(post_index)
        logger.info("Post unliked.")

    def like_by_author(self, author_name: str, max_scroll: int = 5) -> int:
        """Like posts by a specific author.

        Args:
            author_name: Name of the author.
            max_scroll: Max scroll attempts.

        Returns:
            Number of likes given.
        """
        logger.info("Liking posts by author: %s", author_name)
        self._activate()
        self._open_moments()
        time.sleep(self._config.action_delay)

        liked = 0
        for _ in range(max_scroll):
            posts = self._get_post_elements()
            for post in posts:
                if self._post_matches_author(post, author_name):
                    if self._click_like_on_post(post):
                        liked += 1
            self._scroll_down()
            time.sleep(self._config.scroll_delay)

        return liked

    # ------------------------------------------------------------------
    # Implemented: Browse
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=2, delay=1.0)
    def browse(self, scroll_times: int = 3) -> list[dict]:
        """Browse Moments feed and collect visible posts.

        Args:
            scroll_times: Number of scroll-and-collect passes.

        Returns:
            List of post dicts: author, content, likes, comments, time.
        """
        logger.info("Browsing Moments (%d scroll passes).", scroll_times)
        self._activate()
        self._open_moments()
        time.sleep(self._config.action_delay)

        all_posts: list[dict] = []
        seen_contents: set[str] = set()

        for i in range(scroll_times):
            posts = self._collect_visible_posts()
            for post in posts:
                content_key = post.get("content", "")[:50]
                if content_key and content_key not in seen_contents:
                    seen_contents.add(content_key)
                    all_posts.append(post)
            self._scroll_down()
            time.sleep(self._config.scroll_delay)

        logger.info("Total unique posts collected: %d", len(all_posts))
        return all_posts

    # ------------------------------------------------------------------
    # Implemented: Comment
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=2, delay=1.0)
    def comment_moment(self, post_index: int = 0, comment: str = "") -> None:
        """Comment on a Moments post.

        Args:
            post_index: Index of the post in visible list (0 = topmost).
            comment: Comment text.

        Raises:
            MomentsError: If commenting fails.
        """
        logger.info("Commenting on post %d: %s", post_index, comment[:40])
        self._activate()
        self._open_moments()
        time.sleep(self._config.action_delay)

        posts = self._get_post_elements()
        if post_index >= len(posts):
            raise MomentsError(f"Post index {post_index} out of range ({len(posts)} visible).")

        post = posts[post_index]

        # Step 1: Expand the interaction menu (..) button
        self._expand_interaction_menu(post)
        time.sleep(self._config.click_delay)

        # Step 2: Click the comment button
        self._click_comment_button(post)
        time.sleep(self._config.action_delay)

        # Step 3: Type the comment and submit
        self._type_and_submit_comment(comment)
        time.sleep(self._config.after_send_delay)
        logger.info("Comment posted successfully.")

    # ------------------------------------------------------------------
    # Implemented: Timeline
    # ------------------------------------------------------------------

    def get_my_timeline(self, limit: int = 20, hours_range: int = 0) -> list[dict]:
        """Get the Moments timeline (all friends' recent posts).

        Opens the Moments feed and scrolls to collect posts up to the
        specified limit. If hours_range is set, filters by time text.

        Args:
            limit: Max posts to retrieve.
            hours_range: Only posts within last X hours (0 = no filter).

        Returns:
            List of post dicts: author, content, time, likes, comments.
        """
        logger.info("Getting timeline (limit=%d, hours=%d).", limit, hours_range)
        # get_my_timeline is essentially a browse with more control
        scroll_times = max(1, limit // 5 + 1)
        all_posts = self.browse(scroll_times=scroll_times)

        # Apply limit
        all_posts = all_posts[:limit]

        # Filter by hours_range if specified
        if hours_range > 0:
            all_posts = self._filter_by_hours(all_posts, hours_range)

        logger.info("Timeline: %d posts collected.", len(all_posts))
        return all_posts

    def get_friend_moments(self, friend_name: str, limit: int = 10) -> dict:
        """Get a specific friend's Moments feed.

        Args:
            friend_name: Friend's nickname or remark.
            limit: Max number of posts to retrieve.

        Returns:
            Dict with status (SUCCESS/EMPTY/NO_ACCESS) and posts list.

        Note:
            Requires navigating to the friend's profile and accessing
            their Moments. This is complex and not fully automated.
        """
        raise NotImplementedError(
            "get_friend_moments() requires profile navigation which "
            "is not yet implemented. Use get_my_timeline() instead."
        )

    def get_my_own_moments(self, limit: int = 10) -> list[dict]:
        """Get own published Moments history.

        Args:
            limit: Max posts to retrieve.

        Returns:
            List of own post dicts.

        Note:
            Requires navigating to own profile which is not yet automated.
        """
        raise NotImplementedError(
            "get_my_own_moments() requires profile navigation which "
            "is not yet implemented."
        )

    def publish_moment(self, text: str = "", image_paths: list[str] = None) -> None:
        """Publish a new Moments post.

        Args:
            text: Post text content.
            image_paths: Optional list of image file paths.

        Note:
            Requires clicking the camera/publish button and handling
            the post composition window.
        """
        raise NotImplementedError(
            "publish_moment() requires post composition window handling "
            "which is not yet implemented."
        )

    # ------------------------------------------------------------------
    # Private helpers for comment_moment
    # ------------------------------------------------------------------

    def _expand_interaction_menu(self, post_element) -> None:
        """Click the interaction expand button (..) on a post."""
        try:
            # Look for a button at the bottom-right of the post
            children = post_element.children()
            for child in children:
                try:
                    if child.element_info.control_type == "Button":
                        self._finder.click(child)
                        return
                except Exception:
                    continue
            # Fallback: try clicking by coordinate
            rect = post_element.rectangle()
            x = rect.right - 20
            y = rect.bottom - 20
            self.window.click_input(coords=(x, y))
        except Exception as exc:
            raise MomentsError("Failed to expand interaction menu.") from exc

    def _click_comment_button(self, post_element) -> None:
        """Click the comment button in the expanded interaction menu."""
        try:
            comment_btn = self._finder.find_child_by_title(
                post_element, self._config.kw_moments_comment, timeout=3.0
            )
            self._finder.click(comment_btn)
        except Exception as exc:
            raise MomentsError("Failed to click comment button.") from exc

    def _type_and_submit_comment(self, text: str) -> None:
        """Type comment text into the comment box and submit."""
        try:
            edit_boxes = self._finder.find_all_children(self.window, control_type="Edit")
            if not edit_boxes:
                raise MomentsError("Comment input box not found.")
            comment_box = edit_boxes[-1]
            comment_box.click_input()
            time.sleep(self._config.click_delay)

            from wechat_auto.utils.clipboard import ClipboardHelper
            from wechat_auto.utils.keyboard import KeyboardHelper

            ClipboardHelper.set_text(text)
            KeyboardHelper.paste(self.window)
            time.sleep(self._config.action_delay)
            KeyboardHelper.press_enter(self.window)
        except MomentsError:
            raise
        except Exception as exc:
            raise MomentsError("Failed to submit comment.") from exc

    def _filter_by_hours(self, posts: list[dict], hours: int) -> list[dict]:
        """Filter posts by time within the specified hours range.

        This is a best-effort heuristic filter based on time text in posts.
        Returns all posts if time parsing fails.
        """
        import re

        filtered: list[dict] = []
        for post in posts:
            time_str = post.get("time", "")
            # Try to parse patterns like "X小时前", "X分钟前"
            hour_match = re.search(r"(\d+)\s*小时前", time_str)
            minute_match = re.search(r"(\d+)\s*分钟前", time_str)

            if hour_match:
                post_hours = int(hour_match.group(1))
                if post_hours <= hours:
                    filtered.append(post)
            elif minute_match:
                # Minutes ago is always within the hours range
                filtered.append(post)
            else:
                # Can't parse time, include it
                filtered.append(post)

        return filtered

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_post_elements(self) -> list:
        """Get all visible Moments post elements."""
        try:
            active = self._get_active_window()
            return self._finder.find_all_children(active, control_type="ListItem")
        except Exception:
            return []

    def _collect_visible_posts(self) -> list[dict]:
        """Collect data from all currently visible posts."""
        posts = self._get_post_elements()
        results = []
        for post_elem in posts:
            data = self._parse_post_element(post_elem)
            if data:
                results.append(data)
        return results

    def _parse_post_element(self, post_elem) -> Optional[dict]:
        """Parse a Moments post element into a dict."""
        try:
            text_parts = []
            children = post_elem.children()
            for child in children:
                try:
                    t = child.window_text()
                    if t:
                        text_parts.append(t)
                except Exception:
                    continue

            if not text_parts:
                return None

            return {
                "author": text_parts[0] if text_parts else "",
                "content": text_parts[1] if len(text_parts) > 1 else "",
                "likes": "",
                "comments": "",
                "time": text_parts[-1] if len(text_parts) > 2 else "",
            }
        except Exception:
            return None

    def _like_post_at_index(self, index: int) -> bool:
        """Try to like a single post at the given index."""
        posts = self._get_post_elements()
        if index >= len(posts):
            return False
        return self._click_like_on_post(posts[index])

    def _unlike_post_at_index(self, index: int) -> bool:
        """Try to unlike a post at the given index."""
        posts = self._get_post_elements()
        if index >= len(posts):
            return False
        return self._click_unlike_on_post(posts[index])

    def _click_like_on_post(self, post_element) -> bool:
        """Click the like button on a post element."""
        try:
            like_btn = self._finder.find_child_by_title(
                post_element, self._config.kw_moments_like, timeout=2.0
            )
            self._finder.click(like_btn)
            time.sleep(self._config.click_delay)
            return True
        except Exception:
            return False

    def _click_unlike_on_post(self, post_element) -> bool:
        """Click to remove a like on a post."""
        try:
            unlike_btn = self._finder.find_child_by_title(
                post_element, self._config.kw_moments_unlike, timeout=2.0
            )
            self._finder.click(unlike_btn)
            time.sleep(self._config.click_delay)
            return True
        except Exception:
            return False

    def _post_matches_author(self, post_element, author_name: str) -> bool:
        """Check if a post element belongs to the given author."""
        try:
            text = post_element.window_text()
            return author_name in text
        except Exception:
            return False

    def _scroll_down(self) -> None:
        """Scroll down in the Moments feed."""
        try:
            active = self._get_active_window()
            active.type_keys("{PGDN}")
            time.sleep(self._config.scroll_delay)
        except Exception:
            pass
