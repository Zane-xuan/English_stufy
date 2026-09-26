"""APScheduler 定时任务注册。任务随服务启动注册，进程内运行。"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.errors import PipelineError
from app.pipeline import prepare, today
from app.pipeline.media import cleanup_expired_media

logger = logging.getLogger(__name__)

JOB_ID = "daily_content"
CLEANUP_JOB_ID = "media_cleanup"

_scheduler: BackgroundScheduler | None = None


def _daily_job(settings: Settings) -> None:
    """定时任务体，只跑 prepare 阶段。

    finalize 要等 agent 写完结果文件才能跑，由外部脚本串联，
    不放在进程内定时任务里，避免在结果没准备好时空转。
    """
    target = today()
    try:
        message = prepare(settings, target)
        logger.info("定时任务完成：%s", message)
    except PipelineError as exc:
        logger.error("定时任务失败：%s", exc)
    except Exception:
        logger.exception("定时任务出现未预期错误")


def _media_cleanup_job(settings: Settings) -> None:
    """每天清理一次过期的本地媒体文件，保证磁盘上不长期囤积视频。

    清理本身幂等：没有过期文件时什么都不做。
    """
    try:
        removed = cleanup_expired_media(settings)
        if removed:
            logger.info("定时清理过期媒体文件 %d 个", len(removed))
    except Exception:
        logger.exception("媒体清理任务失败")


def start_scheduler(settings: Settings) -> BackgroundScheduler:
    """注册并启动每日任务。重复调用不会产生第二个调度器。"""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    hour, minute = settings.daily_run_hm
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        _daily_job,
        CronTrigger(hour=hour, minute=minute),
        args=[settings],
        id=JOB_ID,
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=3600,
    )
    # 每天 03:00 清理过期媒体文件。保留期由 MEDIA_RETENTION_DAYS 控制（默认 3 天），
    # 每天清一次等价于"每个文件最多留存保留期"，同时磁盘始终干净。
    scheduler.add_job(
        _media_cleanup_job,
        CronTrigger(hour=3, minute=0),
        args=[settings],
        id=CLEANUP_JOB_ID,
        replace_existing=True,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("定时任务已注册：每天 %02d:%02d", hour, minute)
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def is_running() -> bool:
    return _scheduler is not None and _scheduler.running
