"""FastAPI 应用：页面路由与接口。"""

from __future__ import annotations

import base64
import re
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, db, models, render
from .scan import scan as run_scan

SAFE_FILE_NAME = re.compile(r"^[A-Za-z0-9._-]+\.html$")

_scan_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="English Study", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


def _unauthorized() -> PlainTextResponse:
    return PlainTextResponse(
        "需要认证",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="English Study"'},
    )


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """SITE_PASSWORD 未配置时整站开放；配置后全站启用 Basic 认证。"""
    if not config.SITE_PASSWORD or request.url.path == "/healthz":
        return await call_next(request)

    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8")
            _, _, password = decoded.partition(":")
            if secrets.compare_digest(password, config.SITE_PASSWORD):
                return await call_next(request)
        except Exception:
            pass
    return _unauthorized()


# ---------------------------------------------------------------- 页面


@app.get("/", response_class=HTMLResponse)
def page_index(request: Request, d: str = "", q: str = "", category: str = ""):
    """主页面：主内容区显示今天该主攻的那份资源，右侧抽屉列出全部往期。

    d 缺省时选今天落在服务区间内的那一份，一份都不在区间内则退回最新一份。
    """
    today = date.today().isoformat()

    with db.get_conn() as conn:
        total, items = models.list_clips(conn, q=q, category=category)
        categories = models.list_categories(conn)

        current = None
        not_found = False
        if d:
            current = models.get_clip(conn, d)
            not_found = current is None
        if current is None and not not_found:
            current = models.get_current(conn, today)

        fragment = None
        file_exists = False
        if current is not None:
            path = config.CONTENT_DIR / current["file_name"]
            file_exists = path.is_file()
            if file_exists:
                fragment = render.get_fragment(path)
            elif not current["is_missing"]:
                models.set_missing(conn, current["slug"], True)

        day_index = models.focus_day(current, today) if current else None
        day_total = models.focus_total(current) if current else None

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "current": current,
            "fragment": fragment,
            "file_exists": file_exists,
            "not_found": not_found,
            "requested": d,
            "items": items,
            "total": total,
            "categories": categories,
            "q": q,
            "category": category,
            "today": today,
            "day_index": day_index,
            "day_total": day_total,
        },
    )


@app.get("/clip/{slug}")
def page_clip_redirect(slug: str):
    """旧的详情页地址，转到主页面并选中该期。"""
    return RedirectResponse(url=f"/?d={slug}", status_code=307)


@app.get("/content/{file_name}")
def serve_content(file_name: str):
    """提供原始 HTML。校验文件名并确认最终路径落在内容目录内。"""
    if not SAFE_FILE_NAME.match(file_name):
        raise HTTPException(status_code=400, detail="文件名不合法")

    content_root = config.CONTENT_DIR.resolve()
    target = (content_root / file_name).resolve()
    if not target.is_relative_to(content_root) or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(target, media_type="text/html; charset=utf-8")


# ---------------------------------------------------------------- 接口


@app.get("/api/clips")
def api_clips(
    q: str = "",
    category: str = "",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_missing: bool = False,
):
    with db.get_conn() as conn:
        total, items = models.list_clips(
            conn,
            q=q,
            category=category,
            limit=limit,
            offset=offset,
            include_missing=include_missing,
        )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@app.post("/api/scan")
def api_scan(x_admin_token: str = Header(default="")):
    if not config.ADMIN_TOKEN or not secrets.compare_digest(x_admin_token, config.ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="令牌缺失或不匹配")

    if not _scan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="已有扫描在进行中")
    try:
        return run_scan()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        _scan_lock.release()


@app.get("/healthz")
def healthz():
    with db.get_conn() as conn:
        return {"status": "ok", "clips": models.count_clips(conn)}
