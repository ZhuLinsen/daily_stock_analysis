# 📖 完整配置与部署指南

本文档包含 A股智能分析系统的完整配置说明，适合需要高级功能或特殊部署方式的用户。

> 💡 快速上手请参考 [README.md](../README.md)，本文档为进阶配置。

## � 项目结构

```
daily_stock_analysis/
├── main.py              # 主程序入口
├── src/                 # 核心业务逻辑
│   ├── analyzer.py      # AI 分析器
│   ├── config.py        # 配置管理
│   ├── notification.py  # 消息推送
│   └── ...
├── data_provider/       # 多数据源适配器
├── bot/                 # 机器人交互模块
├── api/                 # FastAPI 后端服务
├── apps/dsa-web/        # React 前端
├── docker/              # Docker 配置
├── docs/                # 项目文档
└── .github/workflows/   # GitHub Actions
```

## 📑 目录

- [项目结构](#项目结构)
- [GitHub Actions 详细配置](#github-actions-详细配置)
- [环境变量完整列表](#环境变量完整列表)
- [Docker 部署](#docker-部署)
- [本地运行详细配置](#本地运行详细配置)
- [定时任务配置](#定时任务配置)
- [通知渠道详细配置](#通知渠道详细配置)
- [数据源配置](#数据源配置)
- [高级功能](#高级功能)
- [回测功能](#回测功能)
- [本地 WebUI 管理界面](#本地-webui-管理界面)

---

## GitHub Actions 详细配置

### 1. Fork 本仓库

点击右上角 `Fork` 按钮

### 2. 配置 Secrets

进入你 Fork 的仓库 → `Settings` → `Secrets and variables` → `Actions` → `New repository secret`

<div align="center">
  <img src="../sources/secret_config.png" alt="GitHub Secrets 配置示意图" width="600">
</div>

#### AI 模型配置（二选一）

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/) 获取免费 Key | ✅* |
| `OPENAI_API_KEY` | OpenAI 兼容 API Key（支持 DeepSeek、通义千问等） | 可选 |
| `OPENAI_BASE_URL` | OpenAI 兼容 API 地址（如 `https://api.deepseek.com/v1`） | 可选 |
| `OPENAI_MODEL` | 模型名称（如 `gemini-3.1-pro-preview`、`deepseek-chat`、`gpt-5.2`） | 可选 |

> *注：`GEMINI_API_KEY` 和 `OPENAI_API_KEY` 至少配置一个

#### 通知渠道配置（可同时配置多个，全部推送）

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `WECHAT_WEBHOOK_URL` | 企业微信 Webhook URL | 可选 |
| `FEISHU_WEBHOOK_URL` | 飞书 Webhook URL | 可选 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token（@BotFather 获取） | 可选 |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | 可选 |
| `TELEGRAM_MESSAGE_THREAD_ID` | Telegram Topic ID (用于发送到子话题) | 可选 |
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL（[创建方法](https://support.discord.com/hc/en-us/articles/228383668)） | 可选 |
| `DISCORD_BOT_TOKEN` | Discord Bot Token（与 Webhook 二选一） | 可选 |
| `DISCORD_CHANNEL_ID` | Discord Channel ID（使用 Bot 时需要） | 可选 |
| `EMAIL_SENDER` | 发件人邮箱（如 `xxx@qq.com`） | 可选 |
| `EMAIL_PASSWORD` | 邮箱授权码（非登录密码） | 可选 |
| `EMAIL_RECEIVERS` | 收件人邮箱（多个用逗号分隔，留空则发给自己） | 可选 |
| `EMAIL_SENDER_NAME` | 发件人显示名称（默认：daily_stock_analysis股票分析助手） | 可选 |
| `PUSHPLUS_TOKEN` | PushPlus Token（[获取地址](https://www.pushplus.plus)，国内推送服务） | 可选 |
| `SERVERCHAN3_SENDKEY` | Server酱³ Sendkey（[获取地址](https://sc3.ft07.com/)，手机APP推送服务） | 可选 |
| `CUSTOM_WEBHOOK_URLS` | 自定义 Webhook（支持钉钉等，多个用逗号分隔） | 可选 |
| `CUSTOM_WEBHOOK_BEARER_TOKEN` | 自定义 Webhook 的 Bearer Token（用于需要认证的 Webhook） | 可选 |
| `WEBHOOK_VERIFY_SSL` | Webhook HTTPS 证书校验（默认 true）。设为 false 可支持自签名证书。警告：关闭有严重安全风险（MITM），仅限可信内网 | 可选 |

> *注：至少配置一个渠道，配置多个则同时推送

#### 推送行为配置

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `SINGLE_STOCK_NOTIFY` | 单股推送模式：设为 `true` 则每分析完一只股票立即推送 | 可选 |
| `REPORT_TYPE` | 报告类型：`simple`(精简) 或 `full`(完整)，Docker环境推荐设为 `full` | 可选 |
| `REPORT_SUMMARY_ONLY` | 仅分析结果摘要：设为 `true` 时只推送汇总，不含个股详情；多股时适合快速浏览（默认 false，Issue #262） | 可选 |
| `ANALYSIS_DELAY` | 个股分析和大盘分析之间的延迟（秒），避免API限流，如 `10` | 可选 |
| `MERGE_EMAIL_NOTIFICATION` | 个股与大盘复盘合并推送（默认 false），减少邮件数量、降低垃圾邮件风险；与 `SINGLE_STOCK_NOTIFY` 互斥（单股模式下合并不生效） | 可选 |
| `MARKDOWN_TO_IMAGE_CHANNELS` | 将 Markdown 转为图片发送的渠道（用逗号分隔）：telegram,wechat,custom,email，需安装 wkhtmltopdf | 可选 |
| `MARKDOWN_TO_IMAGE_MAX_CHARS` | 超过此长度不转图片，避免超大图片（默认 15000） | 可选 |

#### 其他配置

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `STOCK_LIST` | 自选股代码，如 `600519,300750,002594` | ✅ |
| `TAVILY_API_KEYS` | [Tavily](https://tavily.com/) 搜索 API（新闻搜索） | 推荐 |
| `BOCHA_API_KEYS` | [博查搜索](https://open.bocha.cn/) Web Search API（中文搜索优化，支持AI摘要，多个key用逗号分隔） | 可选 |
| `BRAVE_API_KEYS` | [Brave Search](https://brave.com/search/api/) API（隐私优先，美股优化，多个key用逗号分隔） | 可选 |
| `SERPAPI_API_KEYS` | [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis) 备用搜索 | 可选 |
| `TUSHARE_TOKEN` | [Tushare Pro](https://tushare.pro/weborder/#/login?reg=834638 ) Token | 可选 |

#### ✅ 最小配置示例

如果你想快速开始，最少需要配置以下项：

1. **AI 模型**：`AIHUBMIX_KEY`（[AIHubmix](https://aihubmix.com/?aff=CfMq)，一 Key 多模型）、`GEMINI_API_KEY` 或 `OPENAI_API_KEY`
2. **通知渠道**：至少配置一个，如 `WECHAT_WEBHOOK_URL` 或 `EMAIL_SENDER` + `EMAIL_PASSWORD`
3. **股票列表**：`STOCK_LIST`（必填）
4. **搜索 API**：`TAVILY_API_KEYS`（强烈推荐，用于新闻搜索）

> 💡 配置完以上 4 项即可开始使用！

### 3. 启用 Actions

1. 进入你 Fork 的仓库
2. 点击顶部的 `Actions` 标签
3. 如果看到提示，点击 `I understand my workflows, go ahead and enable them`

### 4. 手动测试

1. 进入 `Actions` 标签
2. 左侧选择 `每日股票分析` workflow
3. 点击右侧的 `Run workflow` 按钮
4. 选择运行模式
5. 点击绿色的 `Run workflow` 确认

### 5. 完成！

默认每个工作日 **18:00（北京时间）** 自动执行。

---

## 环境变量完整列表

### AI 模型配置

| 变量名 | 说明 | 默认值 | 必填 |
|--------|------|--------|:----:|
| `AIHUBMIX_KEY` | [AIHubmix](https://aihubmix.com/?aff=CfMq) API Key，一 Key 切换使用全系模型，无需额外配置 Base URL | - | 可选 |
| `GEMINI_API_KEY` | Google Gemini API Key | - | 可选 |
| `GEMINI_MODEL` | 主模型名称 | `gemini-3-flash-preview` | 否 |
| `GEMINI_MODEL_FALLBACK` | 备选模型 | `gemini-2.5-flash` | 否 |
| `OPENAI_API_KEY` | OpenAI 兼容 API Key | - | 可选 |
| `OPENAI_BASE_URL` | OpenAI 兼容 API 地址 | - | 可选 |
| `OPENAI_MODEL` | OpenAI 模型名称（AIHubmix 用户可填如 `gemini-3.1-pro-preview`、`gemini-3-flash-preview`、`gpt-5.2`） | `gpt-5.2` | 可选 |
| `ANTHROPIC_API_KEY` | Anthropic Claude API Key | - | 可选 |
| `ANTHROPIC_MODEL` | Claude 模型名称 | `claude-3-5-sonnet-20241022` | 可选 |
| `ANTHROPIC_TEMPERATURE` | Claude 温度参数（0.0-1.0） | `0.7` | 可选 |
| `ANTHROPIC_MAX_TOKENS` | Claude 响应最大 token 数 | `8192` | 可选 |

> *注：`AIHUBMIX_KEY`、`GEMINI_API_KEY`、`ANTHROPIC_API_KEY` 和 `OPENAI_API_KEY` 至少配置一个。`AIHUBMIX_KEY` 无需配置 `OPENAI_BASE_URL`，系统自动适配。

### 通知渠道配置

| 变量名 | 说明 | 必填 |
|--------|------|:----:|
| `WECHAT_WEBHOOK_URL` | 企业微信机器人 Webhook URL | 可选 |
| `FEISHU_WEBHOOK_URL` | 飞书机器人 Webhook URL | 可选 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 可选 |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | 可选 |
| `TELEGRAM_MESSAGE_THREAD_ID` | Telegram Topic ID | 可选 |
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL | 可选 |
| `DISCORD_BOT_TOKEN` | Discord Bot Token（与 Webhook 二选一） | 可选 |
| `DISCORD_CHANNEL_ID` | Discord Channel ID（使用 Bot 时需要） | 可选 |
| `DISCORD_MAX_WORDS` | Discord 最大字数限制（默认 免费服务器限制2000） | 可选 |
| `EMAIL_SENDER` | 发件人邮箱 | 可选 |
| `EMAIL_PASSWORD` | 邮箱授权码（非登录密码） | 可选 |
| `EMAIL_RECEIVERS` | 收件人邮箱（逗号分隔，留空发给自己） | 可选 |
| `EMAIL_SENDER_NAME` | 发件人显示名称 | 可选 |
| `STOCK_GROUP_N` / `EMAIL_GROUP_N` | 股票分组发往不同邮箱（Issue #268），如 `STOCK_GROUP_1=600519,300750` 与 `EMAIL_GROUP_1=user1@example.com` 配对 | 可选 |
| `CUSTOM_WEBHOOK_URLS` | 自定义 Webhook（逗号分隔） | 可选 |
| `CUSTOM_WEBHOOK_BEARER_TOKEN` | 自定义 Webhook Bearer Token | 可选 |
| `WEBHOOK_VERIFY_SSL` | Webhook HTTPS 证书校验（默认 true）。设为 false 可支持自签名。警告：关闭有严重安全风险 | 可选 |
| `PUSHOVER_USER_KEY` | Pushover 用户 Key | 可选 |
| `PUSHOVER_API_TOKEN` | Pushover API Token | 可选 |
| `PUSHPLUS_TOKEN` | PushPlus Token（国内推送服务） | 可选 |
| `SERVERCHAN3_SENDKEY` | Server酱³ Sendkey | 可选 |

#### 飞书云文档配置（可选，解决消息截断问题）

| 变量名 | 说明 | 必填 |
|--------|------|:----:|
| `FEISHU_APP_ID` | 飞书应用 ID | 可选 |
| `FEISHU_APP_SECRET` | 飞书应用 Secret | 可选 |
| `FEISHU_FOLDER_TOKEN` | 飞书云盘文件夹 Token | 可选 |

> 飞书云文档配置步骤：
> 1. 在 [飞书开发者后台](https://open.feishu.cn/app) 创建应用
> 2. 配置 GitHub Secrets
> 3. 创建群组并添加应用机器人
> 4. 在云盘文件夹中添加群组为协作者（可管理权限）

### 搜索服务配置

| 变量名 | 说明 | 必填 |
|--------|------|:----:|
| `TAVILY_API_KEYS` | Tavily 搜索 API Key（推荐） | 推荐 |
| `BOCHA_API_KEYS` | 博查搜索 API Key（中文优化） | 可选 |
| `BRAVE_API_KEYS` | Brave Search API Key（美股优化） | 可选 |
| `SERPAPI_API_KEYS` | SerpAPI 备用搜索 | 可选 |
| `NEWS_MAX_AGE_DAYS` | 新闻最大时效（天），搜索时限制结果在近期内 | 默认 `3` |
| `BIAS_THRESHOLD` | 乖离率阈值（%），超过提示不追高；强势趋势股自动放宽到 1.5 倍 | 默认 `5.0` |

### 数据源配置

| 变量名 | 说明 | 默认值 | 必填 |
|--------|------|--------|:----:|
| `TUSHARE_TOKEN` | Tushare Pro Token | - | 可选 |
| `ENABLE_REALTIME_QUOTE` | 启用实时行情（关闭后使用历史收盘价分析） | `true` | 可选 |
| `ENABLE_REALTIME_TECHNICAL_INDICATORS` | 盘中实时技术面：启用时用实时价计算 MA5/MA10/MA20 与多头排列（Issue #234）；关闭则用昨日收盘 | `true` | 可选 |
| `ENABLE_CHIP_DISTRIBUTION` | 启用筹码分布分析（该接口不稳定，云端部署建议关闭） | `true` | 可选 |
| `ENABLE_EASTMONEY_PATCH` | 东财接口补丁：东财接口频繁失败（如 RemoteDisconnected、连接被关闭）时建议设为 `true`，注入 NID 令牌与随机 User-Agent 以降低被限流概率 | `false` | 可选 |
| `REALTIME_SOURCE_PRIORITY` | 实时行情数据源优先级（逗号分隔），如 `tencent,akshare_sina,efinance,akshare_em` | 见 .env.example | 可选 |

### 其他配置

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `STOCK_LIST` | 自选股代码（逗号分隔） | - |
| `ADMIN_AUTH_ENABLED` | Web 登录：设为 `true` 启用密码保护；首次访问在网页设置初始密码，可在「系统设置 > 修改密码」修改；忘记密码执行 `python -m src.auth reset_password` | `false` |
| `TRUST_X_FORWARDED_FOR` | 反向代理部署时设为 `true`，从 `X-Forwarded-For` 获取真实 IP（限流等）；直连公网时保持 `false` 防伪造 | `false` |
| `MAX_WORKERS` | 并发线程数 | `3` |
| `MARKET_REVIEW_ENABLED` | 启用大盘复盘 | `true` |
| `MARKET_REVIEW_REGION` | 大盘复盘市场区域：cn(A股)、us(美股)、both(两者)，us 适合仅关注美股的用户 | `cn` |
| `TRADING_DAY_CHECK_ENABLED` | 交易日检查：默认 `true`，非交易日跳过执行；设为 `false` 或使用 `--force-run` 可强制执行（Issue #373） | `true` |
| `SCHEDULE_ENABLED` | 启用定时任务 | `false` |
| `SCHEDULE_TIME` | 定时执行时间 | `18:00` |
| `LOG_DIR` | 日志目录 | `./logs` |

---

## Docker 部署

Dockerfile 使用多阶段构建，前端会在构建镜像时自动打包并内置到 `static/`。
如需覆盖静态资源，可挂载本地 `static/` 到容器内 `/app/static`。

### 快速启动

```bash
# 1. 克隆仓库
git clone https://github.com/ZhuLinsen/daily_stock_analysis.git
cd daily_stock_analysis

# 2. 配置环境变量
cp .env.example .env
vim .env  # 填入 API Key 和配置

# 3. 启动容器
docker-compose -f ./docker/docker-compose.yml up -d server     # Web 服务模式（推荐，提供 API 与 WebUI）
docker-compose -f ./docker/docker-compose.yml up -d analyzer   # 定时任务模式
docker-compose -f ./docker/docker-compose.yml up -d            # 同时启动两种模式

# 4. 访问 WebUI
# http://localhost:8000

# 5. 查看日志
docker-compose -f ./docker/docker-compose.yml logs -f server
```

### 运行模式说明

| 命令 | 说明 | 端口 |
|------|------|------|
| `docker-compose -f ./docker/docker-compose.yml up -d server` | Web 服务模式，提供 API 与 WebUI | 8000 |
| `docker-compose -f ./docker/docker-compose.yml up -d analyzer` | 定时任务模式，每日自动执行 | - |
| `docker-compose -f ./docker/docker-compose.yml up -d` | 同时启动两种模式 | 8000 |

### Docker Compose 配置

`docker-compose.yml` 使用 YAML 锚点复用配置：

```yaml
version: '3.8'

x-common: &common
  build:
    context: ..
    dockerfile: docker/Dockerfile
  restart: unless-stopped
  env_file:
    - ../.env
  environment:
    - TZ=Asia/Shanghai
  volumes:
    - ../data:/app/data
    - ../logs:/app/logs
    - ../reports:/app/reports
    - ../.env:/app/.env

services:
  # 定时任务模式
  analyzer:
    <<: *common
    container_name: stock-analyzer

  # FastAPI 模式
  server:
    <<: *common
    container_name: stock-server
    command: ["python", "main.py", "--serve-only", "--host", "0.0.0.0", "--port", "8000"]
    ports:
      - "8000:8000"
```

### 常用命令

```bash
# 查看运行状态
docker-compose -f ./docker/docker-compose.yml ps

# 查看日志
docker-compose -f ./docker/docker-compose.yml logs -f server

# 停止服务
docker-compose -f ./docker/docker-compose.yml down

# 重建镜像（代码更新后）
docker-compose -f ./docker/docker-compose.yml build --no-cache
docker-compose -f ./docker/docker-compose.yml up -d server
```

### 手动构建镜像

```bash
docker build -f docker/Dockerfile -t stock-analysis .
docker run -d --env-file .env -p 8000:8000 -v ./data:/app/data stock-analysis python main.py --serve-only --host 0.0.0.0 --port 8000
```

---

## 本地运行详细配置

### 安装依赖

```bash
# Python 3.10+ 推荐
pip install -r requirements.txt

# 或使用 conda
conda create -n stock python=3.10
conda activate stock
pip install -r requirements.txt
```

### 命令行参数

```bash
python main.py                        # 完整分析（个股 + 大盘复盘）
python main.py --market-review        # 仅大盘复盘
python main.py --no-market-review     # 仅个股分析
python main.py --stocks 600519,300750 # 指定股票
python main.py --dry-run              # 仅获取数据，不 AI 分析
python main.py --no-notify            # 不发送推送
python main.py --schedule             # 定时任务模式
python main.py --force-run            # 非交易日也强制执行（Issue #373）
python main.py --debug                # 调试模式（详细日志）
python main.py --workers 5            # 指定并发数
```

---

## 定时任务配置

### GitHub Actions 定时

编辑 `.github/workflows/daily_analysis.yml`:

```yaml
schedule:
  # UTC 时间，北京时间 = UTC + 8
  - cron: '0 10 * * 1-5'   # 周一到周五 18:00（北京时间）
```

常用时间对照：

| 北京时间 | UTC cron 表达式 |
|---------|----------------|
| 09:30 | `'30 1 * * 1-5'` |
| 12:00 | `'0 4 * * 1-5'` |
| 15:00 | `'0 7 * * 1-5'` |
| 18:00 | `'0 10 * * 1-5'` |
| 21:00 | `'0 13 * * 1-5'` |

#### GitHub Actions 非交易日手动运行（Issue #461 / #466）

`daily_analysis.yml` 支持两种控制方式：

- `TRADING_DAY_CHECK_ENABLED`：仓库级配置（`Settings → Secrets and variables → Actions`），默认 `true`
- `workflow_dispatch.force_run`：手动触发时的单次开关，默认 `false`

推荐优先级理解：

| 配置组合 | 非交易日行为 |
|---------|-------------|
| `TRADING_DAY_CHECK_ENABLED=true` + `force_run=false` | 跳过执行（默认行为） |
| `TRADING_DAY_CHECK_ENABLED=true` + `force_run=true` | 本次强制执行 |
| `TRADING_DAY_CHECK_ENABLED=false` + `force_run=false` | 始终执行（定时和手动都不检查交易日） |
| `TRADING_DAY_CHECK_ENABLED=false` + `force_run=true` | 始终执行 |

手动触发步骤：

1. 打开 `Actions → 每日股票分析 → Run workflow`
2. 选择 `mode`（`full` / `market-only` / `stocks-only`）
3. 若当天是非交易日且希望仍执行，将 `force_run` 设为 `true`
4. 点击 `Run workflow`

### 本地定时任务

内建的定时任务调度器支持每天在指定时间（默认 18:00）运行分析。

#### 命令行方式

```bash
# 启动定时模式（启动时立即执行一次，随后每天 18:00 执行）
python main.py --schedule

# 启动定时模式（启动时不执行，仅等待下次定时触发）
python main.py --schedule --no-run-immediately
```

#### 环境变量方式

你也可以通过环境变量配置定时行为（适用于 Docker 或 .env）：

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|:-------:|:-----:|
| `SCHEDULE_ENABLED` | 是否启用定时任务 | `false` | `true` |
| `SCHEDULE_TIME` | 每日执行时间 (HH:MM) | `18:00` | `09:30` |
| `SCHEDULE_RUN_IMMEDIATELY` | 启动服务时是否立即运行一次 | `true` | `false` |
| `TRADING_DAY_CHECK_ENABLED` | 交易日检查：非交易日跳过执行；设为 `false` 可强制执行 | `true` | `false` |

例如在 Docker 中配置：

```bash
# 设置启动时不立即分析
docker run -e SCHEDULE_ENABLED=true -e SCHEDULE_RUN_IMMEDIATELY=false ...
```

#### 交易日判断（Issue #373）

默认根据自选股市场（A 股 / 港股 / 美股）和 `MARKET_REVIEW_REGION` 判断是否为交易日：
- 使用 `exchange-calendars` 区分 A 股 / 港股 / 美股各自的交易日历（含节假日）
- 混合持仓时，每只股票只在其市场开市日分析，休市股票当日跳过
- 全部相关市场均为非交易日时，整体跳过执行（不启动 pipeline、不发推送）
- 覆盖方式：`TRADING_DAY_CHECK_ENABLED=false` 或 命令行 `--force-run`

#### 使用 Crontab

如果不想使用常驻进程，也可以使用系统的 Cron：

```bash
crontab -e
# 添加：0 18 * * 1-5 cd /path/to/project && python main.py
```

---

## 通知渠道详细配置

### 企业微信

1. 在企业微信群聊中添加"群机器人"
2. 复制 Webhook URL
3. 设置 `WECHAT_WEBHOOK_URL`

### 飞书

1. 在飞书群聊中添加"自定义机器人"
2. 复制 Webhook URL
3. 设置 `FEISHU_WEBHOOK_URL`

### Telegram

1. 与 @BotFather 对话创建 Bot
2. 获取 Bot Token
3. 获取 Chat ID（可通过 @userinfobot）
4. 设置 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID`
5. (可选) 如需发送到 Topic，设置 `TELEGRAM_MESSAGE_THREAD_ID` (从 Topic 链接末尾获取)

### 邮件

1. 开启邮箱的 SMTP 服务
2. 获取授权码（非登录密码）
3. 设置 `EMAIL_SENDER`、`EMAIL_PASSWORD`、`EMAIL_RECEIVERS`

支持的邮箱：
- QQ 邮箱：smtp.qq.com:465
- 163 邮箱：smtp.163.com:465
- Gmail：smtp.gmail.com:587

**股票分组发往不同邮箱**（Issue #268，可选）：
配置 `STOCK_GROUP_N` 与 `EMAIL_GROUP_N` 可实现不同股票组的报告发送到不同邮箱，例如多人共享分析时互不干扰。大盘复盘会发往所有配置的邮箱。

```bash
STOCK_GROUP_1=600519,300750
EMAIL_GROUP_1=user1@example.com
STOCK_GROUP_2=002594,AAPL
EMAIL_GROUP_2=user2@example.com
```

### 自定义 Webhook

支持任意 POST JSON 的 Webhook，包括：
- 钉钉机器人
- Discord Webhook
- Slack Webhook
- Bark（iOS 推送）
- 自建服务

设置 `CUSTOM_WEBHOOK_URLS`，多个用逗号分隔。

### Discord

Discord 支持两种方式推送：

**方式一：Webhook（推荐，简单）**

1. 在 Discord 频道设置中创建 Webhook
2. 复制 Webhook URL
3. 配置环境变量：

```bash
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy
```

**方式二：Bot API（需要更多权限）**

1. 在 [Discord Developer Portal](https://discord.com/developers/applications) 创建应用
2. 创建 Bot 并获取 Token
3. 邀请 Bot 到服务器
4. 获取频道 ID（开发者模式下右键频道复制）
5. 配置环境变量：

```bash
DISCORD_BOT_TOKEN=your_bot_token
DISCORD_CHANNEL_ID=your_channel_id
```

### Pushover（iOS/Android 推送）

[Pushover](https://pushover.net/) 是一个跨平台的推送服务，支持 iOS 和 Android。

1. 注册 Pushover 账号并下载 App
2. 在 [Pushover Dashboard](https://pushover.net/) 获取 User Key
3. 创建 Application 获取 API Token
4. 配置环境变量：

```bash
PUSHOVER_USER_KEY=your_user_key
PUSHOVER_API_TOKEN=your_api_token
```

特点：
- 支持 iOS/Android 双平台
- 支持通知优先级和声音设置
- 免费额度足够个人使用（每月 10,000 条）
- 消息可保留 7 天

### Markdown 转图片（可选）

配置 `MARKDOWN_TO_IMAGE_CHANNELS` 可将报告以图片形式发送至不支持 Markdown 的渠道（telegram, wechat, custom, email）。

**依赖安装**：

1. **imgkit**：已包含在 `requirements.txt`，执行 `pip install -r requirements.txt` 时会自动安装
2. **wkhtmltopdf**：系统级依赖，需手动安装：
   - **macOS**：`brew install wkhtmltopdf`
   - **Debian/Ubuntu**：`apt install wkhtmltopdf`

未安装或安装失败时，将自动回退为 Markdown 文本发送。

---

## 数据源配置

系统默认使用 AkShare（免费），也支持其他数据源：

### AkShare（默认）
- 免费，无需配置
- 数据来源：东方财富爬虫

### Tushare Pro
- 需要注册获取 Token
- 更稳定，数据更全
- 设置 `TUSHARE_TOKEN`

### Baostock
- 免费，无需配置
- 作为备用数据源

### YFinance
- 免费，无需配置
- 支持美股/港股数据
- 美股历史数据与实时行情均统一使用 YFinance，以避免 akshare 美股复权异常导致的技术指标错误

### 东财接口频繁失败时的处理

若日志出现 `RemoteDisconnected`、`push2his.eastmoney.com` 连接被关闭等，多为东财限流。建议：

1. 在 `.env` 中设置 `ENABLE_EASTMONEY_PATCH=true`
2. 将 `MAX_WORKERS=1` 降低并发
3. 若已配置 Tushare，可优先使用 Tushare 数据源

---

## 高级功能

### 港股支持

使用 `hk` 前缀指定港股代码：

```bash
STOCK_LIST=600519,hk00700,hk01810
```

### ETF 与指数分析

针对指数跟踪型 ETF 和美股指数（如 VOO、QQQ、SPY、510050、SPX、DJI、IXIC），分析仅关注**指数走势、跟踪误差、市场流动性**，不纳入基金管理人/发行方的公司层面风险（诉讼、声誉、高管变动等）。风险警报与业绩预期均基于指数成分股整体表现，避免将基金公司新闻误判为标的本身利空。详见 Issue #274。

### 多模型切换

配置多个模型，系统自动切换：

```bash
# Gemini（主力）
GEMINI_API_KEY=xxx
GEMINI_MODEL=gemini-3-flash-preview

# OpenAI 兼容（备选）
OPENAI_API_KEY=xxx
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat
# 思考模式：deepseek-reasoner、deepseek-r1、qwq 等自动识别；deepseek-chat 系统按模型名自动启用
```

### LiteLLM 直接集成（多模型 + 多 Key 负载均衡）

本项目通过 [LiteLLM](https://github.com/BerriAI/litellm) 统一调用所有 LLM，无需单独启动 Proxy 服务。

**两层机制**：同一模型多 Key 轮换（Router）与跨模型降级（Fallback）分层独立，互不干扰。

**多 Key + 跨模型降级配置示例**：

```env
# 主模型：3 个 Gemini Key 轮换，任一 429 时 Router 自动切换下一个 Key
GEMINI_API_KEYS=key1,key2,key3
LITELLM_MODEL=gemini/gemini-3-flash-preview

# 跨模型降级：主模型全部 Key 均失败时，按序尝试 Claude → GPT
# 需配置对应 API Key：ANTHROPIC_API_KEY、OPENAI_API_KEY
LITELLM_FALLBACK_MODELS=anthropic/claude-3-5-sonnet-20241022,openai/gpt-4o-mini
```

**预期行为**：首次请求用 `key1`；若 429，Router 下次用 `key2`；若 3 个 Key 均不可用，则切换到 Claude，再失败则切换到 GPT。

> ⚠️ `LITELLM_MODEL` 必须包含 provider 前缀（如 `gemini/`、`anthropic/`、`openai/`），
> 否则系统无法识别应使用哪组 API Key。旧格式的 `GEMINI_MODEL`（无前缀）仅用于未配置 `LITELLM_MODEL` 时的自动推断。

**依赖说明**：`requirements.txt` 中保留 `openai>=1.0.0`，因 LiteLLM 内部依赖 OpenAI SDK 作为统一接口；显式保留可确保版本兼容性，用户无需单独配置。

**视觉模型（图片提取股票代码）**：

从图片提取股票代码（如 `/api/v1/stocks/extract-from-image`）使用 LiteLLM Vision，采用 OpenAI `image_url` 格式，支持 Gemini、Claude、OpenAI 等所有 Vision-capable 模型。

- **模型优先级**：`OPENAI_VISION_MODEL` > `LITELLM_MODEL` > 根据已有 API Key 推断
- **Gemini 3 限制**：Gemini 3 不支持 Vision，系统自动降级为 `gemini/gemini-2.0-flash`
- **主模型不支持 Vision 时**：若主模型为 DeepSeek 等非 Vision 模型，可显式配置 `OPENAI_VISION_MODEL=openai/gpt-4o` 或 `gemini/gemini-2.0-flash` 供图片提取使用

### 调试模式

```bash
python main.py --debug
```

日志文件位置：
- 常规日志：`logs/stock_analysis_YYYYMMDD.log`
- 调试日志：`logs/stock_analysis_debug_YYYYMMDD.log`

---

## 回测功能

回测模块自动对历史 AI 分析记录进行事后验证，评估分析建议的准确性。

### 工作原理

1. 选取已过冷却期（默认 14 天）的 `AnalysisHistory` 记录
2. 获取分析日之后的日线数据（前向 K 线）
3. 根据操作建议推断预期方向，与实际走势对比
4. 评估止盈/止损命中情况，模拟执行收益
5. 汇总为整体和单股两个维度的表现指标

### 操作建议映射

| 操作建议 | 仓位推断 | 预期方向 | 胜利条件 |
|---------|---------|---------|---------|
| 买入/加仓/strong buy | long | up | 涨幅 ≥ 中性带 |
| 卖出/减仓/strong sell | cash | down | 跌幅 ≥ 中性带 |
| 持有/hold | long | not_down | 未显著下跌 |
| 观望/等待/wait | cash | flat | 价格在中性带内 |

### 配置

在 `.env` 中设置以下变量（均有默认值，可选）：

| 变量 | 默认值 | 说明 |
|------|-------|------|
| `BACKTEST_ENABLED` | `true` | 是否在每日分析后自动运行回测 |
| `BACKTEST_EVAL_WINDOW_DAYS` | `10` | 评估窗口（交易日数） |
| `BACKTEST_MIN_AGE_DAYS` | `14` | 仅回测 N 天前的记录，避免数据不完整 |
| `BACKTEST_ENGINE_VERSION` | `v1` | 引擎版本号，升级逻辑时用于区分结果 |
| `BACKTEST_NEUTRAL_BAND_PCT` | `2.0` | 中性区间阈值（%），±2% 内视为震荡 |

### 自动运行

回测在每日分析流程完成后自动触发（非阻塞，失败不影响通知推送）。也可通过 API 手动触发。

### 评估指标

| 指标 | 说明 |
|------|------|
| `direction_accuracy_pct` | 方向预测准确率（预期方向与实际一致） |
| `win_rate_pct` | 胜率（胜 / (胜+负)，不含中性） |
| `avg_stock_return_pct` | 平均股票收益率 |
| `avg_simulated_return_pct` | 平均模拟执行收益率（含止盈止损退出） |
| `stop_loss_trigger_rate` | 止损触发率（仅统计配置了止损的记录） |
| `take_profit_trigger_rate` | 止盈触发率（仅统计配置了止盈的记录） |

---

## FastAPI API 服务

FastAPI 提供 RESTful API 服务，支持配置管理和触发分析。

### 启动方式

| 命令 | 说明 |
|------|------|
| `python main.py --serve` | 启动 API 服务 + 执行一次完整分析 |
| `python main.py --serve-only` | 仅启动 API 服务，手动触发分析 |

### 功能特性

- 📝 **配置管理** - 查看/修改自选股列表
- 🚀 **快速分析** - 通过 API 接口触发分析
- 📊 **实时进度** - 分析任务状态实时更新，支持多任务并行
- 📈 **回测验证** - 评估历史分析准确率，查询方向胜率与模拟收益
- 🔗 **API 文档** - 访问 `/docs` 查看 Swagger UI

### API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/analysis/analyze` | POST | 触发股票分析 |
| `/api/v1/analysis/tasks` | GET | 查询任务列表 |
| `/api/v1/analysis/status/{task_id}` | GET | 查询任务状态 |
| `/api/v1/history` | GET | 查询分析历史 |
| `/api/v1/backtest/run` | POST | 触发回测 |
| `/api/v1/backtest/results` | GET | 查询回测结果（分页） |
| `/api/v1/backtest/performance` | GET | 获取整体回测表现 |
| `/api/v1/backtest/performance/{code}` | GET | 获取单股回测表现 |
| `/api/v1/stocks/extract-from-image` | POST | 从图片提取股票代码（multipart，超时 60s） |
| `/api/health` | GET | 健康检查 |
| `/docs` | GET | API Swagger 文档 |

**调用示例**：
```bash
# 健康检查
curl http://127.0.0.1:8000/api/health

# 触发分析（A股）
curl -X POST http://127.0.0.1:8000/api/v1/analysis/analyze \
  -H 'Content-Type: application/json' \
  -d '{"stock_code": "600519"}'

# 查询任务状态
curl http://127.0.0.1:8000/api/v1/analysis/status/<task_id>

# 触发回测（全部股票）
curl -X POST http://127.0.0.1:8000/api/v1/backtest/run \
  -H 'Content-Type: application/json' \
  -d '{"force": false}'

# 触发回测（指定股票）
curl -X POST http://127.0.0.1:8000/api/v1/backtest/run \
  -H 'Content-Type: application/json' \
  -d '{"code": "600519", "force": false}'

# 查询整体回测表现
curl http://127.0.0.1:8000/api/v1/backtest/performance

# 查询单股回测表现
curl http://127.0.0.1:8000/api/v1/backtest/performance/600519

# 分页查询回测结果
curl "http://127.0.0.1:8000/api/v1/backtest/results?page=1&limit=20"
```

### 自定义配置

修改默认端口或允许局域网访问：

```bash
python main.py --serve-only --host 0.0.0.0 --port 8888
```

### 支持的股票代码格式

| 类型 | 格式 | 示例 |
|------|------|------|
| A股 | 6位数字 | `600519`、`000001`、`300750` |
| 港股 | hk + 5位数字 | `hk00700`、`hk09988` |
| 美股 | 1-5 字母（可选 .X 后缀） | `AAPL`、`TSLA`、`BRK.B` |
| 美股指数 | SPX/DJI/IXIC 等 | `SPX`、`DJI`、`NASDAQ`、`VIX` |

### 注意事项

- 浏览器访问：`http://127.0.0.1:8000`（或您配置的端口）
- 分析完成后自动推送通知到配置的渠道
- 此功能在 GitHub Actions 环境中会自动禁用

---

## 常见问题

### Q: 推送消息被截断？
A: 企业微信/飞书有消息长度限制，系统已自动分段发送。如需完整内容，可配置飞书云文档功能。

### Q: 数据获取失败？
A: AkShare 使用爬虫机制，可能被临时限流。系统已配置重试机制，一般等待几分钟后重试即可。

### Q: 如何添加自选股？
A: 修改 `STOCK_LIST` 环境变量，多个代码用逗号分隔。

### Q: GitHub Actions 没有执行？
A: 检查是否启用了 Actions，以及 cron 表达式是否正确（注意是 UTC 时间）。

---

更多问题请 [提交 Issue](https://github.com/ZhuLinsen/daily_stock_analysis/issues)
