# English Study 开发文档

> 版本 v0.1 ｜ 更新 2026-09-27
> 配套文档：[技术选型](TECH_STACK.md) ｜ [使用文档](USAGE_DOC.md) ｜ [AI 约定](AGENTS.md)

## 1. 项目概述

**一句话**：一个自用的英语口语学习站，逐期展示「每日英语影视片段」学习页，并提供一个历史回顾入口，列出全部往期。

**目标用户**：你自己。日常在电脑或手机上复习往期影视片段、跟读、查词。

**核心场景**：
1. 新生成一期学习 HTML，放进 `content/` 目录，执行扫描后入库。
2. 打开主页面，主内容区直接就是今天该主攻的那份资源。
3. 点右上角「历史回顾」，右侧滑出抽屉列出全部往期；选某一天，主内容区就地换成那一天。
4. 在抽屉里按关键词或类型筛出往期。

**不做什么**：
- 不做注册、登录、多用户隔离。
- 不做在线编辑台词与词汇，内容由外部生成的 HTML 决定。
- 不做口语录音、语音识别与发音评分。
- 不把台词与词汇全文存进数据库，正文只以 HTML 文件为准。

## 2. 功能清单

### FR-01 内容扫描与入库

- **做什么**：扫描 `CONTENT_DIR` 下的 `*.html`，解析出元数据写入 SQLite。
- **输入**：`CONTENT_DIR` 目录（默认 `content/`）与其中的 HTML 文件。
- **输出**：`clips` 表的插入与更新，以及一份扫描结果统计。
- **验收标准**：给定 `content/` 下有 3 个符合命名规范的 HTML，当执行 `python -m app.scan`，则 `clips` 表新增 3 条记录，且每条都有 `publish_date`、`focus_start`、`focus_end`、`title`、`file_name`。
- **优先级**：必须
- **状态**：待开发

### FR-02 历史回顾抽屉开合

- **做什么**：主页面右上角提供「历史回顾」按钮，点击后右侧滑出抽屉，再点一次或按 Esc 收起。
- **输入**：鼠标点击、触摸点击或键盘 Esc。
- **输出**：抽屉展开或收起，主内容区随之让出或收回宽度。
- **验收标准**：给定打开 `/`，当不点「历史回顾」，则抽屉收起、只显示当天学习内容；当点击该按钮，则抽屉从右侧滑出并展示往期列表。
- **优先级**：必须
- **状态**：待开发

### FR-03 抽屉内的往期列表

- **做什么**：按发布日倒序列出全部资源，每项展示发布日、期数、标题、影片副标题与服务区间，当前选中项与今天正在服务的那份分别高亮。
- **输入**：无，或来自 URL 的筛选参数。
- **输出**：抽屉内的资源列表。
- **验收标准**：给定数据库中有 12 条 `is_missing = 0` 的记录，当展开抽屉，则按 `publish_date` 从新到旧显示 12 项，每项都带服务区间，且当前显示的那一项带选中样式。
- **优先级**：必须
- **状态**：待开发

### FR-04 往期搜索与类型筛选

- **做什么**：在抽屉里按关键词搜索标题与副标题，按类型筛选。
- **输入**：关键词文本、类型下拉框。
- **输出**：过滤后的往期列表，主内容区保持不变。
- **验收标准**：给定库中有 3 条类型为「影视独白」的记录，当在抽屉里选择该类型并提交，则列表只剩这 3 条。
- **优先级**：应该
- **状态**：待开发

### FR-05 主内容区切换学习内容

- **做什么**：在抽屉里选某一天，主内容区就地换成那一天的学习内容，保留原页面的完整版式与交互。
- **输入**：URL 的 `d` 参数，或抽屉里的一次点击。
- **输出**：主内容区渲染该期内容。
- **验收标准**：给定库中存在 slug 为 `2026-09-27_Good-Will-Hunting` 的记录，当访问 `/?d=2026-09-27_Good-Will-Hunting`，则主内容区直接呈现该期原文，语言切换与词汇点击高亮均可用，且页面里不出现 `iframe`。
- **优先级**：必须
- **状态**：待开发

### FR-06 默认显示今天该主攻的资源

