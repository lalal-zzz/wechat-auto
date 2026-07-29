"""Channels skill - official accounts and video channels (Tier 1)."""

from __future__ import annotations

import logging
import time
from typing import Any

from wechat_auto.skills.base import BaseSkill
from wechat_auto.exceptions import ElementNotFoundError
from wechat_auto.utils.clipboard import ClipboardHelper
from wechat_auto.utils.keyboard import KeyboardHelper
from wechat_auto.utils.retry import retry_on_failure

logger = logging.getLogger(__name__)


class ChannelsSkill(BaseSkill):
    """Official accounts and video channels automation.

    Tier 1 skill covering:
        - search_official_article
        - download_channels_video (stub)

    Core rule: Uses the GLOBAL main search box (NOT the contacts-tab
    search box) to search for articles and videos, since these are
    not contacts.
    """

    name = "search_official_article"

    def _run(self, **params) -> Any:
        keyword = params.get("keyword", "")
        return self.search_official_article(keyword)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @retry_on_failure(max_retries=2, delay=1.0)
    def search_official_article(self, keyword: str) -> list[dict]:
        """Search official account articles.

        Uses the global search box (Ctrl+F) to search for articles.
        This is distinct from contact search which uses the contacts-tab
        dedicated search box.

        Args:
            keyword: Search keyword.

        Returns:
            List of article dicts::

                [
                    {
                        "title": str,
                        "account": str,
                        "summary": str,
                    }
                ]

            Returns an empty list if no results found.
        """
        logger.info("Searching official articles: %s", keyword)
        self._activate()

        # Use global search (Ctrl+F) - NOT contacts tab search
        self._finder.open_search()
        time.sleep(self._config.action_delay)

        ClipboardHelper.set_text(keyword)
        KeyboardHelper.paste(self.window)
        time.sleep(self._config.search_timeout)

        # Press Enter to trigger global search (opens TopStoryWnd)
        KeyboardHelper.press_enter(self.window)
        time.sleep(self._config.page_load_timeout)

        # Collect article results from the search results list
        results = self._collect_article_results()

        # Close the search window
        KeyboardHelper.press_escape(self.window)
        time.sleep(self._config.action_delay)

        logger.info("Found %d article(s) for '%s'.", len(results), keyword)
        return results

    def download_channels_video(self, keyword: str, save_path: str = "") -> str:
        """Search and download a video from WeChat Channels (视频号).

        Args:
            keyword: Search keyword for the video.
            save_path: Local path to save the downloaded video.

        Returns:
            Path to the downloaded file.

        Note:
            Not yet fully implemented. Opens TopStoryWnd, searches
            keyword, locates video. Right-click save requires manual
            selection or further UI automation.
        """
        logger.info("Searching channels video: %s", keyword)
        self._activate()

        self._finder.open_search()
        time.sleep(self._config.action_delay)

        ClipboardHelper.set_text(keyword)
        KeyboardHelper.paste(self.window)
        time.sleep(self._config.search_timeout)

        KeyboardHelper.press_enter(self.window)
        time.sleep(self._config.page_load_timeout)

        # TODO: Locate video card, right-click, select "保存视频"
        logger.warning("Video download not fully automated yet.")
        KeyboardHelper.press_escape(self.window)
        return save_path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_article_results(self) -> list[dict]:
        """Collect article search results from the results list.

        Parses ListItem elements in the search results, extracting
        title, account name, and summary text.
        """
        results: list[dict] = []
        try:
            items = self._finder.find_all_children(self.window, control_type="ListItem")
            for item in items:
                article = self._parse_article_item(item)
                if article:
                    results.append(article)
        except Exception as exc:
            logger.debug("Error collecting article results: %s", exc)

        return results

    def _parse_article_item(self, item) -> dict | None:
        """Parse a single ListItem into an article dict.

        Expected text layout:
            [account_name, title, summary, ...]
        """
        try:
            text_parts: list[str] = []
            children = item.children()
            for child in children:
                try:
                    t = child.window_text()
                    if t and t not in text_parts:
                        text_parts.append(t)
                except Exception:
                    continue

            if not text_parts:
                return None

            # Heuristic: first text is account, second is title, rest is summary
            account = text_parts[0] if len(text_parts) > 0 else ""
            title = text_parts[1] if len(text_parts) > 1 else text_parts[0]
            summary = " ".join(text_parts[2:]) if len(text_parts) > 2 else ""

            return {
                "title": title,
                "account": account,
                "summary": summary,
            }
        except Exception:
            return None
