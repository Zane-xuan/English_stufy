"""校验 agent 返回的判定结果。

agent 的返回一律先校验再落库：选中候选的评分是否达标、词条能否在原文定位、
译文段落数是否与原文一致。任一条不满足就抛 AnalyzeError，当天不落库。
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.errors import AnalyzeError
from app.models import (
    SOURCE_KINDS,
    VOCAB_KINDS,
    AgentDecision,
    AgentScore,
    VocabularyItem,
)
from app.pipeline.handoff import (
    candidate_entries,
    selected_transcript_of,
)

logger = logging.getLogger(__name__)


def validate_response(
    payload: dict[str, object],
    request_payload: dict[str, object],
    settings: Settings,
) -> AgentDecision:
    """把 agent 的结果文件校验成 AgentDecision。"""
    candidates = candidate_entries(request_payload)
    scores = _parse_scores(payload, candidates)
    selected_index = _parse_selected_index(payload, scores, candidates)

    selected = candidates[selected_index]
    paragraphs = selected_transcript_of(selected, payload)
    source_text = "\n\n".join(paragraphs)

    vocabulary = _build_vocabulary(payload, source_text, settings)
    translation = _parse_translation(payload, len(paragraphs))

    score = next(item.score for item in scores if item.index == selected_index)
    if score < settings.motivation_threshold:
        raise AnalyzeError(
            f"选中候选的激励性评分 {score} 低于阈值 {settings.motivation_threshold}"
        )

    return AgentDecision(
        selected_index=selected_index,
        scores=scores,
        vocabulary=vocabulary,
        translation=translation,
        source_kind=_parse_source_kind(payload),
        selected_paragraphs=paragraphs,
    )


def _parse_scores(
    payload: dict[str, object], candidates: dict[int, dict[str, object]]
) -> list[AgentScore]:
    raw = payload.get("candidate_scores")
    if not isinstance(raw, list):
        raise AnalyzeError("结果文件缺少 candidate_scores 数组")

    scores: list[AgentScore] = []
    seen: set[int] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))  # type: ignore[arg-type]
            score = float(item.get("score"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if index not in candidates or index in seen:
            continue
        seen.add(index)
        scores.append(
            AgentScore(
                index=index,
                score=max(0.0, min(10.0, score)),
                reason=str(item.get("reason") or "").strip(),
            )
        )

    if not scores:
        raise AnalyzeError("candidate_scores 里没有有效的评分项")
    return scores


def _parse_selected_index(
    payload: dict[str, object],
    scores: list[AgentScore],
    candidates: dict[int, dict[str, object]],
) -> int:
    try:
        index = int(payload.get("selected_index"))  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise AnalyzeError("selected_index 缺失或不是整数") from exc

    if index not in candidates:
        raise AnalyzeError(f"selected_index {index} 不在候选范围内")
    if not any(item.index == index for item in scores):
        raise AnalyzeError(f"selected_index {index} 没有对应的评分")
    return index


def _parse_translation(payload: dict[str, object], expected: int) -> list[str]:
    raw = payload.get("translation")
    if not isinstance(raw, list):
        raise AnalyzeError("结果文件缺少 translation 数组")

    items = [str(item).strip() for item in raw]
    if len(items) != expected:
        raise AnalyzeError(f"译文段落数 {len(items)} 与原文 {expected} 不一致")
    if any(not item for item in items):
        raise AnalyzeError("译文里出现空段落")
    return items


def _parse_source_kind(payload: dict[str, object]) -> str:
    """素材类型。缺失或不在取值范围内时返回空串，由调用方回退到候选自带的类型。"""
    raw = str(payload.get("source_kind") or "").strip().lower()
    if not raw:
        return ""
    if raw not in SOURCE_KINDS:
        logger.info("agent 返回的 source_kind %r 不在取值范围内，已忽略", raw)
        return ""
    return raw


def _build_vocabulary(
    payload: dict[str, object], source_text: str, settings: Settings
) -> list[VocabularyItem]:
    raw_items = payload.get("vocabulary")
    if not isinstance(raw_items, list):
        raise AnalyzeError("结果文件缺少 vocabulary 数组")

    lowered = source_text.lower()
    items: list[VocabularyItem] = []
    seen: set[tuple[str, str]] = set()

    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip().lower()
        term = str(raw.get("term") or "").strip()
        meaning = str(raw.get("meaning_zh") or "").strip()
        if kind not in VOCAB_KINDS or not term or not meaning:
            continue

        key = (kind, term.lower())
        if key in seen:
            continue
        if term.lower() not in lowered:
            logger.info("丢弃原文中定位不到的词条：%s", term)
            continue

        seen.add(key)
        items.append(
            VocabularyItem(
                kind=kind,
                term=term,
                meaning_zh=meaning,
                phonetic=str(raw.get("phonetic") or "").strip(),
                usage_note=str(raw.get("usage_note") or "").strip(),
                example_sentence=str(raw.get("example_sentence") or "").strip(),
            )
        )

    if not items:
        raise AnalyzeError("vocabulary 为空，或全部词条都无法在原文定位")
    if len(items) > settings.vocab_max_count:
        items = items[: settings.vocab_max_count]
    if len(items) < settings.vocab_min_count:
        raise AnalyzeError(
            f"只提取到 {len(items)} 条词条，少于下限 {settings.vocab_min_count}"
        )
    return items
