# English_study 开发文档

> 版本 v0.2 ｜ 更新 2026-09-26
> 配套文档：[技术选型](TECH_STACK.md) ｜ [使用文档](USAGE_DOC.md) ｜ [测试用例](TEST_CASES.md) ｜ [部署说明](DEPLOY.md) ｜ [AI 约定](AGENTS.md)

## 1. 项目概述

**一句话**：每天自动挑一段有激励作用的英语视频，把里面的生词、短语与口语表达挑出来配好翻译，生成全文对照译文，供跟读与精听。

**目标用户**：单人自用，想每天花十几分钟做英语口语输入的学习者。

**核心场景**：

1. 早上打开站点，看当天的视频，用原文／译文按钮对照理解。
2. 看完视频后，过一遍当天的词汇清单，把不认识的词记下来。
3. 出差几天没看，回来翻历史列表补上落下的内容。

**不做什么**：

- 不做用户注册、登录、多用户数据隔离
- 不做生词本、复习提醒、打卡统计，也不做发音评测与跟读打分
- 不下载或转存视频文件，只保存文本与来源信息
- 不调用任何云端大模型接口，判定环节全部交给 agent

## 2. 功能清单

### FR-01 每日定时 prepare

- **做什么**：每天在固定时刻自动跑 prepare 阶段，把当天的候选与字幕准备好。
- **输入**：系统时间触发。
- **输出**：`data/pending/<日期>.request.json`，等待 agent 处理。
- **验收标准**：给定服务已启动且定时任务已注册，当到达配置的执行时刻，则 30 分钟内生成当天的请求文件。
- **优先级**：必须
- **状态**：已完成

### FR-02 多平台候选视频采集与降级

- **做什么**：按配置的平台顺序依次采集候选视频，前一个平台失败或候选不足时自动切到下一个。
- **输入**：`PREFER_PLATFORMS`、`SEARCH_QUERIES`、每平台候选数量上限。
- **输出**：写入 `candidate` 表的候选列表。
- **验收标准**：给定平台顺序为 `bilibili,youtube,podcast` 且 Bilibili 采集抛异常，当执行采集，则继续尝试 YouTube，并在 `fetch_log` 中记录 Bilibili 的失败原因。
- **优先级**：必须
- **状态**：已完成

### FR-03 候选准备与字幕获取

- **做什么**：按顺序取未使用过的候选，取到字幕，凑够 `PREPARE_MAX_CANDIDATES` 条交给 agent。
- **输入**：`candidate` 表中的未使用候选。
- **输出**：若干条「候选 + 字幕段落」。
- **验收标准**：给定候选池中前 3 条带平台字幕、第 4 条无字幕，当执行准备，则取前 3 条且不触发语音转写；若一条带字幕的都没有，则对第一条执行语音转写。
- **优先级**：必须
- **状态**：已完成

### FR-04 语音转写兜底

- **做什么**：视频没有现成字幕时，下载音频并用本地模型转写，转写完成后删除音频文件。
- **输入**：候选视频地址。
- **输出**：英文字幕段落。
- **验收标准**：给定某视频平台无字幕且音频可下载，当执行获取，则返回非空英文字幕，且临时音频文件在处理结束后已被删除。
- **优先级**：必须
- **状态**：已完成

### FR-05 与 agent 的交接文件

- **做什么**：把候选、字幕与输出要求写成请求文件；finalize 时读回结果文件。
- **输入**：候选与字幕。
- **输出**：`<日期>.request.json` 与 `<日期>.response.json`。
- **验收标准**：给定 prepare 已执行，当打开请求文件，则其中含 `instructions`、`output.response_path`、`output.schema`、`requirements` 与 `candidates`，且 `output.response_path` 指向本机可写路径。
- **优先级**：必须
- **状态**：已完成

### FR-06 激励性判定与选题

- **做什么**：由 agent 给每条候选打 0 到 10 分并选出当日素材；流水线校验选中候选的评分是否达到阈值。
- **输入**：请求文件中的候选列表。
- **输出**：`candidate_scores` 与 `selected_index`。
- **验收标准**：给定结果文件中 `selected_index` 指向的候选评分为 6.5、阈值为 7.0，当执行 finalize，则拒绝落库并记 `fetch_log`。
- **优先级**：必须
- **状态**：已完成

### FR-07 生词、短语与口语表达提取

- **做什么**：由 agent 提取三类词条，流水线校验条数与词条能否在原文定位。
- **输入**：选中候选的字幕段落。
- **输出**：`vocabulary` 表中 `kind` 为 `word`、`phrase`、`colloquial` 的条目。
- **验收标准**：给定 agent 返回 50 条词条、上限为 40，当执行 finalize，则只保留前 40 条；给定某条词条在原文中定位不到，则该条被丢弃。
- **优先级**：必须
- **状态**：已完成

