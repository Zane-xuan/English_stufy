# English_study 部署说明

> 版本 v0.2 ｜ 更新 2026-09-26
> 配套：[开发文档](DEV_DOC.md) ｜ [使用文档](USAGE_DOC.md)

## 部署目标

| 项 | 内容 |
|---|---|
| 环境 | 自有 VPS，服务商待定 |
| 系统 | 待定，以下命令按 Debian / Ubuntu 编写 |
| 域名 | 待定，未配域名时直接用服务器 IP 访问 |
| 端口 | 应用监听 `127.0.0.1:8000`，对外由 Nginx 暴露 80 |

## 环境划分

开发在本机 Windows 上做，测试通过后部署到远程 Linux VPS。两边只有四处差异。

| 项 | 本机开发 | VPS 运行 |
|---|---|---|
| 系统 | Windows | Linux |
| 项目路径 | `E:/project/vps/English_study` | `/opt/English_study` |
| 环境管理 | conda 环境 `english_study` | venv（`.venv`） |
| 激活命令 | `conda activate english_study` | `source .venv/bin/activate` |
| 数据库 | `data/english_study.db` | `/opt/English_study/data/english_study.db` |
| 视频平台可达性 | 取决于本机网络 | 需确认能否直连 YouTube |

## 本机开发环境准备

```powershell
# 安装 ffmpeg
winget install Gyan.FFmpeg

# 激活 conda 环境（未创建时先执行 conda create -n english_study python=3.12 -y）
conda activate english_study

# 进入项目目录
cd E:\project\vps\English_study

# 安装依赖
pip install -r requirements.txt

# 复制配置
Copy-Item .env.example .env
```

若 `winget` 不可用，从 ffmpeg 官网下载压缩包，把其中的 `bin` 目录加进系统 `PATH`。

## VPS 前置准备

```bash
# 安装系统依赖
sudo apt update && sudo apt install -y ffmpeg python3-venv python3-pip git nginx apache2-utils

# 确认 ffmpeg 可用
ffmpeg -version

# 创建项目目录
sudo mkdir -p /opt/English_study && sudo chown -R "$USER":"$USER" /opt/English_study
```

**需要配置的环境变量**

| 变量名 | 用途 | 取值 |
|---|---|---|
| `HTTPS_PROXY` | 访问 YouTube 的代理 | 见 `.env`，无代理留空 |
| `PREFER_PLATFORMS` | 平台尝试顺序 | 无代理时改为 `bilibili,podcast` |
| `PODCAST_FEEDS` | 播客 RSS 源 | 不采集播客时留空 |
| `PREPARE_MAX_CANDIDATES` | 每次交给 agent 的候选条数 | 默认 3，机器弱时调到 1 |
| `WHISPER_MODEL` | 转写模型规格 | 无 GPU 时用 `small` 或更小 |
| `DB_PATH` | 数据库文件路径 | `/opt/English_study/data/english_study.db` |
| `PENDING_DIR` | 与 agent 的交接目录 | `/opt/English_study/data/pending` |
| `DAILY_RUN_TIME` | 每日执行时刻 | 见 `.env` |

密钥一律不写入本文件，只写变量名与用途。完整清单见 `.env.example`。

## 部署步骤

```bash
# 1. 本机提交并推送
git add -A && git commit -m "deploy" && git push

# 2. VPS 首次克隆
cd /opt && sudo git clone <仓库地址> English_study

# 2b. 之后每次更新用这条
cd /opt/English_study && git pull

# 3. 创建虚拟环境并安装依赖
cd /opt/English_study
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. 写入配置
cp .env.example .env && nano .env

# 5. 建表
python -c "from app.db import init_db; init_db()"

# 6. 先手动跑通一次 prepare，确认能取到候选与字幕
python scripts/run_once.py --stage prepare

# 7. 交给 systemd 托管
sudo cp deploy/english-study.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now english-study
```

第 6 步必须先成功，再进第 7 步。自动任务出错时排查会麻烦得多。

## 与 agent 的串联

应用内的 APScheduler 只跑 prepare 阶段。agent 判定在应用进程之外，所以每日完整链路由 `deploy/daily-run.sh` 串联：`prepare` → agent → `finalize`。

```bash
# 手动跑一次
bash deploy/daily-run.sh

# 补跑指定日期
bash deploy/daily-run.sh 2026-09-20
```

agent 命令由 `AGENT_CMD` 控制，默认 `hermes -z`。

用 systemd timer 每天触发，比在应用内调度更可靠，因为整条链路一起跑：

