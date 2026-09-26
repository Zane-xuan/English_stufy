"""
===============================================================================
 ytdlp_scraper.py — 通用多站点视频抓取模块（单文件，可直接复用到自己的软件）
===============================================================================

本文件把 yt-dlp 的"多网站抓取能力"封装成一组简单、稳定的 API，
让你不必了解 YoutubeDL 内部细节，就能在自己的软件里抓取 1752 个站点。

-------------------------------------------------------------------------------
 快速开始
-------------------------------------------------------------------------------

    from ytdlp_scraper import VideoScraper

    scraper = VideoScraper()

    # 1) 只解析、不下载 —— 拿到标题/时长/封面/所有可下载格式
    info = scraper.extract("https://www.youtube.com/watch?v=YE7VzlLtp-4")
    print(info.title, info.duration, info.uploader)
    for f in info.formats:
        print(f.format_id, f.ext, f.resolution, f.filesize)

    # 2) 下载 —— 自动选最佳画质（视频+音频自动合并）
    result = scraper.download("https://www.bilibili.com/video/BV1xx411c7mD")
    print(result.filepath, result.status)

    # 3) 批量下载
    results = scraper.download_many([url1, url2, url3])

-------------------------------------------------------------------------------
 安装依赖
-------------------------------------------------------------------------------

    pip install -U yt-dlp

推荐（大幅提升可抓取成功率与画质，非必需但强烈建议）：

    pip install -U brotli certifi mutagen pycryptodomex requests urllib3 websockets
    pip install -U curl-cffi          # 浏览器 TLS 指纹伪装，绕过部分反爬
    # 并安装 ffmpeg（把视频流与音频流合并成完整文件）

-------------------------------------------------------------------------------
 设计说明（为什么这样封装）
-------------------------------------------------------------------------------

yt-dlp 的核心是"一张 URL 正则匹配表 + 1752 个站点解析器 + 统一的 formats 协议"：

    URL ──extract_info()──> info_dict{formats:[{url,vcodec,acodec,ext,...}]}
        ──process_video_result()──> 清洗/排序/选择格式
        ──HttpFD.real_download()──> 落盘

本模块**不复制** yt-dlp 的解析代码（那是 12 万行、且站点一变就要跟），
而是直接调用它公开的稳定 API，把结果规整成自己的数据类。
这样你能白拿 1752 个站点的解析能力，同时升级 yt-dlp 就能自动修好失效站点。

若你确实需要"把解析逻辑抽出来自己维护"，见文末《附录 A：自持解析的边界》。
===============================================================================
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Literal, Sequence

__all__ = [
    "VideoScraper",
    "ScrapeOptions",
    "VideoInfo",
    "FormatInfo",
    "DownloadResult",
    "ScrapeError",
    "CookieError",
    "UnsupportedURLError",
    "extract_info",
    "download",
    "list_supported_sites",
    "guess_extractor",
    "YTDLP_AVAILABLE",
    "SUPPORTED_SITES_COUNT",
]

# ---- yt-dlp 是唯一硬依赖 ----------------------------------------------------
try:
    import yt_dlp
    from yt_dlp.utils import DownloadError

    YTDLP_AVAILABLE = True
except ImportError:  # pragma: no cover - 给未安装时一个明确报错
    yt_dlp = None  # type: ignore[assignment]
    DownloadError = Exception  # type: ignore[misc,assignment]
    YTDLP_AVAILABLE = False

logger = logging.getLogger("ytdlp_scraper")

# 本模块导出时探测到的站点数量（延迟填充，避免 import 时启动 1752 个提取器）
SUPPORTED_SITES_COUNT: int | None = None


# =============================================================================
# 异常
# =============================================================================
class ScrapeError(Exception):
    """抓取失败的统一异常。原始 yt-dlp 异常放在 __cause__ / .raw。"""

    def __init__(self, message: str, url: str | None = None, raw: Exception | None = None):
        self.url = url
        self.raw = raw
        super().__init__(f"[{url}] {message}" if url else message)


class UnsupportedURLError(ScrapeError):
    """没有任何提取器能识别这个 URL。"""


class CookieError(ScrapeError):
    """Cookie 加载失败（需要登录 / 浏览器 cookie 库不可读等）。"""


# =============================================================================
# 数据模型
# =============================================================================
@dataclass
class FormatInfo:
    """单个可下载格式（一道流）。字段已归一化，缺失即为 None。"""

    format_id: str
    ext: str | None = None
    url: str | None = None
    protocol: str | None = None
    # 视频
    vcodec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    resolution: str | None = None  # 如 "1920x1080"
    dynamic_range: str | None = None  # SDR / HDR / Dolby Vision
    # 音频
    acodec: str | None = None
    audio_channels: int | None = None
    abr: float | None = None  # 音频码率 kbps
    language: str | None = None
    # 通用
    tbr: float | None = None  # 总码率 kbps
    filesize: int | None = None
    filesize_approx: int | None = None
    quality: float | None = None
    format_note: str | None = None
    has_drm: bool | None = None
    is_live: bool = False
    http_headers: dict[str, str] = field(default_factory=dict)

    @property
    def is_video_only(self) -> bool:
        return self.vcodec not in (None, "none") and self.acodec in (None, "none")

    @property
    def is_audio_only(self) -> bool:
        return self.acodec not in (None, "none") and self.vcodec in (None, "none")

    @property
    def best_filesize(self) -> int | None:
        """真实大小优先，退化到估算值。"""
        return self.filesize or self.filesize_approx

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "FormatInfo":
        return cls(
            format_id=str(raw.get("format_id") or ""),
            ext=raw.get("ext"),
            url=raw.get("url"),
            protocol=raw.get("protocol"),
            vcodec=raw.get("vcodec"),
            width=raw.get("width"),
            height=raw.get("height"),
            fps=raw.get("fps"),
            resolution=raw.get("resolution"),
            dynamic_range=raw.get("dynamic_range"),
            acodec=raw.get("acodec"),
            audio_channels=raw.get("audio_channels"),
            abr=raw.get("abr"),
            language=raw.get("language"),
            tbr=raw.get("tbr"),
            filesize=raw.get("filesize"),
            filesize_approx=raw.get("filesize_approx"),
            quality=raw.get("quality"),
            format_note=raw.get("format_note"),
            has_drm=raw.get("has_drm"),
            is_live=bool(raw.get("is_live")),
            http_headers=dict(raw.get("http_headers") or {}),
        )


@dataclass
class VideoInfo:
    """一次抓取的完整结果（单视频）。播放列表/多条目见 VideoInfo.entries。"""

    id: str
    title: str | None = None
    description: str | None = None
    duration: float | None = None  # 秒
    uploader: str | None = None
    uploader_id: str | None = None
    channel: str | None = None
    channel_id: str | None = None
    upload_date: str | None = None  # YYYYMMDD
    timestamp: int | None = None
    webpage_url: str | None = None
    thumbnail: str | None = None
    thumbnails: list[dict[str, Any]] = field(default_factory=list)
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    age_limit: int | None = None
    is_live: bool = False
    live_status: str | None = None  # is_live / post_live / was_live / not_live
    extractor: str | None = None  # 如 "youtube" / "bilibili" / "vimeo"
    extractor_key: str | None = None
    webpage_url_domain: str | None = None
    subtitles: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    automatic_captions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    # 归一化后的格式清单（核心产物）
    formats: list[FormatInfo] = field(default_factory=list)
    # 直接可下载 URL（单流场景，如直链 mp4 或 best 已选定）
    direct_url: str | None = None
    direct_ext: str | None = None
    # 播放列表 / 多条目
    is_playlist: bool = False
    playlist_id: str | None = None
    playlist_title: str | None = None
    entries: list["VideoInfo"] = field(default_factory=list)
    # 原始 info_dict（需要冷门字段时用；已剔除内部私有键）
    raw: dict[str, Any] = field(default_factory=dict)

    # ---- 便捷筛选 -------------------------------------------------------
    def video_formats(self) -> list[FormatInfo]:
        return [f for f in self.formats if f.is_video_only]

    def audio_formats(self) -> list[FormatInfo]:
        return [f for f in self.formats if f.is_audio_only]

    def merged_formats(self) -> list[FormatInfo]:
        """同时含视频与音频的单文件格式（如 360p mp4）。"""
        return [f for f in self.formats if not f.is_video_only and not f.is_audio_only]

    def best_audio(self) -> FormatInfo | None:
        """码率最高的纯音频格式。"""
        pool = self.audio_formats() or self.merged_formats()
        return max(pool, key=lambda f: (f.abr or 0, f.tbr or 0), default=None)

    def best_video(self, max_height: int | None = None, *, strict: bool = False) -> FormatInfo | None:
        """分辨率最高的纯视频格式。

        max_height: 限高。默认**不严格**——若没有 <= max_height 的流，
                    自动退化到"高于该值里最小的那条"（即最接近且不低于），
                    避免因为没有恰好 720p 就返回 None。
                    传 strict=True 则严格执行"只取 <= max_height"，无匹配返回 None。
        """
        pool = self.video_formats() or self.merged_formats()
        if not pool:
            return None
        key = lambda f: (f.height or 0, f.fps or 0, f.tbr or 0)
        if max_height is None:
            return max(pool, key=key)

        under = [f for f in pool if (f.height or 0) <= max_height]
        if under:
            return max(under, key=key)
        if strict:
            return None
        # 退化：没有低于上限的流时，取"高于上限里最小"的那条
        over = [f for f in pool if (f.height or 0) > max_height]
        return min(over, key=key) if over else None

    def format_by_id(self, format_id: str) -> FormatInfo | None:
        return next((f for f in self.formats if f.format_id == format_id), None)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, default=str)


@dataclass
class DownloadResult:
    """一次下载的结果。"""

    url: str
    status: Literal["finished", "failed", "skipped", "cancelled"]
    filepath: str | None = None
    info: VideoInfo | None = None
    error: str | None = None
    elapsed_sec: float | None = None


# =============================================================================
# 选项
# =============================================================================
Quality = Literal[
    "best",            # 最佳视频+最佳音频（默认，自动合并）
    "bestvideo",       # 只要最佳视频（无音频）
    "bestaudio",       # 只要最佳音频
    "worst",           # 最小体积
    "best_merged",     # 最佳"单文件"格式（含音视频，无需合并）
]


@dataclass
class ScrapeOptions:
    """抓取/下载选项。只暴露常用项，全部可选，安全默认值。

    需要冷门 yt-dlp 参数时，用 extra_opts 直接透传（键名同 yt-dlp params）。
    """

    # --- 画质与格式 ---
    quality: Quality = "best"
    max_height: int | None = None          # 例如 1080，只取 <=1080p
    format_spec: str | None = None         # 直接给 yt-dlp 表达式，优先级最高，如 "bv*[height<=720]+ba/b"
    merge_output_format: str | None = None  # 合并容器，如 "mp4" / "mkv"

    # --- 输出 ---
    output_dir: str | None = None          # 下载目录（默认当前目录）
    output_template: str | None = None     # 文件名模板，见 yt-dlp 的 output_template 文档
    overwrite: bool = False                # False = 已存在则跳过
    write_thumbnail: bool = False
    write_subtitles: bool = False
    subtitle_langs: Sequence[str] = ("zh-Hans", "zh-CN", "en")

    # --- 网络与反爬 ---
    cookies_from_browser: str | None = None   # "chrome"/"edge"/"firefox"/"brave"...
    cookiefile: str | None = None             # Netscape 格式 cookies.txt 路径
    impersonate: str | None = None            # "chrome" 等，需 curl-cffi
    proxy: str | None = None                  # "http://127.0.0.1:7890"
    http_headers: dict[str, str] = field(default_factory=dict)  # 如 Referer
    retries: int = 10
    socket_timeout: float = 30.0
    quiet: bool = True                        # 静默：不打印 yt-dlp 进度
    no_warnings: bool = False
    verbose: bool = False

    # --- 限速与并发 ---
    rate_limit: int | None = None             # 字节/秒
    concurrent_fragments: int | None = None   # HLS/DASH 分片并发数
    sleep_interval: float = 0.0               # 每个请求间随机休眠下限（防限流）
    max_sleep_interval: float = 0.0
    playlist_items: str | None = None         # 如 "1-10" / "1,3,5"
    no_playlist: bool = False

    # --- 提取行为 ---
    extract_flat: bool | str = False          # True = 只列举条目不解析每个视频
    ignore_errors: bool = True
    geo_bypass: bool = True
    force_generic: bool = False               # 强制用通用提取器

    # --- 透传 ---
    extra_opts: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# 主类
# =============================================================================
class VideoScraper:
    """多站点视频抓取器。线程/任务内可复用一个实例。

    参数:
        options:  ScrapeOptions，抓取/下载默认选项
        logger_impl: 可选自定义 logger（需实现 debug/info/warning/error），
                     用于把 yt-dlp 的输出接到你软件自己的日志里
        progress_hook: 可选进度回调，签名 fn(dict)；'status' 为
                       downloading / finished / error
                      downloading 时含 downloaded_bytes/total_bytes/speed/eta
    """

    def __init__(
        self,
        options: ScrapeOptions | None = None,
        *,
        logger_impl: Any | None = None,
        progress_hook: Callable[[dict[str, Any]], None] | None = None,
        postprocessor_hook: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if not YTDLP_AVAILABLE:
            raise ImportError(
                "未安装 yt-dlp。请执行：pip install -U yt-dlp\n"
                "（完整能力建议同时安装：pip install -U brotli certifi mutagen "
                "pycryptodomex requests urllib3 websockets curl-cffi）"
            )
        self.options = options or ScrapeOptions()
        self._logger_impl = logger_impl
        self._progress_hook = progress_hook
        self._postprocessor_hook = postprocessor_hook

    # ------------------------------------------------------------------ 内部
    @staticmethod
    def _strip_private(d: dict[str, Any]) -> dict[str, Any]:
        """剔除 yt-dlp 内部私有键（下划线开头）与不可序列化对象。"""
        out: dict[str, Any] = {}
        for k, v in d.items():
            if str(k).startswith("_"):
                continue
            if isinstance(v, (str, int, float, bool, type(None), list, dict)):
                out[k] = v
        return out

    def _opt_to_params(self, opt: ScrapeOptions, *, for_download: bool) -> dict[str, Any]:
        """把 ScrapeOptions 翻译成 yt-dlp 的 params 字典。"""
        p: dict[str, Any] = {
            "quiet": opt.quiet,
            "no_warnings": opt.no_warnings,
            "verbose": opt.verbose,
            "retries": opt.retries,
            "socket_timeout": opt.socket_timeout,
            "ignoreerrors": opt.ignore_errors,
            "geo_bypass": opt.geo_bypass,
            "noprogress": opt.quiet,
            "overwrites": opt.overwrite,
            "nopart": False,          # 允许 .part 断点续传
            "continuedl": True,       # 支持续传
            "no_color": True,
            # 强制使用内置下载器，避免依赖外部程序
            "external_downloader": None,
        }

        # 画质 / 格式表达式
        p["format"] = opt.format_spec or self._build_format_spec(opt)

        # 输出
        out_dir = str(Path(opt.output_dir).expanduser().resolve()) if opt.output_dir else os.getcwd()
        p["paths"] = {"home": out_dir}
        if opt.output_template:
            p["outtmpl"] = {"default": opt.output_template}
        if opt.merge_output_format:
            p["merge_output_format"] = opt.merge_output_format
        if opt.write_thumbnail:
            p["writethumbnail"] = True
        if opt.write_subtitles:
            p["writesubtitles"] = True
            p["writeautomaticsub"] = True
            p["subtitleslangs"] = list(opt.subtitle_langs)

        # 网络 / 反爬
        if opt.cookies_from_browser:
            p["cookiesfrombrowser"] = self._parse_cookies_from_browser(opt.cookies_from_browser)
        if opt.cookiefile:
            p["cookiefile"] = opt.cookiefile
        if opt.impersonate:
            p["impersonate"] = opt.impersonate
        if opt.proxy:
            p["proxy"] = opt.proxy
        if opt.http_headers:
            p["http_headers"] = dict(opt.http_headers)

        # 限速 / 并发 / 休眠
        if opt.rate_limit:
            p["ratelimit"] = opt.rate_limit
        if opt.concurrent_fragments:
            p["concurrent_fragment_downloads"] = opt.concurrent_fragments
        if opt.sleep_interval:
            p["sleep_interval"] = opt.sleep_interval
        if opt.max_sleep_interval:
            p["max_sleep_interval"] = opt.max_sleep_interval
        if opt.playlist_items:
            p["playlist_items"] = opt.playlist_items
        if opt.no_playlist:
            p["noplaylist"] = True

        # 提取行为
        if opt.extract_flat:
            p["extract_flat"] = opt.extract_flat
        if opt.force_generic:
            p["force_generic_extractor"] = True
        # 不下载时不要写任何文件
        if not for_download:
            p["skip_download"] = True

        # 钩子
        if self._logger_impl is not None:
            p["logger"] = self._logger_impl
        if self._progress_hook is not None:
            p["progress_hooks"] = [self._progress_hook]
        if self._postprocessor_hook is not None:
            p["postprocessor_hooks"] = [self._postprocessor_hook]

        p.update(opt.extra_opts)
        return p

    @staticmethod
    def _build_format_spec(opt: ScrapeOptions) -> str:
        """把简易 quality 选项翻译成 yt-dlp 格式表达式。"""
        if opt.quality == "bestvideo":
            base = "bv*" if not opt.max_height else f"bv*[height<={opt.max_height}]"
            return f"{base}/b"          # 退化到单文件
        if opt.quality == "bestaudio":
            return "ba/b"
        if opt.quality == "worst":
            return "wv*+wa/w"
        if opt.quality == "best_merged":
            # 只要"单文件"格式（含音视频），不需要 ffmpeg 合并。
            # 注意：DASH-only 站点可能没有此类格式 → 退化到 bv*+ba（需 ffmpeg）
            if opt.max_height:
                return f"b[height<={opt.max_height}]/b/bv*[height<={opt.max_height}]+ba/bv*+ba"
            return "b/bv*+ba"
        # best（默认）：最佳视频 + 最佳音频，自动合并；失败退化单文件
        if opt.max_height:
            return f"bv*[height<={opt.max_height}]+ba/b[height<={opt.max_height}]/bv*[height<={opt.max_height}]+ba/b"
        return "bv*+ba/b"

    @staticmethod
    def _parse_cookies_from_browser(spec: str) -> tuple:
        """'chrome' / 'chrome:Profile 1' / 'firefox' → yt-dlp 需要的元组。"""
        parts = spec.split(":", 1)
        browser = parts[0].strip().lower()
        profile = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
        return (browser, profile, None, None) if profile else (browser,)

    def _make_ydl(self, params: dict[str, Any]):
        # auto_init=True：加载默认提取器（1752 个），首次约需 1~3 秒
        return yt_dlp.YoutubeDL(params)

    # ------------------------------------------------------------ 公共 API
    def extract(
        self,
        url: str,
        *,
        options: ScrapeOptions | None = None,
        process: bool = True,
    ) -> VideoInfo:
        """解析 URL，返回结构化 VideoInfo（不下载）。

        process=False 时不做后续解析（更快，但播放列表条目不会被展开成完整信息）。

        失败时抛 ScrapeError 的子类：
            UnsupportedURLError  —— 没有提取器认领该 URL
            CookieError          —— 需要登录 / cookie 不可用
            ScrapeError          —— 其它（含站点解析失败、格式无可用等）
        """
        opt = options or self.options
        params = self._opt_to_params(opt, for_download=False)

        # 收集 yt-dlp 的错误消息，以便 None 返回时给出真实原因
        err_sink: list[str] = []

        class _ErrLogger:
            def debug(self, msg: str) -> None:
                pass

            def info(self, msg: str) -> None:
                pass

            def warning(self, msg: str) -> None:
                pass

            def error(self, msg: str) -> None:
                err_sink.append(str(msg))

        if "logger" not in params:
            params["logger"] = _ErrLogger()

        try:
            with self._make_ydl(params) as ydl:
                raw = ydl.extract_info(url, download=False, process=process)
                if raw is None:
                    detail = "; ".join(err_sink) or "提取器未返回结果（原因未知）"
                    raise self._classify_error(url, detail)
                if process:
                    raw = ydl.sanitize_info(raw, remove_private_keys=True)
                return self._to_video_info(raw)
        except DownloadError as e:
            raise self._wrap_error(url, e) from e

    def extract_many(
        self,
        urls: Iterable[str],
        *,
        options: ScrapeOptions | None = None,
        raise_on_error: bool = False,
    ) -> Iterator[VideoInfo]:
        """逐个解析多个 URL，逐个 yield（惰性，适合大列表）。"""
        for u in urls:
            try:
                yield self.extract(u, options=options)
            except ScrapeError as e:
                if raise_on_error:
                    raise
                logger.warning("解析失败，跳过: %s", e)

    def download(
        self,
        url: str,
        *,
        options: ScrapeOptions | None = None,
    ) -> DownloadResult:
        """下载单个 URL，返回 DownloadResult。

        不抛异常——失败信息放在 DownloadResult.status / .error 里，
        便于批量下载时继续处理下一个。
        """
        import time

        opt = options or self.options
        params = self._opt_to_params(opt, for_download=True)
        started = time.time()

        captured: dict[str, Any] = {}

        def _hook(d: dict[str, Any]) -> None:
            # 依次记录：下载完成 → 后处理完成后的最终路径
            if d.get("status") == "finished":
                captured["downloaded"] = d.get("filename")
                captured.setdefault("filepath", d.get("filename"))
            if d.get("status") == "finished" and d.get("postprocessor"):
                captured["filepath"] = d.get("info_dict", {}).get("filepath") or d.get("filename")
            if self._progress_hook is not None:
                self._progress_hook(d)

        def _pp_hook(d: dict[str, Any]) -> None:
            # MoveFilesAfterDownloadPP / 合并 之后拿最终文件名最可靠
            if d.get("status") == "finished" and d.get("postprocessor") in (
                "MoveFilesAfterDownload", "FFmpegMerger", "FFmpegVideoConvertor",
                "FFmpegExtractAudio", "FFmpegVideoRemuxer",
            ):
                captured["filepath"] = d.get("info_dict", {}).get("filepath")
            if self._postprocessor_hook is not None:
                self._postprocessor_hook(d)

        params["progress_hooks"] = [_hook]
        params["postprocessor_hooks"] = [_pp_hook]

        try:
            with self._make_ydl(params) as ydl:
                # 关闭 ignoreerrors 期间我们要能看到失败；但为兼容批量场景，
                # 用 try/except 捕获，并同时检查 extract_info 是否返回 None
                info_raw = ydl.extract_info(url, download=True)
                info = self._to_video_info(info_raw) if info_raw else None

                # ★ info_raw 为 None 说明 yt-dlp 内部吞掉了错误（ignoreerrors=True）
                if info_raw is None:
                    return DownloadResult(
                        url=url, status="failed",
                        error="提取或下载失败（原因被 yt-dlp 的 ignoreerrors 吞掉，"
                              "可设置 ScrapeOptions(ignore_errors=False) 查看详细报错）",
                        elapsed_sec=round(time.time() - started, 2),
                    )

                # 文件名解析优先级：后处理最终路径 > 下载完成路径 > prepare_filename
                filepath = (
                    captured.get("filepath")
                    or captured.get("downloaded")
                    or self._resolve_final_path(ydl, info_raw)
                )

            # 兜底：仍找不到时就按 video id 在输出目录里搜
            if not (filepath and os.path.exists(filepath)):
                out_dir = params.get("paths", {}).get("home") or os.getcwd()
                vid = (info_raw or {}).get("id") or (captured.get("filepath") or "")
                found = self._find_by_id(out_dir, str(vid))
                if found:
                    filepath = found

            # 若拿不到任何文件路径，且不是 simulate，则视为失败
            if not filepath and not params.get("simulate"):
                if not captured.get("downloaded"):
                    return DownloadResult(
                        url=url, status="failed", info=info,
                        error="下载未产生文件（可能是格式不可用 / 被跳过 / 权限问题）",
                        elapsed_sec=round(time.time() - started, 2),
                    )

            if filepath and not os.path.exists(filepath):
                return DownloadResult(
                    url=url, status="skipped", filepath=filepath, info=info,
                    error="文件未生成（可能命中 simulate / 写 stdout 等跳过逻辑）",
                    elapsed_sec=round(time.time() - started, 2),
                )

            return DownloadResult(
                url=url, status="finished", filepath=filepath, info=info,
                elapsed_sec=round(time.time() - started, 2),
            )
        except DownloadError as e:
            err = self._wrap_error(url, e)
            return DownloadResult(
                url=url, status="failed", error=str(err),
                elapsed_sec=round(time.time() - started, 2),
            )
        except Exception as e:  # 兜底，保证批量不中断
            return DownloadResult(
                url=url, status="failed", error=f"{type(e).__name__}: {e}",
                elapsed_sec=round(time.time() - started, 2),
            )

    @staticmethod
    def _resolve_final_path(ydl: Any, info_raw: dict[str, Any] | None) -> str | None:
        """用 yt-dlp 的 prepare_filename 反推落盘路径（含后处理改名/合并）。

        合并音视频时，实际文件是 <basename>.<merge_ext>，而 prepare_filename
        可能返回带 .fNNN 的子流名；这里做多轮候选探测。
        """
        if not info_raw:
            return None

        candidates: list[str] = []

        def _add(p: str | None) -> None:
            if p and p not in candidates:
                candidates.append(p)

        try:
            base_fn = ydl.prepare_filename(info_raw)
        except Exception:
            base_fn = None

        # ① 实际写入路径（yt-dlp 在 info 里记录的最准）
        for key in ("filepath", "_filename", "__files_to_move"):
            v = info_raw.get(key)
            if isinstance(v, str):
                _add(v)
            elif isinstance(v, dict):
                candidates.extend(x for x in v.keys() if isinstance(x, str))

        _add(base_fn)

        # ② 同主名的各种扩展名（后处理改名、合并换容器）
        if base_fn:
            base = os.path.splitext(base_fn)[0]
            # 去掉 yt-dlp 的 .fNNN 子流后缀
            base_nostream = re.sub(r"\.f\d+(-\w+)?$", "", base)
            for b in (base, base_nostream):
                _add(b)
                for ext in info_raw.get("ext"), "mp4", "mkv", "webm", "m4a", "mp3", "opus", "flac", "aac", "ogg", "wav":
                    if ext:
                        _add(f"{b}.{ext}")

        # ③ 在输出目录里按 id 找（最后兜底）
        for c in list(candidates):
            if os.path.exists(c):
                return c
        return candidates[0] if candidates else None

    @staticmethod
    def _find_by_id(output_dir: str, video_id: str) -> str | None:
        """在输出目录里按视频 id 搜文件（兜底，慢但可靠）。"""
        try:
            if not video_id or not os.path.isdir(output_dir):
                return None
            matches = [
                os.path.join(output_dir, f)
                for f in os.listdir(output_dir)
                if video_id in f and not f.endswith((".part", ".ytdl"))
            ]
            if not matches:
                return None
            return max(matches, key=os.path.getmtime)
        except OSError:
            return None

    def download_many(
        self,
        urls: Sequence[str],
        *,
        options: ScrapeOptions | None = None,
        on_result: Callable[[DownloadResult], None] | None = None,
        stop_on_error: bool = False,
    ) -> list[DownloadResult]:
        """批量下载。on_result 可用于边下边更新你软件的 UI。"""
        results: list[DownloadResult] = []
        for u in urls:
            r = self.download(u, options=options)
            results.append(r)
            if on_result is not None:
                on_result(r)
            if stop_on_error and r.status == "failed":
                break
        return results

    def list_formats(self, url: str, *, options: ScrapeOptions | None = None) -> list[FormatInfo]:
        """只拿格式清单（等价 --list-formats），比 extract() 更聚焦。"""
        return self.extract(url, options=options).formats

    def resolve_direct_url(
        self, url: str, *, quality: Quality = "best", options: ScrapeOptions | None = None
    ) -> str | None:
        """解析出可交给播放器/第三方下载器的【直链】。

        注意：返回的是**当前时刻**有效的 CDN 直链，通常带时效签名，
        必须立刻使用（尤其 YouTube/B 站）。要长期可用请自己下载落盘。
        """
        opt = options or self.options
        opt = ScrapeOptions(**{**asdict(opt), "quality": quality})
        info = self.extract(url, options=opt)
        # 若结果是单流（非 DASH），info.direct_url 已填好
        if info.direct_url:
            return info.direct_url
        # 否则按质量挑一条
        if quality == "bestaudio":
            fmt = info.best_audio()
        elif quality == "bestvideo":
            fmt = info.best_video(opt.max_height)
        else:
            fmt = info.best_video(opt.max_height)
            if fmt is None:
                merged = info.merged_formats()
                fmt = max(merged, key=lambda f: (f.height or 0, f.tbr or 0), default=None)
        return fmt.url if fmt else None

    # ------------------------------------------------------- 结果转换
    def _to_video_info(self, raw: dict[str, Any]) -> VideoInfo:
        if raw is None:
            raise ScrapeError("空结果")

        result_type = raw.get("_type", "video")

        # 播放列表
        if result_type in ("playlist", "multi_video", "compat_list"):
            entries = [self._to_video_info(e) for e in (raw.get("entries") or []) if e]
            return VideoInfo(
                id=str(raw.get("id") or ""),
                title=raw.get("title"),
                is_playlist=True,
                playlist_id=raw.get("id"),
                playlist_title=raw.get("title"),
                webpage_url=raw.get("webpage_url"),
                extractor=raw.get("extractor"),
                extractor_key=raw.get("extractor_key"),
                entries=entries,
                raw=self._strip_private(raw),
            )

        # 单视频（含 url / url_transparent 透传后已是 video）
        formats = [FormatInfo.from_raw(f) for f in (raw.get("formats") or []) if isinstance(f, dict)]

        return VideoInfo(
            id=str(raw.get("id") or ""),
            title=raw.get("title"),
            description=raw.get("description"),
            duration=raw.get("duration"),
            uploader=raw.get("uploader") or raw.get("creator"),
            uploader_id=raw.get("uploader_id"),
            channel=raw.get("channel"),
            channel_id=raw.get("channel_id"),
            upload_date=raw.get("upload_date"),
            timestamp=raw.get("timestamp"),
            webpage_url=raw.get("webpage_url"),
            thumbnail=raw.get("thumbnail"),
            thumbnails=list(raw.get("thumbnails") or []),
            view_count=raw.get("view_count"),
            like_count=raw.get("like_count"),
            comment_count=raw.get("comment_count"),
            tags=list(raw.get("tags") or []),
            categories=list(raw.get("categories") or []),
            age_limit=raw.get("age_limit"),
            is_live=bool(raw.get("is_live")),
            live_status=raw.get("live_status"),
            extractor=raw.get("extractor"),
            extractor_key=raw.get("extractor_key"),
            webpage_url_domain=raw.get("webpage_url_domain"),
            subtitles=dict(raw.get("subtitles") or {}),
            automatic_captions=dict(raw.get("automatic_captions") or {}),
            formats=formats,
            direct_url=raw.get("url"),
            direct_ext=raw.get("ext"),
            raw=self._strip_private(raw),
        )

    @staticmethod
    def _classify_error(url: str, detail: str) -> ScrapeError:
        """根据错误文本把失败归类成更精确的异常类型。"""
        low = detail.lower()
        if "no suitable extractor" in low or "unsupported url" in low:
            return UnsupportedURLError("没有提取器能识别该 URL", url)
        if any(k in low for k in (
            "login", "logged-in", "sign in", "cookies", "credential",
            "authentication", "unauthorized", "private video", "members-only",
            "age-restricted", "log in",
        )):
            return CookieError(
                "该站点需要登录凭证。请设置 "
                "ScrapeOptions(cookies_from_browser='chrome') 或 cookiefile=...\n"
                f"原始信息: {detail}",
                url,
            )
        if "impersonate" in low and "no impersonate target" in low:
            return ScrapeError(
                "该站点需要浏览器指纹伪装。请安装 curl-cffi 并设置 impersonate='chrome'\n"
                f"原始信息: {detail}",
                url,
            )
        return ScrapeError(detail, url)

    @staticmethod
    def _wrap_error(url: str, e: Exception) -> ScrapeError:
        return VideoScraper._classify_error(url, str(e))


# =============================================================================
# 站点能力查询
# =============================================================================
def list_supported_sites(*, keyword: str | None = None, limit: int | None = None) -> list[tuple[str, str]]:
    """列出 yt-dlp 支持的所有站点。

    返回 [(IE_NAME, IE_DESC), ...]。keyword 做大小写不敏感的子串过滤。
    IE_NAME 可作为 extract(..., ie_key=...) 的目标，或用于判断 URL 归属。
    """
    global SUPPORTED_SITES_COUNT
    if not YTDLP_AVAILABLE:
        raise ImportError("未安装 yt-dlp：pip install -U yt-dlp")

    from yt_dlp.extractor import gen_extractor_classes

    out: list[tuple[str, str]] = []
    for cls in gen_extractor_classes():
        name = getattr(cls, "IE_NAME", "") or ""
        desc = getattr(cls, "IE_DESC", "") or ""
        if keyword and keyword.lower() not in f"{name} {desc}".lower():
            continue
        out.append((name, desc))
    SUPPORTED_SITES_COUNT = len(out) if not keyword else SUPPORTED_SITES_COUNT
    out.sort(key=lambda x: x[0])
    return out[:limit] if limit else out


def guess_extractor(url: str) -> str | None:
    """判断某个 URL 会由哪个提取器处理（返回 IE_NAME，如 "youtube"）。"""
    if not YTDLP_AVAILABLE:
        raise ImportError("未安装 yt-dlp：pip install -U yt-dlp")
    from yt_dlp.extractor import gen_extractor_classes

    for cls in gen_extractor_classes():
        if cls.IE_NAME == "generic":
            continue
        try:
            if cls.suitable(url):
                return cls.IE_NAME
        except Exception:
            continue
    return "generic"


# =============================================================================
# 极简函数式 API（不想建实例时用）
# =============================================================================
def extract_info(url: str, *, download: bool = False, **opt_kwargs: Any) -> VideoInfo | DownloadResult:
    """一行抓取。

    extract_info("https://...")                → VideoInfo（仅解析）
    extract_info("https://...", download=True) → DownloadResult（下载）
    """
    scraper = VideoScraper(ScrapeOptions(**opt_kwargs))
    if download:
        return scraper.download(url)
    return scraper.extract(url)


def download(url: str, *, output_dir: str | None = None, quality: Quality = "best",
             **opt_kwargs: Any) -> DownloadResult:
    """一行下载。"""
    scraper = VideoScraper(ScrapeOptions(output_dir=output_dir, quality=quality, **opt_kwargs))
    return scraper.download(url)


# =============================================================================
# 使用示例
# =============================================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # ① 支持站点数
    sites = list_supported_sites()
    print(f"yt-dlp 支持的提取器数量: {len(sites)}")
    print("示例:", [n for n, _ in sites if n in ("Youtube", "BiliBili", "Vimeo", "twitter")])

    # ② 判断 URL 归属
    for u in ("https://www.youtube.com/watch?v=YE7VzlLtp-4",
              "https://www.bilibili.com/video/BV1xx411c7mD",
              "https://vimeo.com/76979871"):
        print(f"{guess_extractor(u):>10}  <-  {u}")

    # ③ 只解析（不下载）
    demo_url = "https://www.youtube.com/watch?v=YE7VzlLtp-4"
    try:
        scraper = VideoScraper(ScrapeOptions(quiet=True))
        info = scraper.extract(demo_url)
        print(f"\n标题: {info.title}")
        print(f"时长: {info.duration}s  上传者: {info.uploader}  站点: {info.extractor}")
        print(f"格式数: {len(info.formats)}")
        print("\n可用格式（前 10）:")
        for f in info.formats[:10]:
            size = f"{f.best_filesize / 1024 / 1024:.1f}MB" if f.best_filesize else "?"
            print(f"  {f.format_id:>10}  {str(f.ext):>5}  {str(f.resolution):>10}  "
                  f"v={str(f.vcodec)[:12]:<12} a={str(f.acodec)[:10]:<10} {size}")
    except ScrapeError as e:
        print(f"抓取失败（可能是网络/环境问题）: {e}")

    # ④ 下载（真实使用请取消注释）
    # r = scraper.download(demo_url, options=ScrapeOptions(
    #     output_dir="./downloads", quality="best", max_height=1080,
    #     output_template="%(title)s [%(id)s].%(ext)s",
    # ))
    # print(r.status, r.filepath)

    # ⑤ 直链（给播放器用，时效性）
    # direct = scraper.resolve_direct_url(demo_url, quality="best")
    # print("直链:", (direct or "")[:120])


# =============================================================================
# 附录 A：自持解析的边界（想"把抓取代码抽出来自己维护"时读这里）
# =============================================================================
"""
问题：能不能把 yt-dlp 的解析代码抽出来，放进自己项目，不依赖 yt-dlp？