- **做什么**：不带 `d` 参数打开主页面时，按服务区间选出今天该主攻的那一份资源；今天不落在任何区间内则退回最新一份。
- **输入**：服务器当天日期。
- **输出**：主页面，顶栏标注今天是这份资源的第几天。
- **验收标准**：给定库中有两份资源，A 服务 2026-09-28 至 09-30、B 服务 2026-10-01 至 10-03，当今天是 2026-09-29 打开 `/`，则主内容区显示 A 且顶栏显示「资源第 2/3 天」；当今天是 2026-10-04 打开 `/`，则显示 B 且顶栏提示今天不在这份资源的服务区间内。
- **优先级**：必须
- **状态**：待开发

### FR-07 扫描触发接口

- **做什么**：提供一个带令牌保护的接口，供服务器端定时任务或手工触发重新扫描。
- **输入**：`POST /api/scan`，请求头带 `X-Admin-Token`。
- **输出**：扫描结果统计 JSON。
- **验收标准**：给定 `ADMIN_TOKEN` 已配置，当带正确令牌调用 `POST /api/scan`，则返回 200 与统计结果；当不带令牌或令牌错误，则返回 401。
- **优先级**：必须
- **状态**：待开发

## 3. 界面说明

### 界面清单

| 编号 | 界面名 | 用途 |
|---|---|---|
| UI-01 | 主内容区 | 展示当天学习内容，随抽屉选择切换 |
| UI-02 | 历史回顾抽屉 | 列出全部往期，支持搜索与类型筛选 |

两处共用同一套视觉变量，取色与字体沿用学习页模板（见 `content/` 下的任一 HTML）：底色 `#f7f6f3`，卡片 `#ffffff`，主色 `#1c6b4a`，正文色 `#16181d`，衬线字体用于英文台词，无衬线字体用于界面文案。

### UI-01 主内容区

**关键元素**：
- 顶部栏：站点名、今天是一份资源的第几天、发布日与期数、「历史回顾」按钮。
- 内容区：某份资源的原始学习页面，样式已限定在 `#clip-root` 之内。

**交互流程**：
1. 用户打开 `/`。
2. 系统取今天落在服务区间内的那一份资源；一份都不落在区间内则退回发布日最新的一份。
3. 把该份 HTML 的样式加上 `#clip-root` 前缀，取出 `<body>` 内容与脚本，一起渲染进主内容区。
4. 用户在页面内使用语言切换与词汇点击高亮。

**异常状态**：
- 库为空：显示「还没有学习记录，把生成的 HTML 放进 content/ 目录后执行扫描」。
- `d` 指向的 slug 不存在：主内容区显示「没有找到这一期」。
- 记录存在但磁盘文件缺失：显示「这一期的 HTML 文件已不在磁盘上」，并把该记录标记为 `is_missing`。

### UI-02 历史回顾抽屉

**关键元素**：
- 顶部：「历史回顾」标题与关闭按钮。
- 搜索框、类型下拉框、筛选与重置按钮。
- 日期列表，每项显示发布日、期数、标题、副标题与服务区间；当前项高亮，今天正在服务的那份带「服务中」标记。
- 列表底部显示资源总数。

**交互流程**：
1. 用户点顶部「历史回顾」，抽屉从右侧滑出，主内容区让出宽度。
2. 系统按 `publish_date` 倒序查询并渲染列表。
3. 用户点某一份，页面带 `d` 参数重新渲染，主内容区换成那一份，抽屉保持展开。
4. 用户输入关键词或选择类型并提交，页面带 `q` 与 `category` 参数重新渲染列表，主内容区不变。
5. 用户点关闭按钮、按 Esc，或点遮罩收起抽屉。

**异常状态**：
- 无任何记录：显示「还没有往期记录」。
- 筛选无结果：显示「没有匹配的期数」，保留筛选条件便于改条件。

## 4. 技术选型

> 完整方案对比与落选原因见 [技术选型文档](TECH_STACK.md)。本节只列结论。

