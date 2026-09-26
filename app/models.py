"""领域对象与常量定义。"""

from __future__ import annotations

from dataclasses import dataclass, field

PLATFORMS = ("bilibili", "youtube", "podcast", "official")

SOURCE_KINDS = (
    "speech",
    "movie",
    "dialogue",
    "monologue",
    "news",
    "interview",
    "podcast",
)

SOURCE_KIND_LABELS = {
    "speech": "演讲",
    "movie": "电影片段",
    "dialogue": "影视对话",
    "monologue": "独白",
    "news": "新闻",
    "interview": "访谈",
    "podcast": "播客",
}

VOCAB_WORD = "word"
VOCAB_PHRASE = "phrase"
VOCAB_COLLOQUIAL = "colloquial"
VOCAB_KINDS = (VOCAB_WORD, VOCAB_PHRASE, VOCAB_COLLOQUIAL)

STAGE_COLLECT = "collect"
STAGE_SUBTITLE = "subtitle"
STAGE_AGENT = "agent"
STAGE_STORE = "store"
STAGE_MEDIA = "media"
STAGES = (STAGE_COLLECT, STAGE_SUBTITLE, STAGE_AGENT, STAGE_STORE, STAGE_MEDIA)

RESULT_SUCCESS = "success"
RESULT_FAILED = "failed"

STATUS_PUBLISHED = "published"
STATUS_FAILED = "failed"

VOCAB_KIND_LABELS = {
    VOCAB_WORD: "生词",
    VOCAB_PHRASE: "短语",
    VOCAB_COLLOQUIAL: "口语表达",
}


@dataclass
class Candidate:
    """候选视频。platform 与 external_id 组合唯一。"""

    platform: str
    external_id: str
    url: str
    title: str = ""
    author: str = ""
    work: str = ""
    kind: str = ""
    duration_seconds: int | None = None
    motivation_score: float | None = None
    used: int = 0
    id: int | None = None


@dataclass
class VocabularyItem:
    """一条词汇或短语。"""

    kind: str
    term: str
    meaning_zh: str
    phonetic: str = ""
    usage_note: str = ""
    example_sentence: str = ""
    id: int | None = None
    content_id: int | None = None


@dataclass
class RawSubtitle:
    """平台返回的原始字幕内容，尚未解析。"""

    content: str
    fmt: str
    lang: str = "en"


@dataclass
class Transcript:
    """字幕结果。段落以列表形式承载，落库时用空行拼接。"""

    paragraphs: list[str] = field(default_factory=list)
    from_platform_subtitle: bool = False

    @property
    def is_empty(self) -> bool:
        return not any(part.strip() for part in self.paragraphs)

    def to_text(self) -> str:
        return "\n\n".join(part.strip() for part in self.paragraphs if part.strip())


@dataclass
class PreparedCandidate:
    """已拿到字幕、准备交给 agent 判断的候选。index 从 1 开始。"""

    index: int
    candidate: Candidate
    transcript: Transcript


@dataclass
class AgentScore:
    """agent 给某条候选的激励性评分。"""

    index: int
    score: float
    reason: str = ""


@dataclass
class AgentDecision:
    """agent 返回并通过校验的判定结果。"""

    selected_index: int
    scores: list[AgentScore] = field(default_factory=list)
    vocabulary: list[VocabularyItem] = field(default_factory=list)
    translation: list[str] = field(default_factory=list)
    source_kind: str = ""
    selected_paragraphs: list[str] = field(default_factory=list)

    @property
    def selected_score(self) -> float:
        for item in self.scores:
            if item.index == self.selected_index:
                return item.score
        return 0.0


@dataclass
class DailyContent:
    """当日内容。"""

    content_date: str
    title: str
    source_platform: str
    source_url: str
    source_kind: str
    transcript_en: str
    transcript_zh: str
    video_embed_url: str = ""
    source_author: str = ""
    source_work: str = ""
    duration_seconds: int | None = None
    motivation_score: float | None = None
    status: str = STATUS_PUBLISHED
    created_at: str = ""
    id: int | None = None


@dataclass
class FetchLogEntry:
    """一次采集或处理阶段的记录。"""

    run_date: str
    stage: str
    result: str
    platform: str = ""
    message: str = ""
    created_at: str = ""
    id: int | None = None


def split_paragraphs(text: str) -> list[str]:
    """按空行切分段落。正文与译文的段落对应关系依赖这个规则。"""
    if not text:
        return []
    blocks = text.replace("\r\n", "\n").split("\n\n")
    return [block.strip() for block in blocks if block.strip()]