结论：**不推荐**，原因如下（这是踩过的坑，写在这里省你时间）：

1. 解析代码不是一个模块，而是 941 个文件的集合，且**站点一变就要跟着改**。
   yt-dlp 平均每天都有站点修复提交（Changelog 里大量 `[ie/xxx] Fix ...`）。
   你自己维护 = 自己承担每天跟 1800 个网站的解析失效。这是无底洞。

2. 真正"通用"的抓取代码其实只有三块，可以复用，但价值有限：

   (a) URL 匹配：类属性 `_VALID_URL` 正则 + 命名组 (?P<id>...)
       ── 见 `extractor/common.py:_match_valid_url` / `suitable`
       ── 复用它 = 你得到一张"URL → 站点"的路由表

   (b) 统一结果协议：info_dict 的 `formats` 字段
       ── {format_id, url, ext, vcodec, acodec, width, height, tbr, filesize, ...}
       ── 复用它 = 你的下游（播放器/下载器/UI）只认一套字段

   (c) 取网页与抽字段：`_download_webpage` / `_search_regex` / `_search_json`
       ── 见 `extractor/common.py`

3. 推荐姿势（本模块采用）：
   · 直接 `import yt_dlp`，调用它稳定的公开 API（extract_info / download）
   · 把结果**转成你自己的数据类**（本模块的 VideoInfo/FormatInfo）
   · 你的业务代码只依赖本模块，不直接依赖 yt_dlp
   · 升级 `pip install -U yt-dlp` 即可自动修好失效站点，你的代码零改动

