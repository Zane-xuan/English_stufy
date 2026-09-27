"""周日「今天任务」与预览开关的端到端测试。

生产库里「今天」不落在无服务区间的日子，所以这里把日期固定成周日，
并用临时数据库与临时内容目录，完全不碰生产数据。
开发期一周可能有多份资源，测试里特意放了不止两份。
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, db, models  # noqa: E402
from app.parser import ClipMeta  # noqa: E402

# 「今天」固定在这个周日；近 7 天窗口 = 2026-09-28 ~ 2026-10-04
SUNDAY = (2026, 10, 4)

SAMPLE_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>body{color:#111}</style></head>
<body><div class="kicker">Daily English · clip 001 · 影视独白</div>
<h1>示例标题<span class="sub">Sample</span></h1>
<div class="script" data-lang="en"><div class="turn"><span class="en-text">hi</span>
<span class="zh-text">嗨</span></div></div></body></html>
"""

# (slug, 发布日, 服务起, 服务止) —— 开发期一周不止两份
CLIPS = [
    ("2026-09-27_Eve", "2026-09-27", "2026-09-27", "2026-09-29"),  # 7 天前，刚好在窗口外
    ("2026-09-28_Mon", "2026-09-28", "2026-09-28", "2026-09-30"),  # 窗口第一天
    ("2026-09-30_Wed", "2026-09-30", "2026-09-30", "2026-10-02"),  # 开发期多出来的一份
    ("2026-10-01_Thu", "2026-10-01", "2026-10-01", "2026-10-03"),  # 周四那份
]


def _fake_today(year: int, month: int, day: int) -> type[date]:
    """构造一个 date 子类，today() 永远返回指定的那一天。"""

    class _FixedDate(date):
        @classmethod
        def today(cls) -> date:
            return cls(year, month, day)

    return _FixedDate


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    from app import main

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    monkeypatch.setattr(config, "CONTENT_DIR", content_dir)

    db.init_db()
    with db.get_conn() as conn:
        for index, (slug, publish, start, end) in enumerate(CLIPS, start=1):
            (content_dir / f"{slug}.html").write_text(SAMPLE_HTML, encoding="utf-8")
            models.upsert_clip(
                conn,
                ClipMeta(
                    slug=slug,
                    file_name=f"{slug}.html",
                    publish_date=publish,
                    focus_start=start,
                    focus_end=end,
                    period=index,
                    title=slug,
                    category="影视独白",
                ),
                1.0,
                10,
            )

    with TestClient(main.app) as client:
        yield client


def _taskbar(body: str) -> str:
    """截出左侧「今天任务」抽屉那一段，避免和右侧历史列表混淆。"""
    start = body.index('class="taskbar"')
    end = body.index("</aside>", start)
    return body[start:end]


def test_sunday_lists_only_the_last_seven_days(app_client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "date", _fake_today(*SUNDAY))

    response = app_client.get("/")
    assert response.status_code == 200

    bar = _taskbar(response.text)
    # 窗口内 3 份，按发布日正序；窗口外那份不出现
    assert re.findall(r'href="/\?d=([^"]+)"', bar) == [
        "2026-09-28_Mon",
        "2026-09-30_Wed",
        "2026-10-01_Thu",
    ]
    assert "本周复习 · 3 份" in bar
    assert "今天不在服务区间内" in bar


def test_sunday_plan_follows_the_learning_plan(app_client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "date", _fake_today(*SUNDAY))

    bar = _taskbar(app_client.get("/").text)

    assert "今天计划 · 综合复盘日" in bar
    assert "快速过一遍资源 A 与 B 的重点表达" in bar


def test_non_sunday_still_shows_the_day_card(app_client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "date", _fake_today(2026, 9, 29))  # 周二

    bar = _taskbar(app_client.get("/").text)

    assert "本周复习" not in bar
    assert "taskbar-review" not in bar
    assert "服务第 <b>2</b>/<b>3</b> 天" in bar
    assert "今天计划 · 拆解跟读日" in bar


