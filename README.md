# BOSS 人才索引采集助手

这是一个本地 RPA MVP，用于辅助 HR 在已经登录的 BOSS 直聘人才库页面中读取**当前可见**候选人信息，并写入轻量索引文件。它不是无人值守爬虫，也不绕过登录、验证码、风控或隐藏接口。

## 目标边界

- 读取 HR 当前可见的搜索结果卡片。
- 可选点开详情弹窗，对在线简历 canvas 截图 OCR，保存简历快照和轻量索引字段。
- 不保存账号密码。
- 在线简历长文本只保存 HR 当前账号可见内容的 OCR 快照；联系方式会做基础脱敏。
- 不采集联系方式。
- 遇到登录、验证码、账号异常时由人工处理，脚本暂停或退出。

## 安装

```bash
npm install
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

默认使用本机 Chrome。也可以通过环境变量指定浏览器路径：

```bash
BOSS_BROWSER_EXECUTABLE="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" npm run capture
```

## 使用

```bash
npm run capture -- --limit 10 --details
```

首次运行会打开一个独立 Chrome 用户目录 `.browser-profile`。请在浏览器里手动登录 BOSS，进入人才库搜索页，设置好城市、岗位、关键词和筛选条件。准备好后回到终端按回车，脚本会读取页面上可见候选人。

常用参数：

```text
--limit 20              最多读取多少个候选人卡片
--details               点开详情弹窗并抽取轻量索引
--no-details            只读取列表页卡片
--start-url <url>       起始页面
--user-data-dir <dir>   浏览器登录态目录
--output-dir <dir>      输出目录
--headless              无头模式，不推荐用于首次登录
```

输出文件。`capture` 默认写入 `data/`，`capture:cdp` 默认写入 `data-python/`：

```text
<output-dir>/candidates.ndjson        候选人索引，追加写入
<output-dir>/observations.ndjson      每次搜索观察记录，追加写入
<output-dir>/resume_snapshots.ndjson  在线简历 OCR 快照，追加写入
<output-dir>/runs/run-*.json          单次运行结果，便于复核
```

候选人索引会保留页面上的 `active_status` 原始活跃标签，例如 `刚刚活跃`、`3日内活跃`、`本周活跃`，并推断一个保守的 `last_seen_at`。区间类标签按区间起点推断，例如 `今日活跃` 记为当天 00:00，`本周活跃` 记为本周一 00:00，`3日内活跃` 记为采集时间减 3 天。

如果你已经在普通 Chrome 里打开并登录了 BOSS 页面，但 Chrome 没有开启远程调试，也没有允许 Apple Events 执行 JavaScript，可以用辅助功能 fallback：

```bash
npm run capture:chrome-ax -- --limit 15
```

这个模式只读取当前 Chrome 窗口里辅助功能树暴露出来的候选人卡片文本，不会点开详情页。

Python + CDP 连接已启动 Chrome：

```bash
open -na "Google Chrome" --args \
  --remote-debugging-port=9222 \
  --remote-allow-origins=http://127.0.0.1:9222 \
  --user-data-dir=/tmp/boss-rpa-chrome \
  --no-first-run \
  https://www.zhipin.com/web/chat/search

npm run capture:cdp -- --limit 10 --skip-apply --detail-max-pages 3
```

这个模式会连接 9222 端口上的 Chrome，用 DOM 读取页面，比辅助功能 fallback 快很多。
详情页正文由 BOSS 的 canvas 渲染，脚本会裁剪详情弹窗截图并用 macOS Vision OCR 读取文字；原始截图会保存在 `data-python/resume-screenshots/<run-id>/` 便于复核。

如果当前搜索结果每次只加载 15 个，可以让脚本先滚动加载更多：

```bash
npm run capture:cdp -- --limit 100 --skip-apply --no-details
```

`--limit 100` 会滚动到累计 100 个候选人或没有更多结果为止。要一直加载到列表没有新增候选人：

```bash
npm run capture:cdp -- --load-all --skip-apply --no-details
```

量产抓详情时可以去掉 `--no-details`，并用 `--detail-max-pages 1` 或 `2` 控制每份在线简历 OCR 的页数。

## 数据策略

这个 MVP 采用 B+C 混合版：

- B：Playwright 半自动读取页面可见信息。
- C：候选人索引落主表，在线简历落快照表，避免覆盖历史。

OCR 快照用于内部检索和复核，最终原文仍以 BOSS 页面为准。

## PostgreSQL

见 [sql/schema.sql](sql/schema.sql)。第一版先落 NDJSON，确认字段稳定后再接 PostgreSQL。

当前也可以把单次 run 导入本地 SQLite：

```bash
.venv/bin/python python/import_run_sqlite.py data-python/runs/run-*.json \
  --db data-python/boss_talent.sqlite
```

## 测试

```bash
npm test
```
