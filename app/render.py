"""把每期 HTML 转成可以内嵌进主页面的片段。

原始页面是一份完整文档，带自己的 <style> 与 <script>。
直接塞进主页面会让它的样式外泄，也会被外壳样式污染。
这里把它的 CSS 统一加上 #clip-root 前缀，只取 <body> 内容，脚本单独返回。
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from bs4 import BeautifulSoup

SCOPE = "#clip-root"

# 这些 at-rule 里面还是普通规则，需要继续加前缀
AT_RULE_WITH_BLOCK = {"media", "supports", "layer", "container", "scope", "document"}
AT_RULE_NAME = re.compile(r"@([a-zA-Z-]+)")

# 选择器整体替换成作用域本身
SCOPE_ITSELF = {":root", "html", "body"}


def _iter_rules(css: str):
    """按顶层大括号把 CSS 切成一条条规则，跳过注释。"""
    buf: list[str] = []
    depth = 0
    i = 0
    length = len(css)

    while i < length:
        char = css[i]
        if char == "/" and i + 1 < length and css[i + 1] == "*":
            end = css.find("*/", i + 2)
            i = length if end == -1 else end + 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            buf.append(char)
            if depth == 0:
                yield "".join(buf)
                buf = []
            i += 1
            continue
        buf.append(char)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        yield tail


def _scope_selector(selector: str, scope: str) -> list[str]:
    low = selector.lower().strip()
    if low in SCOPE_ITSELF:
        return [scope]
    if low == "*":
        return [scope, f"{scope} *"]
    for prefix in ("body ", "html "):
        if low.startswith(prefix):
            return [f"{scope} {selector.strip()[len(prefix):].strip()}"]
    return [f"{scope} {selector.strip()}"]


def _scope_rule(rule: str, scope: str) -> str:
    open_brace = rule.find("{")
    if open_brace == -1:
        return rule.strip()

    head = rule[:open_brace].strip()
    close_brace = rule.rfind("}")
    body = rule[open_brace + 1:close_brace] if close_brace > open_brace else rule[open_brace + 1:]

    if head.startswith("@"):
        matched = AT_RULE_NAME.match(head)
        name = matched.group(1).lower() if matched else ""
        if name in AT_RULE_WITH_BLOCK:
            inner = "\n".join(
                scoped for scoped in (_scope_rule(r, scope) for r in _iter_rules(body)) if scoped
            )
            return f"{head}{{\n{inner}\n}}"
        # @keyframes、@font-face、@import 之类原样保留
        return rule.strip()

    selectors: list[str] = []
    for part in head.split(","):
        part = part.strip()
        if part:
            selectors.extend(_scope_selector(part, scope))
    if not selectors:
        return ""
    return ", ".join(selectors) + " {" + body + "}"


def scope_css(css: str, scope: str = SCOPE) -> str:
    parts = [_scope_rule(rule, scope) for rule in _iter_rules(css)]
    return "\n".join(part for part in parts if part.strip())


def build_fragment(path: Path) -> dict:
    """返回 {css, html, script} 三部分，分别注入主页面。"""
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    css_parts = [tag.get_text() for tag in soup.find_all("style")]
    script_parts = [tag.get_text() for tag in soup.find_all("script")]
    for tag in soup.find_all(["style", "script"]):
        tag.decompose()

    body = soup.body
    if body is not None:
        body_html = body.decode_contents()
    else:
        for tag in soup.find_all(["head", "title", "meta", "link"]):
            tag.decompose()
        body_html = soup.decode()

    return {
        "css": scope_css("\n".join(css_parts)),
        "html": body_html,
        "script": "\n".join(script_parts),
    }


@lru_cache(maxsize=64)
def _cached_fragment(path_str: str, _mtime: float, _size: int) -> dict:
    return build_fragment(Path(path_str))


def get_fragment(path: Path) -> dict:
    """按文件修改时间缓存，文件一变就重新解析。"""
    stat = path.stat()
    return _cached_fragment(str(path), stat.st_mtime, stat.st_size)