4. 若确实想自持某一站点的解析（例如你只抓 1~2 个自家/合作站点）：
   · 用本模块的 `extract()` 拿到 `FormatInfo.url`，观察它的结构
   · 然后照着 `extractor/<site>.py` 的 `_real_extract` 自己实现
   · 只维护你关心的那几个站点，成本可控 —— 但**别试图覆盖全部**
"""

# =============================================================================
# 附录 B：常见站点接入速查
# =============================================================================
"""
┌─────────────────┬───────────────────────────────────────────┬──────────────────────────┐
│ 站点            │ 典型做法                                  │ 需要留意                 │
├─────────────────┼───────────────────────────────────────────┼──────────────────────────┤
│ YouTube         │ 开箱即用；高质量需 ffmpeg 合并            │ 需要 cookies 才能拿高码率│
│                 │                                           │ 有时要 JS runtime+PO tok │
│ Bilibili        │ 开箱即用；大会员/高码率需 cookie          │ 设 Referer: bilibili.com │
│ Twitter / X     │ 开箱即用                                  │ 部分需登录 cookie        │
│ Vimeo           │ 开箱即用                                  │ 私密视频需 cookie        │
│ TikTok          │ 开箱即用；常触发反爬                      │ 建议 impersonate="chrome"│
│ Instagram       │ 开箱即用；多数需登录                      │ cookies_from_browser     │
│ 优酷/腾讯视频等 │ 部分支持，常需会员 cookie                 │ 见 list_supported_sites  │
│ 直链 mp4 / m3u8 │ GenericIE 兜底；也可自行解析              │ 非 HTML 页面直接给直链   │
└─────────────────┴───────────────────────────────────────────┴──────────────────────────┘

反爬三板斧（按优先级）：
  1. cookies_from_browser="chrome"    —— 解决"需要登录"
  2. impersonate="chrome"             —— 解决"TLS 指纹被识别"（需 curl-cffi）
  3. proxy="http://127.0.0.1:7890"    —— 解决"IP 被限制"

抓取不到时的排查顺序：
  guess_extractor(url)  → 确认有没有提取器认领
  extract(url)          → 看抛的异常（ScrapeError.url / .raw 有原始信息）
  list_supported_sites(keyword="xxx") → 确认站点是否支持
"""
