"""Moments skill - full Moments automation scenarios (Tier 1)."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

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
        """Navigate to the Moments feed."""
        try:
            moments_btn = self._finder.find_child_by_title(
                self.window,
                self._config.kw_moments,
                timeout=self._config.find_element_timeout,
            )
            self._finder.click(moments_btn)
            time.sleep(self._config.page_load_timeout)
            logger.info("Opened Moments feed.")
        except Exception as exc:
            raise MomentsError("Failed to open Moments.") from exc

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
    # Stubs: Comment / Publish / Friend Moments / Own Moments
    # ------------------------------------------------------------------

    def comment_moment(self, post_index: int = 0, comment: str = "") -> None:
        """Comment on a Moments post.

        Args:
            post_index: Index of the post.
            comment: Comment text.

        Note: Stub - not yet implemented.
        """
        raise NotImplementedError("comment_moment() is not yet implemented.")

    def publish_moment(self, text: str = "", image_paths: list[str] = None) -> None:
        """Publish a new Moments post.

        Args:
            text: Post text content.
            image_paths: Optional list of image file paths.

        Note: Stub - not yet implemented.
        """
        raise NotImplementedError("publish_moment() is not yet implemented.")

    def get_friend_moments(self, friend_name: str, limit: int = 10) -> dict:
        """Get a specific friend's Moments feed.

        Args:
            friend_name: Friend's nickname or remark.
            limit: Max number of posts to retrieve.

        Returns:
            Dict with status (SUCCESS/EMPTY/NO_ACCESS) and posts list.

        Note: Stub - not yet implemented.
        """
        raise NotImplementedError("get_friend_moments() is not yet implemented.")

    def get_my_timeline(self, limit: int = 20, hours_range: int = 24) -> list[dict]:
        """Get the Moments timeline (all friends' recent posts).

        Args:
            limit: Max posts to retrieve.
            hours_range: Only posts within last X hours.

        Returns:
            List of post dicts.

        Note: Stub - not yet implemented.
        """
        raise NotImplementedError("get_my_timeline() is not yet implemented.")

    def get_my_own_moments(self, limit: int = 10) -> list[dict]:
        """Get own published Moments history.

        Args:
            limit: Max posts to retrieve.

        Returns:
            List of own post dicts.

        Note: Stub - not yet implemented.
        """
        raise NotImplementedError("get_my_own_moments() is not yet implemented.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_post_elements(self) -> list:
        """Get all visible Moments post elements."""
        try:
            return self._finder.find_all_children(self.window, control_type="ListItem")
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
            self.window.type_keys("{PGDN}")
            time.sleep(self._config.scroll_delay)
        except Exception:
            pass
