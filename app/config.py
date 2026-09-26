"""读取 .env 配置，集中暴露为 Settings 对象。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from app.errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

# 默认搜索关键词，覆盖演讲、电影、访谈、新闻四类。
# 电影类刻意用 monologue、speech scene 这类词，避开 movie scene 会召回的打斗片段。
# 前缀 recent: 表示按上传时间排序，用于新闻类，保证时效。
DEFAULT_SEARCH_QUERIES = (
    "motivational speech",
    "TED talk",
    "famous movie monologue",
    "best movie speech scene",
    "movie scene powerful dialogue",
    "english interview",
    "recent:BBC news report",
    "recent:english news segment",
)


def _raw(key: str, default: str = "") -> str:
    """取字符串配置，去掉首尾空白。"""
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip()


def _int(key: str, default: int) -> int:
    text = _raw(key)
    if not text:
        return default
    try:
        return int(text)
    except ValueError as exc:
        raise ConfigError(f"配置项 {key} 必须是整数，当前值为 {text!r}") from exc


def _float(key: str, default: float) -> float:
    text = _raw(key)
    if not text:
        return default
    try:
        return float(text)
    except ValueError as exc:
        raise ConfigError(f"配置项 {key} 必须是数字，当前值为 {text!r}") from exc


def _items(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    text = _raw(key)
    if not text:
        return default
    return tuple(part.strip() for part in text.split(",") if part.strip())


def _lower_items(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    text = _raw(key)
    if not text:
        return default
    items = tuple(part.strip().lower() for part in text.split(",") if part.strip())
    if not items:
        raise ConfigError(f"配置项 {key} 不能为空列表")
    return items


@dataclass(frozen=True)
class Settings:
    """应用配置快照。字段与 .env.example 一一对应。"""

    https_proxy: str
    prefer_platforms: tuple[str, ...]
    search_queries: tuple[str, ...]
    podcast_feeds: tuple[str, ...]
    candidate_limit_per_platform: int
    prepare_max_candidates: int
    min_duration_seconds: int
    max_duration_seconds: int
    preferred_duration_seconds: int
    daily_run_time: str
    motivation_threshold: float
    vocab_min_count: int
    vocab_max_count: int
    whisper_model: str
    whisper_device: str
    db_path: Path
    pending_dir: Path
    site_base_url: str

    @property
    def daily_run_hm(self) -> tuple[int, int]:
        """把 DAILY_RUN_TIME 解析成 (时, 分)。"""
        text = self.daily_run_time
        parts = text.split(":")
        if len(parts) != 2:
            raise ConfigError(f"DAILY_RUN_TIME 格式应为 HH:MM，当前值为 {text!r}")
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except ValueError as exc:
            raise ConfigError(f"DAILY_RUN_TIME 格式应为 HH:MM，当前值为 {text!r}") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ConfigError(f"DAILY_RUN_TIME 超出取值范围，当前值为 {text!r}")
        return hour, minute

    @property
    def db_file(self) -> Path:
        return resolve_path(self.db_path)

    @property
    def pending_path(self) -> Path:
        return resolve_path(self.pending_dir)


def resolve_path(target: Path) -> Path:
    """相对路径按项目根目录解析，避免受工作目录影响。"""
    if target.is_absolute():
        return target
    return PROJECT_ROOT / target


def load_settings(env_file: Path | None = None) -> Settings:
    """从 .env 加载配置。env_file 不存在时退回系统环境变量。"""
    target = env_file if env_file is not None else DEFAULT_ENV_FILE
    if target.exists():
        load_dotenv(target, override=False)

    settings = Settings(
        https_proxy=_raw("HTTPS_PROXY"),
        prefer_platforms=_lower_items(
            "PREFER_PLATFORMS", ("bilibili", "youtube", "podcast")
        ),
        search_queries=_items("SEARCH_QUERIES", DEFAULT_SEARCH_QUERIES),
        podcast_feeds=_items("PODCAST_FEEDS", ()),
        candidate_limit_per_platform=_int("CANDIDATE_LIMIT_PER_PLATFORM", 5),
        prepare_max_candidates=_int("PREPARE_MAX_CANDIDATES", 3),
        min_duration_seconds=_int("MIN_DURATION_SECONDS", 120),
        max_duration_seconds=_int("MAX_DURATION_SECONDS", 300),
        preferred_duration_seconds=_int("PREFERRED_DURATION_SECONDS", 210),
        daily_run_time=_raw("DAILY_RUN_TIME", "07:00"),
        motivation_threshold=_float("MOTIVATION_THRESHOLD", 7.0),
        vocab_min_count=_int("VOCAB_MIN_COUNT", 8),
        vocab_max_count=_int("VOCAB_MAX_COUNT", 40),
        whisper_model=_raw("WHISPER_MODEL", "small"),
        whisper_device=_raw("WHISPER_DEVICE", "cpu"),
        db_path=Path(_raw("DB_PATH", "data/english_study.db")),
        pending_dir=Path(_raw("PENDING_DIR", "data/pending")),
        site_base_url=_raw("SITE_BASE_URL", "http://127.0.0.1:8000"),
    )

    if settings.min_duration_seconds >= settings.max_duration_seconds:
        raise ConfigError("MIN_DURATION_SECONDS 必须小于 MAX_DURATION_SECONDS")
    if not (
        settings.min_duration_seconds
        <= settings.preferred_duration_seconds
        <= settings.max_duration_seconds
    ):
        raise ConfigError(
            "PREFERRED_DURATION_SECONDS 必须落在 MIN_DURATION_SECONDS 与 "
            "MAX_DURATION_SECONDS 之间"
        )
    if settings.vocab_min_count > settings.vocab_max_count:
        raise ConfigError("VOCAB_MIN_COUNT 不能大于 VOCAB_MAX_COUNT")
    if settings.prepare_max_candidates < 1:
        raise ConfigError("PREPARE_MAX_CANDIDATES 至少为 1")

    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内复用同一份配置。"""
    return load_settings()


def reset_settings_cache() -> None:
    """清掉配置缓存，供测试改写环境变量后调用。"""
    get_settings.cache_clear()
