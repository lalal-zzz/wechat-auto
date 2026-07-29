"""Channels skill - official accounts and video channels (Tier 1, stub)."""

from __future__ import annotations

import logging
from typing import Any

from wechat_auto.skills.base import BaseSkill

logger = logging.getLogger(__name__)


class ChannelsSkill(BaseSkill):
    """Official accounts and video channels automation.

    Tier 1 skill covering:
        - download_channels_video
        - search_official_article

    Note: Stub implementation - not yet fully implemented.
    """

    name = "search_official_article"

    def _run(self, **params) -> Any:
        keyword = params.get("keyword", "")
        return self.search_official_article(keyword)

    def download_channels_video(self, keyword: str, save_path: str = "") -> str:
        """Search and download a video from WeChat Channels (视频号).

        Args:
            keyword: Search keyword for the video.
            save_path: Local path to save the downloaded video.

        Returns:
            Path to the downloaded file.

        Note: Stub - not yet implemented.
        """
        raise NotImplementedError(
            "download_channels_video() is not yet implemented. "
            "Full implementation should open TopStoryWnd, search keyword, "
            "locate video, right-click and save."
        )

    def search_official_article(self, keyword: str) -> list[dict]:
        """Search official account articles.

        Args:
            keyword: Search keyword.

        Returns:
            List of article dicts: title, account, url, summary.

        Note: Stub - not yet implemented.
        """
        raise NotImplementedError(
            "search_official_article() is not yet implemented. "
            "Full implementation should use the global search box "
            "(NOT contacts search) to find articles."
        )
