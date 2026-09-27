# English Study 使用文档

> 版本 v0.1 ｜ 更新 2026-09-27
> 配套文档：[技术选型](TECH_STACK.md) ｜ [开发文档](DEV_DOC.md)

## 1. 这是什么

一个给你自己用的英语口语学习站。每生成一期「每日英语影视片段」页面，把它放进 `content/` 目录，站点就会收录它。

打开站点，主内容区直接就是今天该主攻的那份资源，语言切换、词汇点击高亮都能用。右上角有一个「历史回顾」按钮，不去点它，页面就只有今天这份内容。
点一下这个按钮，右侧滑出一个抽屉，里面是以前学过的全部期数，按日期从新到旧排好，也能按关键词或类型筛选。在抽屉里选某一天，主内容区就地换成那一天，抽屉留在原地不用反复开合。

往期的索引信息存在一个 SQLite 数据库里，备份就是拷一个文件。

## 2. 安装

**前置条件**：Python 3.13。

```bash
cd /path/to/English_study
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env
```

Windows 上激活脚本在 `.venv/Scripts/activate`，Linux 上在 `.venv/bin/activate`。`.venv` 已经建好时，只需执行激活这一步。

打开 `.env`，把 `ADMIN_TOKEN` 填成一个随机长字符串。可以这样生成：

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 3. 快速上手

1. 把一期学习页 HTML 放进 `content/`，文件名形如 `2026-09-27_Good-Will-Hunting.html`。
2. 执行扫描，把这一期收录进数据库。
3. 启动站点，打开浏览器访问。

```bash
python -m app.scan
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

启动后终端会打印 `INFO: Uvicorn running on http://127.0.0.1:8000`，浏览器打开该地址，看到当天的学习内容即成功。点右上角「历史回顾」可以翻往期。

## 4. 常用操作

### 收录新的一期

把 HTML 放进 `content/` 后执行扫描。已收录且文件未变动的资源会被跳过，只处理新增和改动过的文件。

```bash
python -m app.scan
```

### 收录前先自检

新写的一份资源在扫描前跑一次自检，查标签配平、词汇 key 与原文锚点是否双向对上、站点要用的字段是否齐全。带文件名参数可以只查一个。

```bash
python scripts/check_content.py
python scripts/check_content.py content/2026-09-26_Steve-Jobs-Stanford.html
```

改了页面文件后重新扫描，元数据会刷新。若怀疑索引脏了，删库重建即可，`content/` 下的 HTML 不受影响。

```bash
rm data/clips.db
python -m app.scan
```

### 在服务器上触发扫描

站点已在服务器上运行时，不必登录服务器，直接调接口。需要先导出令牌。

```bash
export ADMIN_TOKEN=你在.env里填的值
curl -X POST http://127.0.0.1:8000/api/scan -H "X-Admin-Token: ${ADMIN_TOKEN}"
```

返回的统计里，`inserted` 是新增条数，`updated` 是重新解析的条数，`skipped` 是未变动的条数。

### 备份数据库

索引数据都在一个文件里，直接拷走即可。

```bash
cp data/clips.db data/clips.db.bak
```

### 部署到服务器

服务器上准备项目目录并安装依赖：

```bash
cd /opt/english-study
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` 里保持 `HOST=127.0.0.1`，由 Nginx 反向代理对外，不要直接把 Uvicorn 暴露到公网。

新一期的页面由 agent 生成，agent 只往 `content/` 写文件，入库仍走扫描。执行方式与边界见 [开发文档](DEV_DOC.md) 第 9 节。

写 systemd 服务文件 `/etc/systemd/system/english-study.service`：

```ini
[Unit]
Description=English Study
After=network.target

[Service]
WorkingDirectory=/opt/english-study
ExecStart=/opt/english-study/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

Nginx 反向代理配置，写进 `/etc/nginx/sites-available/english-study`：

```nginx
server {
    listen 80;
    server_name 你的域名;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

启动服务、设为开机自启，再启用 Nginx 配置：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now english-study
sudo ln -s /etc/nginx/sites-available/english-study /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 定时扫描

内容每周一、周四更新，扫描跟内容节奏无关，每天跑一次即可：没变动的文件会被跳过，开销很小。

```bash
crontab -e
# 写入这一行
0 6 * * * cd /opt/english-study && .venv/bin/python -m app.scan >> /var/log/english-scan.log 2>&1
```

## 5. 常见问题

**Q：打开 `/history` 是空的。**
A：往期列表已经收进右侧抽屉，没有单独的 `/history` 页面。点右上角「历史回顾」展开即可。若抽屉里也是空的，先确认 `content/` 下有 HTML 文件，然后执行 `python -m app.scan`。

**Q：某一期的标题显示的是一串文件名。**
A：说明页面里没取到标题。查这条记录的 `parse_note` 字段，里面会写明缺哪一项。修正 HTML 后重新扫描即可。

**Q：详情页提示「这一期的 HTML 文件已不在磁盘上」。**
A：文件被移动、改名或删除了。把文件放回 `content/` 并重新扫描，记录会恢复；也可以直接删掉这条记录。

**Q：调扫描接口返回 401。**
A：请求头里的令牌与 `.env` 里的 `ADMIN_TOKEN` 不一致。确认两边完全相同，注意别带多余空格。

**Q：页面里的中文变成乱码。**
A：HTML 文件不是 UTF-8 编码。用编辑器另存为 UTF-8 后重新扫描。

## 6. 卸载与清理

```bash
# 本地：直接删除项目目录即可
rm -rf /path/to/English_study

# 服务器：先停服务与反代，再删目录
sudo systemctl disable --now english-study
sudo rm /etc/systemd/system/english-study.service
sudo systemctl daemon-reload
sudo rm -f /etc/nginx/sites-enabled/english-study /etc/nginx/sites-available/english-study
sudo systemctl reload nginx
sudo rm -rf /opt/english-study
```

需要保留的残留数据位置：

| 内容 | 位置 |
|---|---|
| 索引数据库 | `data/clips.db` |
| 每期学习页面 | `content/` |
| 配置与令牌 | `.env` |
