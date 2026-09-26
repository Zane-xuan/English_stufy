# English_study 项目约定

> 本文件给 AI 编码工具读取。详细设计见 [开发文档](DEV_DOC.md)。

## 项目是什么

一个自用的英语口语学习站。每天自动从公开视频平台选一段有激励作用的英语视频，提取生词、短语与口语化表达，生成全文中文译文，在网页上以原文／译文可切换的方式呈现。单人使用，不做登录。

判定环节（打分、选材、提取词汇、翻译）**不调用任何大模型接口**，而是通过 `data/pending/` 下的两个 JSON 文件交给 agent 完成。流水线因此分成 prepare 与 finalize 两段。

开发在本机 Windows 上做（项目路径 `E:/project/vps/English_study`，conda 环境 `english_study`），测试通过后部署到远程 Linux VPS（`/opt/English_study`，venv）。写代码时按 Windows 环境验证，不要写只能在 Linux 上跑的命令。

## 技术栈（不要擅自更换）

| 项 | 选择 | 版本 |
|---|---|---|
| 语言／运行时 | Python | 3.12 |
| Web 框架 | FastAPI + Uvicorn | 0.141.1 / 0.54.0 |
| 模板 | Jinja2 | 3.1.6 |
| 前端 | 原生 HTML / CSS / JS | 无 |
| 存储 | SQLite（标准库 `sqlite3`） | 3 |
| 调度 | APScheduler | 3.11.3 |
| 采集 | yt-dlp + ffmpeg | 2026.8.19 / 系统级 |
| 转写 | faster-whisper | 1.2.1 |
| 判定 | agent + 文件交接 | 无依赖 |

**不要引入新的第三方依赖**，除非先说明理由并征得同意。特别是不要引入 ORM、前端框架、任务队列，**也不要引入任何大模型 SDK**。

## 常用命令

```powershell
# 激活虚拟环境（本机 Windows 用 conda）
conda activate english_study

# 启动服务
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 看某天卡在哪一步
python scripts/run_once.py --date 2026-09-26

# 第一段：采集候选、取字幕、写交接请求
python scripts/run_once.py --stage prepare --date 2026-09-26

# 第二段：读回 agent 结果并落库
python scripts/run_once.py --stage finalize --date 2026-09-26

# 覆盖重跑
python scripts/run_once.py --stage prepare --date 2026-09-26 --force

# 运行测试
pytest tests/ -q

# 静态检查
ruff check app/ scripts/ tests/
```

服务器上用 venv，激活命令是 `source .venv/bin/activate`，其余相同。

## 代码约定

- 所有函数写类型注解
- 路径统一用 `pathlib.Path`，不用字符串拼接
- 数据库访问集中在 `app/db.py`，其他模块不直接 `sqlite3.connect`
- 写 `fetch_log` 一律走 `db.log_stage()`，它用独立事务，保证流水线失败时日志不跟着回滚
- agent 返回的内容一律先校验再落库，校验不过抛异常，不要静默兜底
- 平台适配器都实现 `app/providers/base.py` 的接口，新增平台只加文件加一行注册
- 异常统一用 `app/errors.py` 里的自定义异常，不要裸 `except`
- 注释与日志用中文，标识符用英文

## 不要动的地方

- 不要改 `app/db.py` 里 `init_db()` 的建表语句，结构变更必须走单独的迁移脚本
- 不要改 `candidate` 表 `(platform, external_id)` 的唯一约束，它保证每天内容不重复
- 不要改 `app/pipeline/subtitle.py` 里 `group_into_paragraphs` 的分段规则，正文与译文的段落对应关系依赖它
- 不要改 `app/pipeline/handoff.py` 里请求与结果的字段名，agent 与外部脚本都按这套字段对接
- 不要动 `tests/` 下已有的断言

## 配置与密钥

- 真实配置放 `.env`，该文件已被 `.gitignore` 忽略，**不要提交，也不要读取后写入其他文件**
- 需要新增配置项时，先更新 `.env.example`，再在 `.env` 里填真实值
- **不要在代码里硬编码任何密钥**
- 日志里不要打印代理地址的完整值

## 文档索引

| 想了解 | 看哪份 |
|---|---|
| 技术方案与选型理由 | [技术选型](TECH_STACK.md) |
| 功能清单与实现要点 | [开发文档](DEV_DOC.md) |
| 怎么运行与使用 | [使用文档](USAGE_DOC.md) |
| 测试用例与风险点 | [测试用例](TEST_CASES.md) |
| 上线与故障排查 | [部署说明](DEPLOY.md) |
