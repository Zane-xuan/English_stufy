"""APScheduler 定时任务注册。任务随服务启动注册，进程内运行。"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.errors import PipelineError
from app.pipeline import prepare, today

logger = logging.getLogger(__name__)

JOB_ID = "daily_content"

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
