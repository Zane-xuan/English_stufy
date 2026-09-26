# English_study 使用文档

> 版本 v0.2 ｜ 更新 2026-09-26  
> 配套文档：[技术选型](TECH_STACK.md) ｜ [开发文档](DEV_DOC.md) ｜ [部署说明](DEPLOY.md)

## 1. 这是什么

每天早上，它会自动从公开视频平台挑一段有激励作用的英语视频，比如一段演讲，或者影视里的精彩独白。挑好之后，它把视频里的生词、短语、地道口语表达单独列出来，配好中文释义，再把整段英语翻译成中文。

打开网页就能看：上面是视频，下面是文本。想对照理解就点一下切换按钮，正文会在英文和中文之间来回换。看完视频，顺手把下面的词汇清单过一遍。点任意一个词条，原文里对应的位置会高亮。

每天的内容都不一样，往期的也能翻回去看。

## 2. 它是怎么跑起来的

它不调用任何大模型接口。需要判断的地方（挑哪条视频、哪些词值得学、怎么翻译）交给 agent，中间靠两个 JSON 文件交接：

1. **prepare**：采集候选视频、取好字幕，写成 `data/pending/<日期>.request.json`
2. **agent**：读取该文件，按里面的说明处理，把结果写到同目录的 `<日期>.response.json`
3. **finalize**：读回结果，校验没问题就落库，网页上就能看到。在 VPS 上用 `deploy/daily-run.sh` 把这三步串起来

## 3. 安装

**前置条件**：Python 3.12 及以上，`ffmpeg`。本机开发在 Windows 上用 conda，正式运行放在远程 Linux VPS 上。

### 本机开发环境

```powershell
# 安装 ffmpeg
winget install Gyan.FFmpeg

# 激活 conda 环境
conda activate english_study

# 进入项目目录
cd E:\project\vps\English_study

# 安装 Python 依赖
pip install -r requirements.txt

# 复制配置模板
Copy-Item .env.example .env
```

### 服务器运行环境

```bash
# 安装 ffmpeg
sudo apt update && sudo apt install -y ffmpeg

# 进入项目目录
cd /opt/English_study

# 创建并激活虚拟环境
python3 -m venv .venv && source .venv/bin/activate

# 安装 Python 依赖
pip install -r requirements.txt

# 复制配置模板
cp .env.example .env
```

两处都装好后，打开各自的 `.env` 按需调整，变量含义见文件内注释。这两个文件相互独立，都不提交。

## 4. 快速上手

```powershell
# 首次运行前建表
python -c "from app.db import init_db; init_db()"

# 启动服务
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`，此时会显示「今日内容尚未生成」，这是正常的，因为还没有跑流水线。

手动跑一次完整链路：

```powershell
# 第一段：采集候选、取字幕、写交接请求
python scripts/run_once.py --stage prepare

# 把 data/pending/<今天>.request.json 交给 agent 处理，
# 让它把结果写到同目录的 .response.json

# 第二段：读回结果并落库
python scripts/run_once.py --stage finalize
```

预期输出：

```text
已准备 3 条候选，请求文件：E:\project\vps\English_study\data\pending\2026-09-26.request.json
把该文件交给 agent 处理，结果写到 ...\2026-09-26.response.json，然后执行 finalize 阶段
已生成 2026-09-26：某大学 2026 届毕业演讲
```

刷新页面就能看到当天内容。

## 5. 常用操作

### 看某天卡在哪一步

不确定该跑哪一段时，先看状态。

```bash
python scripts/run_once.py --date 2026-09-26
```

| 输出                                | 含义           |
| --------------------------------- | ------------ |
| `还没开始，请先执行 prepare 阶段`            | 当天还没采集       |
| `已备好候选，等待 agent 处理`               | 该让 agent 干活了 |
| `已收到 agent 结果，可以执行 finalize 阶段落库` | 结果文件已就位      |
| `已有内容，需要重跑请加 --force`             | 当天已完成        |

