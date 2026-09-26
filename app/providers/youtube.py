"""YouTube 适配器。搜索走 yt-dlp 的 ytsearch。需要能访问 YouTube。"""

from __future__ import annotations

from app.models import Candidate
from app.providers.base import YtDlpProvider


class YouTubeProvider(YtDlpProvider):
    """YouTube。演讲与访谈类内容质量最高，但服务器需经代理访问。"""

    search_prefix = "ytsearch"
    recent_search_prefix = "ytsearchdate"
    platform = "youtube"

    def build_url(self, external_id: str) -> str:
        return f"https://www.youtube.com/watch?v={external_id}"

    def embed_url(self, candidate: Candidate) -> str:
        """YouTube 官方嵌入地址。部分视频作者关闭了嵌入，需退回原站。"""
        return f"https://www.youtube.com/embed/{candidate.external_id}"