```bash
sudo tee /etc/systemd/system/english-study-daily.service > /dev/null <<'EOF'
[Unit]
Description=English_study 每日内容生成
After=network-online.target

[Service]
Type=oneshot
User=www-data
WorkingDirectory=/opt/English_study
EnvironmentFile=/opt/English_study/.env
Environment=AGENT_CMD=/usr/local/bin/hermes -z
ExecStart=/bin/bash /opt/English_study/deploy/daily-run.sh
EOF

sudo tee /etc/systemd/system/english-study-daily.timer > /dev/null <<'EOF'
[Unit]
Description=每天生成英语学习内容

[Timer]
OnCalendar=*-*-* 07:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now english-study-daily.timer
systemctl list-timers english-study-daily.timer
```

`Persistent=true` 表示机器关机错过了时间点，开机后会补跑一次。

`AGENT_CMD` 要用绝对路径。systemd 的 `PATH` 很窄，用户级安装的 CLI 通常找不到。

## 进程守护

`deploy/english-study.service`

```ini
[Unit]
Description=English_study 每日英语口语学习站
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/English_study
EnvironmentFile=/opt/English_study/.env
ExecStart=/opt/English_study/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

用 `User=www-data` 时，要先把项目目录与 `data/` 的属主改过去：

```bash
sudo chown -R www-data:www-data /opt/English_study
```

定时任务由 APScheduler 在进程内注册，不需要额外配 cron。服务重启后任务会重新注册。

## 反向代理

`deploy/nginx.conf.example`，部署时复制到 `/etc/nginx/sites-available/english-study`

```nginx
server {
    listen 80;
    server_name <域名或服务器IP>;

    location /static/ {
        alias /opt/English_study/app/static/;
        expires 7d;
    }

    location / {
        auth_basic "English Study";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
# 生成访问口令
sudo htpasswd -c /etc/nginx/.htpasswd <用户名>

# 启用站点并重载
sudo ln -sf /etc/nginx/sites-available/english-study /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

应用本身不做登录，访问控制全部靠这一层 Basic Auth。若只在自有内网访问，可以去掉 `auth_basic` 两行。

## 验证部署

```bash
# 服务状态
systemctl status english-study --no-pager

# 应用直接连通
curl -s http://127.0.0.1:8000/api/days

# 经 Nginx 访问
curl -s -u <用户名>:<口令> http://127.0.0.1/history -o /dev/null -w "%{http_code}\n"

# 最近日志
journalctl -u english-study -n 50 --no-pager
```

预期输出：服务状态为 `active (running)`，接口返回含 `total` 字段的 JSON，Nginx 返回 `200`。

## 回滚

```bash
cd /opt/English_study
git log --oneline -5
git checkout <上一个可用提交>
sudo systemctl restart english-study
```

数据库结构变更前先备份，回滚代码不会回滚数据：

```bash
cp /opt/English_study/data/english_study.db /opt/English_study/data/english_study.db.bak
```

## 常见故障

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 服务起不来，状态显示 `203/EXEC` | `ExecStart` 路径不对，或虚拟环境没建 | 确认 `/opt/English_study/.venv/bin/uvicorn` 存在 |
| 页面 502 | 应用没在 8000 端口监听 | 先看 `systemctl status english-study`，再看 `journalctl -u english-study -n 50` |
| 定时任务跑了但页面仍无内容 | 只跑了 prepare，agent 与 finalize 没执行 | 确认 timer 调的是 `deploy/daily-run.sh`；手动跑一次看卡在哪一步 |
| 某天内容缺失 | 机器在触发时刻处于关机状态 | `Persistent=true` 会在开机后补跑；仍缺失则 `bash deploy/daily-run.sh <日期>` |
| agent 说找不到请求文件 | 运行 agent 的用户读不到交接目录，或 `PENDING_DIR` 与实际不一致 | 检查目录属主，确认 `.env` 里的 `PENDING_DIR` |
| finalize 报结果校验失败 | agent 输出不符合 schema | 按报错信息改结果文件后重跑 finalize，不用重新采集 |
| YouTube 采集全部失败 | VPS 无法直连，`HTTPS_PROXY` 没配或代理没起来 | 检查代理进程；短期可把 `PREFER_PLATFORMS` 改成 `bilibili,podcast` |
| 转写极慢 | 用 CPU 转写长视频 | 调小 `WHISPER_MODEL`、`PREPARE_MAX_CANDIDATES` 或收紧 `MAX_DURATION_SECONDS` |
| 写库报 `readonly` | `data/` 属主不是服务运行用户 | `sudo chown -R www-data:www-data /opt/English_study/data` |
