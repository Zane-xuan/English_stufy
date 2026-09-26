"""SQLite 连接、建表与数据访问。其他模块不直接 sqlite3.connect。"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.config import get_settings, resolve_path
from app.errors import StoreError
from app.models import (
    Candidate,
    DailyContent,
    FetchLogEntry,
    VocabularyItem,
    split_paragraphs,
)

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_date TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    source_platform TEXT NOT NULL,
    source_url TEXT NOT NULL,
    video_embed_url TEXT,
    source_author TEXT,
    source_work TEXT,
    source_kind TEXT NOT NULL,
    duration_seconds INTEGER,
    transcript_en TEXT NOT NULL,
    transcript_zh TEXT NOT NULL,
    motivation_score REAL,
    status TEXT NOT NULL DEFAULT 'published',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vocabulary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER NOT NULL REFERENCES daily_content(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    term TEXT NOT NULL,
    phonetic TEXT,
    meaning_zh TEXT NOT NULL,
    usage_note TEXT,
    example_sentence TEXT
);

CREATE TABLE IF NOT EXISTS candidate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    author TEXT,
    work TEXT,
    kind TEXT,
    duration_seconds INTEGER,
    motivation_score REAL,
    used INTEGER NOT NULL DEFAULT 0,
    discovered_at TEXT NOT NULL,
    UNIQUE (platform, external_id)
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    platform TEXT,
    stage TEXT NOT NULL,
    result TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vocabulary_content ON vocabulary (content_id);
CREATE INDEX IF NOT EXISTS idx_candidate_pick ON candidate (used, motivation_score DESC);
CREATE INDEX IF NOT EXISTS idx_fetch_log_run_date ON fetch_log (run_date);
"""


