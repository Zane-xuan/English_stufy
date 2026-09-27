"""clips 表的读写。"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime

from .parser import ClipMeta


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _item(row: sqlite3.Row) -> dict:
    return {
        "slug": row["slug"],
        "publish_date": row["publish_date"],
        "focus_start": row["focus_start"],
        "focus_end": row["focus_end"],
        "period": row["period"],
        "title": row["title"],
        "subtitle": row["subtitle"],
        "category": row["category"],
        "duration": row["duration"],
        "difficulty": row["difficulty"],
        "accent": row["accent"],
        "file_name": row["file_name"],
        "links": json.loads(row["links_json"] or "[]"),
        "parse_ok": bool(row["parse_ok"]),
        "parse_note": row["parse_note"],
        "is_missing": bool(row["is_missing"]),
    }


def upsert_clip(
    conn: sqlite3.Connection,
    meta: ClipMeta,
    file_mtime: float,
    file_size: int,
) -> str:
    """写入或更新一条记录，返回 inserted / updated / unchanged。"""
    row = conn.execute(
        "SELECT id, file_mtime, file_size, is_missing FROM clips WHERE slug = ?",
        (meta.slug,),
    ).fetchone()

    links_json = json.dumps(meta.links, ensure_ascii=False)
    stamp = now_iso()

    if row is None:
        conn.execute(
            """
            INSERT INTO clips (
                slug, file_name, file_mtime, file_size,
                publish_date, focus_start, focus_end, period,
                title, subtitle, category, duration, difficulty, accent, links_json,
                is_missing, parse_ok, parse_note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            """,
            (
                meta.slug, meta.file_name, file_mtime, file_size,
                meta.publish_date, meta.focus_start, meta.focus_end, meta.period,
                meta.title, meta.subtitle, meta.category, meta.duration,
                meta.difficulty, meta.accent, links_json,
                1 if meta.parse_ok else 0, meta.parse_note, stamp, stamp,
            ),
        )
        return "inserted"

    unchanged = (
        row["file_mtime"] == file_mtime
        and row["file_size"] == file_size
        and not row["is_missing"]
    )
    if unchanged:
        return "unchanged"

    conn.execute(
        """
        UPDATE clips SET
            file_name = ?, file_mtime = ?, file_size = ?,
            publish_date = ?, focus_start = ?, focus_end = ?, period = ?,
            title = ?, subtitle = ?, category = ?,
            duration = ?, difficulty = ?, accent = ?, links_json = ?,
            is_missing = 0, parse_ok = ?, parse_note = ?, updated_at = ?
        WHERE slug = ?
        """,
        (
            meta.file_name, file_mtime, file_size,
            meta.publish_date, meta.focus_start, meta.focus_end, meta.period,
            meta.title, meta.subtitle, meta.category,
            meta.duration, meta.difficulty, meta.accent, links_json,
            1 if meta.parse_ok else 0, meta.parse_note, stamp,
            meta.slug,
        ),
    )
    return "updated"


def mark_missing(conn: sqlite3.Connection, present_slugs: list[str]) -> int:
    """把磁盘上已不存在的记录标为缺失，不删记录。返回新标记的条数。"""
    if present_slugs:
        placeholders = ",".join("?" * len(present_slugs))
        conn.execute(
            f"UPDATE clips SET is_missing = 0, updated_at = ? "
            f"WHERE slug IN ({placeholders}) AND is_missing = 1",
            [now_iso(), *present_slugs],
        )
        cursor = conn.execute(
            f"UPDATE clips SET is_missing = 1, updated_at = ? "
            f"WHERE slug NOT IN ({placeholders}) AND is_missing = 0",
            [now_iso(), *present_slugs],
        )
    else:
        cursor = conn.execute(
            "UPDATE clips SET is_missing = 1, updated_at = ? WHERE is_missing = 0",
            (now_iso(),),
        )
    return cursor.rowcount


def set_missing(conn: sqlite3.Connection, slug: str, flag: bool) -> None:
    conn.execute(
        "UPDATE clips SET is_missing = ?, updated_at = ? WHERE slug = ?",
        (1 if flag else 0, now_iso(), slug),
    )


def get_supplement(conn: sqlite3.Connection, slug: str) -> str:
    """读取某一期的补充文字，没有记录时返回空串。"""
    row = conn.execute(
        "SELECT body FROM supplements WHERE slug = ?", (slug,)
    ).fetchone()
    return row["body"] if row else ""


def set_supplement(conn: sqlite3.Connection, slug: str, body: str) -> None:
    """写入或覆盖某一期的补充；内容为空白时删除该条记录。"""
    if not body.strip():
        conn.execute("DELETE FROM supplements WHERE slug = ?", (slug,))
        return
    conn.execute(
        "INSERT INTO supplements (slug, body, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(slug) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at",
        (slug, body, now_iso()),
    )


def _where(q: str, category: str, include_missing: bool) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if not include_missing:
        clauses.append("is_missing = 0")
    if q:
        clauses.append("(title LIKE ? OR subtitle LIKE ? OR slug LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    if category:
        clauses.append("category = ?")
        params.append(category)
    sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return sql, params


def list_clips(
    conn: sqlite3.Connection,
    q: str = "",
    category: str = "",
    limit: int | None = None,
    offset: int = 0,
    include_missing: bool = False,
) -> tuple[int, list[dict]]:
    where, params = _where(q, category, include_missing)

    total = conn.execute(f"SELECT COUNT(*) AS n FROM clips{where}", params).fetchone()["n"]

    sql = f"SELECT * FROM clips{where} ORDER BY publish_date DESC, id DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = [*params, limit, offset]

    rows = conn.execute(sql, params).fetchall()
    return total, [_item(row) for row in rows]


def get_clip(conn: sqlite3.Connection, slug: str) -> dict | None:
    row = conn.execute("SELECT * FROM clips WHERE slug = ?", (slug,)).fetchone()
    return _item(row) if row else None


def get_latest(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM clips WHERE is_missing = 0 ORDER BY publish_date DESC, id DESC LIMIT 1"
    ).fetchone()
    return _item(row) if row else None


def list_clips_between(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    """返回发布日落在 [start, end] 区间内、文件未缺失的资源，按发布日正序（复习按学习顺序看）。"""
    rows = conn.execute(
        "SELECT * FROM clips WHERE is_missing = 0 "
        "AND publish_date IS NOT NULL AND publish_date >= ? AND publish_date <= ? "
        "ORDER BY publish_date ASC, id ASC",
        (start, end),
    ).fetchall()
    return [_item(row) for row in rows]


def get_current(conn: sqlite3.Connection, today: str) -> dict | None:
    """返回今天该主攻的一份资源。

    服务区间内有多个时取发布日最近的一份；一个都没有时退回最新的一份。
    今天是否真的落在区间内，用 focus_day() 判断。
    """
    row = conn.execute(
        "SELECT * FROM clips WHERE is_missing = 0 "
        "AND focus_start IS NOT NULL AND focus_end IS NOT NULL "
        "AND focus_start <= ? AND focus_end >= ? "
        "ORDER BY publish_date DESC, id DESC LIMIT 1",
        (today, today),
    ).fetchone()
    if row is not None:
        return _item(row)
    return get_latest(conn)


def focus_day(clip: dict, today: str) -> int | None:
    """今天是一份资源的第几天，不在区间内返回 None。"""
    start, end = clip.get("focus_start"), clip.get("focus_end")
    if not (start and end and start <= today <= end):
        return None
    try:
        return (date.fromisoformat(today) - date.fromisoformat(start)).days + 1
    except ValueError:
        return None


def focus_total(clip: dict) -> int | None:
    """一份资源服务几天。"""
    start, end = clip.get("focus_start"), clip.get("focus_end")
    if not (start and end):
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    except ValueError:
        return None


def count_clips(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM clips WHERE is_missing = 0").fetchone()["n"]


def list_categories(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT category FROM clips "
        "WHERE category IS NOT NULL AND category <> '' ORDER BY category"
    ).fetchall()
    return [row["category"] for row in rows]