### FR-08 全文翻译

- **做什么**：由 agent 逐段翻译成中文，流水线校验译文段落数与原文一致。
- **输入**：选中候选的字幕段落。
- **输出**：与英文段落一一对应的中文译文。
- **验收标准**：给定英文字幕有 N 个段落，当执行 finalize，则中文译文段落数等于 N；若不等则拒绝落库。
- **优先级**：必须
- **状态**：已完成

### FR-09 内容落库

- **做什么**：校验通过后把当天内容与词汇一次性写入数据库，并把候选标记为已使用、回填评分。
- **输入**：校验通过的判定结果。
- **输出**：`daily_content` 一条，`vocabulary` 若干条。
- **验收标准**：给定同一天重复执行 finalize，当第二次执行，则 `daily_content` 中当天仍只有一条记录。
- **优先级**：必须
- **状态**：已完成

### FR-10 每日学习页面展示

- **做什么**：展示当天视频、来源信息、可切换的原文／译文正文、词汇清单。
- **输入**：浏览器访问。
- **输出**：HTML 页面。
- **验收标准**：给定当天内容已生成，当打开首页，则页面显示视频、来源与日期；点击切换按钮，正文在英文与中文之间切换，按钮文案同步变化。
- **优先级**：必须
- **状态**：已完成

### FR-11 历史内容浏览

- **做什么**：按日期倒序列出历史内容，点进去看某一天。
- **输入**：浏览器访问历史页。
- **输出**：历史列表与单日页面。
- **验收标准**：给定数据库中有 10 天记录，当打开历史页，则按日期倒序显示 10 条；点击任意一条，则进入该日页面且内容与该日记录一致。
- **优先级**：应该
- **状态**：已完成

## 3. 界面说明

### 界面清单

| 编号 | 界面名 | 用途 |
|---|---|---|
| UI-01 | 每日学习页 | 看当天视频、对照原文译文、过词汇 |
| UI-02 | 历史列表页 | 按日期找往期内容 |

### UI-01 每日学习页

**关键元素**：

- 视频播放区：视频用平台官方 iframe 嵌入，播客用 `<audio>` 播放器
- 来源信息区：标题、演讲者或作品名、平台、日期、时长、激励性评分
- 切换按钮：在「显示原文」「显示译文」之间切换，默认显示原文
- 正文区：按段落排列
- 词汇清单：分「生词」「短语」「口语表达」三组
- 日期导航：前一天、后一天、回历史列表

**交互流程**：

1. 打开页面，请求当天数据，显示原文。
2. 点击切换按钮，正文整体替换为译文，按钮文案变为「显示原文」。
3. 点击词汇条目，正文中该词的所有出现位置加高亮底色；点其他词条则换高亮，点自己则取消。
4. 点击日期导航，跳转到对应日期的页面。

**异常状态**：

- 当天未生成：显示「今日内容尚未生成」，给出补录命令与前一天入口
- 生成失败：额外显示最近一次失败原因，取自 `fetch_log`
- 词汇为空：词汇区显示「今日无提取结果」，正文正常显示

### UI-02 历史列表页

日期倒序列表，每条显示日期、标题、平台与来源。点击任意条目进入对应日期的每日学习页。无任何记录时显示「还没有历史内容」。

## 4. 技术选型

> 完整方案对比与落选原因见 [技术选型文档](TECH_STACK.md)。

| 维度 | 选型 | 版本 | 说明 |
|---|---|---|---|
| 语言／运行时 | Python | 3.12 | 本机用 conda 环境 `english_study` |
| Web 框架 | FastAPI + Uvicorn | 0.141.1 / 0.54.0 | 服务端渲染，不做前后端分离 |
| 模板／前端 | Jinja2 + 原生 HTML/CSS/JS | 3.1.6 | 切换与高亮写在原生 JS 里 |
| 视频采集 | yt-dlp | 2026.8.19 | 同时用于取元数据与字幕 |
| 音视频处理 | ffmpeg | 系统级 | 供抽取音频使用 |
| 语音转写 | faster-whisper | 1.2.1 | 仅在没有现成字幕时调用 |
| 判定环节 | agent + 文件交接 | 无依赖 | 不引入大模型 SDK |
| 数据存储 | SQLite | 3 | Python 标准库 `sqlite3` |
| 定时调度 | APScheduler | 3.11.3 | 只跑 prepare 阶段 |
| 部署 | Nginx + systemd | 系统自带 | Nginx 反代页面与接口 |

