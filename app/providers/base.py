"""平台适配器接口，以及基于 yt-dlp 的通用实现。"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

import httpx
from yt_dlp import YoutubeDL

from app.config import Settings
from app.errors import CollectError, SubtitleError
from app.models import Candidate, RawSubtitle

logger = logging.getLogger(__name__)

SUBTITLE_LANGS = ("en", "en-US", "en-GB", "en-orig", "en-au")

SUBTITLE_FORMATS = ("json3", "srt", "vtt", "json")

# 搜索关键词的前缀，表示按上传时间排序，用于新闻类素材
RECENT_PREFIX = "recent:"

# 每次搜索取多少条结果。时长区间收窄后过滤掉的会变多，
# 所以搜索深度要比实际需要的候选数大得多。
SEARCH_DEPTH_MULTIPLIER = 5
MIN_SEARCH_DEPTH = 20


class PlatformProvider(ABC):
    """一个平台要实现三件事：采集候选、取字幕、给出嵌入地址。"""

    name: str = ""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    def collect(self, limit: int, queries: Sequence[str]) -> list[Candidate]:
        """采集候选。整个平台都失败时抛 CollectError。"""

    @abstractmethod
    def fetch_raw_subtitle(self, candidate: Candidate) -> RawSubtitle | None:
        """取原始字幕。平台没有字幕返回 None，取字幕过程出错抛 SubtitleError。"""

    def embed_url(self, candidate: Candidate) -> str:
        """可嵌入的播放地址。默认用原地址。"""
        return candidate.url

    def duration_ok(self, seconds: int | None) -> bool:
        """时长过滤。时长未知时不拦，交给后续环节。"""
        if seconds is None:
            return True
        return (
            self.settings.min_duration_seconds
            <= seconds
            <= self.settings.max_duration_seconds
        )


class YtDlpProvider(PlatformProvider):
    """基于 yt-dlp 的适配器基类。子类只需给出搜索前缀与平台标识。"""

    search_prefix = ""
    recent_search_prefix = ""
    platform = ""

    def _ydl_options(self, **extra: object) -> dict[str, object]:
        options: dict[str, object] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "ignoreerrors": True,
            "skip_download": True,
            "socket_timeout": 20,
        }
        if self.settings.https_proxy:
            options["proxy"] = self.settings.https_proxy
        options.update(extra)
        return options

    def build_url(self, external_id: str) -> str:
        """由平台内 ID 拼出可访问地址，供子类覆盖。"""
        return external_id

    def _search(self, query: str, depth: int) -> list[dict[str, object]]:
        """搜索一批候选。

        query 以 recent: 开头时改用按上传时间排序的前缀，
        让新闻类素材拿到近期内容。平台不支持时退回默认前缀。
        """
        prefix = self.search_prefix
        text = query
        if query.startswith(RECENT_PREFIX):
            text = query[len(RECENT_PREFIX) :].strip()
            prefix = self.recent_search_prefix or self.search_prefix
        if not text:
            return []

        target = f"{prefix}{depth}:{text}"
        try:
            with YoutubeDL(self._ydl_options(extract_flat=True)) as ydl:
                info = ydl.extract_info(target, download=False)
        except Exception as exc:
            raise CollectError(f"{self.platform} 搜索 {query!r} 失败：{exc}") from exc
        if not info:
            return []
        entries = info.get("entries") or []
        return [entry for entry in entries if isinstance(entry, dict)]

    def collect(self, limit: int, queries: Sequence[str]) -> list[Candidate]:
        results: list[Candidate] = []
        seen: set[str] = set()
        errors: list[str] = []
        depth = max(limit * SEARCH_DEPTH_MULTIPLIER, MIN_SEARCH_DEPTH)

        for query in queries:
            if len(results) >= limit:
                break
            try:
                entries = self._search(query, depth)
            except CollectError as exc:
                errors.append(str(exc))
                logger.warning("%s", exc)
                continue

            for entry in entries:
                external_id = str(entry.get("id") or "").strip()
                if not external_id or external_id in seen:
                    continue
                duration = entry.get("duration")
                seconds = int(duration) if isinstance(duration, (int, float)) else None
                if not self.duration_ok(seconds):
                    continue
                seen.add(external_id)
                results.append(self._to_candidate(entry, external_id, seconds))
                if len(results) >= limit:
                    break

        if not results and errors:
            raise CollectError(f"{self.platform} 全部搜索失败：" + "；".join(errors[:3]))
        return results

    def _to_candidate(
        self, entry: dict[str, object], external_id: str, seconds: int | None
    ) -> Candidate:
        url = str(entry.get("url") or entry.get("webpage_url") or "").strip()
        if not url.startswith("http"):
            url = self.build_url(external_id)
        return Candidate(
            platform=self.platform,
            external_id=external_id,
            url=url,
            title=str(entry.get("title") or "").strip(),
            author=str(
                entry.get("uploader") or entry.get("channel") or ""
            ).strip(),
            duration_seconds=seconds,
        )

    def fetch_raw_subtitle(self, candidate: Candidate) -> RawSubtitle | None:
        try:
            with YoutubeDL(self._ydl_options()) as ydl:
                info = ydl.extract_info(candidate.url, download=False)
        except Exception as exc:
            raise SubtitleError(
                f"{self.platform} 取 {candidate.external_id} 的字幕信息失败：{exc}"
            ) from exc

        if not info:
            return None

        track = self._pick_track(info)
        if track is None:
            return None

        content = self._download_text(track["url"])
        if not content.strip():
            return None
        return RawSubtitle(content=content, fmt=track["ext"], lang=track["lang"])

    def _pick_track(self, info: dict[str, object]) -> dict[str, str] | None:
        """按 人工字幕优先、英文优先、解析难度从低到高 挑一条。"""
        sources = (
            info.get("subtitles") or {},
            info.get("automatic_captions") or {},
        )
        for source in sources:
            if not isinstance(source, dict):
                continue
            for lang in SUBTITLE_LANGS:
                formats = source.get(lang)
                picked = self._pick_format(formats, lang)
                if picked:
                    return picked
            for lang, formats in source.items():
                if not str(lang).lower().startswith("en"):
                    continue
                picked = self._pick_format(formats, str(lang))
                if picked:
                    return picked
        return None

    @staticmethod
    def _pick_format(formats: object, lang: str) -> dict[str, str] | None:
        if not isinstance(formats, list):
            return None
        for wanted in SUBTITLE_FORMATS:
            for item in formats:
                if not isinstance(item, dict):
                    continue
                if item.get("ext") == wanted and item.get("url"):
                    return {"url": str(item["url"]), "ext": wanted, "lang": lang}
        return None

    def _download_text(self, url: str) -> str:
        proxy = self.settings.https_proxy or None
        try:
            with httpx.Client(
                timeout=30, follow_redirects=True, proxy=proxy
            ) as client:
                response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                response.raise_for_status()
                return response.text
        except httpx.HTTPError as exc:
            raise SubtitleError(f"下载字幕文件失败：{exc}") from exc


def download_audio(url: str, settings: Settings, dest_dir: Path) -> Path:
    """把音频拉到本地，供语音转写使用。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    options: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "audio.%(ext)s"),
        "socket_timeout": 60,
    }
    if settings.https_proxy:
        options["proxy"] = settings.https_proxy

    try:
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise SubtitleError("音频下载没有返回信息")
            filename = ydl.prepare_filename(info)
    except SubtitleError:
        raise
    except Exception as exc:
        raise SubtitleError(f"音频下载失败：{exc}") from exc

    path = Path(filename)
    if not path.exists():
        matches = sorted(dest_dir.glob("audio.*"))
        if not matches:
            raise SubtitleError("音频下载完成但找不到文件")
        path = matches[0]
    return path


def clean_caption_line(line: str) -> str:
    """去掉字幕里的样式标签与内联时间戳。"""
    line = re.sub(r"<[^>]+>", "", line)
    line = re.sub(r"\{\\[^}]*\}", "", line)
    return line.strip()
