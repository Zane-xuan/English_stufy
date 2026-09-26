"""每日内容流水线。

判定环节交给 agent，不调用任何大模型接口，因此流水线分成两段：

- ``prepare``：采集候选、取字幕、写出交接请求文件，然后停下等 agent
- ``finalize``：读回 agent 的结果文件，校验通过后落库

两段可以分开、隔天执行，全部状态都在 ``data/pending/`` 下的两个 JSON 文件里。
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date

from app.config import Settings
from app.db import (
    connection,
    get_candidate,
    has_content,
    list_pending_candidates,
    log_stage,
    mark_candidate_used,
    update_candidate_score,
)
from app.errors import (
    EnglishStudyError,
    PipelineError,
    SubtitleError,
)
from app.models import (
    RESULT_FAILED,
    RESULT_SUCCESS,
    STAGE_AGENT,
    STAGE_SUBTITLE,
    DailyContent,
    PreparedCandidate,
    Transcript,
)
from app.pipeline.analyze import validate_response
from app.pipeline.collect import collect_candidates
from app.pipeline.handoff import (
    candidate_entries,
    read_request,
    read_response,
    request_path,
    response_path,
    write_request,
)
from app.pipeline.media import download_local_video
from app.pipeline.store import save_content
from app.pipeline.subtitle import get_transcript
from app.providers import get_provider

logger = logging.getLogger(__name__)

__all__ = ["finalize", "prepare", "today"]


def today() -> str:
    return date.today().isoformat()


def prepare(
    settings: Settings,
    run_date: str | None = None,
    *,
    force: bool = False,
    only_platform: str | None = None,
) -> str:
    """采集候选并写出交接请求文件。"""
    target = run_date or today()
    if only_platform:
        settings = replace(settings, prefer_platforms=(only_platform.strip().lower(),))

    _ensure_date_free(target, force)

    collect_candidates(settings, target)
    prepared = _prepare_candidates(settings, target)
    request = write_request(settings, target, prepared)

    return (
        f"已准备 {len(prepared)} 条候选，请求文件：{request}\n"
        f"把该文件交给 agent 处理，结果写到 {response_path(settings, target)}，"
        f"然后执行 finalize 阶段"
    )


def finalize(
    settings: Settings,
    run_date: str | None = None,
    *,
    force: bool = False,
) -> str:
    """读回 agent 的结果文件，校验通过后落库。"""
    target = run_date or today()
    _ensure_date_free(target, force)

    request_payload = read_request(settings, target)
    response_payload = read_response(settings, target)

    try:
        decision = validate_response(response_payload, request_payload, settings)
        entries = candidate_entries(request_payload)
        selected = entries[decision.selected_index]
        paragraphs = decision.selected_paragraphs
    except EnglishStudyError as exc:
        log_stage(target, STAGE_AGENT, RESULT_FAILED, str(exc))
        raise PipelineError(f"agent 结果校验失败：{exc}") from exc

    with connection() as conn:
        candidate = get_candidate(
            conn, str(selected.get("platform") or ""), str(selected.get("external_id") or "")
        )
    if candidate is None:
        raise PipelineError("请求文件里的候选在数据库中已不存在，请重新执行 prepare")

    top_score = max(item.score for item in decision.scores)
    if decision.selected_score < top_score:
        logger.warning(
            "agent 选中的候选评分 %s 不是本批最高分 %s，按 agent 的选择继续",
            decision.selected_score,
            top_score,
        )

    provider = get_provider(candidate.platform, settings)
    embed_url = provider.embed_url(candidate) if provider else candidate.url

    content = DailyContent(
        content_date=target,
        title=candidate.title or "未命名素材",
        source_platform=candidate.platform,
        source_url=candidate.url,
        video_embed_url=embed_url,
        source_author=candidate.author,
        source_work=candidate.work,
        source_kind=decision.source_kind or candidate.kind or "speech",
        duration_seconds=candidate.duration_seconds,
        transcript_en="\n\n".join(paragraphs),
        transcript_zh="\n\n".join(decision.translation),
        motivation_score=decision.selected_score,
    )
    save_content(content, decision.vocabulary, replace=force)

    with connection() as conn:
        for score in decision.scores:
            entry = entries.get(score.index)
            if entry is None:
                continue
            update_candidate_score(
                conn,
                str(entry.get("platform") or ""),
                str(entry.get("external_id") or ""),
                score.score,
            )
        if candidate.id is not None:
            mark_candidate_used(conn, candidate.id)

    log_stage(
        target,
        STAGE_AGENT,
        RESULT_SUCCESS,
        f"选中候选 {decision.selected_index}，评分 {decision.selected_score}",
        candidate.platform,
    )

    if candidate.kind != "podcast":
        download_local_video(candidate, settings, target)

    return f"已生成 {target}：{content.title}"


def pending_status(settings: Settings, run_date: str | None = None) -> str:
    """看当前卡在哪一步，供命令行与接口展示。"""
    target = run_date or today()
    request = request_path(settings, target)
    response = response_path(settings, target)

    with connection() as conn:
        done = has_content(conn, target)

    if done:
        return f"{target} 已有内容，需要重跑请加 --force"
    if not request.exists():
        return f"{target} 还没开始，请先执行 prepare 阶段"
    if not response.exists():
        return (
            f"{target} 已备好候选，等待 agent 处理。\n"
            f"  请求文件：{request}\n"
            f"  结果写到：{response}"
        )
    return f"{target} 已收到 agent 结果，可以执行 finalize 阶段落库"


def _ensure_date_free(target: str, force: bool) -> None:
    if force:
        return
    with connection() as conn:
        if has_content(conn, target):
            raise PipelineError(f"{target} 已有记录，需要覆盖请加 --force")


def _prepare_candidates(
    settings: Settings, run_date: str
) -> list[PreparedCandidate]:
    """取候选并准备字幕，凑够 PREPARE_MAX_CANDIDATES 条交给 agent。

    只用平台现有字幕，不下载任何音视频：没有字幕的候选直接跳过，
    记进 fetch_log，不做语音转写。
    """
    pool_size = max(
        settings.prepare_max_candidates * 3, settings.candidate_limit_per_platform
    )
    with connection() as conn:
        pool = list_pending_candidates(
            conn,
            limit=pool_size,
            preferred_duration=settings.preferred_duration_seconds,
            min_duration=settings.min_duration_seconds,
            max_duration=settings.max_duration_seconds,
        )
    if not pool:
        raise PipelineError("候选池里没有未使用过的候选，请检查采集配置")

    prepared: list[PreparedCandidate] = []
    failures: list[str] = []

    for candidate in pool:
        if len(prepared) >= settings.prepare_max_candidates:
            break

        provider = get_provider(candidate.platform, settings)
        if provider is None:
            continue

        try:
            transcript = get_transcript(
                candidate, provider, settings, allow_transcribe=False
            )
        except SubtitleError as exc:
            logger.warning(
                "%s 取平台字幕失败（%s），标记为待 agent 搜索字幕",
                candidate.external_id, exc,
            )
            log_stage(
                run_date,
                STAGE_SUBTITLE,
                RESULT_FAILED,
                f"取字幕失败，交给 agent 搜索：{exc}",
                candidate.platform,
            )
            transcript = None

        if transcript is None:
            prepared.append(
                PreparedCandidate(
                    index=len(prepared) + 1,
                    candidate=candidate,
                    transcript=Transcript(),
                )
            )
            continue

        prepared.append(
            PreparedCandidate(
                index=len(prepared) + 1, candidate=candidate, transcript=transcript
            )
        )

    if not prepared:
        detail = "；".join(failures[:3]) if failures else "候选池为空"
        raise PipelineError(f"没有可交给 agent 的候选：{detail}")
    return prepared
