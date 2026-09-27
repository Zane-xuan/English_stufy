from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, db, models  # noqa: E402
from app.parser import ClipMeta  # noqa: E402


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    with db.get_conn() as connection:
        yield connection


def _add(connection, slug: str, start: str, end: str) -> None:
    meta = ClipMeta(
        slug=slug,
        file_name=f"{slug}.html",
        publish_date=start,
        focus_start=start,
        focus_end=end,
        title=slug,
    )
    models.upsert_clip(connection, meta, 1.0, 10)


def test_get_current_picks_the_resource_covering_today(conn):
    _add(conn, "2026-09-28_Resource-A", "2026-09-28", "2026-09-30")
    _add(conn, "2026-10-01_Resource-B", "2026-10-01", "2026-10-03")

    assert models.get_current(conn, "2026-09-28")["slug"] == "2026-09-28_Resource-A"
    assert models.get_current(conn, "2026-09-30")["slug"] == "2026-09-28_Resource-A"
    assert models.get_current(conn, "2026-10-01")["slug"] == "2026-10-01_Resource-B"
    # 周日两份都不覆盖，退回最新一份
    assert models.get_current(conn, "2026-10-04")["slug"] == "2026-10-01_Resource-B"


def test_focus_day_and_total(conn):
    _add(conn, "2026-09-28_Resource-A", "2026-09-28", "2026-09-30")
    clip = models.get_clip(conn, "2026-09-28_Resource-A")

    assert models.focus_day(clip, "2026-09-28") == 1
    assert models.focus_day(clip, "2026-09-29") == 2
    assert models.focus_day(clip, "2026-09-30") == 3
    assert models.focus_day(clip, "2026-10-01") is None
    assert models.focus_total(clip) == 3


def test_list_clips_orders_by_publish_date_desc(conn):
    _add(conn, "2026-09-28_Resource-A", "2026-09-28", "2026-09-30")
    _add(conn, "2026-10-01_Resource-B", "2026-10-01", "2026-10-03")

    total, items = models.list_clips(conn)

    assert total == 2
    assert [item["slug"] for item in items] == [
        "2026-10-01_Resource-B",
        "2026-09-28_Resource-A",
    ]


def test_migration_renames_old_column_and_backfills_window(tmp_path, monkeypatch):
    """旧库（列名是 learn_date、没有服务区间）升级后应能自动改名并补上区间。"""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "legacy.db")

    legacy = db.connect()
    legacy.executescript(
        """
        CREATE TABLE clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            file_name TEXT NOT NULL,
            file_mtime REAL NOT NULL,
            file_size INTEGER NOT NULL,
            learn_date TEXT,
            period INTEGER,
            title TEXT,
            subtitle TEXT,
            category TEXT,
            duration TEXT,
            difficulty TEXT,
            accent TEXT,
            links_json TEXT,
            is_missing INTEGER NOT NULL DEFAULT 0,
            parse_ok INTEGER NOT NULL DEFAULT 0,
            parse_note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_clips_learn_date ON clips(learn_date);
        INSERT INTO clips (
            slug, file_name, file_mtime, file_size, learn_date, period, title,
            links_json, is_missing, parse_ok, created_at, updated_at
        ) VALUES (
            '2026-09-28_Resource-A', '2026-09-28_Resource-A.html', 1.0, 10,
            '2026-09-28', 1, '旧记录', '[]', 0, 1, 'x', 'x'
        );
        """
    )
    legacy.commit()
    legacy.close()

    db.init_db()

    with db.get_conn() as connection:
        clip = models.get_clip(connection, "2026-09-28_Resource-A")
        old_index = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_clips_learn_date'"
        ).fetchone()

    assert clip["publish_date"] == "2026-09-28"
    assert (clip["focus_start"], clip["focus_end"]) == ("2026-09-28", "2026-09-30")
    assert clip["title"] == "旧记录"
    assert old_index is None, "旧的 learn_date 索引应该被删掉"
