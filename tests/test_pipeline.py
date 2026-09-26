"""单元测试。对应 TEST_CASES.md 中不依赖网络的用例。

涉及真实平台抓取、语音转写与 agent 实际判定的用例（TC-01 到 TC-04、TC-09 到 TC-11、
TC-14、TC-18、TC-19）需要手工验证，不在本文件内。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.config import get_settings, reset_settings_cache
from app.db import (
    connection,
    get_daily_content,
    init_db,
    list_pending_candidates,
    upsert_candidates,
)
from app.errors import AnalyzeError, HandoffError, StoreError
from app.models import (
    Candidate,
    DailyContent,
    PreparedCandidate,
    RawSubtitle,
    Transcript,
    VocabularyItem,
)
from app.pipeline.analyze import validate_response
from app.pipeline.handoff import (
    candidate_entries,
    read_request,
    read_response,
    response_path,
    transcript_paragraphs_of,
    write_request,
)
from app.pipeline.store import save_content
from app.pipeline.subtitle import (
    dedupe_segments,
    group_into_paragraphs,
    parse_raw_subtitle,
)

PARAGRAPHS = ["You have got to keep going.", "Resilience matters most."]


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    """把数据库与交接目录指到临时目录，避免污染 data/。"""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("PENDING_DIR", str(tmp_path / "pending"))
    monkeypatch.setenv("VOCAB_MIN_COUNT", "2")
    monkeypatch.setenv("VOCAB_MAX_COUNT", "5")
    reset_settings_cache()
    init_db()
    yield get_settings()
    reset_settings_cache()


def make_candidate(external_id: str, score: float | None, **kwargs) -> Candidate:
    return Candidate(
        platform=kwargs.pop("platform", "bilibili"),
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        title=kwargs.pop("title", f"视频 {external_id}"),
        motivation_score=score,
        **kwargs,
    )


def make_content(content_date: str, **kwargs) -> DailyContent:
    return DailyContent(
        content_date=content_date,
        title=kwargs.pop("title", "测试素材"),
        source_platform="bilibili",
        source_url="https://example.com/v/1",
        source_kind="speech",
        transcript_en="Hello there.\n\nKeep going.",
        transcript_zh="你好。\n\n继续前进。",
        **kwargs,
    )


def make_vocab(kind: str, term: str) -> VocabularyItem:
    return VocabularyItem(kind=kind, term=term, meaning_zh="释义")


def make_request_payload(
    paragraphs_by_index: dict[int, list[str]],
) -> dict[str, object]:
    return {
        "version": 1,
        "date": "2026-09-26",
        "candidates": [
            {
                "index": index,
                "platform": "bilibili",
                "external_id": f"BV{index}",
                "title": f"候选 {index}",
                "transcript_paragraphs": paragraphs,
            }
            for index, paragraphs in paragraphs_by_index.items()
        ],
    }


def make_response_payload(
    selected_index: int,
    scores: dict[int, float],
    vocabulary: list[dict[str, object]],
    translation: list[str],
) -> dict[str, object]:
    return {
        "version": 1,
        "date": "2026-09-26",
        "candidate_scores": [
            {"index": index, "score": score, "reason": ""}
            for index, score in scores.items()
        ],
        "selected_index": selected_index,
        "vocabulary": vocabulary,
        "translation": translation,
    }


def default_vocabulary() -> list[dict[str, object]]:
    return [
        {"kind": "phrase", "term": "keep going", "meaning_zh": "继续前进"},
        {"kind": "word", "term": "Resilience", "meaning_zh": "韧性"},
    ]


def test_daily_run_time_parsing(settings):
    assert settings.daily_run_hm == (7, 0)


def test_candidate_dedupe(settings):
    """TC-05：同一批候选重复采集不新增。"""
    batch = [make_candidate("BV1", 8.0), make_candidate("BV2", 7.5)]
    with connection() as conn:
        first = upsert_candidates(conn, batch)
        second = upsert_candidates(conn, batch)
        total = conn.execute("SELECT COUNT(*) AS n FROM candidate").fetchone()["n"]
    assert first == 2
    assert second == 0
    assert total == 2


def test_pending_candidates_skips_used(settings):
    """TC-08：已使用过的候选不再进入下一轮。"""
    with connection() as conn:
        upsert_candidates(conn, [make_candidate("BV1", 9.2), make_candidate("BV2", None)])
        conn.execute("UPDATE candidate SET used = 1 WHERE external_id = 'BV1'")
        pending = list_pending_candidates(conn, limit=10)
    assert [item.external_id for item in pending] == ["BV2"]


def test_pending_candidates_puts_scored_first(settings):
    """已打分的候选优先复用，避免重复判断。"""
    with connection() as conn:
        upsert_candidates(conn, [make_candidate("BV1", None), make_candidate("BV2", 8.0)])
        pending = list_pending_candidates(conn, limit=10)
    assert [item.external_id for item in pending] == ["BV2", "BV1"]


def test_save_content_rejects_duplicate_date(settings):
    """TC-17：同日重复执行且未指定覆盖时拒绝写入。"""
    save_content(make_content("2026-09-26"), [make_vocab("word", "resilience")])
    with pytest.raises(StoreError):
        save_content(make_content("2026-09-26"), [make_vocab("word", "grit")])


def test_save_content_replace_clears_old_vocabulary(settings):
    """TC-17：带覆盖重跑时旧词汇被清掉，不累加。"""
    target = "2026-09-26"
    save_content(make_content(target), [make_vocab("word", "resilience")])
    save_content(
        make_content(target, title="新标题"),
        [make_vocab("word", "grit"), make_vocab("phrase", "hold on")],
        replace=True,
    )

    with connection() as conn:
        rows = conn.execute("SELECT COUNT(*) AS n FROM daily_content").fetchone()["n"]
        result = get_daily_content(conn, target)

    assert rows == 1
    assert result is not None
    content, vocabulary = result
    assert content.title == "新标题"
    assert {item.term for item in vocabulary} == {"grit", "hold on"}


def test_write_and_read_request(settings):
    """交接请求写出去还能原样读回来。"""
    prepared = [
        PreparedCandidate(
            index=1,
            candidate=make_candidate("BV1", None),
            transcript=Transcript(paragraphs=PARAGRAPHS, from_platform_subtitle=True),
        )
    ]
    path = write_request(settings, "2026-09-26", prepared)
    assert path.exists()

    payload = read_request(settings, "2026-09-26")
    assert payload["date"] == "2026-09-26"
    assert payload["output"]["response_path"] == str(
        response_path(settings, "2026-09-26")
    )

    entries = candidate_entries(payload)
    assert transcript_paragraphs_of(entries[1]) == PARAGRAPHS


def test_read_request_missing_raises(settings):
    with pytest.raises(HandoffError):
        read_request(settings, "2026-09-26")


def test_read_response_missing_raises(settings):
    with pytest.raises(HandoffError):
        read_response(settings, "2026-09-26")


def test_read_response_invalid_json_raises(settings):
    """TC-20：结果文件不是合法 JSON 时报错，不落库。"""
    path = response_path(settings, "2026-09-26")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("这不是 JSON", encoding="utf-8")
    with pytest.raises(HandoffError):
        read_response(settings, "2026-09-26")


def test_validate_response_ok(settings):
    """TC-06：选中候选评分达标、词汇与译文都合法时通过。"""
    request = make_request_payload({1: PARAGRAPHS})
    response = make_response_payload(
        1, {1: 8.5}, default_vocabulary(), ["你必须继续前进。", "韧性最重要。"]
    )
    decision = validate_response(response, request, settings)

    assert decision.selected_index == 1
    assert decision.selected_score == 8.5
    assert len(decision.translation) == len(PARAGRAPHS)
    assert {item.term for item in decision.vocabulary} == {"keep going", "Resilience"}


def test_validate_response_rejects_below_threshold(settings):
    """TC-07：选中候选评分低于阈值时拒绝。"""
    request = make_request_payload({1: PARAGRAPHS})
    response = make_response_payload(1, {1: 6.5}, default_vocabulary(), ["一", "二"])
    with pytest.raises(AnalyzeError):
        validate_response(response, request, settings)


def test_validate_response_rejects_bad_selected_index(settings):
    request = make_request_payload({1: PARAGRAPHS})
    response = make_response_payload(9, {1: 8.5}, default_vocabulary(), ["一", "二"])
    with pytest.raises(AnalyzeError):
        validate_response(response, request, settings)


def test_validate_response_rejects_translation_length_mismatch(settings):
    """TC-15：译文段落数与原文不一致时拒绝。"""
    request = make_request_payload({1: PARAGRAPHS})
    response = make_response_payload(1, {1: 8.5}, default_vocabulary(), ["只有一段"])
    with pytest.raises(AnalyzeError):
        validate_response(response, request, settings)


def test_validate_response_long_transcript_paragraph_count(settings):
    """TC-16：超长字幕的译文段落数同样必须与原文一致。"""
    long_paragraphs = [
        "You have got to keep going, and Resilience matters."
    ] + [f"Paragraph {index} of the talk." for index in range(2, 121)]
    assert len(long_paragraphs) == 120

    request = make_request_payload({1: long_paragraphs})
    response = make_response_payload(1, {1: 8.5}, default_vocabulary(), ["译文"] * 119)
    with pytest.raises(AnalyzeError):
        validate_response(response, request, settings)


def test_validate_response_drops_unlocatable_terms(settings):
    """TC-13：原文里定位不到的词条被丢弃。"""
    request = make_request_payload({1: PARAGRAPHS})
    vocabulary = [
        *default_vocabulary(),
        {"kind": "word", "term": "perseverance", "meaning_zh": "毅力"},
    ]
    response = make_response_payload(1, {1: 8.5}, vocabulary, ["一", "二"])

    decision = validate_response(response, request, settings)
    assert "perseverance" not in {item.term for item in decision.vocabulary}


def test_validate_response_rejects_too_few_vocabulary(settings):
    """TC-12：词条数少于下限时拒绝。"""
    request = make_request_payload({1: PARAGRAPHS})
    response = make_response_payload(
        1,
        {1: 8.5},
        [{"kind": "word", "term": "Resilience", "meaning_zh": "韧性"}],
        ["一", "二"],
    )
    with pytest.raises(AnalyzeError):
        validate_response(response, request, settings)


def test_validate_response_truncates_extra_vocabulary(settings):
    """TC-12：词条数超过上限时截断。"""
    paragraphs = ["alpha beta gamma delta epsilon zeta eta theta"]
    request = make_request_payload({1: paragraphs})
    vocabulary = [
        {"kind": "word", "term": term, "meaning_zh": "释义"}
        for term in ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    ]
    response = make_response_payload(1, {1: 8.5}, vocabulary, ["一"])

    decision = validate_response(response, request, settings)
    assert len(decision.vocabulary) == settings.vocab_max_count == 5


def test_validate_response_missing_vocabulary_array(settings):
    request = make_request_payload({1: PARAGRAPHS})
    response = make_response_payload(1, {1: 8.5}, [], ["一", "二"])
    with pytest.raises(AnalyzeError):
        validate_response(response, request, settings)


def test_dedupe_merges_rolling_captions():
    segments = dedupe_segments(["Hello", "Hello there", "Hello there", "Keep going."])
    assert segments == ["Hello there", "Keep going."]


def test_group_into_paragraphs_keeps_short_text():
    assert group_into_paragraphs(["Hello there."]) == ["Hello there."]


def test_group_into_paragraphs_splits_long_text():
    segments = ["This is a sentence." for _ in range(60)]
    paragraphs = group_into_paragraphs(segments, target_chars=100, max_chars=200)
    assert len(paragraphs) > 1
    assert all(len(paragraph) <= 200 for paragraph in paragraphs)


JSON3_SAMPLE = json.dumps(
    {
        "events": [
            {"segs": [{"utf8": "Hello "}, {"utf8": "there."}]},
            {"segs": [{"utf8": "Hello "}, {"utf8": "there."}]},
            {"segs": [{"utf8": "Keep "}, {"utf8": "going."}]},
        ]
    }
)

VTT_SAMPLE = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.000
Hello there.

00:00:03.000 --> 00:00:05.000
Keep going.
"""

BILIBILI_SAMPLE = json.dumps(
    {
        "body": [
            {"from": 0.0, "to": 2.0, "content": "Hello there."},
            {"from": 2.0, "to": 4.0, "content": "Keep going."},
        ]
    }
)


def test_parse_json3_subtitle():
    segments = parse_raw_subtitle(RawSubtitle(content=JSON3_SAMPLE, fmt="json3"))
    assert segments == ["Hello there.", "Keep going."]


def test_parse_vtt_subtitle():
    segments = parse_raw_subtitle(RawSubtitle(content=VTT_SAMPLE, fmt="vtt"))
    assert segments == ["Hello there.", "Keep going."]


def test_parse_bilibili_subtitle():
    segments = parse_raw_subtitle(RawSubtitle(content=BILIBILI_SAMPLE, fmt="json"))
    assert segments == ["Hello there.", "Keep going."]


def test_parse_empty_subtitle():
    assert parse_raw_subtitle(RawSubtitle(content="   ", fmt="vtt")) == []
