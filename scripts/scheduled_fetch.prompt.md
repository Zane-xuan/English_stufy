你要为「English Study」站点生成**新的一期**英语口语学习资源。

工作目录是 `/opt/English_study`，你已在其中。开始前先读这三份文件，严格遵循里面的约定，尤其是 `AGENTS.md` 的「不要动的地方」：

- `AGENTS.md`
- `DEV_DOC.md` 第 9 节「每期内容的生成约定」（素材来源、选片标准、台词来源、每期结构、词汇 key 约束）
- `LEARNING_PLAN.md`

## 本次任务

1. 确定发布日：用北京时间今天的日期，格式 `YYYY-MM-DD`（环境里已设 `TZ=Asia/Shanghai`，直接 `date +%F` 即可）。
2. 确定期号：新一期期号 = 现有最大期号 + 1。可执行
   `python -c "import sqlite3;c=sqlite3.connect('data/clips.db');print(c.execute('select max(period) from clips').fetchone()[0])"`
   取当前最大期号；没有记录则从 1 开始。
3. 选素材：按 `DEV_DOC.md` 第 9 节的四类来源与选片标准，挑一段 **2 至 5 分钟**的资源。轮换作品与类型，避免与 `content/` 下已有几期重复（先看看现有文件名与标题）。
4. 取逐字稿：**必须**从真实来源取得（转录站、官方发布稿、剧本库等），用 WebSearch / WebFetch 核对。**不得凭记忆编写台词，不得编造视频 ID**。观看链接要真的能打开。
5. 写页面：新建 `content/YYYY-MM-DD_<Title>.html`，`Title` 用英文短标题。必须完整包含这套类名：
   `.kicker`、`h1` 与 `h1 .sub`、`.meta .chip`（日期/类型/时长/难度/口音）、`.watch a`（含 `.site` 与 `.ttl`）、`.script[data-lang]` 与 `#langBtn`、`.turn`（`.en-text` / `.zh-text` 成对）、`.vrow[data-keys]`、`.tgt[data-key]`、`.pron`。
   词汇 key 与原文锚点必须**双向一一对应且不嵌套**（重叠的短语要拆成相邻但不重叠的两段）。
6. 自检：运行
   `python scripts/check_content.py content/<你写的文件名>`
   必须通过。不通过就修改到通过为止。

## 边界（务必遵守，不要越界）

- 只允许新增或修改 `content/` 下的这一个 HTML 文件。
- **不要**改动 `app/`、`scripts/`、`templates/`、`static/`、任何文档、`.env`、数据库。
- **不要**运行 `app.scan`（入库由外层脚本统一处理）。
- **不要**执行任何 `git` 操作。
- 如果拿不到合格素材或可靠逐字稿，**不要编造**，直接结束并说明失败原因。

## 输出

全部完成后，**最后只输出一行**：

- 成功：`OK <文件名> | 第 N 期 | <作品> | <类型>`
- 失败：`FAIL <原因>`
