# 个人股票新闻雷达 Demo

该模式面向单用户，复用项目已有的股票搜索、OpenAI-compatible/LiteLLM、企业微信、飞书、FastAPI、React WebUI 和 SQLite。它不依赖 Firebase、Google Play Services、PostgreSQL、Redis、Celery、Kafka 或原生 Android 客户端。

## 本地运行

复制配置并至少填写自选股、一个新闻搜索来源，以及可选的 AI 和推送凭据：

```powershell
Copy-Item .env.example .env
notepad .env
python main.py --news-watch
```

浏览器打开 `http://127.0.0.1:8000/news`。轮询模式会立即执行一轮，之后按 `POLL_INTERVAL_MINUTES` 间隔运行。单个新闻源、LLM 或推送渠道失败不会终止服务。

最小配置：

```env
WATCHLIST=600519,300750,002594,hk00700,hk09988,AAPL,NVDA,TSLA
MACRO_KEYWORDS=美联储,中国人民银行,利率,关税,制裁,芯片出口,人工智能,新能源汽车,原油,黄金,汇率
POLL_INTERVAL_MINUTES=15
MIN_ANALYSIS_SCORE=60
MIN_PUSH_SCORE=75
PUBLIC_BASE_URL=https://stocks.example.com

OPENAI_BASE_URL=https://你的兼容服务/v1
OPENAI_API_KEY=你的密钥
OPENAI_MODEL=你的模型标识

WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的密钥
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/你的密钥
```

`WATCHLIST` 未设置时会复用现有 `STOCK_LIST`。所有密钥只保存在 `.env` 服务端配置中，不会进入浏览器、service worker 或 Git；仓库已忽略 `.env`。

## 处理规则

程序先标准化 URL、标题、来源、时间和股票代码，再通过规范 URL、标题哈希以及“股票代码 + 标题 + 六小时时间窗”事件哈希去重。哈希、分析和每个通知渠道的发送状态都持久化在现有 SQLite 数据库中，因此重启后不会重新分析或重复推送；失败的渠道可在下一次发现同一新闻时单独重试。

重要性是 0–100 的确定性程序评分，考虑公告/监管属性、自选股命中、高影响事件、来源可靠度、多源确认、时效、价格/成交量变化和实体匹配置信度。LLM 不参与打分：默认 60 分以上才分析，75 分以上才推送。

AI 只解释输入证据，并通过 Pydantic 验证固定 JSON。输出缺少来源、正面因素或负面因素，或 JSON 非法时会重试一次；再次失败只保存错误，不推送无效分析。

## 企业微信与飞书

企业微信群机器人使用 `WECHAT_WEBHOOK_URL`。飞书可使用简单的 `FEISHU_WEBHOOK_URL`，也可继续使用项目现有 App Bot 配置。两者可以同时启用；某一渠道失败不影响另一渠道或分析入库。

推送详情链接格式为 `PUBLIC_BASE_URL/news/{news_id}`。公网部署必须把 `PUBLIC_BASE_URL` 设置成手机可访问的 HTTPS 地址。

## Android 安装 PWA

先通过 HTTPS 打开 `/news`，然后在 Chrome、Edge 或支持安装 PWA 的 Android 浏览器菜单中选择“添加到主屏幕”或“安装应用”。安装后显示名称为“股票雷达”，以 standalone 模式启动，并对应用壳、历史新闻列表与详情响应做简单离线缓存。

第一阶段没有生成 APK，也没有加入 Capacitor：PWA 已覆盖个人 Demo 的核心使用方式，且当前任务不应让 Android SDK/Java 环境阻塞后端和 Web 完成。如果后续确实需要 APK，可在通过 PWA 验收后增加只加载现有 WebUI 的 `mobile-wrapper/`。

## 香港轻量服务器部署

以下示例使用 Python 虚拟环境、systemd 和 Caddy；实际域名、用户和路径请替换，密钥仍只放在 `.env`：

```bash
sudo apt update
sudo apt install -y python3-venv nodejs npm caddy
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git /opt/stock-news-demo
cd /opt/stock-news-demo
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd apps/dsa-web && npm ci && npm run build && cd ../..
cp .env.example .env
chmod 600 .env
```

`/etc/systemd/system/stock-news-demo.service`：

```ini
[Unit]
Description=Personal stock news radar
After=network-online.target

[Service]
Type=simple
User=stockradar
WorkingDirectory=/opt/stock-news-demo
EnvironmentFile=/opt/stock-news-demo/.env
ExecStart=/opt/stock-news-demo/.venv/bin/python main.py --news-watch
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`/etc/caddy/Caddyfile`：

```caddy
stocks.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now stock-news-demo
sudo systemctl reload caddy
sudo systemctl status stock-news-demo
```

Caddy 会为有效公网域名自动申请 HTTPS 证书。建议启用项目现有管理员认证，并通过防火墙只开放 80/443。