def now_iso() -> str:
    """当前时间的 ISO 8601 字符串，精确到秒。"""
    return datetime.now().isoformat(timespec="seconds")


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """打开一个连接。调用方负责关闭。"""
    target = resolve_path(db_path or get_settings().db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """连接上下文，正常结束提交，异常回滚。"""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> Path:
    """建表并返回数据库文件路径。可重复执行。"""
    target = resolve_path(db_path or get_settings().db_path)
    with connection(target) as conn:
        conn.executescript(SCHEMA)
    return target


def upsert_candidates(conn: sqlite3.Connection, candidates: Sequence[Candidate]) -> int:
    """写入候选，已存在的按 (platform, external_id) 跳过。返回新增条数。"""
    if not candidates:
        return 0
    stamp = now_iso()
    rows = [
        (
            item.platform,
            item.external_id,
            item.url,
            item.title,
            item.author,
            item.work,
            item.kind,
            item.duration_seconds,
            item.motivation_score,
            stamp,
        )
        for item in candidates
    ]
    before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO candidate
            (platform, external_id, url, title, author, work, kind,
             duration_seconds, motivation_score, discovered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return conn.total_changes - before


def update_candidate_score(
    conn: sqlite3.Connection, platform: str, external_id: str, score: float
) -> None:
    """回填激励性评分。"""
    conn.execute(
        "UPDATE candidate SET motivation_score = ? WHERE platform = ? AND external_id = ?",
        (score, platform, external_id),
    )


def mark_candidate_used(conn: sqlite3.Connection, candidate_id: int) -> None:
    conn.execute("UPDATE candidate SET used = 1 WHERE id = ?", (candidate_id,))


def list_pending_candidates(
    conn: sqlite3.Connection,
    limit: int = 10,
    preferred_duration: int = 0,
    min_duration: int = 0,
    max_duration: int = 0,
) -> list[Candidate]:
    """取未使用过的候选，已打分的排在前面，时长越接近偏好值越靠前。

    时长超出区间的候选直接排除，否则改了时长配置之后，
    候选池里遗留的长视频还会被反复选中。时长未知的候选保留但排在最后。
    上一轮被评了高分但没选中的候选会优先复用，避免重复判断。
    """
    where = ["used = 0"]
    params: list[object] = []
    if max_duration > min_duration:
        where.append(
            "(duration_seconds IS NULL "
            "OR (duration_seconds BETWEEN ? AND ?))"
        )
        params.extend([min_duration, max_duration])
    params.append(preferred_duration)
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT * FROM candidate
        WHERE {' AND '.join(where)}
        ORDER BY
            (motivation_score IS NULL),
            motivation_score DESC,
            ABS(COALESCE(duration_seconds, 999999) - ?) ASC,
            id ASC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_row_to_candidate(row) for row in rows]


def get_candidate(
    conn: sqlite3.Connection, platform: str, external_id: str
) -> Candidate | None:
    """按 (platform, external_id) 取候选。"""
    row = conn.execute(
        "SELECT * FROM candidate WHERE platform = ? AND external_id = ?",
        (platform, external_id),
    ).fetchone()
    return _row_to_candidate(row) if row else None


def _row_to_candidate(row: sqlite3.Row) -> Candidate:
    return Candidate(
        id=row["id"],
        platform=row["platform"],
        external_id=row["external_id"],
        url=row["url"],
        title=row["title"] or "",
        author=row["author"] or "",
        work=row["work"] or "",
        kind=row["kind"] or "",
        duration_seconds=row["duration_seconds"],
        motivation_score=row["motivation_score"],
        used=row["used"],
    )


def delete_daily_content(conn: sqlite3.Connection, content_date: str) -> None:
    """删除某天的内容与词汇，供重跑使用。"""
    row = conn.execute(
        "SELECT id FROM daily_content WHERE content_date = ?", (content_date,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM vocabulary WHERE content_id = ?", (row["id"],))
    conn.execute("DELETE FROM daily_content WHERE id = ?", (row["id"],))


def insert_daily_content(conn: sqlite3.Connection, content: DailyContent) -> int:
    """写入当天内容，返回新记录 id。"""
    created = content.created_at or now_iso()
    cursor = conn.execute(
        """
        INSERT INTO daily_content
            (content_date, title, source_platform, source_url, video_embed_url,
             source_author, source_work, source_kind, duration_seconds,
             transcript_en, transcript_zh, motivation_score, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            content.content_date,
            content.title,
            content.source_platform,
            content.source_url,
            content.video_embed_url,
            content.source_author,
            content.source_work,
            content.source_kind,
            content.duration_seconds,
            content.transcript_en,
            content.transcript_zh,
            content.motivation_score,
            content.status,
            created,
        ),
    )
    return int(cursor.lastrowid or 0)


def insert_vocabulary(
    conn: sqlite3.Connection, content_id: int, items: Sequence[VocabularyItem]
) -> int:
    """批量写入词汇，返回写入条数。"""
    if not items:
        return 0
    rows = [
        (
            content_id,
            item.kind,
            item.term,
            item.phonetic,
            item.meaning_zh,
            item.usage_note,
            item.example_sentence,
        )
        for item in items
    ]
    conn.executemany(
        """
        INSERT INTO vocabulary
            (content_id, kind, term, phonetic, meaning_zh, usage_note, example_sentence)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def has_content(conn: sqlite3.Connection, content_date: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM daily_content WHERE content_date = ? LIMIT 1", (content_date,)
    ).fetchone()
    return row is not None


def get_daily_content(
    conn: sqlite3.Connection, content_date: str
) -> tuple[DailyContent, list[VocabularyItem]] | None:
    """取某天的内容与词汇。没有记录时返回 None。"""
    row = conn.execute(
        "SELECT * FROM daily_content WHERE content_date = ?", (content_date,)
    ).fetchone()
    if row is None:
        return None
    content = DailyContent(
        id=row["id"],
        content_date=row["content_date"],
        title=row["title"],
        source_platform=row["source_platform"],
        source_url=row["source_url"],
        video_embed_url=row["video_embed_url"] or "",
        source_author=row["source_author"] or "",
        source_work=row["source_work"] or "",
        source_kind=row["source_kind"],
        duration_seconds=row["duration_seconds"],
        transcript_en=row["transcript_en"],
        transcript_zh=row["transcript_zh"],
        motivation_score=row["motivation_score"],
        status=row["status"],
        created_at=row["created_at"],
    )
    return content, get_vocabulary(conn, row["id"])


def get_vocabulary(conn: sqlite3.Connection, content_id: int) -> list[VocabularyItem]:
    rows = conn.execute(
        """
        SELECT * FROM vocabulary WHERE content_id = ?
        ORDER BY CASE kind
            WHEN 'word' THEN 0
            WHEN 'phrase' THEN 1
            ELSE 2
        END, id ASC
        """,
        (content_id,),
    ).fetchall()
    return [
        VocabularyItem(
            id=row["id"],
            content_id=row["content_id"],
            kind=row["kind"],
            term=row["term"],
            phonetic=row["phonetic"] or "",
            meaning_zh=row["meaning_zh"],
            usage_note=row["usage_note"] or "",
            example_sentence=row["example_sentence"] or "",
        )
        for row in rows
    ]


def count_content(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM daily_content").fetchone()
    return int(row["n"]) if row else 0


def list_content_summaries(
    conn: sqlite3.Connection, limit: int = 30, offset: int = 0
) -> list[dict[str, object]]:
    """历史列表，按日期倒序。"""
    rows = conn.execute(
        """
        SELECT content_date, title, source_platform, source_author, source_work
        FROM daily_content
        ORDER BY content_date DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [
        {
            "content_date": row["content_date"],
            "title": row["title"],
            "source_platform": row["source_platform"],
            "source_author": row["source_author"] or "",
            "source_work": row["source_work"] or "",
        }
        for row in rows
    ]


def get_adjacent_dates(
    conn: sqlite3.Connection, content_date: str
) -> tuple[str | None, str | None]:
    """取相邻两天有记录的日期，返回 (前一天, 后一天)。"""
    prev_row = conn.execute(
        "SELECT content_date FROM daily_content WHERE content_date < ? "
        "ORDER BY content_date DESC LIMIT 1",
        (content_date,),
    ).fetchone()
    next_row = conn.execute(
        "SELECT content_date FROM daily_content WHERE content_date > ? "
        "ORDER BY content_date ASC LIMIT 1",
        (content_date,),
    ).fetchone()
    return (
        prev_row["content_date"] if prev_row else None,
        next_row["content_date"] if next_row else None,
    )


def log_fetch(conn: sqlite3.Connection, entry: FetchLogEntry) -> None:
    """记一条阶段日志。日志失败不应中断流水线。"""
    try:
        conn.execute(
            """
            INSERT INTO fetch_log (run_date, platform, stage, result, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry.run_date,
                entry.platform,
                entry.stage,
                entry.result,
                entry.message[:2000],
                entry.created_at or now_iso(),
            ),
        )
    except sqlite3.Error as exc:
        raise StoreError(f"写入 fetch_log 失败：{exc}") from exc


def get_fetch_logs(conn: sqlite3.Connection, run_date: str) -> list[FetchLogEntry]:
    rows = conn.execute(
        "SELECT * FROM fetch_log WHERE run_date = ? ORDER BY id ASC", (run_date,)
    ).fetchall()
    return [
        FetchLogEntry(
            id=row["id"],
            run_date=row["run_date"],
            platform=row["platform"] or "",
            stage=row["stage"],
            result=row["result"],
            message=row["message"] or "",
            created_at=row["created_at"],
        )
        for row in rows
    ]


def log_stage(
    run_date: str, stage: str, result: str, message: str, platform: str = ""
) -> None:
    """用独立事务写一条阶段日志。

    流水线的其他写入会在失败时回滚，日志必须留下来供排查，
    所以这里自己开连接，不复用调用方的事务。
    """
    try:
        with connection() as conn:
            log_fetch(
                conn,
                FetchLogEntry(
                    run_date=run_date,
                    platform=platform,
                    stage=stage,
                    result=result,
                    message=message,
                ),
            )
    except Exception as exc:  # 日志写不进去也不该中断主流程
        logger.warning("写 fetch_log 失败：%s", exc)


def transcript_paragraphs(text: str) -> list[str]:
    """暴露给上层用的段落切分，保持与落库规则一致。"""
    return split_paragraphs(text)
