"""平台适配器注册表。新增平台只加文件与一行注册，不改调用方。"""

from __future__ import annotations

from app.config import Settings
from app.providers.base import PlatformProvider, YtDlpProvider
from app.providers.bilibili import BilibiliProvider
from app.providers.podcast import PodcastProvider
from app.providers.youtube import YouTubeProvider

PROVIDER_CLASSES: dict[str, type[PlatformProvider]] = {
    "bilibili": BilibiliProvider,
    "youtube": YouTubeProvider,
    "podcast": PodcastProvider,
}


def get_provider(name: str, settings: Settings) -> PlatformProvider | None:
    """按名字取适配器。未支持的平台返回 None。"""
    cls = PROVIDER_CLASSES.get(name.strip().lower())
    if cls is None:
        return None
    return cls(settings)


__all__ = [
    "PROVIDER_CLASSES",
    "PlatformProvider",
    "YtDlpProvider",
    "get_provider",
]
