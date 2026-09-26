# English_study

每天一段 3 到 4 分钟的英语视频，配好生词、短语与全文翻译，打开网页就能学。

视频来源是公开平台上的短片——演讲、电影独白、影视对话、访谈、新闻片段都可能出现。
内容挑好之后，程序把里面的生词与地道表达单独列出来，配中文释义，再把整段英语译成中文。
页面上视频在上、文本在下，点一下就能在英文与中文之间切换；点词条时，原文中对应的位置会高亮。

## 它是怎么工作的

这个项目**不调用任何大模型接口**，也不引入大模型 SDK。需要判断的环节（挑哪条视频、
哪些词值得学、怎么翻译）交给 agent 完成，中间靠两个 JSON 文件交接：

```text
prepare  ──►  data/pending/<日期>.request.json  ──►  agent  ──►  <日期>.response.json  ──►  finalize
  采集候选视频、取字幕            候选 + 字幕 + 要求              评分/选题/词条/译文          校验并落库
```

流水线拆成 `prepare` 与 `finalize` 两段，全部状态都写在交接文件里，
因此两段可以跨进程、跨天执行，中途失败也不用重头再来。

- **本机开发**：由 WorkBuddy（或任意 CLI agent）读取请求文件并写回结果
- **服务器运行**：由 `deploy/daily-run.sh` 串联三步，其中 agent 环节用 hermes CLI

## 技术栈

| 层次 | 选型 |
|---|---|
| 后端 | Python 3.12 + FastAPI + Uvicorn |
| 模板与前端 | Jinja2 + 原生 HTML / CSS / JS，无前端框架 |
| 存储 | SQLite（标准库 `sqlite3`，无 ORM） |
| 定时 | APScheduler（应用内，只跑 `prepare`） |
| 采集 | yt-dlp + 平台 RSS |
| 字幕与转写 | 平台字幕优先，缺失时用 faster-whisper 兜底（依赖系统 ffmpeg） |
| 部署 | Nginx + systemd |

版本固定在 `requirements.txt`，代码风格规则固定在 `ruff.toml`。

## 快速开始

前置条件：Python 3.12 及以上，以及系统级的 `ffmpeg`。

```powershell
conda activate english_study
cd E:\project\vps\English_study
pip install -r requirements.txt
Copy-Item .env.example .env

# 首次运行前建表
python -c "from app.db import init_db; init_db()"

# 启动服务
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000>。首次会显示「今日内容尚未生成」，因为还没跑流水线。

跑一次完整链路：

```powershell
python scripts/run_once.py --stage prepare    # 采集候选、取字幕、写交接请求
# 把 data/pending/<今天>.request.json 交给 agent，结果写到同目录的 .response.json
python scripts/run_once.py --stage finalize   # 校验结果并落库
```

`python scripts/run_once.py` 不带参数时只查状态，会提示当前该跑哪一段。

## 目录结构

```text
English_study/
├── app/
│   ├── config.py            # 配置中心，读取 .env
│   ├── db.py                # 全部 SQLite 访问集中在此
│   ├── models.py            # 领域对象与常量
│   ├── main.py              # FastAPI 路由
│   ├── scheduler.py         # 应用内定时任务
│   ├── pipeline/
│   │   ├── handoff.py       # 与 agent 的交接契约（核心）
│   │   ├── collect.py       # 候选视频采集
│   │   ├── subtitle.py      # 字幕获取与段落切分
│   │   ├── analyze.py       # 校验 agent 返回的结果
│   │   └── store.py         # 结果落库
│   ├── providers/           # 平台适配器：bilibili / youtube / podcast
│   ├── templates/           # Jinja2 模板
│   └── static/              # 样式与脚本
├── scripts/run_once.py      # 手动补录与查状态
├── deploy/                  # systemd 单元、Nginx 示例、每日串联脚本
├── tests/                   # 测试用例
└── data/                    # 数据库与交接文件（不进版本库）
```

## 文档

| 文档 | 内容 |
|---|---|
| [TECH_STACK.md](TECH_STACK.md) | 技术选型，含落选方案与原因 |
| [DEV_DOC.md](DEV_DOC.md) | 功能清单、数据模型、接口、实现要点 |
| [USAGE_DOC.md](USAGE_DOC.md) | 安装、使用与常见问题 |
| [DEPLOY.md](DEPLOY.md) | 上线步骤与故障排查 |
| [TEST_CASES.md](TEST_CASES.md) | 测试用例 |
| [AGENTS.md](AGENTS.md) | 给 AI 编码工具的硬约束 |

## 配置

所有配置集中在 `.env`，变量含义见文件内注释。启动前从模板复制一份：

```bash
cp .env.example .env      # Windows: Copy-Item .env.example .env
```

`.env` 只放在本机与服务器上，**不提交**。模板 `.env.example` 里不放任何真实值。

主要内容包括：平台尝试顺序、搜索关键词、候选时长区间（默认 120-300 秒）、
每天生成时刻、评分阈值、词条条数区间、转写模型与设备。

## 开发约定

- 判定环节一律交给 agent，**不要引入任何大模型 API 调用**
- 开发在 Windows 上做，文档里的命令按 Windows 写；服务器差异单独注明
- `data/`、`.env`、缓存目录都已加入 `.gitignore`，不要提交

```powershell
ruff check .                 # 代码风格
pytest                       # 测试
```

## 许可

个人自用项目，未附许可协议。
