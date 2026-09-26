#!/usr/bin/env bash
# VPS 上每天跑一次的完整链路：prepare -> agent 判定 -> finalize
#
# 用 systemd timer 或 crontab 调用。不要依赖应用内的 APScheduler，
# 因为 agent 这一步在应用进程之外，进程内调度只能跑 prepare。
#
# 用法：
#   bash deploy/daily-run.sh              # 跑今天
#   bash deploy/daily-run.sh 2026-09-20   # 补跑指定日期
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/English_study}"
PYTHON="${PYTHON:-$PROJECT_DIR/.venv/bin/python}"
AGENT_CMD="${AGENT_CMD:-hermes -z}"
TARGET_DATE="${1:-$(date +%F)}"

cd "$PROJECT_DIR"

echo "[1/3] prepare $TARGET_DATE"
"$PYTHON" scripts/run_once.py --stage prepare --date "$TARGET_DATE"

echo "[2/3] 交给 agent 判定"
PROMPT="读取 $PROJECT_DIR/data/pending/$TARGET_DATE.request.json，按其中 instructions 与 output 的说明完成判定，把结果 JSON 写入 output.response_path 指定的文件。只写文件，不要输出其他内容。"
# shellcheck disable=SC2086
$AGENT_CMD "$PROMPT"

echo "[3/3] finalize $TARGET_DATE"
"$PYTHON" scripts/run_once.py --stage finalize --date "$TARGET_DATE"

echo "完成：$TARGET_DATE"
