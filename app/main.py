"""FastAPI 应用：页面路由与接口。"""

from __future__ import annotations

import base64
import re
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, db, models, plan, render
from .scan import scan as run_scan

SAFE_FILE_NAME = re.compile(r"^[A-Za-z0-9._-]+\.html$")

# 预览「今天」用的查询参数与 cookie
PREVIEW_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PREVIEW_COOKIE = "preview_today"

# 单条补充的长度上限（字符）
MAX_SUPPLEMENT_LEN = 10000

# 不在服务区间的日子（按设计是周日）回顾这么多天里发布过的资源
REVIEW_DAYS = 7

_scan_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


# 对外只开放页面与必要接口，关闭默认可视化文档与 schema，避免向外暴露接口结构
app = FastAPI(
    title="English Study",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


def _static_version() -> str:
    """静态资源版本号：取 static 目录里最新的修改时间。

    文件一变版本号就变，页面里引用的地址随之改变，浏览器与 CDN 就不会再拿旧缓存。
    """
    latest = max(
        (p.stat().st_mtime for p in config.STATIC_DIR.glob("*") if p.is_file()),
        default=0.0,
    )
    return str(int(latest))


templates.env.globals["static_v"] = _static_version()


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


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """给所有响应加一组安全的默认响应头；HTML 不缓存，保证外壳标记始终最新。"""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ---------------------------------------------------------------- 页面


def _resolve_preview(request: Request, raw: str) -> str:
    """解析预览用的「今天」。开关关闭时永远返回空串。

    优先取 ?today=，其次取上次写入的 cookie，这样预览期间点来点去都停在同一天。
    """
    if not config.ALLOW_TODAY_OVERRIDE:
        return ""
    candidate = (raw or request.cookies.get(PREVIEW_COOKIE, "")).strip()
    if not PREVIEW_DATE_RE.match(candidate):
        return ""
    try:
        date.fromisoformat(candidate)
    except ValueError:
        return ""
    return candidate


@app.get("/", response_class=HTMLResponse)
def page_index(
    request: Request,
    d: str = "",
    q: str = "",
    category: str = "",
    today: str = "",
):
    """主页面：主内容区显示今天该主攻的那份资源，右侧抽屉列出全部往期。

    d 缺省时选今天落在服务区间内的那一份，一份都不在区间内则退回最新一份。
    today 仅在 ALLOW_TODAY_OVERRIDE 打开时生效，用来预览某一天的页面；预览时不写库。
    """
    preview_date = _resolve_preview(request, today)
    today_iso = preview_date or date.today().isoformat()

    with db.get_conn() as conn:
        total, items = models.list_clips(conn, q=q, category=category)
        categories = models.list_categories(conn)

        current = None
        not_found = False
        if d:
            current = models.get_clip(conn, d)
            not_found = current is None
        if current is None and not not_found:
            current = models.get_current(conn, today_iso)

        fragment = None
        file_exists = False
        if current is not None:
            path = config.CONTENT_DIR / current["file_name"]
            file_exists = path.is_file()
            if file_exists:
                fragment = render.get_fragment(path)
            elif not current["is_missing"] and not preview_date:
                # 预览模式只读，不标记缺失
                models.set_missing(conn, current["slug"], True)

        day_index = models.focus_day(current, today_iso) if current else None
        day_total = models.focus_total(current) if current else None

        # 今天任务：与正在浏览的 current 无关，只由今天落在谁的区间决定
        task = models.get_current(conn, today_iso)
        task_day = models.focus_day(task, today_iso) if task else None
        task_total = models.focus_total(task) if task else None

        supplement = models.get_supplement(conn, current["slug"]) if current else ""

        # 今天该做哪一步：取自 LEARNING_PLAN.md，只展示不落库
        daily_plan = plan.today_plan(task_day) if task else None

        # 今天不在任何服务区间（按设计是周日）：列出近 REVIEW_DAYS 天发布过的资源供综合复盘
        review_clips: list[dict] = []
        if task and task_day is None:
            review_start = (
                date.fromisoformat(today_iso) - timedelta(days=REVIEW_DAYS - 1)
            ).isoformat()
            review_clips = models.list_clips_between(conn, review_start, today_iso)

    response = templates.TemplateResponse(
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
            "today": today_iso,
            "preview_date": preview_date,
            "day_index": day_index,
            "day_total": day_total,
            "task": task,
            "task_day": task_day,
            "task_total": task_total,
            "daily_plan": daily_plan,
            "review_clips": review_clips,
            "supplement": supplement,
            "notes_enabled": bool(config.NOTES_PASSWORD),
        },
    )

    # 预览开关打开时：带上 ?today= 就记住，?today=off 就清掉，其余情况沿用 cookie
    if config.ALLOW_TODAY_OVERRIDE:
        if preview_date:
            response.set_cookie(
                PREVIEW_COOKIE,
                preview_date,
                max_age=7 * 24 * 3600,
                httponly=True,
                samesite="lax",
            )
        elif today.strip() in {"off", "0"}:
            response.delete_cookie(PREVIEW_COOKIE)

    return response


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


def _notes_authorized(token: str) -> bool:
    """校验补充写入口令。未配置口令时一律拒绝（fail closed）。"""
    if not config.NOTES_PASSWORD:
        return False
    return secrets.compare_digest(
        token.encode("utf-8"), config.NOTES_PASSWORD.encode("utf-8")
    )


@app.post("/api/supplements")
def api_supplement_set(
    slug: str = Body(...),
    text: str = Body(""),
    x_notes_password: str = Header(default=""),
):
    """保存某一期的补充文字。需要 X-Notes-Password 请求头；内容为空白表示清空。"""
    if not _notes_authorized(x_notes_password):
        raise HTTPException(status_code=401, detail="口令缺失或不匹配")

    slug = slug.strip()
    if not slug:
        raise HTTPException(status_code=400, detail="缺少 slug")
    if len(text) > MAX_SUPPLEMENT_LEN:
        raise HTTPException(status_code=413, detail="补充内容过长")

    with db.get_conn() as conn:
        if models.get_clip(conn, slug) is None:
            raise HTTPException(status_code=404, detail="这一期不存在")
        models.set_supplement(conn, slug, text)

    return {"slug": slug, "text": text if text.strip() else ""}


@app.get("/healthz")
def healthz():
    with db.get_conn() as conn:
        return {"status": "ok", "clips": models.count_clips(conn)}