**选定方案**：方案 A ｜ **决策日期**：2026-09-26

## 5. 目录结构

```text
English_study/
├── app/
│   ├── main.py               FastAPI 入口与页面路由
│   ├── config.py             读取 .env 配置
│   ├── db.py                 SQLite 连接、建表与数据访问
│   ├── models.py             数据表结构与领域对象
│   ├── errors.py             自定义异常
│   ├── scheduler.py          APScheduler 任务注册
│   ├── pipeline/
│   │   ├── __init__.py       prepare / finalize 两段编排
│   │   ├── collect.py        多平台候选采集与降级
│   │   ├── subtitle.py       字幕获取、解析与语音转写兜底
│   │   ├── handoff.py        与 agent 的交接文件读写
│   │   ├── analyze.py        校验 agent 返回的判定结果
│   │   └── store.py          落库
│   ├── providers/
│   │   ├── base.py           平台适配器接口与 yt-dlp 通用实现
│   │   ├── bilibili.py
│   │   ├── youtube.py
│   │   └── podcast.py
│   ├── templates/            base.html / day.html / history.html
│   └── static/               style.css / app.js
├── data/
│   ├── english_study.db      SQLite 数据库，已忽略
│   └── pending/              agent 交接文件，已忽略
├── deploy/
│   ├── english-study.service systemd 单元文件
│   ├── nginx.conf.example    Nginx 站点配置示例
│   └── daily-run.sh          prepare → agent → finalize 串联脚本
├── scripts/
│   └── run_once.py           手动执行流水线的某一段
├── tests/
│   └── test_pipeline.py
├── .env.example
├── .gitignore
├── requirements.txt
└── ruff.toml
```

## 6. 数据模型

### daily_content

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INTEGER | 主键自增 | |
| content_date | TEXT | 非空，唯一 | 格式 `YYYY-MM-DD` |
| title | TEXT | 非空 | 视频标题 |
| source_platform | TEXT | 非空 | `bilibili` / `youtube` / `podcast` / `official` |
| source_url | TEXT | 非空 | 原始地址；播客指向音频文件 |
| video_embed_url | TEXT | | 嵌入地址，播客为音频地址 |
| source_author | TEXT | | 演讲者、说话人或节目主播 |
| source_work | TEXT | | 影视作品名或节目名 |
| source_kind | TEXT | 非空 | `speech` / `dialogue` / `monologue` / `podcast` |
| duration_seconds | INTEGER | | 视频时长 |
| transcript_en | TEXT | 非空 | 英文字幕全文，段落用空行分隔 |
| transcript_zh | TEXT | 非空 | 中文译文，段落数与英文一致 |
| motivation_score | REAL | | 激励性评分，取值 0 到 10 |
| status | TEXT | 非空，默认 `published` | `published` / `failed` |
| created_at | TEXT | 非空 | ISO 8601 时间戳 |

### vocabulary

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INTEGER | 主键自增 | |
| content_id | INTEGER | 非空，外键 | 指向 `daily_content.id` |
| kind | TEXT | 非空 | `word` / `phrase` / `colloquial` |
| term | TEXT | 非空 | 词条原形 |
| phonetic | TEXT | | 音标 |
| meaning_zh | TEXT | 非空 | 中文释义 |
| usage_note | TEXT | | 语境与用法说明 |
| example_sentence | TEXT | | 原文中的例句 |

### candidate

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INTEGER | 主键自增 | |
| platform | TEXT | 非空 | 来源平台 |
| external_id | TEXT | 非空 | 平台内视频 ID，用于去重 |
| url | TEXT | 非空 | 视频地址 |
| title | TEXT | | |
| author | TEXT | | |
| work | TEXT | | |
| kind | TEXT | | |
| duration_seconds | INTEGER | | |
| motivation_score | REAL | | 由 agent 判定后回填 |
| used | INTEGER | 非空，默认 0 | 0 未使用，1 已使用 |
| discovered_at | TEXT | 非空 | 首次采集时间 |

唯一约束：`(platform, external_id)`

### fetch_log

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INTEGER | 主键自增 | |
| run_date | TEXT | 非空 | 运行日期 `YYYY-MM-DD` |
| platform | TEXT | | 失败或执行的平台 |
| stage | TEXT | 非空 | `collect` / `subtitle` / `agent` / `store` |
| result | TEXT | 非空 | `success` / `failed` |
| message | TEXT | | 失败原因 |
| created_at | TEXT | 非空 | ISO 8601 时间戳 |

## 7. 接口契约

### 页面路由

