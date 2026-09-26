"""手动执行流水线的一段，用于补录与排障。

流水线分两段，中间由 agent 完成判定：

    python scripts/run_once.py --stage prepare --date 2026-09-26
    # 把 data/pending/2026-09-26.request.json 交给 agent，
    # 让它把结果写到同目录的 .response.json
    python scripts/run_once.py --stage finalize --date 2026-09-26

不带 --stage 时只看当前进度，不做任何写操作。
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.db import init_db
from app.errors import EnglishStudyError
from app.pipeline import finalize, pending_status, prepare, today

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s  %(message)s"

STAGES = ("prepare", "finalize")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_once.py",
        description="手动执行每日英语内容流水线",
    )
    parser.add_argument(
        "--stage",
        choices=STAGES,
        help="要执行的阶段，省略时只显示当前进度",
    )
    parser.add_argument("--date", help="指定日期，格式 YYYY-MM-DD，省略则为当天")
    parser.add_argument(
        "--force", action="store_true", help="该日期已有记录时覆盖重跑"
    )
    parser.add_argument(
        "--platform",
        help="prepare 阶段只从指定平台采集，如 bilibili、youtube、podcast",
    )
    parser.add_argument("--verbose", action="store_true", help="输出调试级别日志")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format=LOG_FORMAT,
    )

    target = args.date or today()
    if args.date:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            print(f"日期格式应为 YYYY-MM-DD，收到 {args.date!r}", file=sys.stderr)
            return 2

    settings = get_settings()
    init_db()

    if args.stage is None:
        print(pending_status(settings, target))
        return 0

    try:
        if args.stage == "prepare":
            message = prepare(
                settings,
                target,
                force=args.force,
                only_platform=args.platform,
            )
        else:
            message = finalize(settings, target, force=args.force)
    except EnglishStudyError as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1

    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