| 维度 | 选型 | 版本 | 说明 |
|---|---|---|---|
| 语言 / 运行时 | Python | 3.13 | 本机已装 |
| 服务端框架 | FastAPI + Uvicorn | 版本待定 | 自带 `/docs` |
| 界面 / 交互 | Jinja2 模板 + 原生 HTML/CSS/JS | 版本待定 | 不引入前端框架 |
| 数据存储 | SQLite（`sqlite3` 标准库） | 随 Python | 单文件 `data/clips.db` |
| HTML 解析 | BeautifulSoup4 | 版本待定 | 取元数据，并把原始页面拆成可内嵌的片段 |
| 内嵌渲染 | 自研 `app/render.py` | 不适用 | 给原始页面的 CSS 加 `#clip-root` 前缀，隔离样式 |
| 部署 / 分发 | Uvicorn + systemd + Nginx | 版本待定 | 见使用文档 |

**选定方案**：方案 A ｜ **决策日期**：2026-09-27

## 5. 目录结构

```text
English_study/
├── app/
│   ├── __init__.py
│   ├── config.py          # 读取 .env，集中配置
│   ├── db.py              # 连接与建表
│   ├── models.py          # clips 与 supplements 表的读写
│   ├── parser.py          # HTML 元数据解析
│   ├── plan.py            # 从 LEARNING_PLAN.md 取今天该做哪一步
│   ├── render.py          # 把原始页面拆成可内嵌的片段
│   ├── scan.py            # 扫描导入，可作 CLI 运行
│   └── main.py            # FastAPI 应用与路由
├── templates/
│   ├── base.html          # 外壳：顶栏 + 今天任务抽屉 + 主内容区 + 历史抽屉
│   └── index.html         # 主内容区
├── static/
│   ├── style.css
│   └── app.js             # 左右抽屉开合与补充保存
├── content/               # 每期学习 HTML 原样放入
├── data/                  # clips.db
├── scripts/
│   ├── check_content.py   # 每期 HTML 的交付前自检
│   ├── scheduled_fetch.sh # 定时唤起 agent 生成新一期并入库
│   └── scheduled_fetch.prompt.md
├── tests/
│   ├── test_models.py
│   ├── test_parser.py
│   ├── test_plan.py
│   └── test_render.py
├── .env.example
├── .gitignore
├── requirements.txt
├── TECH_STACK.md
├── DEV_DOC.md
├── USAGE_DOC.md
├── LEARNING_PLAN.md       # 学习目标与更新节奏，功能取舍以它为准
└── AGENTS.md
```

## 6. 数据模型

只存元数据，台词与词汇正文不落库。

| 表 / 集合 | 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|---|
| clips | id | INTEGER | 主键，自增 | |
| clips | slug | TEXT | 非空，唯一 | 取自 HTML 文件名（不含扩展名） |
| clips | file_name | TEXT | 非空 | HTML 文件名，用于拼接 `/content/` 地址 |
| clips | file_mtime | REAL | 非空 | 文件最后修改时间戳，用于判断是否需重新解析 |
| clips | file_size | INTEGER | 非空 | 文件字节数，与 `file_mtime` 共同判断变更 |
| clips | publish_date | TEXT | | 发布日 `YYYY-MM-DD`，取自文件名前缀。周一或周四发布 |
| clips | focus_start | TEXT | | 服务区间起，默认等于发布日 |
| clips | focus_end | TEXT | | 服务区间止，默认发布日 +2 天，即一份资源服务 3 天 |
| clips | period | INTEGER | | 期数，取自页面 kicker 文本；全库期号按 `publish_date` 升序连续 |
| clips | title | TEXT | | 中文标题 |
| clips | subtitle | TEXT | | 英文副标题，通常是影片名与片段名 |
| clips | category | TEXT | | 类型，如「影视独白」 |
| clips | duration | TEXT | | 时长，如「≈ 3 分钟」 |
| clips | difficulty | TEXT | | 难度，如「中高级」 |
| clips | accent | TEXT | | 口音，如「美音（波士顿）」 |
| clips | links_json | TEXT | | 观看链接的 JSON 数组，元素含 site、title 与 url |
| clips | is_missing | INTEGER | 非空，默认 0 | 磁盘文件是否已缺失，1 表示缺失 |
| clips | parse_ok | INTEGER | 非空，默认 0 | 元数据是否解析完整，1 表示完整 |
| clips | parse_note | TEXT | | 解析缺失项或失败原因的说明 |
| clips | created_at | TEXT | 非空 | 首次入库时间，ISO 8601 |
| clips | updated_at | TEXT | 非空 | 最近一次解析或状态变更时间，ISO 8601 |

