"""FastAPI 入口与页面路由。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator

from app import __version__
from app.config import get_settings
from app.db import (
    connection,
    count_content,
    get_adjacent_dates,
    get_daily_content,
    get_fetch_logs,
    has_content,
    init_db,
    list_content_summaries,
)
from app.errors import PipelineError
from app.models import (
    RESULT_FAILED,
    SOURCE_KIND_LABELS,
    VOCAB_COLLOQUIAL,
    VOCAB_KIND_LABELS,
    VOCAB_PHRASE,
    VOCAB_WORD,
)
from app.pipeline import finalize, pending_status, prepare, today
from app.scheduler import is_running, shutdown_scheduler, start_scheduler

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    init_db()
    start_scheduler(settings)
    try:
        yield
    finally:
        shutdown_scheduler()


app = FastAPI(title="English_study", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


class RunRequest(BaseModel):
    """手动触发流水线的某一段。"""

    date: str | None = None
    force: bool = False
    stage: str = "prepare"

    @field_validator("date")
    @classmethod
    def check_date(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        text = value.strip()
        try:
            datetime.strptime(text, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("date 格式应为 YYYY-MM-DD") from exc
        return text

    @field_validator("stage")
    @classmethod
    def check_stage(cls, value: str) -> str:
        text = (value or "").strip().lower()
        if text not in ("prepare", "finalize"):
            raise ValueError("stage 只能是 prepare 或 finalize")
        return text


def _day_context(request: Request, content_date: str) -> dict[str, object]:
    """组装每日学习页需要的全部数据。"""
    with connection() as conn:
        result = get_daily_content(conn, content_date)
        prev_date, next_date = get_adjacent_dates(conn, content_date)
        has_any = count_content(conn) > 0
        failure_note = ""
        if result is None:
            failure_note = _latest_failure(conn, content_date)

    context: dict[str, object] = {
        "today": today(),
        "daily_run_time": get_settings().daily_run_time,
        "content_date": content_date,
        "content": None,
        "source_kind_label": "",
        "paragraphs_en": [],
        "paragraphs_zh": [],
        "groups": [],
        "prev_date": prev_date,
        "next_date": next_date,
        "has_any": has_any,
        "failure_note": failure_note,
    }
    if result is None:
        return context

    content, vocabulary = result
    context["content"] = content
    context["source_kind_label"] = SOURCE_KIND_LABELS.get(content.source_kind, "")
    context["paragraphs_en"] = [
        part.strip() for part in content.transcript_en.split("\n\n") if part.strip()
    ]
    context["paragraphs_zh"] = [
        part.strip() for part in content.transcript_zh.split("\n\n") if part.strip()
    ]
    groups = [
        {
            "kind": kind,
            "label": VOCAB_KIND_LABELS[kind],
            "entries": [item for item in vocabulary if item.kind == kind],
        }
        for kind in (VOCAB_WORD, VOCAB_PHRASE, VOCAB_COLLOQUIAL)
    ]
    context["groups"] = [group for group in groups if group["entries"]]
    return context


def _latest_failure(conn, content_date: str) -> str:
    """当天有失败记录时，给出一句可读的原因。"""
    entries = get_fetch_logs(conn, content_date)
    failures = [entry for entry in entries if entry.result == RESULT_FAILED]
    if not failures:
        return ""
    last = failures[-1]
    platform = f"[{last.platform}] " if last.platform else ""
    return f"{platform}{last.stage}：{last.message}"


@app.get("/", response_class=HTMLResponse)
def page_today(request: Request):
    """当天学习页。"""
    return templates.TemplateResponse(
        request, "day.html", _day_context(request, today())
    )


@app.get("/day/{content_date}", response_class=HTMLResponse)
def page_day(request: Request, content_date: str):
    """指定日期的学习页。"""
    return templates.TemplateResponse(
        request, "day.html", _day_context(request, content_date)
    )


@app.get("/history", response_class=HTMLResponse)
def page_history(request: Request):
    """历史列表页。"""
    with connection() as conn:
        items = list_content_summaries(conn, limit=200, offset=0)
    return templates.TemplateResponse(
        request,
        "history.html",
        {"today": today(), "items": items},
    )


@app.get("/api/day/{content_date}")
def api_day(content_date: str):
    """单日内容 JSON。"""
    with connection() as conn:
        result = get_daily_content(conn, content_date)
    if result is None:
        raise HTTPException(status_code=404, detail=f"{content_date} 没有记录")

    content, vocabulary = result
    return {
        "date": content.content_date,
        "title": content.title,
        "source": {
            "platform": content.source_platform,
            "url": content.source_url,
            "embed_url": content.video_embed_url,
            "author": content.source_author,
            "work": content.source_work,
            "kind": content.source_kind,
            "duration_seconds": content.duration_seconds,
        },
        "motivation_score": content.motivation_score,
        "status": content.status,
        "transcript_en": content.transcript_en,
        "transcript_zh": content.transcript_zh,
        "vocabulary": [
            {
                "kind": item.kind,
                "term": item.term,
                "phonetic": item.phonetic,
                "meaning_zh": item.meaning_zh,
                "usage_note": item.usage_note,
                "example_sentence": item.example_sentence,
            }
            for item in vocabulary
        ],
    }


@app.get("/api/days")
def api_days(
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """历史列表 JSON。"""
    with connection() as conn:
        total = count_content(conn)
        items = list_content_summaries(conn, limit=limit, offset=offset)
    return {"total": total, "items": items}


@app.post("/api/admin/run")
def api_admin_run(payload: RunRequest | None = None):
    """手动触发流水线的某一段，用于补录与排障。"""
    settings = get_settings()
    body = payload or RunRequest()
    target = body.date or today()

    if not body.force:
        with connection() as conn:
            if has_content(conn, target):
                raise HTTPException(
                    status_code=409,
                    detail=f"{target} 已有记录，需要覆盖请传 force=true",
                )

    try:
        if body.stage == "finalize":
            message = finalize(settings, target, force=body.force)
        else:
            message = prepare(settings, target, force=body.force)
    except PipelineError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "status": "ok",
        "content_date": target,
        "stage": body.stage,
        "message": message,
    }


@app.get("/api/admin/status")
def api_admin_status(date: str | None = Query(None)):
    """看某天卡在 prepare 还是 finalize。"""
    settings = get_settings()
    target = date or today()
    return {"content_date": target, "status": pending_status(settings, target)}


@app.get("/api/health")
def api_health():
    """健康检查，部署后用 curl 打这个接口验证。"""
    settings = get_settings()
    return {
        "status": "ok",
        "version": __version__,
        "scheduler_running": is_running(),
        "platforms": list(settings.prefer_platforms),
        "pending_dir": str(settings.pending_path),
    }