| 方法 | 路径 | 用途 | 说明 |
|---|---|---|---|
| `GET` | `/` | 渲染当天学习页 | 无记录时仍返回 200，页面渲染空状态 |
| `GET` | `/day/{content_date}` | 渲染指定日期的学习页 | 同上 |
| `GET` | `/history` | 渲染历史列表页 | 无记录时显示空态 |

### `GET /api/day/{content_date}`

- **用途**：供前端脚本取当天数据
- **请求**：`content_date` 路径参数，格式 `YYYY-MM-DD`
- **响应**：`{ date, title, source, motivation_score, status, transcript_en, transcript_zh, vocabulary }`
- **错误码**：`404` — 该日期无记录

### `GET /api/days`

- **用途**：历史列表数据
- **请求**：`limit` 查询参数，默认 30，取值 1 到 200；`offset` 查询参数，默认 0
- **响应**：`{ total: number, items: array }`
- **错误码**：`422` — 分页参数非整数或超出范围

### `POST /api/admin/run`

- **用途**：手动触发流水线的某一段，用于补录与排障
- **请求**：`{ date?: string, force?: boolean, stage?: "prepare" | "finalize" }`，`stage` 默认 `prepare`
- **响应**：`{ status, content_date, stage, message }`
- **错误码**：`409` — 该日期已有记录且未传 `force`；`422` — `stage` 取值非法；`500` — 该阶段执行失败

### `GET /api/admin/status`

- **用途**：看某天卡在 prepare 还是 finalize
- **请求**：`date` 查询参数，省略则为当天。**响应**：`{ content_date: string, status: string }`
- **错误码**：无

### `GET /api/health`

- **用途**：健康检查，部署后用 curl 打这个接口验证
- **请求**：无
- **响应**：`{ status, version, scheduler_running, platforms, pending_dir }`
- **错误码**：无

## 8. 关键实现要点

**交接文件**

- 请求文件里的 `output.response_path` 是绝对路径，agent 照它写就行，不用自己拼
- 结果校验不过时不落库，但请求文件保留，改完结果文件重跑 finalize 即可，不用重新采集
- `requirements` 里重复了阈值与条数区间，agent 不必去读代码

**边界条件**

- 候选池按 `(platform, external_id)` 去重，`used = 1` 的视频永不再选
- 视频时长低于 60 秒或高于 20 分钟的候选直接过滤；时长未知的候选不拦
- 准备候选时先只挑有平台字幕的，避免为每条候选都跑一次昂贵的转写
- 字幕按空行分段，正文与译文的段落对应关系依赖 `subtitle.group_into_paragraphs`
- 全部候选都取不到字幕时不写 `daily_content`，只记 `fetch_log`
- 同一天重复 finalize 时，先删当天旧的 `vocabulary` 再写入，避免重复累积

**安全要求**

- 视频以平台官方 iframe 嵌入，不下载、不转存、不二次分发视频文件
- 站点若暴露在公网，在 Nginx 层加 Basic Auth；应用本身不做登录
- `.env` 与 `data/` 都在 `.gitignore` 里；交接文件含正文，不要提交

**性能与兼容性**

- 每日一次串行执行，不做并发；语音转写只在没有现成字幕时触发，且一次只转一条
- 页面接口只读 SQLite 单表，不做额外缓存
- 服务器需能访问目标平台，YouTube 依赖 `HTTPS_PROXY` 配置
- `ffmpeg` 必须是系统级安装，不从 Python 包引入；前端只用原生 API，需支持主流现代浏览器最近两个大版本

## 9. 开发环境与运行

开发在本机 Windows 上用 conda 环境 `english_study`，测试通过后部署到远程 Linux VPS 的 venv。

```powershell
# 本机开发（Windows PowerShell）
conda activate english_study
cd E:\project\vps\English_study
pip install -r requirements.txt
python -c "from app.db import init_db; init_db()"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
# 服务器运行（Linux）
cd /opt/English_study
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -c "from app.db import init_db; init_db()"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**环境要求**：Python 3.12 及以上，系统级 `ffmpeg`，能访问目标视频平台

**配置**：需要配置的变量见 `.env.example`。本机与服务器的 `.env` 各自独立，都不提交

**测试与部署**：测试用例见 [测试用例](TEST_CASES.md)，上线步骤见 [部署说明](DEPLOY.md)

## 10. 待确认事项

- [ ] 定时任务的具体执行时刻，暂定每天 07:00；激励性评分阈值暂定 7 分；每次交给 agent 的候选暂定 3 条
- [ ] VPS 是否具备访问 YouTube 的网络条件，是否需要配置 `HTTPS_PROXY`
- [ ] VPS 是否有可用 GPU，决定 faster-whisper 用哪个模型规格
