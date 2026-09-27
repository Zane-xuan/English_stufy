"""集中读取配置。业务代码不直接读环境变量。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _resolve(value: str) -> Path:
    """相对路径按项目根目录展开。"""
    path = Path(value)
    return path if path.is_absolute() else (BASE_DIR / path)


HOST: str = os.getenv("HOST", "127.0.0.1")
PORT: int = int(os.getenv("PORT", "8000"))
DB_PATH: Path = _resolve(os.getenv("DB_PATH", "data/clips.db"))
CONTENT_DIR: Path = _resolve(os.getenv("CONTENT_DIR", "content"))
ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "")
SITE_PASSWORD: str = os.getenv("SITE_PASSWORD", "")
NOTES_PASSWORD: str = os.getenv("NOTES_PASSWORD", "")

# 仅预览用：置 1 允许用 ?today=YYYY-MM-DD 覆盖「今天」，便于查看某一天的页面。
# 预览模式下不写库。平时保持关闭
ALLOW_TODAY_OVERRIDE: bool = os.getenv("ALLOW_TODAY_OVERRIDE", "").strip() == "1"

TEMPLATES_DIR: Path = BASE_DIR / "templates"
STATIC_DIR: Path = BASE_DIR / "static"