索引：`slug` 唯一索引；`publish_date` 普通索引，用于倒序列表；`(focus_start, focus_end)` 复合索引，用于按今天选期。

### supplements

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| slug | TEXT | 主键 | 对应 `clips.slug`，一期只保留一条补充 |
| body | TEXT | 非空，默认 `''` | 补充正文；写入空白即删除该条 |
| updated_at | TEXT | 非空 | 最近一次写入时间，ISO 8601 |

补充是「只存元数据」的一个例外：它是用户手写、需要长期保存的内容。它按资源挂载（一期一条，可覆盖），写入走 `POST /api/supplements`，读取在渲染主页面时一并带出。新表用 `CREATE TABLE IF NOT EXISTS` 建，老库在下次 `init_db()` 时自动补上，不需要写迁移。

**旧库升级**：`db.init_db()` 在建表建索引之前先跑 `_migrate()`。它会核对 `PRAGMA table_info`，把旧的 `learn_date` 列改名为 `publish_date`，补齐缺的列，删掉旧索引，再给没有服务区间的记录按发布日补算。迁移只补不改已有数据。

## 7. 接口契约

### 页面路由

| 路径 | 说明 |
|---|---|
| `GET /` | 主页面。左侧抽屉是「今天任务」（今天该主攻的那份，周日改为列出近 7 天资源供复盘），主内容区显示该期资源，右侧抽屉列出全部往期并可在底部写「补充」。`d` 选份，`q` 与 `category` 筛选抽屉里的列表。不带 `d` 时主内容区显示今天该主攻的那份资源 |
| `GET /clip/{slug}` | 旧地址，`307` 转到 `/?d={slug}` |
| `GET /content/{file_name}` | 原样返回某期 HTML，用于页面上的「打开原始页面」 |

### `GET /api/clips`

- **用途**：返回往期元数据列表，按 `publish_date` 倒序。默认只返回 `is_missing = 0` 的记录。
- **请求**：`{ q?: string, category?: string, limit?: int, offset?: int, include_missing?: bool }`，均为查询参数。
- **响应**：`{ total: int, limit: int, offset: int, items: [{ slug: string, publish_date: string, focus_start: string, focus_end: string, period: int, title: string, subtitle: string, category: string, duration: string, difficulty: string, accent: string, file_name: string, links: [{ site: string, title: string, url: string }], parse_ok: bool, parse_note: string, is_missing: bool }] }`
- **错误码**：`422` 参数类型或取值范围非法。

### `POST /api/scan`

- **用途**：触发一次全量增量扫描，把新增或变更的 HTML 解析入库，并把磁盘上已消失的文件标记为缺失。
- **请求**：无请求体。请求头必须带 `X-Admin-Token`。
- **响应**：`{ scanned: int, inserted: int, updated: int, skipped: int, missing: int, errors: [{ file: string, reason: string }] }`
- **错误码**：`401` 令牌缺失或不匹配；`409` 已有扫描在进行中；`500` 内容目录不存在或不可读。

### `POST /api/supplements`

- **用途**：写入或覆盖某一期的「补充」文字。内容为空白表示删除该条补充。
- **请求**：JSON 体 `{ slug: string, text: string }`。请求头必须带 `X-Notes-Password`，值等于 `.env` 里的 `NOTES_PASSWORD`。
- **响应**：`{ slug: string, text: string }`，清空时 `text` 为空串。
- **错误码**：`401` 口令缺失或不匹配（`NOTES_PASSWORD` 未配置时也一律返回 401）；`400` 缺少 slug；`404` 该 slug 不存在；`413` 超过 10000 字符；`422` 请求体格式非法。

### `GET /healthz`

- **用途**：健康检查，供 systemd 探活或反向代理使用。
- **请求**：无。
- **响应**：`{ status: "ok", clips: int }`
- **错误码**：`500` 数据库不可读。

## 8. 关键实现要点

