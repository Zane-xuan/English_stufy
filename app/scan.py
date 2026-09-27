"""扫描 CONTENT_DIR，把每期 HTML 的元数据导入数据库。

可直接作为 CLI 运行：python -m app.scan
"""

from __future__ import annotations

import json
import sys

from . import config, db, models
from .parser import parse_clip


def scan() -> dict:
    """执行一次全量增量扫描，返回统计结果。

    内容目录不存在或一个 HTML 都没有时抛 FileNotFoundError，
    此时不写库、也不标记缺失，避免目录临时未挂载导致整库被标脏。
    """
    if not config.CONTENT_DIR.is_dir():
        raise FileNotFoundError(f"内容目录不存在：{config.CONTENT_DIR}")

    files = sorted(config.CONTENT_DIR.glob("*.html"))
    if not files:
        raise FileNotFoundError(f"内容目录里没有 HTML 文件：{config.CONTENT_DIR}")

    db.init_db()

    result = {
        "scanned": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "missing": 0,
        "errors": [],
    }
    present: list[str] = []

    with db.get_conn() as conn:
        for path in files:
            result["scanned"] += 1
            try:
                stat = path.stat()
                meta = parse_clip(path)
                outcome = models.upsert_clip(conn, meta, stat.st_mtime, stat.st_size)
            except Exception as exc:  # 单个文件失败不影响整次扫描
                result["errors"].append({"file": path.name, "reason": str(exc)})
                continue

            present.append(meta.slug)
            if outcome == "inserted":
                result["inserted"] += 1
            elif outcome == "updated":
                result["updated"] += 1
            else:
                result["skipped"] += 1

        result["missing"] = models.mark_missing(conn, present)

    return result


def main() -> int:
    try:
        result = scan()
    except FileNotFoundError as exc:
        print(f"扫描中止：{exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
