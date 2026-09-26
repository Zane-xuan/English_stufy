"""Bilibili 适配器。搜索走 yt-dlp 的 bilisearch。"""

from __future__ import annotations

import re

from app.models import Candidate
from app.providers.base import YtDlpProvider

BV_PATTERN = re.compile(r"(BV[0-9A-Za-z]{10})")


class BilibiliProvider(YtDlpProvider):
    """Bilibili。国内可直连，多数视频带 CC 字幕。"""

    search_prefix = "bilisearch"
    platform = "bilibili"

    def build_url(self, external_id: str) -> str:
        if external_id.startswith("BV"):
            return f"https://www.bilibili.com/video/{external_id}"
        return f"https://www.bilibili.com/video/av{external_id}"

    def embed_url(self, candidate: Candidate) -> str:
        """Bilibili 官方播放器。分 P 视频只嵌第一 P。"""
        match = BV_PATTERN.search(candidate.url) or BV_PATTERN.search(
            candidate.external_id
        )
        if match:
            return (
                "https://player.bilibili.com/player.html?bvid="
                f"{match.group(1)}&high_quality=1&danmaku=0"
            )
        return candidate.url
