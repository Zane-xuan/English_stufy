"""多平台候选采集与降级。

按 PREFER_PLATFORMS 的顺序依次尝试，第一个能产出新候选的平台就用它，
后面的平台不再尝试。单个平台失败不中断，失败原因记进 fetch_log。
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.db import connection, log_stage, upsert_candidates
from app.errors import CollectError
from app.models import RESULT_FAILED, RESULT_SUCCESS, STAGE_COLLECT
from app.providers import get_provider

logger = logging.getLogger(__name__)


def collect_candidates(settings: Settings, run_date: str) -> int:
    """采集候选并写库，返回新增条数。全平台都没结果时抛 CollectError。"""
    total_new = 0
    errors: list[str] = []

    for name in settings.prefer_platforms:
        provider = get_provider(name, settings)
        if provider is None:
            logger.warning("未支持的平台 %s，跳过", name)
            log_stage(run_date, STAGE_COLLECT, RESULT_FAILED, "未支持的平台", name)
            continue

        try:
            candidates = provider.collect(
                settings.candidate_limit_per_platform, settings.search_queries
            )
        except CollectError as exc:
            errors.append(f"{name}: {exc}")
            log_stage(run_date, STAGE_COLLECT, RESULT_FAILED, str(exc), name)
            logger.warning("%s 采集失败：%s", name, exc)
            continue

        new_count = _save(candidates)
        total_new += new_count
        log_stage(
            run_date,
            STAGE_COLLECT,
            RESULT_SUCCESS,
            f"采集 {len(candidates)} 条，新增 {new_count} 条",
            name,
        )
        if total_new > 0:
            break

    if total_new == 0:
        detail = "；".join(errors) if errors else "候选均已使用过"
        raise CollectError(f"所有平台都没有采集到新候选：{detail}")
    return total_new


def _save(candidates) -> int:
    """独立事务写候选，保证后续环节失败时候选池不丢。"""
    if not candidates:
        return 0
    with connection() as conn:
        return upsert_candidates(conn, candidates)
