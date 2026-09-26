"""项目自定义异常。禁止裸 except，所有异常都从这里派生。"""

from __future__ import annotations


class EnglishStudyError(Exception):
    """所有项目异常的基类。"""


class ConfigError(EnglishStudyError):
    """配置缺失或格式非法。"""


class CollectError(EnglishStudyError):
    """候选视频采集失败。"""


class SubtitleError(EnglishStudyError):
    """字幕获取与语音转写失败。"""


class HandoffError(EnglishStudyError):
    """与 agent 交接文件时出错：文件缺失、格式非法、字段不符。"""


class AnalyzeError(EnglishStudyError):
    """agent 返回的判定结果不合法。"""


class StoreError(EnglishStudyError):
    """落库失败。"""


class PipelineError(EnglishStudyError):
    """整条流水线失败，当天无法产出内容。"""
