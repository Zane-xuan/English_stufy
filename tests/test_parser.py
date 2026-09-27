from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.parser import parse_clip  # noqa: E402

SAMPLE = ROOT / "content" / "2026-09-27_Good-Will-Hunting.html"

SYNTHETIC = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>t</title></head><body>
<header>
  <div class="kicker">Daily English · Clip 007 · 演讲</div>
  <h1>主标题<span class="sub">Some Film (2001) — A Scene</span></h1>
  <div class="meta">
    <span class="chip hot">2026-10-01 · 周四</span>
    <span class="chip">类型 · 演讲</span>
    <span class="chip">时长 ≈ 2 分钟</span>
  </div>
</header>
<div class="watch"><a href="https://example.com/a"><div class="site">YouTube</div><div class="ttl">A</div></a></div>
</body></html>
"""


def test_sample_clip_parsed_fully():
    if not SAMPLE.is_file():
        pytest.skip("样本内容不存在")
    meta = parse_clip(SAMPLE)

    assert meta.slug == "2026-09-27_Good-Will-Hunting"
    assert meta.publish_date == "2026-09-27"
    assert meta.period == 4
    assert meta.title
    assert meta.subtitle and "Good Will Hunting" in meta.subtitle
    assert meta.category == "影视独白"
    assert meta.duration == "≈ 3 分钟"
    assert meta.difficulty == "中高级"
    assert meta.accent == "美音（波士顿）"
    assert len(meta.links) == 3
    assert meta.links[0]["url"].startswith("https://")
    assert meta.parse_ok, meta.parse_note


def test_all_content_passes_checker():
    """content/ 下每一期都要能通过 scripts/check_content.py 的全部检查。"""
    import sys as _sys

    _sys.path.insert(0, str(ROOT / "scripts"))
    from check_content import check_file

    files = sorted((ROOT / "content").glob("*.html"))
    assert files, "content/ 下没有 HTML"

    for path in files:
        problems, _n_tgt, _n_row = check_file(path)
        assert not problems, f"{path.name}：{problems}"


def test_focus_window_derived_from_publish_date(tmp_path: Path):
    """默认服务 3 天：周一发布服务到周三，周四发布服务到周六。"""
    for name, expected in [
        ("2026-09-28_Monday.html", ("2026-09-28", "2026-09-30")),
        ("2026-10-01_Thursday.html", ("2026-10-01", "2026-10-03")),
    ]:
        path = tmp_path / name
        path.write_text(SYNTHETIC, encoding="utf-8")
        meta = parse_clip(path)
        assert (meta.focus_start, meta.focus_end) == expected


def test_focus_window_declared_by_chip_wins(tmp_path: Path):
    """页面显式声明服务区间时，以页面为准。"""
    html = SYNTHETIC.replace(
        '<span class="chip">时长 ≈ 2 分钟</span>',
        '<span class="chip">时长 ≈ 2 分钟</span>\n'
        '    <span class="chip">服务 · 2026-10-01 ~ 2026-10-05</span>',
    )
    path = tmp_path / "2026-10-01_Declared.html"
    path.write_text(html, encoding="utf-8")
    meta = parse_clip(path)

    assert (meta.focus_start, meta.focus_end) == ("2026-10-01", "2026-10-05")
    assert meta.parse_ok, meta.parse_note


def test_bad_focus_chip_is_recorded_and_falls_back(tmp_path: Path):
    html = SYNTHETIC.replace(
        '<span class="chip">时长 ≈ 2 分钟</span>',
        '<span class="chip">时长 ≈ 2 分钟</span>\n'
        '    <span class="chip">服务 · 下周一到周三</span>',
    )
    path = tmp_path / "2026-10-01_Bad.html"
    path.write_text(html, encoding="utf-8")
    meta = parse_clip(path)

    assert not meta.parse_ok
    assert "服务 chip" in meta.parse_note
    # 读不出来时仍要退回按发布日推导，不能把区间留空
    assert (meta.focus_start, meta.focus_end) == ("2026-10-01", "2026-10-03")


def test_chip_without_separator(tmp_path: Path):
    path = tmp_path / "2026-10-01_Some-Film.html"
    path.write_text(SYNTHETIC, encoding="utf-8")
    meta = parse_clip(path)

    assert meta.publish_date == "2026-10-01"
    assert meta.period == 7
    assert meta.title == "主标题"
    assert meta.subtitle == "Some Film (2001) — A Scene"
    assert meta.category == "演讲"
    assert meta.duration == "≈ 2 分钟"
    assert meta.difficulty is None
    assert len(meta.links) == 1
    assert meta.parse_ok, meta.parse_note


def test_missing_fields_are_recorded_not_raised(tmp_path: Path):
    path = tmp_path / "broken.html"
    path.write_text("<html><body><p>什么都没有</p></body></html>", encoding="utf-8")
    meta = parse_clip(path)

    assert meta.publish_date is None
    assert meta.title is None
    assert meta.links == []
    assert not meta.parse_ok
    assert "YYYY-MM-DD" in meta.parse_note
    assert "h1" in meta.parse_note
    assert "watch" in meta.parse_note
