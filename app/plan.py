"""从 LEARNING_PLAN.md 读「今天该做哪一步」。

站点只负责展示，不复制计划正文：改学习计划文档就等于改站点。
计划正文在第 3 节「每天的学习安排」，每个 ### 小节是一天的流程。
按资源服务第几天取对应小节：第 1 天初识、第 2 天拆解跟读、第 3 天及以后输出；
今天不在任何资源的服务区间内（通常是周日）取综合复盘。
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from . import config

PLAN_FILE: Path = config.BASE_DIR / "LEARNING_PLAN.md"

# 只认第 3 节
PLAN_HEADING = re.compile(r"^##\s+3\.")
SECTION_HEADING = re.compile(r"^###\s+(?P<title>.+?)\s*$")
NUMBERED_STEP = re.compile(r"^\s*\d+\.\s+(?P<text>.+?)\s*$")

# 服务第几天 → 小节标题里的关键词；第 3 天及以后都算输出日
DAY_KEYWORDS: dict[int, str] = {1: "初识", 2: "拆解跟读"}
LATER_KEYWORD = "输出"
REVIEW_KEYWORD = "复盘"


def _clean_title(raw: str) -> str:
    """「周二，资源 A 拆解跟读日」→「拆解跟读日」，去掉星期与资源代号。"""
    title = raw.split("，", 1)[-1]
    cleaned = title.replace("资源 A", "").replace("资源 B", "").strip()
    return cleaned or raw


def _extract_sections(text: str) -> list[dict]:
    """取出第 3 节下每个 ### 小节的标题与编号步骤，丢掉没有步骤的小节。"""
    sections: list[dict] = []
    in_plan = False

    for line in text.splitlines():
        if line.startswith("## "):
            in_plan = bool(PLAN_HEADING.match(line))
            continue
        if not in_plan:
            continue

        heading = SECTION_HEADING.match(line)
        if heading:
            sections.append({"title": _clean_title(heading.group("title")), "steps": []})
            continue

        step = NUMBERED_STEP.match(line)
        if step and sections:
            sections[-1]["steps"].append(step.group("text"))

    return [section for section in sections if section["steps"]]


@lru_cache(maxsize=8)
def _parse(path_str: str, mtime: float, size: int) -> list[dict]:
    """按（路径, mtime, 大小）缓存，文档一改缓存自然失效。"""
    text = Path(path_str).read_text(encoding="utf-8", errors="replace")
    return _extract_sections(text)


def load_sections(path: Path | None = None) -> list[dict]:
    """读取并解析计划文档；文件不存在时返回空列表，不抛异常。"""
    target = path or PLAN_FILE
    try:
        stat = target.stat()
    except OSError:
        return []
    return _parse(str(target), stat.st_mtime, stat.st_size)


def today_plan(day_index: int | None, path: Path | None = None) -> dict | None:
    """返回今天该做的那一步；取不到返回 None。"""
    sections = load_sections(path)
    if not sections:
        return None

    if not day_index:
        keyword = REVIEW_KEYWORD
    else:
        keyword = DAY_KEYWORDS.get(day_index, LATER_KEYWORD)

    for section in sections:
        if keyword in section["title"]:
            return section
    return None
