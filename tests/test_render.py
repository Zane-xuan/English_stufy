from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.render import build_fragment, scope_css  # noqa: E402

SAMPLE = ROOT / "content" / "2026-09-27_Good-Will-Hunting.html"


def test_scope_css_rewrites_root_body_and_plain_selectors():
    css = ":root{--x:1;}body{margin:0;}*{box-sizing:border-box;}.wrap{max-width:880px;}"
    out = scope_css(css)

    assert "#clip-root {--x:1;}" in out
    assert "#clip-root {margin:0;}" in out
    assert "#clip-root, #clip-root * {box-sizing:border-box;}" in out
    assert "#clip-root .wrap {max-width:880px;}" in out
    assert "\nbody{" not in out


def test_scope_css_keeps_keyframes_and_recurses_media():
    css = "@keyframes flash{0%{background:#fff;}100%{background:#000;}}@media(max-width:600px){h1{font-size:24px;}}"
    out = scope_css(css)

    assert "@keyframes flash{0%{background:#fff;}100%{background:#000;}}" in out
    assert "@media(max-width:600px){" in out
    assert "#clip-root h1 {font-size:24px;}" in out


def test_scope_css_handles_selector_lists_and_body_prefix():
    css = "h1,h2{margin:0;}body .inner{color:red;}"
    out = scope_css(css)

    assert "#clip-root h1, #clip-root h2 {margin:0;}" in out
    assert "#clip-root .inner {color:red;}" in out


def test_build_fragment_splits_style_script_and_body():
    if not SAMPLE.is_file():
        import pytest

        pytest.skip("样本内容不存在")

    fragment = build_fragment(SAMPLE)

    assert fragment["css"].startswith("#clip-root")
    assert "<style" not in fragment["html"]
    assert "<script" not in fragment["html"]
    assert 'class="wrap"' in fragment["html"]
    assert 'id="script"' in fragment["html"]
    assert "langBtn" in fragment["script"]
    # 原始脚本仍靠全局 id 找元素，内嵌后这些 id 必须在片段里存在
    assert 'id="langBtn"' in fragment["html"]
