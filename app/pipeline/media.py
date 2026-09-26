"""本地媒体文件：下载、查找与过期清理。

浏览器里播放视频有两条渠道：

1. 本地渠道（优先）：把当天选中的视频下载到固定目录 ``MEDIA_DIR``，
   文件名按内容日期命名（``YYYY-MM-DD.<ext>``），页面用 <video>/<audio> 播放。
2. 在线渠道（兜底）：本地文件不存在或下载失败时，用来源平台的嵌入地址。

下载引擎用 third_party/ytdlp_scraper.py（yt-dlp 多平台封装，
支持 B 站 / YouTube / 播客音频 / X 等），通过 .env 的
YTDLP_COOKIE_FILE 与 HTTPS_PROXY 控制反爬登录态与代理。

数据库不保存任何媒体资源，只存来源 URL 与基本信息；
本地文件路径完全由内容日期派生，不需要落库。

媒体文件保留 ``MEDIA_RETENTION_DAYS`` 天（默认 3 天），
服务启动与每日流水线都会触发一次清理。
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import date
from pathlib import Path

from app.config import Settings
from app.models import (
    RESULT_FAILED,
    RESULT_SUCCESS,
    STAGE_MEDIA,
    Candidate,
)
from third_party.ytdlp_scraper import ScrapeOptions, VideoScraper

logger = logging.getLogger(__name__)

_FILENAME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.\w+$")


def local_media_candidates(media_root: Path, content_date: str) -> list[Path]:
    """列出某内容日期的全部本地媒体文件（视频与音频各一算两个）。"""
    if not media_root.is_dir():
        return []
    prefix = f"{content_date}."
    return sorted(
        path for path in media_root.iterdir()
        if path.is_file() and path.name.startswith(prefix)
    )


def find_local_media(settings: Settings, content_date: str) -> Path | None:
    """按日期找本地媒体文件。视频优先，其次音频，都没有返回 None。"""
    paths = local_media_candidates(settings.media_root, content_date)
    if not paths:
        return None
    video_exts = {"mp4", "mkv", "webm", "mov"}
    for path in paths:
        if path.suffix.lstrip(".").lower() in video_exts:
            return path
    return paths[0]


def download_local_media(candidate: Candidate, settings: Settings, content_date: str) -> Path | None:
    """把选中的媒体（视频或播客音频）下载到固定目录，失败时记日志并返回 None。

    下载引擎是 third_party/ytdlp_scraper.py 的 VideoScraper：
    自动识别平台（B 站 / YouTube / 播客音频直链等），按最佳质量合并输出。
    下载产物先落在临时目录，成功后重命名为 ``YYYY-MM-DD.<ext>``，
    保证文件名与内容日期一致（前端与清理逻辑都依赖这个约定）。
    失败不影响流水线：页面回退到在线渠道播放。
    """
    media_root = settings.media_root
    media_root.mkdir(parents=True, exist_ok=True)

    options = ScrapeOptions(
        output_dir=str(media_root),
        output_template=f"{content_date}.%(ext)s",
        quality="best" if candidate.kind != "podcast" else "bestaudio",
        overwrite=True,
        cookiefile=settings.ytdlp_cookie_file or None,
        proxy=settings.https_proxy or None,
        socket_timeout=120.0,
        retries=5,
    )
    scraper = VideoScraper(options)
    result = scraper.download(candidate.url)
    if result.status != "finished" or not result.filepath:
        reason = result.error or f"状态 {result.status}"
        logger.warning("本地媒体下载失败，页面将使用在线播放：%s", reason)
        _log_stage(settings, content_date, STAGE_MEDIA, RESULT_FAILED, f"下载失败：{reason}")
        return None

    path = Path(result.filepath)
    # yt-dlp 合并/转换后扩展名可能变化（如 .mkv → .mp4），把最终文件
    # 挪到扁平的 data/media/<日期>.<ext>，保持前端 /media 路由与清理约定。
    final = media_root / path.name
    if path != final:
        try:
            shutil.move(str(path), str(final))
            path = final
        except OSError as exc:
            logger.warning("媒体文件改名失败，保留原路径：%s", exc)

    logger.info("本地媒体已下载：%s（%.1f MB）", path, path.stat().st_size / 1_048_576)
    _log_stage(settings, content_date, STAGE_MEDIA, RESULT_SUCCESS, f"下载到 {path.name}")
    return path


def cleanup_expired_media(settings: Settings) -> list[Path]:
    """删除超过保留天数的本地媒体文件，返回被删掉的文件列表。

    只按文件名里的日期判断（文件名就是内容日期），不读文件内容。
    保留策略：日期距今 <= MEDIA_RETENTION_DAYS 天的一律保留。
    """
    root = settings.media_root
    if not root.is_dir():
        return []

    today = date.today()
    removed: list[Path] = []
    for path in sorted(root.iterdir()):
        if not path.is_file() or not _FILENAME_PATTERN.match(path.name):
            continue
        try:
            file_date = date.fromisoformat(path.name[:10])
        except ValueError:
            continue
        age_days = (today - file_date).days
        if age_days > settings.media_retention_days:
            try:
                path.unlink()
                removed.append(path)
                logger.info("清理过期媒体文件：%s（%d 天前）", path.name, age_days)
            except OSError as exc:
                logger.warning("清理 %s 失败：%s", path.name, exc)
    return removed


def _log_stage(
    settings: Settings, content_date: str, stage: str, result: str, message: str
) -> None:
    from app.db import log_stage

    try:
        log_stage(content_date, stage, result, message)
    except Exception:  # 日志失败不应影响下载主流程
        logger.debug("media 阶段日志写入失败", exc_info=True)
