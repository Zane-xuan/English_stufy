"""从每期 HTML 中解析元数据。

只读元数据，不修改原页面。字段定位依赖参考页面里的类名：
.kicker、h1、h1 .sub、.meta .chip、.watch a。
任一字段缺失都不抛异常中断，记进 notes，由调用方写入 parse_note。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from bs4 import BeautifulSoup

DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+)$")
PERIOD_IN_KICKER = re.compile(r"(\d+)")
FOCUS_RANGE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*[~～至到]\s*(\d{4}-\d{2}-\d{2})")

# 一份资源默认服务几天。周一发布服务到周三，周四发布服务到周六，都是 3 天。
FOCUS_DAYS = 3

# 页面 meta 里的标签名到目标字段的映射
CHIP_FIELDS = {
    "类型": "category",
    "时长": "duration",
    "难度": "difficulty",
    "口音": "accent",
}


@dataclass
class ClipMeta:
    slug: str
    file_name: str
    publish_date: str | None = None
    focus_start: str | None = None
    focus_end: str | None = None
    period: int | None = None
    title: str | None = None
    subtitle: str | None = None
    category: str | None = None
    duration: str | None = None
    difficulty: str | None = None
    accent: str | None = None
    links: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def parse_ok(self) -> bool:
        return not self.notes

    @property
    def parse_note(self) -> str | None:
        return "；".join(self.notes) if self.notes else None


def default_focus_window(publish_date: str | None) -> tuple[str | None, str | None]:
    """按发布日推导服务区间，发布日当天算第 1 天。"""
    if not publish_date:
        return None, None
    try:
        start = date.fromisoformat(publish_date)
    except ValueError:
        return None, None
    return start.isoformat(), (start + timedelta(days=FOCUS_DAYS - 1)).isoformat()


def _text(node) -> str | None:
    """取文本并压平空白，空字符串归为 None。"""
    if node is None:
        return None
    cleaned = " ".join(node.get_text(" ", strip=True).split())
    return cleaned or None


def _chip_value(text: str, label: str) -> str:
    """把「类型 · 影视独白」切成「影视独白」，把「时长 ≈ 3 分钟」切成「≈ 3 分钟」。"""
    if "·" in text:
        return text.split("·", 1)[1].strip()
    return text[len(label):].lstrip(" ·：:").strip()


def parse_clip(path: Path) -> ClipMeta:
    file_name = path.name
    slug = path.stem
    meta = ClipMeta(slug=slug, file_name=file_name)

    matched = DATE_PREFIX.match(slug)
    if matched:
        meta.publish_date = matched.group(1)
    else:
        meta.notes.append("文件名缺少 YYYY-MM-DD 前缀")

    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    kicker = _text(soup.select_one(".kicker"))
    if kicker:
        parts = [part.strip() for part in kicker.split("·")]
        for part in parts:
            if "clip" in part.lower():
                found = PERIOD_IN_KICKER.search(part)
                if found:
                    meta.period = int(found.group(1))
        if len(parts) >= 3:
            meta.category = parts[-1] or None
    else:
        meta.notes.append("缺少 .kicker")

    heading = soup.select_one("h1")
    if heading is not None:
        sub = heading.select_one(".sub")
        if sub is not None:
            meta.subtitle = _text(sub)
            sub.extract()
        meta.title = _text(heading)
    if not meta.title:
        meta.notes.append("缺少 h1 标题")

    for chip in soup.select(".meta .chip"):
        text = _text(chip)
        if not text:
            continue
        if "服务" in text:
            found = FOCUS_RANGE.search(text)
            if found:
                meta.focus_start, meta.focus_end = found.group(1), found.group(2)
            else:
                meta.notes.append("服务 chip 的日期区间读不出来，格式应为 YYYY-MM-DD ~ YYYY-MM-DD")
            continue
        for label, attr in CHIP_FIELDS.items():
            if label in text:
                setattr(meta, attr, _chip_value(text, label) or None)
                break

    # 页面没声明服务区间就按发布日推导
    if not (meta.focus_start and meta.focus_end):
        meta.focus_start, meta.focus_end = default_focus_window(meta.publish_date)

    for anchor in soup.select(".watch a"):
        url = (anchor.get("href") or "").strip()
        if not url:
            continue
        meta.links.append(
            {
                "site": _text(anchor.select_one(".site")),
                "title": _text(anchor.select_one(".ttl")),
                "url": url,
            }
        )
    if not meta.links:
        meta.notes.append("缺少 .watch 观看链接")

    return meta
