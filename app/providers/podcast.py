"""播客适配器。从 RSS 源拉取单集。

播客没有现成字幕，fetch_raw_subtitle 一律返回 None，由上层走语音转写。
候选的 url 指向音频文件本身，因为转写需要直接拿到音频。
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Sequence

import httpx

from app.errors import CollectError
from app.models import Candidate, RawSubtitle
from app.providers.base import PlatformProvider

logger = logging.getLogger(__name__)

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"

USER_AGENT = "Mozilla/5.0 (compatible; EnglishStudy/0.1)"


def parse_duration(text: str | None) -> int | None:
    """itunes:duration 可能是秒数，也可能是 HH:MM:SS。"""
    if not text:
        return None
    value = text.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    parts = value.split(":")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


class PodcastProvider(PlatformProvider):
    """播客。源地址由 PODCAST_FEEDS 配置，未配置时不产出候选。"""

    name = "podcast"
    platform = "podcast"

    def collect(self, limit: int, queries: Sequence[str]) -> list[Candidate]:
        feeds = self.settings.podcast_feeds
        if not feeds:
            raise CollectError("未配置 PODCAST_FEEDS，跳过播客采集")

        results: list[Candidate] = []
        errors: list[str] = []
        for feed in feeds:
            if len(results) >= limit:
                break
            try:
                episodes = self._fetch_feed(feed)
            except CollectError as exc:
                errors.append(str(exc))
                logger.warning("%s", exc)
                continue
            for episode in episodes:
                if len(results) >= limit:
                    break
                if not self.duration_ok(episode.duration_seconds):
                    continue
                results.append(episode)

        if not results and errors:
            raise CollectError("播客源全部失败：" + "；".join(errors[:3]))
        return results

    def fetch_raw_subtitle(self, candidate: Candidate) -> RawSubtitle | None:
        """播客没有字幕，交给语音转写。"""
        return None

    def embed_url(self, candidate: Candidate) -> str:
        return candidate.url

    def _fetch_feed(self, feed_url: str) -> list[Candidate]:
        proxy = self.settings.https_proxy or None
        try:
            with httpx.Client(
                timeout=30, follow_redirects=True, proxy=proxy
            ) as client:
                response = client.get(feed_url, headers={"User-Agent": USER_AGENT})
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CollectError(f"拉取播客源失败 {feed_url}：{exc}") from exc

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise CollectError(f"播客源不是合法 XML：{feed_url}") from exc

        channel = root.find("channel")
        if channel is None:
            raise CollectError(f"播客源缺少 channel 节点：{feed_url}")

        show_title = (channel.findtext("title") or "").strip()
        show_author = (
            channel.findtext(f"{{{ITUNES_NS}}}author") or show_title
        ).strip()

        episodes: list[Candidate] = []
        for item in channel.findall("item"):
            audio_url = self._enclosure_url(item)
            if not audio_url:
                continue
            title = (item.findtext("title") or "").strip()
            guid = (item.findtext("guid") or "").strip()
            duration = parse_duration(item.findtext(f"{{{ITUNES_NS}}}duration"))
            episodes.append(
                Candidate(
                    platform=self.platform,
                    external_id=guid or audio_url,
                    url=audio_url,
                    title=title,
                    author=show_author,
                    work=show_title,
                    kind="podcast",
                    duration_seconds=duration,
                )
            )
        return episodes

    @staticmethod
    def _enclosure_url(item: ET.Element) -> str:
        enclosure = item.find("enclosure")
        if enclosure is None:
            return ""
        url = (enclosure.get("url") or "").strip()
        if not url.startswith("http"):
            return ""
        return url
