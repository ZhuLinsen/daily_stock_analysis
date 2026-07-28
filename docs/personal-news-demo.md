# 个人股票新闻 Demo

这是现有项目中的单用户轻量模式，复用 SQLite、FastAPI、React、现有搜索/LLM/飞书模块。它不需要原生 Android、Firebase、PostgreSQL、Redis、Celery 或多用户系统。

## 最小配置

复制 `.env.example` 为 `.env`，只需填写三个服务的凭据：

```env
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=你的模型 API Key
OPENAI_MODEL=deepseek-v4-flash

BOCHA_API_KEYS=你的博查 API Key

FEISHU_WEBHOOK_URL=你的飞书机器人 Webhook
FEISHU_WEBHOOK_SECRET=
```

`FEISHU_WEBHOOK_SECRET` 仅在机器人启用签名校验时填写。股票不再写进 `.env`，请在 `/news` 页面添加、批量粘贴或删除。

这些默认值通常无需修改：

```env
APP_TIMEZONE=Asia/Shanghai
NEWS_PUSH_INTERVAL_HOURS=12
REFRESH_ON_OPEN=true
OPEN_REFRESH_COOLDOWN_MINUTES=10
MAX_AI_ITEMS_PER_RUN=5
```

## 启动与使用

```powershell
Copy-Item .env.example .env
notepad .env
python main.py --news-watch
```

打开 `http://127.0.0.1:8000/news`：

- 输入单只或批量股票，支持逗号、空格和换行；
- A 股保存为 `600519.SH`、`300750.SZ`、`920000.BJ`，港股保存为 `00700.HK`，美股保存为 `NVDA`；
- 新加入的股票会触发一次后台检查；页面仍可浏览历史结果；
- 每个浏览器会话首次打开页面会异步请求刷新，后端有 10 分钟全局冷却和进程锁；
- 页面显示刷新状态、最后检查时间、本轮新增、最新 AI 观察、重要新增和历史资讯。

## 调度、分析与推送

服务启动时不扫描、不推送。任务固定在 `Asia/Shanghai` 的 08:00 和 20:00 运行；`NEWS_PUSH_INTERVAL_HOURS=12` 用于表达产品节奏，不恢复 15 分钟轮询。

每轮先抓取、规范化、去重和确定性评分。只有数据库中首次出现的新闻才进入 AI，按重要性降序最多处理 5 条；没有新增时不调用 AI，也不推送。已经分析过的新闻不会因为重启或再次打开页面而重复分析。

同一轮最多发送一条飞书汇总，包含股票、重要性、方向、摘要、中文“观察策略”、原因、风险、失效条件和原始来源。重复新闻不会重复推送。AI 输出经过严格 Pydantic 校验，缺少正反因素、风险、失效条件或可核验来源时不会推送。

## PWA 与部署

移动浏览器通过 HTTPS 打开 `/news` 后，可选择“添加到主屏幕”或“安装应用”。PWA 仅缓存应用外壳和最近历史；刷新失败时仍能查看已经保存的资讯。

香港轻量服务器可继续使用现有 systemd + Caddy 部署方式：构建 Web 后让 systemd 执行 `python main.py --news-watch`，Caddy 反向代理到 FastAPI。凭据只保存在服务器 `.env`，不要写入浏览器、service worker 或 Git。

该 Demo 不是交易所级实时系统，不自动交易，也不提供确定性买卖建议或目标价。
