"""与 agent 的文件交接。

流水线不调用任何大模型接口。需要判断的环节交给 agent：

1. prepare 阶段把候选与字幕写成 ``<日期>.request.json``
2. agent 读取该文件，按其中的 output 说明处理，写出 ``<日期>.response.json``
3. finalize 阶段读回结果，校验后落库

两个阶段可以在不同进程、不同时间执行，交接文件本身就是全部状态。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.db import now_iso
from app.errors import HandoffError
from app.models import SOURCE_KINDS, VOCAB_KINDS, PreparedCandidate

logger = logging.getLogger(__name__)

REQUEST_VERSION = 1
RESPONSE_VERSION = 1

REQUEST_SUFFIX = ".request.json"
RESPONSE_SUFFIX = ".response.json"

INSTRUCTIONS = [
    "你是英语口语学习内容的选题与加工者。下面给出今天采集到的候选素材，每条含标题、来源、时长与字幕段落。",
    "素材面向每天只花十几分钟的学习者，偏好 3 到 4 分钟的短片段。",
    "请完成四件事：",
    "1. 给每条候选打 0 到 10 分的激励性评分。",
    "2. 选出最合适的一条，把它的序号填进 selected_index。同等条件下优先选时长接近 3 到 4 分钟的。",
    "3. 判断选中素材的 source_kind，取值见 output.schema。",
    "4. 对选中那条，提取生词、短语与口语化表达，并逐段翻译成中文。",
    "评分重点：内容有激励作用或表达有分量，口语自然地道，适合模仿跟读，语句完整能独立理解。",
    "以下情况要显著扣分，必要时直接排除：",
    "- 通篇脏话或侮辱性表达",
    "- 打斗、追逐、爆炸等几乎没有对白的片段",
    "- 对白零碎、缺上下文就看不懂的片段",
    "- 充斥人名、地名、专有名词，学不到通用表达的片段",
    "need_subtitles 为 true 的候选没有平台字幕，不要凭空生成字幕：",
    "- 若选中了这类候选，先按标题与来源搜索一份适配的英文字幕或完整台词（字幕站、台词站、社区转录均可），",
    "- 只复制字幕文本本身，不要下载视频或音频文件；",
    "- 把找到的全文按自然段落写进 response 的 selected_paragraphs，译文段落数必须与它一致；",
    "- 找不到可靠字幕就改选其他候选；所有候选都选不出来时才把该候选评 0 分。",
    "词条的 term 必须原样出现在选中候选的字幕文本里（自带或找到的）。",
    "只输出 JSON，不要输出任何解释性文字。",
]

RESPONSE_SCHEMA: dict[str, object] = {
    "version": f"number，固定为 {RESPONSE_VERSION}",
    "date": "string，格式 YYYY-MM-DD，与请求中的 date 一致",
    "candidate_scores": [
        {
            "index": "number，候选序号，从 1 开始",
            "score": "number，0 到 10，保留一位小数",
            "reason": "string，不超过 20 字",
        }
    ],
    "selected_index": "number，选中候选的序号，必须出现在 candidate_scores 中",
    "selected_paragraphs": [
        "string，仅当选中候选的 need_subtitles 为 true 时必填。",
        "agent 搜索得到的英文字幕全文，按自然段落划分；其他情况留空数组",
    ],
    "source_kind": f"string，选中素材的类型，取值 {'、'.join(SOURCE_KINDS)} 之一",
    "vocabulary": [
        {
            "kind": "string，取值 word、phrase 或 colloquial",
            "term": "string，必须原样出现在选中候选的字幕里，不要改成原形",
            "phonetic": "string，音标，可留空",
            "meaning_zh": "string，中文释义，不超过 20 字",
            "usage_note": "string，适用场合说明，不超过 30 字，可留空",
            "example_sentence": "string，从原文中原样摘一句，可留空",
        }
    ],
    "translation": [
        "string，第 1 段中文译文",
        "string，第 2 段中文译文，长度必须与选中候选的 transcript_paragraphs 完全一致",
    ],
}


@dataclass
class HandoffState:
    """某一天的交接进度。"""

    request_path: Path
    response_path: Path
    has_request: bool
    has_response: bool


def request_path(settings: Settings, run_date: str) -> Path:
    return settings.pending_path / f"{run_date}{REQUEST_SUFFIX}"


def response_path(settings: Settings, run_date: str) -> Path:
    return settings.pending_path / f"{run_date}{RESPONSE_SUFFIX}"


def handoff_state(settings: Settings, run_date: str) -> HandoffState:
    request = request_path(settings, run_date)
    response = response_path(settings, run_date)
    return HandoffState(
        request_path=request,
        response_path=response,
        has_request=request.exists(),
        has_response=response.exists(),
    )


def build_request_payload(
    settings: Settings, run_date: str, prepared: list[PreparedCandidate]
) -> dict[str, object]:
    """组装交给 agent 的请求内容。"""
    return {
        "version": REQUEST_VERSION,
        "date": run_date,
        "generated_at": now_iso(),
        "instructions": INSTRUCTIONS,
        "output": {
            "response_path": str(response_path(settings, run_date)),
            "schema": RESPONSE_SCHEMA,
        },
        "requirements": {
            "motivation_threshold": settings.motivation_threshold,
            "preferred_duration_seconds": settings.preferred_duration_seconds,
            "duration_range_seconds": [
                settings.min_duration_seconds,
                settings.max_duration_seconds,
            ],
            "source_kind_options": list(SOURCE_KINDS),
            "vocab_count_range": [settings.vocab_min_count, settings.vocab_max_count],
            "vocab_kinds": list(VOCAB_KINDS),
            "term_must_appear_in_transcript": True,
            "translation_must_match_selected_paragraphs": True,
        },
        "candidates": [
            {
                "index": item.index,
                "platform": item.candidate.platform,
                "external_id": item.candidate.external_id,
                "title": item.candidate.title,
                "author": item.candidate.author,
                "work": item.candidate.work,
                "url": item.candidate.url,
                "kind": item.candidate.kind,
                "duration_seconds": item.candidate.duration_seconds,
                "need_subtitles": item.transcript.is_empty,
                "from_platform_subtitle": item.transcript.from_platform_subtitle,
                "paragraph_count": len(item.transcript.paragraphs),
                "transcript_paragraphs": item.transcript.paragraphs,
            }
            for item in prepared
        ],
    }


def write_request(
    settings: Settings, run_date: str, prepared: list[PreparedCandidate]
) -> Path:
    """写出请求文件，覆盖同名旧文件。"""
    path = request_path(settings, run_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_request_payload(settings, run_date, prepared)
    _write_json(path, payload)
    logger.info("已写出交接请求：%s", path)
    return path


def read_request(settings: Settings, run_date: str) -> dict[str, object]:
    """读回请求文件。finalize 阶段靠它还原候选与字幕。"""
    path = request_path(settings, run_date)
    if not path.exists():
        raise HandoffError(
            f"找不到请求文件 {path}，请先执行 prepare 阶段生成候选"
        )
    return _read_json(path)


def read_response(settings: Settings, run_date: str) -> dict[str, object]:
    """读回 agent 写出的结果文件。"""
    path = response_path(settings, run_date)
    if not path.exists():
        raise HandoffError(
            f"还没有收到 agent 的结果文件 {path}，"
            f"请让 agent 按请求文件里的 output 说明处理后重试"
        )
    return _read_json(path)


def candidate_entries(
    request_payload: dict[str, object],
) -> dict[int, dict[str, object]]:
    """把请求文件里的候选按 index 索引起来。"""
    raw = request_payload.get("candidates")
    if not isinstance(raw, list) or not raw:
        raise HandoffError("请求文件里没有 candidates")

    entries: dict[int, dict[str, object]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        entries[index] = item

    if not entries:
        raise HandoffError("请求文件里的 candidates 缺少合法的 index")
    return entries


def transcript_paragraphs_of(candidate: dict[str, object]) -> list[str]:
    """取候选的字幕段落。"""
    raw = candidate.get("transcript_paragraphs")
    if not isinstance(raw, list):
        raise HandoffError("候选缺少 transcript_paragraphs 字段")

    paragraphs = [str(item).strip() for item in raw if str(item).strip()]
    if not paragraphs:
        raise HandoffError("候选的字幕为空")
    return paragraphs


# agent 搜索回来的字幕上限。3 到 4 分钟视频的字幕全文远够不到这个值，
# 超过就认定抄进了别的长文，拒收。
MAX_SEARCHED_SUBTITLE_CHARS = 20_000


def selected_transcript_of(
    candidate: dict[str, object], response_payload: dict[str, object]
) -> list[str]:
    """选中候选的字幕段落。

    need_subtitles 候选取 response 里 agent 搜索得到的 selected_paragraphs；
    其余候选取请求里的 transcript_paragraphs。
    """
    if bool(candidate.get("need_subtitles")):
        raw = response_payload.get("selected_paragraphs")
        if not isinstance(raw, list):
            raise HandoffError(
                "选中候选需要字幕，但结果文件缺少 selected_paragraphs 数组"
            )
        paragraphs = [str(item).strip() for item in raw if str(item).strip()]
        if not paragraphs:
            raise HandoffError("选中候选需要字幕，但 selected_paragraphs 为空")
        total_chars = sum(len(part) for part in paragraphs)
        if total_chars > MAX_SEARCHED_SUBTITLE_CHARS:
            raise HandoffError(
                f"selected_paragraphs 过长（{total_chars} 字符），疑似不是字幕文本"
            )
        return paragraphs
    return transcript_paragraphs_of(candidate)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise HandoffError(f"写入 {path} 失败：{exc}") from exc


def _read_json(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HandoffError(f"读取 {path} 失败：{exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HandoffError(f"{path} 不是合法 JSON：{exc}") from exc

    if not isinstance(data, dict):
        raise HandoffError(f"{path} 的顶层结构不是对象")
    return data
