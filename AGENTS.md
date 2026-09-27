# English Study 项目约定

> 本文件给 AI 编码工具读取。详细设计见 [开发文档](DEV_DOC.md)。

## 项目是什么

一个自用的英语口语学习站。每份资源是一个独立的 HTML 文件，放在 `content/` 目录。站点扫描这些文件，把发布日、服务区间、标题、影片、类型等元数据写进 SQLite。页面是两栏：主内容区直接内嵌今天该主攻的那份资源的原始学习页面，右侧抽屉按发布日倒序列出全部资源，点某一份就换主内容区。台词与词汇正文不落库，只以 HTML 文件为准。

站点的目标是支撑 [学习计划](LEARNING_PLAN.md) 里的口语训练：每周一、周四各更新一份 2 至 5 分钟的资源，用两份材料撑起全周。**做功能取舍时先看学习计划，不要只看现有实现。**

## 技术栈（不要擅自更换）

| 项        | 选择                    | 版本       |
| -------- | --------------------- | -------- |
| 语言 / 运行时 | Python                | 3.13     |
| 服务端框架    | FastAPI + Uvicorn     | 版本待定     |
| 模板       | Jinja2                | 版本待定     |
| HTML 解析  | BeautifulSoup4        | 版本待定     |
| 存储       | SQLite，走标准库 `sqlite3` | 随 Python |
| 前端       | 原生 HTML/CSS/JS        | 不适用      |

**不要引入新的第三方依赖**，除非先说明理由并征得同意。特别是不要引入 ORM、前端框架、CSS 框架。

## 常用命令

```bash
# 激活虚拟环境（Windows Git Bash）
source .venv/Scripts/activate

# 扫描导入 content/ 下的 HTML
python -m app.scan

# 每份资源的 HTML 交付前自检（标签配平、词汇 key 与原文锚点双向一致、字段齐全）
python scripts/check_content.py

# 启动开发服务器
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 测试
pytest -q
```

## 代码约定

- 所有函数写类型注解。
- 路径操作统一用 `pathlib.Path`，不用 `os.path` 拼字符串。
- 读写文件一律显式写 `encoding="utf-8"`，不要依赖系统默认编码。
- 配置只在 `app/config.py` 读取，业务代码不直接读环境变量。
- 数据库写入必须放在事务里。
- 注释用中文，标识符用英文。
- 页面文案与文档正文用全角标点，代码、路径、命令用半角。

## 不要动的地方

- `app/parser.py` 里对应参考页面类名的字段映射表（`.kicker`、`h1 .sub`、`.meta .chip`、`.watch a`）。这些类名由外部生成的 HTML 决定，改了会直接导致解析失败。
- `app/render.py` 里给 CSS 加 `#clip-root` 前缀的逻辑。原始页面的样式全靠它隔离，改错会让原始样式泄漏到外壳，或让外壳样式污染学习内容。
- 外壳模板与样式里不要使用 `script`、`langBtn` 这类 id，原始页面的脚本要靠全局 id 找自己的元素，撞名会直接坏掉交互。
- `content/` 目录下的 HTML 文件。它们是内容源，只读，不要格式化、不要改样式、不要重写。新增一期必须带齐这套类名：`.kicker`（期数与类型）、`h1` + `h1 .sub`、`.meta .chip`（日期/类型/时长/难度/口音，可选再加 `服务 · 起 ~ 止`）、`.watch a`（含 `.site`/`.ttl`）、`.script[data-lang]` + `#langBtn`、`.turn`（`.en-text`/`.zh-text` 成对）、`.vrow[data-keys]`、`.tgt[data-key]`、`.pron`。改完先跑 `python scripts/check_content.py`。
- 服务区间的推导规则（`app/parser.py` 的 `default_focus_window`，发布日起 3 天）。改它会直接改变首页「今天该学哪份」的判断。
- `clips` 表的字段名与 `GET /api/clips` 的响应字段。它们是数据契约，改名要同步改接口、模板与文档。
- `POST /api/scan` 的令牌校验。不要为了调试方便去掉或放宽。

## 配置与密钥

- 真实配置放 `.env`，该文件已被 `.gitignore` 忽略，**不要提交，也不要读取后写入其他文件**。
- 需要新增配置项时，先更新 `.env.example`，再在 `.env` 里填真实值。
- **不要在代码里硬编码任何密钥**，包括 `ADMIN_TOKEN` 与 `SITE_PASSWORD`。
- 文档、示例文件、注释里只写变量名，不写真实值。

## 文档索引

| 想了解               | 看哪份                   |
| ----------------- | --------------------- |
| 技术方案与选型理由         | [技术选型](TECH_STACK.md) |
| 学习目标、更新节奏、素材来源与筛选标准 | [学习计划](LEARNING_PLAN.md) |
| 功能清单、数据模型、接口、实现要点 | [开发文档](DEV_DOC.md)    |
| 素材优先级、台词来源、每期结构与词汇 key 约束 | [开发文档](DEV_DOC.md) 第 9 节 |
| 怎么安装、运行、部署        | [使用文档](USAGE_DOC.md)  |