**每期 HTML 的结构约定**：站点靠固定的类名定位内容，新生成的一期必须带这些元素。`.kicker` 里写期数与类型，`h1` 与 `h1 .sub` 是标题与英文副标题，`.meta .chip` 依次写日期、类型、时长、难度、口音，可选再加一个 `服务 · 2026-09-28 ~ 2026-09-30` 显式声明服务区间，`.watch a` 里用 `.site` 与 `.ttl` 标来源与标题，`.script[data-lang]` 配一个 `#langBtn` 做整段中英切换，`.turn` 是台词段且 `.en-text` 与 `.zh-text` 成对出现，`.vrow[data-keys]` 是词汇行，`.tgt[data-key]` 是原文里的可点击锚点，`.pron` 放发音与连读提示。词汇 key 必须与原文锚点双向一致，交付前跑 `python scripts/check_content.py`。

**解析器容错**：按参考页面的类名定位字段，`.kicker` 取期数与类型，`h1` 取标题，`h1 .sub` 取副标题，`.meta .chip` 取日期、类型、时长、难度、口音，`.watch a` 取观看链接。任一字段缺失不得中断整次扫描，把该条写成 `parse_ok = 0` 并在 `parse_note` 里记明缺哪项，标题回退为文件名。页面照常可列出。

**增量策略**：`file_mtime` 与 `file_size` 都未变则跳过，不重新解析。任一变化则重新解析并更新，同时刷新 `updated_at`。扫描整体放在一个事务里，避免中途失败留下半份数据。

**文件缺失**：磁盘文件消失时只把 `is_missing` 置 1，不删记录。历史列表默认过滤掉这些记录，数据仍可追溯。

**目录为空保护**：`CONTENT_DIR` 不存在或读不到任何文件时，直接报错退出，不做任何写入，也不标记缺失。避免目录临时未挂载导致整库被标记。

**路径安全**：`/content/{file_name}` 必须校验 `file_name` 只含字母、数字、下划线、连字符与点，且拼接后的绝对路径落在 `CONTENT_DIR` 之内。拒绝任何含 `..` 或绝对路径的取值，防止目录穿越。

**样式隔离**：原始页面自带 `<style>`，直接内嵌会与外壳互相污染。`app/render.py` 把它的每条规则的选择器都加上 `#clip-root` 前缀：`:root`、`html`、`body` 整体替换成 `#clip-root`，`*` 展开成 `#clip-root, #clip-root *`，`@media` 与 `@supports` 递归进去继续加前缀，`@keyframes`、`@font-face` 原样保留。外壳样式选择器都不带 id，特异性天然低于加了 id 的原始样式，所以原始页面永远赢。

**脚本注入**：原始页面的脚本靠全局 id 找元素（`document.getElementById('script')`、`getElementById('langBtn')`）。内嵌到主文档后这些 id 依然唯一，脚本不用改写就能跑。外壳不得使用 `script`、`langBtn` 这类 id。每次切换日期都是整页重新渲染，脚本不会重复绑定。

**抽屉状态**：抽屉开合状态存在 `sessionStorage` 的 `drawer` 键里，并在 `<head>` 里用一段同步脚本在首次绘制前恢复，避免展开动画闪一下。点日期项时先写 `open` 再让浏览器跳转，所以换一天之后抽屉仍是展开的。

**左右抽屉**：`.app` 是 flex 行，从左到右依次是 `.taskbar`（今天任务，自左侧滑出）、`.pane`（主内容）、`aside.sidebar`（历史回顾，自右侧滑出）。两个抽屉共用同一套开合机制：靠 `html` 上的一个类控制（`taskbar-open` 与 `drawer-open`），桌面上动画 `flex-basis` 把中间列挤开，窄屏（≤820px）改成 `position:fixed` 浮层加遮罩，`Escape` 与点遮罩都能收起。开合状态分别存在 `sessionStorage` 的 `taskbar` 与 `drawer` 键，并在首次绘制前恢复。今天任务取自 `models.get_current(today)`，与正在浏览的 `?d=` 相互独立。

