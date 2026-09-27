"""SQLite 连接、建表与迁移。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from . import config
from .parser import default_focus_window

SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT    NOT NULL UNIQUE,
    file_name    TEXT    NOT NULL,
    file_mtime   REAL    NOT NULL,
    file_size    INTEGER NOT NULL,
    publish_date TEXT,
    focus_start  TEXT,
    focus_end    TEXT,
    period       INTEGER,
    title        TEXT,
    subtitle     TEXT,
    category     TEXT,
    duration     TEXT,
    difficulty   TEXT,
    accent       TEXT,
    links_json   TEXT,
    is_missing   INTEGER NOT NULL DEFAULT 0,
    parse_ok     INTEGER NOT NULL DEFAULT 0,
    parse_note   TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clips_publish_date ON clips(publish_date);
CREATE INDEX IF NOT EXISTS idx_clips_focus ON clips(focus_start, focus_end);
"""

# 建表之外的字段，旧库缺哪个补哪个。SQLite 的 ADD COLUMN 不校验已有数据，加完补算即可。
ADDABLE_COLUMNS = {
    "publish_date": "TEXT",
    "focus_start": "TEXT",
    "focus_end": "TEXT",
    "period": "INTEGER",
    "title": "TEXT",
    "subtitle": "TEXT",
    "category": "TEXT",
    "duration": "TEXT",
    "difficulty": "TEXT",
    "accent": "TEXT",
    "links_json": "TEXT",
    "is_missing": "INTEGER NOT NULL DEFAULT 0",
    "parse_ok": "INTEGER NOT NULL DEFAULT 0",
    "parse_note": "TEXT",
}


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {row["name"] for row in conn.execute("PRAGMA table_info(clips)")}


def _migrate(conn: sqlite3.Connection) -> None:
    """把旧库升到当前结构。只在缺列时动手，已有数据不动。

    必须在建索引之前跑：旧表里还没有 publish_date，直接建索引会报 no such column。
    """
    columns = _columns(conn)
    if not columns:
        return

    # 旧库把学习日期存在 learn_date 里，现在语义是发布日
    if "learn_date" in columns and "publish_date" not in columns:
        conn.execute("ALTER TABLE clips RENAME COLUMN learn_date TO publish_date")
        columns.discard("learn_date")
        columns.add("publish_date")

    for name, ddl in ADDABLE_COLUMNS.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE clips ADD COLUMN {name} {ddl}")
            columns.add(name)

    conn.execute("DROP INDEX IF EXISTS idx_clips_learn_date")

    rows = conn.execute(
        "SELECT id, publish_date FROM clips "
        "WHERE focus_start IS NULL OR focus_end IS NULL"
    ).fetchall()
    for row in rows:
        start, end = default_focus_window(row["publish_date"])
        conn.execute(
            "UPDATE clips SET focus_start = ?, focus_end = ? WHERE id = ?",
            (start, end, row["id"]),
        )


def init_db() -> None:
    conn = connect()
    try:
        _migrate(conn)
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """写入放在事务里，退出时提交；异常时回滚。"""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