### 补录某一天

自动任务失败，或者漏了几天想补上时用。

```bash
python scripts/run_once.py --stage prepare --date 2026-09-20
# agent 处理
python scripts/run_once.py --stage finalize --date 2026-09-20
```

| 参数           | 说明                                  | 是否必填 |
| ------------ | ----------------------------------- | ---- |
| `--stage`    | `prepare` 或 `finalize`，省略则只看状态      | 否    |
| `--date`     | 指定日期，格式 `YYYY-MM-DD`，省略则为当天         | 否    |
| `--force`    | 该日期已有记录时覆盖重跑                        | 否    |
| `--platform` | 只从指定平台采集，如 `youtube`，仅 prepare 阶段有效 | 否    |
| `--verbose`  | 输出调试级别日志                            | 否    |

### 通过接口触发

服务已启动时，也可以直接调接口。

```bash
curl -X POST http://127.0.0.1:8000/api/admin/run -H "Content-Type: application/json" -d '{"stage":"prepare","date":"2026-09-26"}'
curl -X POST http://127.0.0.1:8000/api/admin/run -H "Content-Type: application/json" -d '{"stage":"finalize","date":"2026-09-26"}'
curl "http://127.0.0.1:8000/api/admin/status?date=2026-09-26"
curl http://127.0.0.1:8000/api/day/2026-09-26
```

### 备份数据与查看日志

所有内容都在一个 SQLite 文件里，复制即可备份；运行日志用 `journalctl` 看。

```bash
mkdir -p ~/backup && cp data/english_study.db ~/backup/english_study-$(date +%F).db
journalctl -u english-study -n 100 --no-pager
```

### 配置开机自启

```bash
sudo cp deploy/english-study.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now english-study
```

## 6. 常见问题

**Q：页面显示「今日内容尚未生成」**  
A：先跑 `python scripts/run_once.py` 看状态，按提示补跑缺的那一段。页面上的失败原因取自 `fetch_log`，能看出是哪个平台出的问题。

**Q：finalize 报「结果校验失败」**  
A：agent 写的结果文件不符合要求，报错会说清是哪一项：评分低于阈值、译文段落数不对、词条在原文里找不到。改完结果文件重跑 finalize 就行，不用重新采集。

**Q：报错 `ffmpeg not found`**  
A：服务器没装 ffmpeg，或者它不在 `PATH` 里。执行 `sudo apt install -y ffmpeg`，装完用 `ffmpeg -version` 确认。

**Q：词汇提取结果太少**  
A：在 `.env` 里调 `VOCAB_MIN_COUNT` 与 `VOCAB_MAX_COUNT` 控制条数。低于下限会被判为不合格而拒绝落库。

**Q：某段视频没有字幕，转写又很慢**  
A：转写速度取决于服务器有没有 GPU。没有 GPU 时把 `WHISPER_MODEL` 换成更小的规格，或调小 `PREPARE_MAX_CANDIDATES` 少准备几条候选。

**Q：页面上的视频打不开**  
A：部分平台禁止跨站嵌入。调整 `.env` 里 `PREFER_PLATFORMS` 的顺序，把允许嵌入的平台提前；或者点来源链接去原站看。

**Q：改了每天的生成时间但没生效**  
A：定时任务在服务启动时注册，改完 `.env` 里的 `DAILY_RUN_TIME` 需要重启服务。

## 7. 卸载与清理

```bash
# 停掉并移除服务与定时器
sudo systemctl disable --now english-study english-study-daily.timer
sudo rm /etc/systemd/system/english-study.service /etc/systemd/system/english-study-daily.*
sudo systemctl daemon-reload

# 删除程序目录（含数据库与交接文件，先备份再删）
rm -rf /opt/English_study
```

数据库在 `data/english_study.db`，交接文件在 `data/pending/`，删掉程序目录会一并丢失。