**补充的写入鉴权**：站点公开，写补充必须带 `X-Notes-Password` 请求头并等于 `NOTES_PASSWORD`。口令在浏览器里输入一次后存 `localStorage`，之后随请求头发送。`NOTES_PASSWORD` 未配置时 `_notes_authorized()` 直接返回假，一切写入 401，前端按钮也禁用，保证默认关闭。用自定义请求头而不是 Cookie 或表单字段，是因为跨站请求无法伪造非安全列表内的请求头，而应用没有注册 CORS 中间件，所以天然免疫 CSRF；同时也没有可被利用的凭据型 Cookie。口令对比用 `secrets.compare_digest`，比较前两侧都 `.encode("utf-8")`，避免非 ASCII 口令触发 `TypeError`。

**补充的转义**：补充文字由用户输入，模板里一律交给 Jinja 自动转义，不使用 `|safe`，避免存储型 XSS。

**日期来源**：`publish_date` 一律取自文件名前缀，不使用服务器当前时间，避免时区与补录导致日期错位。只有「今天是哪天」用到服务器当天日期。

**扫描并发**：SQLite 同一时刻只允许一个写入者。用进程内锁保证同一进程内不并发扫描，第二个请求返回 409。

**今天该做哪一步**：学习计划把每份资源拆成「初识 → 拆解跟读 → 输出」三天，周日综合复盘。`app/plan.py` 读取 `LEARNING_PLAN.md` 第 3 节，按资源服务第几天取对应小节（第 1 天初识、第 2 天拆解跟读、第 3 天及以后输出，不在任何区间取复盘），只取标题与编号步骤，展示在「今天任务」抽屉里。计划正文只保留在文档一处，站点不复制内容，改文档即改站点；`LEARNING_PLAN.md` 不存在或格式对不上时静默不显示，不影响页面。解析结果按（路径, mtime, 大小）缓存。

**周日复盘入口**：今天不在任何资源的服务区间内时（按服务区间规则就是周日），「今天任务」不再只指向最新一份，而是列出**近 7 天发布过**的资源（`models.list_clips_between`，按发布日正序，跳过文件缺失的），正好对应本周的两份，配合「综合复盘日」的计划一起用。近 7 天一份都没有时才退回「复习最近一期」按钮。

**静态资源缓存**：页面里引用的 `style.css` 与 `app.js` 都带 `?v=<static 目录最新修改时间>`，静态文件一改地址就变，浏览器与 CDN 不会继续用旧缓存；HTML 响应另带 `Cache-Control: no-cache`，保证外壳标记始终最新。改了静态文件只需重启服务，不需要手动清缓存。

**预览某一天（可选开关）**：`.env` 里 `ALLOW_TODAY_OVERRIDE=1` 时，主页面接受 `?today=YYYY-MM-DD` 覆盖「今天」，用来查看某一天的页面（例如周日的复盘视图）。该日期会写进 `preview_today` cookie，预览期间点选资源不会跳出这一天；`?today=off` 退出。此模式下**跳过一切写库动作**（不标记文件缺失），保证只读。开关默认关闭，关闭时参数与 cookie 一律忽略。

**编码**：读写 HTML 一律显式指定 `encoding="utf-8"`，不依赖系统默认编码，避免 Windows 上按 GBK 解析出错。

**配置读取**：`.env` 由 `app/config.py` 统一加载，业务代码不直接读环境变量。所有配置项都有默认值，缺 `.env` 时也能以默认值启动。

## 9. 每期内容的生成约定

目标与学习节奏以 [学习计划](LEARNING_PLAN.md) 为准，本节只讲怎么把一份资源做成一个页面。

每周一与周四各生成一期，命名 `content/YYYY-MM-DD_<Title>.html`，放进 `content/` 后由扫描收录。

**执行方式**：生产端保持 agent 驱动，不写死抓取脚本。选素材、取逐字稿、写页面、跑自检这几步都由 agent 按本节约定完成，再把结果写入 `content/`。定时触发由系统 cron 承担：服务器上每周一、周四北京时间 06:00 运行 `scripts/scheduled_fetch.sh`，脚本以非交互方式唤起本机的 CodeBuddy agent 执行本节任务，生成后再统一走扫描入库。agent 的具体实现可替换（本机用 CodeBuddy），只要遵守本节约定与下面的边界即可。

