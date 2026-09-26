"""字幕获取与语音转写兜底。

先取平台现成字幕，取不到才下载音频做语音转写。
段落切分规则集中在本模块，正文与译文的段落对应关系依赖它。
"""

from __future__ import annotations

import json
import logging
import re

from app.config import Settings
from app.errors import SubtitleError
from app.models import Candidate, RawSubtitle, Transcript
from app.providers.base import PlatformProvider, clean_caption_line

logger = logging.getLogger(__name__)

TARGET_PARAGRAPH_CHARS = 320
MAX_PARAGRAPH_CHARS = 600

TIMESTAMP_PATTERN = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3}\s*-->")
CUE_META_PATTERN = re.compile(r"^(Kind|Language|NOTE|STYLE|REGION)\b", re.IGNORECASE)
SENTENCE_ENDINGS = (".", "!", "?", "\u2026")


def get_transcript(
    candidate: Candidate,
    provider: PlatformProvider,
    settings: Settings,
    *,
    allow_transcribe: bool = True,
) -> Transcript | None:
    """拿到字幕。只用平台现有字幕，不下载任何音视频。

    没有平台字幕时返回 None，由调用方跳过该候选。
    allow_transcribe 保留仅为接口兼容，转写行为已整体移除。
    """
    raw = provider.fetch_raw_subtitle(candidate)
    if raw is not None:
        segments = parse_raw_subtitle(raw)
        if segments:
            return Transcript(
                paragraphs=group_into_paragraphs(segments),
                from_platform_subtitle=True,
            )
        logger.info("%s 的平台字幕为空", candidate.external_id)
    return None


def parse_raw_subtitle(raw: RawSubtitle) -> list[str]:
    """把平台原始字幕解析成句子列表。格式靠 fmt 与内容特征双重判断。"""
    text = (raw.content or "").strip()
    if not text:
        return []

    fmt = (raw.fmt or "").lower()
    head = text[:2000]

    if fmt == "json3" or '"events"' in head:
        segments = _parse_json3(text)
    elif fmt == "vtt" or text.startswith("WEBVTT"):
        segments = _parse_cue_text(text, expect_index=False)
    elif fmt == "srt":
        segments = _parse_cue_text(text, expect_index=True)
    elif text.startswith(("{", "[")):
        segments = _parse_bilibili_json(text)
    else:
        segments = _parse_cue_text(text, expect_index=False)

    return dedupe_segments(segments)


def _parse_json3(text: str) -> list[str]:
    """YouTube 的 json3 格式。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SubtitleError(f"json3 字幕解析失败：{exc}") from exc

    segments: list[str] = []
    for event in data.get("events") or []:
        if not isinstance(event, dict):
            continue
        pieces = event.get("segs") or []
        line = "".join(
            str(piece.get("utf8") or "")
            for piece in pieces
            if isinstance(piece, dict)
        )
        line = clean_caption_line(line.replace("\n", " "))
        if line:
            segments.append(line)
    return segments


def _parse_bilibili_json(text: str) -> list[str]:
    """Bilibili 的字幕接口返回 body 数组。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SubtitleError(f"Bilibili 字幕解析失败：{exc}") from exc

    body = data.get("body") if isinstance(data, dict) else data
    if not isinstance(body, list):
        return []

    segments: list[str] = []
    for item in body:
        if isinstance(item, dict):
            content = item.get("content")
        elif isinstance(item, str):
            content = item
        else:
            content = None
        if not content:
            continue
        line = clean_caption_line(str(content).replace("\n", " "))
        if line:
            segments.append(line)
    return segments


def _parse_cue_text(text: str, expect_index: bool) -> list[str]:
    """解析 vtt 与 srt。跳过头部元信息、时间轴与序号行。"""
    segments: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("WEBVTT") or CUE_META_PATTERN.match(line):
            continue
        if "-->" in line or TIMESTAMP_PATTERN.search(line):
            continue
        if expect_index and line.isdigit():
            continue
        cleaned = clean_caption_line(line)
        if cleaned:
            segments.append(cleaned)
    return segments


def dedupe_segments(segments: list[str]) -> list[str]:
    """去掉完全重复的句子，并合并滚动字幕的递进重复。"""
    result: list[str] = []
    for segment in segments:
        text = segment.strip()
        if not text:
            continue
        if not result:
            result.append(text)
            continue
        previous = result[-1]
        if text == previous or previous.endswith(text):
            continue
        if text.startswith(previous):
            result[-1] = text
            continue
        result.append(text)
    return result


def group_into_paragraphs(
    segments: list[str],
    target_chars: int = TARGET_PARAGRAPH_CHARS,
    max_chars: int = MAX_PARAGRAPH_CHARS,
) -> list[str]:
    """把句子合并成段落。译文与原文一一对应，依赖这个规则。"""
    paragraphs: list[str] = []
    buffer = ""

    for segment in segments:
        if not buffer:
            buffer = segment
        elif len(buffer) + 1 + len(segment) <= max_chars:
            buffer = f"{buffer} {segment}"
        else:
            paragraphs.append(buffer)
            buffer = segment

        if len(buffer) >= target_chars and _ends_sentence(buffer):
            paragraphs.append(buffer)
            buffer = ""

    if buffer:
        paragraphs.append(buffer)
    return paragraphs


def _ends_sentence(text: str) -> bool:
    return text.rstrip().rstrip("\"'").endswith(SENTENCE_ENDINGS)
