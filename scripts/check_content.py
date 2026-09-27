"""每期 HTML 的交付前自检。

查三件事：
1. 标签配平，避免手写 HTML 漏闭合。
2. 词汇 key 双向一致：原文里每个 data-key 都要有词汇行，词汇行里每个 key 都要在原文出现，且不能重复引用。
3. 站点解析所需的字段齐全（复用 app.parser）。

用法：
    python scripts/check_content.py
    python scripts/check_content.py content/2026-09-26_Steve-Jobs-Stanford.html
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup  # noqa: E402

from app.parser import parse_clip  # noqa: E402

PAIRED_TAGS = [
    "html", "head", "body", "style", "script", "div", "span", "p",
    "section", "header", "footer", "table", "thead", "tbody", "tr", "td", "th",
    "h1", "h2", "h3", "button", "a",
]


def check_pairing(raw: str) -> list[str]:
    problems: list[str] = []
    for tag in PAIRED_TAGS:
        opened = len(re.findall(rf"<{tag}[\s>]", raw))
        closed = len(re.findall(rf"</{tag}>", raw))
        if opened != closed:
            problems.append(f"标签不配平：<{tag}> 开 {opened} 个、闭 {closed} 个")
    return problems


def check_keys(soup: BeautifulSoup) -> tuple[list[str], int, int]:
    problems: list[str] = []

    tgt_keys: dict[str, int] = {}
    for el in soup.select(".tgt"):
        key = (el.get("data-key") or "").strip()
        if not key:
            problems.append("有 .tgt 没写 data-key")
            continue
        tgt_keys[key] = tgt_keys.get(key, 0) + 1

    row_keys: dict[str, int] = {}
    for row in soup.select(".vrow"):
        raw_keys = (row.get("data-keys") or "").strip()
        if not raw_keys:
            problems.append("有 .vrow 没写 data-keys")
            continue
        for key in (part.strip() for part in raw_keys.split(",")):
            if key:
                row_keys[key] = row_keys.get(key, 0) + 1

    for key in sorted(set(tgt_keys) - set(row_keys)):
        problems.append(f"key {key}：原文里有，词汇表里没有")
    for key in sorted(set(row_keys) - set(tgt_keys)):
        problems.append(f"key {key}：词汇表里有，原文里找不到")
    for key, count in sorted(row_keys.items()):
        if count > 1:
            problems.append(f"key {key}：被 {count} 个词汇行重复引用")

    return problems, len(tgt_keys), len(row_keys)


def check_structure(path: Path, soup: BeautifulSoup) -> list[str]:
    problems: list[str] = []

    script = soup.select_one(".script")
    if script is None:
        problems.append("缺少 .script 容器")
    elif script.get("data-lang") not in ("en", "zh"):
        problems.append(".script 的 data-lang 必须是 en 或 zh")

    if soup.select_one("#langBtn") is None:
        problems.append("缺少 #langBtn 语言切换按钮")

    if not soup.select(".turn"):
        problems.append("没有任何 .turn 台词段落")

    if not soup.select(".pron"):
        problems.append("缺少 .pron 发音与连读提示")

    expected_date = path.stem.split("_")[0]
    if expected_date not in soup.get_text():
        problems.append(f"正文里找不到文件名上的日期 {expected_date}")

    meta = parse_clip(path)
    if not meta.parse_ok:
        problems.append(f"站点解析器读不全：{meta.parse_note}")

    return problems


def check_file(path: Path) -> tuple[list[str], int, int]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw, "html.parser")

    problems = check_pairing(raw)
    key_problems, n_tgt, n_row = check_keys(soup)
    problems.extend(key_problems)
    problems.extend(check_structure(path, soup))
    return problems, n_tgt, n_row


def main(argv: list[str]) -> int:
    targets = [Path(a) for a in argv] if argv else sorted((ROOT / "content").glob("*.html"))
    if not targets:
        print("没有找到要检查的 HTML", file=sys.stderr)
        return 1

    failed = 0
    for path in targets:
        problems, n_tgt, n_row = check_file(path)
        if problems:
            failed += 1
            print(f"[失败] {path.name}")
            for problem in problems:
                print(f"       - {problem}")
        else:
            print(f"[通过] {path.name}  原文锚点 {n_tgt} 个 / 词汇行 {n_row} 个")

    print(f"\n共 {len(targets)} 个文件，失败 {failed} 个")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