**agent 与站点的边界**：agent 只负责往 `content/` 写文件，不直接改数据库。入库统一走 `python -m app.scan` 或 `POST /api/scan`，保证解析、增量判断与标记缺失的逻辑只有一处。这样换 agent、换服务器都不影响站点。

**素材来源**（按学习计划的四类排序，同一类内轮换作品与来源，避免连续同一部片、同一类型）：

1. 电影或剧集经典独白、对峙戏，最推荐。
2. 访谈里嘉宾的个人故事。
3. TED 或演讲的 3 分钟精华段。
4. 播客里主持人与嘉宾的自然对话。

**选片标准**：时长 2 至 5 分钟；有较清晰的文字稿或字幕；口语表达丰富，含 3 个以上地道表达；情绪或观点鲜明，方便模仿语气；有公开可看的链接。

**台词来源**：必须从转录站或官方发布稿取逐字稿，例如 clip.cafe、youtubetotranscript、IMSDb 剧本库、机构官网。不凭记忆写台词。观看链接必须能实际打开，不编造视频 ID。

**每期的固定结构**：

1. 观看链接，两到三个来源，标注各自特点。
2. 场景背景，讲清人物处境与这段戏在片中的位置。
3. 原文台词，可整段切换中英。
4. 三分类词汇表：地道表达与俚语、常用短语与搭配、进阶与不常见单词；另附文化与典故注释。
5. 发音与连读提示。

**不要写「口语练习路线」这类练习步骤清单**，用户明确要求删除，只保留发音与连读提示。

**台词呈现方式**：不做逐句中英对照。英文按角色分段整段呈现，说话人标签内联在段首，同一角色连续的台词合在一段里。一个语言切换按钮控制整段在中英之间切换，默认英文。

**词汇与原文的联动**：词汇行写 `class="vrow" data-keys="k1,k2"`，原文目标写 `class="tgt" data-key="k1"`。点词汇行高亮原文并滚动定位，再点一次取消；点原文里的高亮词反向定位到词汇行。在中文状态下点词汇行时先自动切回英文，因为高亮只在英文下可见。

**词汇 key 的硬约束**：每个 key 都必须出现在台词里，与原文锚点双向一一对应。**原文锚点不能嵌套**，像 `be trapped by dogma` 与单独的 `dogma` 会重叠，要拆成相邻但不重叠的两段。交付前跑 `python scripts/check_content.py`。

**服务区间**：一份资源服务 3 天，发布日当天算第 1 天，所以周一发布的资源服务到周三，周四发布的服务到周六，周日两边都不覆盖，正好留给综合复盘。区间默认按发布日推导，页面也可以在 `.meta` 里写一个 `服务 · 起 ~ 止` 的 chip 显式覆盖，补录或临时调整时用得上。chip 格式读不出来时不静默忽略，会记进 `parse_note`，同时退回按发布日推导。

**期号**：按 `publish_date` 升序连续编号，与日期顺序一致。补录早期日期时要顺延重排已有期号。

## 10. 开发环境与运行

```bash
# 创建虚拟环境
python -m venv .venv

# 激活（Windows Git Bash）
source .venv/Scripts/activate

# 安装依赖
pip install -r requirements.txt

# 准备配置
cp .env.example .env

# 扫描导入 content/ 下的 HTML
python -m app.scan

# 启动开发服务器
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 运行测试
pytest -q
```

**环境要求**：Python 3.13。Windows 本地开发或 Linux 服务器均可，不依赖系统级编译工具。

**配置**：需要 `HOST`、`PORT`、`DB_PATH`、`CONTENT_DIR`、`ADMIN_TOKEN`、`SITE_PASSWORD`、`NOTES_PASSWORD`，见 `.env.example`。

## 11. 待确认事项

- [ ] 是否需要给整站加访问口令（`SITE_PASSWORD`），还是仅靠服务器防火墙与 IP 白名单
- [ ] 定时任务连续失败时如何告警（当前只写 `/var/log/english-fetch.log`，需人工查看）
- [ ] 往期数量增长到多少需要分页，当前按一次返回 20 条设计
- [ ] `content/` 下的 HTML 是否纳入 git 版本管理