def test_sunday_falls_back_when_window_is_empty(tmp_path, monkeypatch):
    """近 7 天一份都没有时，退回「复习最近一期」按钮，而不是空列表。"""
    from app import main

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "empty.db")
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    monkeypatch.setattr(config, "CONTENT_DIR", content_dir)

    db.init_db()
    with db.get_conn() as conn:
        (content_dir / "2026-08-01_Old.html").write_text(SAMPLE_HTML, encoding="utf-8")
        models.upsert_clip(
            conn,
            ClipMeta(
                slug="2026-08-01_Old",
                file_name="2026-08-01_Old.html",
                publish_date="2026-08-01",
                focus_start="2026-08-01",
                focus_end="2026-08-03",
                period=1,
                title="很久以前的一份",
            ),
            1.0,
            10,
        )

    monkeypatch.setattr(main, "date", _fake_today(*SUNDAY))

    with TestClient(main.app) as client:
        bar = _taskbar(client.get("/").text)

    assert "taskbar-review" not in bar
    assert "复习最近一期" in bar
    assert "今天计划 · 综合复盘日" in bar


def test_today_override_is_ignored_when_switch_is_off(app_client, monkeypatch):
    from app import main

    monkeypatch.setattr(config, "ALLOW_TODAY_OVERRIDE", False)
    monkeypatch.setattr(main, "date", _fake_today(2026, 9, 29))  # 周二

    response = app_client.get("/?today=2026-10-04")

    assert "预览" not in response.text
    assert "preview_today" not in response.headers.get("set-cookie", "")
    # 仍按真实「今天」走正常卡片
    assert "服务第 <b>2</b>/<b>3</b> 天" in _taskbar(response.text)


def test_today_override_applies_when_switch_is_on(app_client, monkeypatch):
    from app import main

    monkeypatch.setattr(config, "ALLOW_TODAY_OVERRIDE", True)
    monkeypatch.setattr(main, "date", _fake_today(2026, 9, 29))  # 真实「今天」是周二

    response = app_client.get("/?today=2026-10-04")
    bar = _taskbar(response.text)

    # 按预览的周日算：近 7 天 = 2026-09-28 ~ 2026-10-04
    assert "本周复习 · 3 份" in bar
    assert re.findall(r'href="/\?d=([^"]+)"', bar) == [
        "2026-09-28_Mon",
        "2026-09-30_Wed",
        "2026-10-01_Thu",
    ]
    assert "预览 <b>2026-10-04</b>" in response.text
    assert "preview_today=2026-10-04" in response.headers["set-cookie"]


def test_preview_persists_via_cookie_and_can_exit(app_client, monkeypatch):
    from app import main

    monkeypatch.setattr(config, "ALLOW_TODAY_OVERRIDE", True)
    monkeypatch.setattr(main, "date", _fake_today(2026, 9, 29))

    app_client.get("/?today=2026-10-04")  # 带上参数，种下 cookie
    assert "本周复习" in _taskbar(app_client.get("/").text)  # 不带参数也停在预览日

    assert "本周复习" not in _taskbar(app_client.get("/?today=off").text)
    # 退出后回到真实「今天」：周二 → 拆解跟读日
    assert "今天计划 · 拆解跟读日" in _taskbar(app_client.get("/").text)


def test_preview_does_not_write_to_db(tmp_path, monkeypatch):
    """预览模式只读：文件缺失的资源不该被标记成 is_missing。"""
    from app import main

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "readonly.db")
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    monkeypatch.setattr(config, "CONTENT_DIR", content_dir)  # 故意不放 HTML 文件

    db.init_db()
    with db.get_conn() as conn:
        models.upsert_clip(
            conn,
            ClipMeta(
                slug="2026-08-01_Gone",
                file_name="2026-08-01_Gone.html",
                publish_date="2026-08-01",
                focus_start="2026-08-01",
                focus_end="2026-08-03",
                period=1,
                title="文件不在",
            ),
            1.0,
            10,
        )

    monkeypatch.setattr(main, "date", _fake_today(2026, 8, 2))

    def missing_flag() -> int:
        with db.get_conn() as conn:
            return conn.execute("SELECT is_missing FROM clips").fetchone()["is_missing"]

    monkeypatch.setattr(config, "ALLOW_TODAY_OVERRIDE", True)
    with TestClient(main.app) as client:
        client.get("/?today=2026-08-02")
    assert missing_flag() == 0, "预览模式不应写库"

    monkeypatch.setattr(config, "ALLOW_TODAY_OVERRIDE", False)
    with TestClient(main.app) as client:
        client.get("/")
    assert missing_flag() == 1, "非预览时文件缺失仍应被标记"
