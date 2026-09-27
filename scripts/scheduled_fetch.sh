#!/usr/bin/env bash
# 每周一、周四（北京时间 06:00）唤起本机 CodeBuddy agent 生成新一期学习资源，
# 生成后统一走 app.scan 入库。
#
# 由 root 的 crontab 调用，字段为：0 22 * * 0,3
# （服务器时区 UTC，22:00 UTC 周日/周三 = 北京时间周一/周四 06:00）
#
# 也可手动试跑：sudo /opt/English_study/scripts/scheduled_fetch.sh
# 可用环境变量覆盖：ES_MODEL（模型）、ES_AGENT_TIMEOUT（agent 超时秒数）
set -uo pipefail

PROJECT_DIR=/opt/English_study
PROMPT_FILE="$PROJECT_DIR/scripts/scheduled_fetch.prompt.md"
LOG_FILE=/var/log/english-fetch.log
MODEL="${ES_MODEL:-deepseek-v4.1-flash}"
AGENT_TIMEOUT="${ES_AGENT_TIMEOUT:-1800}"

log() { printf '%s %s\n' "$(date -Is)" "$*" >>"$LOG_FILE"; }

cd "$PROJECT_DIR" || { log "进入 $PROJECT_DIR 失败"; exit 1; }
touch "$LOG_FILE"
log "===== 新一期生成开始（model=$MODEL, tz=Asia/Shanghai）====="

# 必须清空环境再调 codebuddy：如果从一个带 CODEBUDDY_*/CLAUDE_* 变量的会话里
# 嵌套调用，子进程会继承这些变量并卡住不返回。
# PATH 把项目 venv 放最前，让 agent 里的 `python` 就是带 beautifulsoup4 的那一个。
env -i \
  HOME=/root \
  TZ=Asia/Shanghai \
  LANG=C.UTF-8 \
  LC_ALL=C.UTF-8 \
  TERM=dumb \
  PATH="$PROJECT_DIR/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  timeout "$AGENT_TIMEOUT" codebuddy \
    -p "$(cat "$PROMPT_FILE")" \
    --output-format text \
    --model "$MODEL" \
    --permission-mode bypassPermissions \
    --add-dir "$PROJECT_DIR" \
    < /dev/null >>"$LOG_FILE" 2>&1
agent_rc=$?
log "agent 结束 rc=$agent_rc"

# agent 只写内容，入库与属主在这里收口，保证与站点服务用户一致
chown -R www-data:www-data "$PROJECT_DIR/content" 2>>"$LOG_FILE"
runuser -u www-data -- "$PROJECT_DIR/.venv/bin/python" -m app.scan >>"$LOG_FILE" 2>&1
scan_rc=$?
log "扫描结束 rc=$scan_rc"
log "===== 完成 ====="

if [[ $agent_rc -ne 0 || $scan_rc -ne 0 ]]; then
  exit 1
fi
exit 0
