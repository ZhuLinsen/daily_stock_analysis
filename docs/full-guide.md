# 📖 完整配置与部署指南

本文档包含 A股智能分析系统的完整配置说明，适合需要高级功能或特殊部署方式的用户。

> 💡 快速上手请参考 [README.md](../README.md)，本文档为进阶配置。

## 📁 项目结构

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
| `FEISHU_WEBHOOK_SECRET` | 飞书 Webhook 签名密钥（开启“签名校验”时必填） | 可选 |
| `FEISHU_WEBHOOK_KEYWORD` | 飞书 Webhook 关键词（开启“关键词”时必填） | 可选 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token（@BotFather 获取） | 可选 |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | 可选 |
| `TELEGRAM_MESSAGE_THREAD_ID` | Telegram Topic ID (用于发送到子话题) | 可选 |
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL（[创建方法](https://support.discord.com/hc/en-us/articles/228383668)） | 可选 |
| `DISCORD_BOT_TOKEN` | Discord Bot Token（与 Webhook 二选一） | 可选 |
| `DISCORD_MAIN_CHANNEL_ID` | Discord Channel ID（使用 Bot 时需要） | 可选 |
| `DISCORD_INTERACTIONS_PUBLIC_KEY` | Discord Public Key（仅入站 Interaction/Webhook 回调验签时需要） | 可选 |
| `SLACK_BOT_TOKEN` | Slack Bot Token（推荐，支持图片上传；同时配置时优先于 Webhook） | 可选 |
| `SLACK_CHANNEL_ID` | Slack Channel ID（使用 Bot 时需要） | 可选 |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL（仅文本，不支持图片） | 可选 |
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
>
> 当前默认 `daily_analysis.yml` 只显式映射固定 Secret / Variable 名称，不会自动把 `STOCK_GROUP_1`、`EMAIL_GROUP_1` 这类任意编号变量导入运行环境。所以分组邮箱功能目前不适用于仓库自带默认 GitHub Actions workflow；它适用于本地 `.env`、Docker，或你自行显式扩展过 `env:` 映射的运行环境。

#### 推送行为配置

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `SINGLE_STOCK_NOTIFY` | 单股推送模式：设为 `true` 则每分析完一只股票立即推送 | 可选 |
| `REPORT_TYPE` | 报告类型：`simple`(精简)、`full`(完整)、`brief`(3-5句概括)，Docker环境推荐设为 `full` | 可选 |
| `REPORT_LANGUAGE` | 报告输出语言：`zh`(默认中文) / `en`(英文)；会同步影响 Prompt、模板、通知 fallback 与 Web 报告页固定文案。仓库自带 `daily_analysis.yml` 已显式映射该变量，直接在 Actions Secrets/Variables 中配置即可生效 | 可选 |
| `REPORT_SUMMARY_ONLY` | 仅分析结果摘要：设为 `true` 时只推送汇总，不含个股详情；多股时适合快速浏览（默认 false，Issue #262） | 可选 |
| `REPORT_TEMPLATES_DIR` | Jinja2 模板目录（相对项目根，默认 `templates`） | 可选 |
| `REPORT_RENDERER_ENABLED` | 启用 Jinja2 模板渲染（默认 `false`，保证零回归） | 可选 |
| `REPORT_INTEGRITY_ENABLED` | 启用报告完整性校验，缺失必填字段时重试或占位补全（默认 `true`） | 可选 |
| `REPORT_INTEGRITY_RETRY` | 完整性校验重试次数（默认 `1`，`0` 表示仅占位不重试） | 可选 |
| `REPORT_HISTORY_COMPARE_N` | 历史信号对比条数，`0` 关闭（默认），`>0` 启用 | 可选 |
| `ANALYSIS_DELAY` | 个股分析和大盘分析之间的延迟（秒），避免API限流，如 `10` | 可选 |
| `MERGE_EMAIL_NOTIFICATION` | 个股与大盘复盘合并推送（默认 false），减少邮件数量、降低垃圾邮件风险；与 `SINGLE_STOCK_NOTIFY` 互斥（单股模式下合并不生效） | 可选 |
| `MARKDOWN_TO_IMAGE_CHANNELS` | 将 Markdown 转为图片发送的渠道（用逗号分隔）：telegram,wechat,custom,email,slack；单股推送需同时配置且安装转图工具 | 可选 |
| `MARKDOWN_TO_IMAGE_MAX_CHARS` | 超过此长度不转图片，避免超大图片（默认 15000） | 可选 |
| `MD2IMG_ENGINE` | 转图引擎：`wkhtmltoimage`（默认，需 wkhtmltopdf）或 `markdown-to-file`（emoji 更好，需 `npm i -g markdown-to-file`） | 可选 |
| `PREFETCH_REALTIME_QUOTES` | 设为 `false` 可禁用实时行情预取，避免 efinance/akshare_em 全市场拉取（默认 true） | 可选 |

#### 其他配置

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `STOCK_LIST` | 自选股代码，如 `600519,300750,002594` | ✅ |
| `TAVILY_API_KEYS` | [Tavily](https://tavily.com/) 搜索 API（新闻搜索） | 推荐 |
| `ANSPIRE_API_KEYS` | [Anspire AI Search](https://aisearch.anspire.cn/) 针对中文内容特别优化 (可有效增强A股分析效果) | 可选 |
| `MINIMAX_API_KEYS` | [MiniMax](https://platform.minimaxi.com/) Coding Plan Web Search（结构化搜索结果） | 可选 |
| `BOCHA_API_KEYS` | [博查搜索](https://open.bocha.cn/) Web Search API（中文搜索优化，支持AI摘要，多个key用逗号分隔） | 可选 |
| `BRAVE_API_KEYS` | [Brave Search](https://brave.com/search/api/) API（隐私优先，美股优化，多个key用逗号分隔） | 可选 |
| `SERPAPI_API_KEYS` | [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis) 备用搜索 | 可选 |
| `SEARXNG_BASE_URLS` | SearXNG 自建实例（无配额兜底，需在 settings.yml 启用 format: json）；留空时默认自动发现公共实例 | 可选 |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED` | 是否在 `SEARXNG_BASE_URLS` 为空时自动从 `searx.space` 获取公共实例（默认 `true`） | 可选 |
| `TUSHARE_TOKEN` | [Tushare Pro](https://tushare.pro/weborder/#/login?reg=834638 ) Token | 可选 |
| `LONGBRIDGE_APP_KEY` | [Longbridge OpenAPI](https://open.longbridge.com/) App Key（美股/港股量比、换手率、PE 兜底） | 可选 |
| `LONGBRIDGE_APP_SECRET` | Longbridge App Secret | 可选 |
| `LONGBRIDGE_ACCESS_TOKEN` | Longbridge Access Token | 可选 |
| `LONGBRIDGE_STATIC_INFO_TTL_SECONDS` | 长桥 `static_info` 进程内缓存秒数（默认 86400，0=不缓存） | 可选 |
| `LONGBRIDGE_HTTP_URL` | HTTP 接口地址（默认 `https://openapi.longbridge.com`） | 可选 |
| `LONGBRIDGE_QUOTE_WS_URL` | 行情 WebSocket 地址（默认 `wss://openapi-quote.longbridge.com/v2`） | 可选 |
| `LONGBRIDGE_TRADE_WS_URL` | 交易 WebSocket 地址（默认 `wss://openapi-trade.longbridge.com/v2`） | 可选 |
| `LONGBRIDGE_REGION` | 覆盖接入点；SDK 会按网络自动选择，默认 `hk`，若判断不正确可设置（如 `cn`、`hk`） | 可选 |
| `LONGBRIDGE_ENABLE_OVERNIGHT` | 是否开启夜盘行情 `true` / `false`，默认 `false` | 可选 |
| `LONGBRIDGE_PUSH_CANDLESTICK_MODE` | K 线推送模式：`realtime` 或 `confirmed`（默认 `realtime`） | 可选 |
| `LONGBRIDGE_PRINT_QUOTE_PACKAGES` | 连接时是否打印行情包（未设置时默认 `false`；设为 `1`/`true`/`yes` 开启） | 可选 |
| `ENABLE_CHIP_DISTRIBUTION` | 启用筹码分布（Actions 默认 false；需筹码数据时在 Variables 中设为 true，接口可能不稳定） | 可选 |

> **GitHub Actions：** 仓库自带 `daily_analysis.yml` 已把上表中的 `LONGBRIDGE_*` 映射到任务环境。若未在 **Settings → Secrets and variables → Actions** 中配置 `LONGBRIDGE_APP_KEY`、`LONGBRIDGE_APP_SECRET`、`LONGBRIDGE_ACCESS_TOKEN`，CI 内不会调用长桥（日志中一般看不到 `[Longbridge]` 相关行情行）。可选接入点变量（如 `LONGBRIDGE_REGION`）可放在 **Variables** 或 **Secrets**。

> 补充说明
- TUSHARE_TOKEN，当此参数配置后，但不具备港股日线接口权限时，也会出现港股数据查询不出来或者错误的情况，和老版本提示不支持港股效果相同

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

> 完整说明见 [LLM 配置指南](LLM_CONFIG_GUIDE.md)（三层配置、渠道模式、Vision、Agent、排错）。

| 变量名 | 说明 | 默认值 | 必填 |
|--------|------|--------|:----:|
| `LITELLM_MODEL` | 主模型，格式 `provider/model`（如 `gemini/gemini-2.5-flash`），推荐优先使用 | - | 否 |
| `AGENT_LITELLM_MODEL` | Agent 主模型（可选）；留空继承主模型，无 provider 前缀按 `openai/<model>` 解析 | - | 否 |
| `LITELLM_FALLBACK_MODELS` | 备选模型，逗号分隔 | - | 否 |
| `LLM_CHANNELS` | 渠道名称列表（逗号分隔），配合 `LLM_{NAME}_*` 使用，详见 [LLM 配置指南](LLM_CONFIG_GUIDE.md) | - | 否 |
| `LITELLM_CONFIG` | 高级模型路由 YAML 配置文件路径（高级） | - | 否 |
| `AIHUBMIX_KEY` | [AIHubmix](https://aihubmix.com/?aff=CfMq) API Key，一 Key 切换使用全系模型，无需额外配置 Base URL | - | 可选 |
| `GEMINI_API_KEY` | Google Gemini API Key | - | 可选 |
| `GEMINI_MODEL` | 主模型名称（legacy，`LITELLM_MODEL` 优先） | `gemini-3-flash-preview` | 否 |
| `GEMINI_MODEL_FALLBACK` | 备选模型（legacy） | `gemini-2.5-flash` | 否 |
| `OPENAI_API_KEY` | OpenAI 兼容 API Key | - | 可选 |
| `OPENAI_BASE_URL` | OpenAI 兼容 API 地址 | - | 可选 |
| `OLLAMA_API_BASE` | Ollama 本地服务地址（如 `http://localhost:11434`），详见 [LLM 配置指南](LLM_CONFIG_GUIDE.md) | - | 可选 |
| `OPENAI_MODEL` | OpenAI 模型名称（legacy，AIHubmix 用户可填如 `gemini-3.1-pro-preview`、`gpt-5.2`） | `gpt-5.2` | 可选 |
| `ANTHROPIC_API_KEY` | Anthropic Claude API Key | - | 可选 |
| `ANTHROPIC_MODEL` | Claude 模型名称 | `claude-3-5-sonnet-20241022` | 可选 |
| `ANTHROPIC_TEMPERATURE` | Claude 温度参数（0.0-1.0） | `0.7` | 可选 |
| `ANTHROPIC_MAX_TOKENS` | Claude 响应最大 token 数 | `8192` | 可选 |

> *注：`AIHUBMIX_KEY`、`GEMINI_API_KEY`、`ANTHROPIC_API_KEY`、`OPENAI_API_KEY` 或 `OLLAMA_API_BASE` 至少配置一个。`AIHUBMIX_KEY` 无需配置 `OPENAI_BASE_URL`，系统自动适配。

### 通知渠道配置

| 变量名 | 说明 | 必填 |
|--------|------|:----:|
| `WECHAT_WEBHOOK_URL` | 企业微信机器人 Webhook URL | 可选 |
| `FEISHU_WEBHOOK_URL` | 飞书机器人 Webhook URL | 可选 |
| `FEISHU_WEBHOOK_SECRET` | 飞书机器人签名密钥（仅在机器人安全设置启用“签名校验”时填写） | 可选 |
| `FEISHU_WEBHOOK_KEYWORD` | 飞书机器人关键词（仅在机器人安全设置启用“关键词”时填写） | 可选 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | 可选 |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | 可选 |
| `TELEGRAM_MESSAGE_THREAD_ID` | Telegram Topic ID | 可选 |
| `DISCORD_WEBHOOK_URL` | Discord Webhook URL | 可选 |
| `DISCORD_BOT_TOKEN` | Discord Bot Token（与 Webhook 二选一） | 可选 |
| `DISCORD_MAIN_CHANNEL_ID` | Discord Channel ID（使用 Bot 时需要） | 可选 |
| `DISCORD_INTERACTIONS_PUBLIC_KEY` | Discord Public Key（仅入站 Interaction/Webhook 回调验签时需要） | 可选 |
| `DISCORD_MAX_WORDS` | Discord 最大字数限制（默认 免费服务器限制2000） | 可选 |
| `SLACK_BOT_TOKEN` | Slack Bot Token（推荐，支持图片上传；同时配置时优先于 Webhook） | 可选 |
| `SLACK_CHANNEL_ID` | Slack Channel ID（使用 Bot 时需要） | 可选 |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL（仅文本，不支持图片） | 可选 |
| `EMAIL_SENDER` | 发件人邮箱 | 可选 |
| `EMAIL_PASSWORD` | 邮箱授权码（非登录密码） | 可选 |
| `EMAIL_RECEIVERS` | 收件人邮箱（逗号分隔，留空发给自己） | 可选 |
| `EMAIL_SENDER_NAME` | 发件人显示名称 | 可选 |
| `STOCK_GROUP_N` / `EMAIL_GROUP_N` | 邮件分组路由（Issue #268）：`STOCK_GROUP_N` 应为 `STOCK_LIST` 子集，仅影响邮件收件人，不改变分析范围或其他通知渠道 | 可选 |
| `CUSTOM_WEBHOOK_URLS` | 自定义 Webhook（逗号分隔） | 可选 |
| `CUSTOM_WEBHOOK_BEARER_TOKEN` | 自定义 Webhook Bearer Token | 可选 |
| `WEBHOOK_VERIFY_SSL` | Webhook HTTPS 证书校验（默认 true）。设为 false 可支持自签名。警告：关闭有严重安全风险 | 可选 |
| `PUSHOVER_USER_KEY` | Pushover 用户 Key | 可选 |
| `PUSHOVER_API_TOKEN` | Pushover API Token | 可选 |
| `PUSHPLUS_TOKEN` | PushPlus Token（国内推送服务） | 可选 |
| `SERVERCHAN3_SENDKEY` | Server酱³ Sendkey | 可选 |

> 说明：默认 `daily_analysis` GitHub Actions workflow 只映射固定变量名，不会自动导入任意编号的 `STOCK_GROUP_N` / `EMAIL_GROUP_N`。因此分组邮箱目前仅在本地 `.env`、Docker 或其他已显式注入这些环境变量的运行环境中生效；若你要在自己的 GitHub Actions 中使用，需在 workflow 的 job `env:` 中逐组显式映射。

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
>
> 说明：`FEISHU_APP_ID` / `FEISHU_APP_SECRET` 用于飞书应用、云文档或 Stream Bot 模式，不会直接启用群 Webhook 推送。只想收通知时，请优先配置 `FEISHU_WEBHOOK_URL`。

### 搜索服务配置

| 变量名 | 说明 | 必填 |
|--------|------|:----:|
| `TAVILY_API_KEYS` | Tavily 搜索 API Key（推荐） | 推荐 |
| `ANSPIRE_API_KEYS` | Anspire 搜索 API Key（可有效增强A股分析效果） | 可选 | 
| `MINIMAX_API_KEYS` | MiniMax Coding Plan Web Search（结构化搜索结果） | 可选 |
| `BOCHA_API_KEYS` | 博查搜索 API Key（中文优化） | 可选 |
| `BRAVE_API_KEYS` | Brave Search API Key（美股优化） | 可选 |
| `SERPAPI_API_KEYS` | SerpAPI 备用搜索 | 可选 |
| `SOCIAL_SENTIMENT_API_KEY` | Stock Sentiment API Key（Reddit / X / Polymarket，可选） | 可选 |
| `SOCIAL_SENTIMENT_API_URL` | Stock Sentiment API 地址（默认 `https://api.adanos.org`） | 可选 |
| `SEARXNG_BASE_URLS` | SearXNG 自建实例（无配额兜底，需在 settings.yml 启用 format: json）；留空时默认自动发现公共实例 | 可选 |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED` | 是否在 `SEARXNG_BASE_URLS` 为空时自动从 `searx.space` 获取公共实例（默认 `true`） | 可选 |
| `NEWS_STRATEGY_PROFILE` | 新闻策略窗口档位：`ultra_short`(1天)/`short`(3天)/`medium`(7天)/`long`(30天)；实际窗口取与 `NEWS_MAX_AGE_DAYS` 的最小值 | 默认 `short` |
| `NEWS_MAX_AGE_DAYS` | 新闻最大时效（天），搜索时限制结果在近期内 | 默认 `3` |
| `BIAS_THRESHOLD` | 乖离率阈值（%），超过提示不追高；强势趋势股自动放宽到 1.5 倍 | 默认 `5.0` |

> 行为说明：搜索服务与社交舆情服务为可选增强链路。任一服务初始化失败时，系统会记录 warning 并降级为跳过该服务，仅影响对应环节，不会阻塞技术面主链路和主任务流。

### 数据源配置

| 变量名 | 说明 | 默认值 | 必填 |
|--------|------|--------|:----:|
| `TUSHARE_TOKEN` | Tushare Pro Token | - | 可选 |
| `TICKFLOW_API_KEY` | TickFlow API Key；配置后 A 股大盘复盘指数优先尝试 TickFlow，若套餐支持标的池查询则市场统计也会优先尝试 TickFlow | - | 可选 |
| `LONGBRIDGE_APP_KEY` | [Longbridge OpenAPI](https://open.longbridge.com/) App Key；配置后美股/港股的量比、换手率、PE 等 YFinance 缺失字段会自动从长桥补充 | - | 可选 |
| `LONGBRIDGE_APP_SECRET` | Longbridge App Secret | - | 可选 |
| `LONGBRIDGE_ACCESS_TOKEN` | Longbridge Access Token | - | 可选 |
| `LONGBRIDGE_*`（可选） | 见官方 [环境变量](https://open.longbridge.com/zh-CN/docs/getting-started#环境变量)；另有 `LONGBRIDGE_STATIC_INFO_TTL_SECONDS` | - | 可选 |
| `ENABLE_REALTIME_QUOTE` | 启用实时行情（关闭后使用历史收盘价分析） | `true` | 可选 |
| `ENABLE_REALTIME_TECHNICAL_INDICATORS` | 盘中实时技术面：启用时用实时价计算 MA5/MA10/MA20 与多头排列（Issue #234）；关闭则用昨日收盘 | `true` | 可选 |
| `ENABLE_CHIP_DISTRIBUTION` | 启用筹码分布分析（该接口不稳定，云端部署建议关闭）。GitHub Actions 用户需在 Repository Variables 中设置 `ENABLE_CHIP_DISTRIBUTION=true` 方可启用；workflow 默认关闭。 | `true` | 可选 |
| `ENABLE_EASTMONEY_PATCH` | 东财接口补丁：东财接口频繁失败（如 RemoteDisconnected、连接被关闭）时建议设为 `true`，注入 NID 令牌与随机 User-Agent 以降低被限流概率 | `false` | 可选 |
| `REALTIME_SOURCE_PRIORITY` | 实时行情数据源优先级（逗号分隔），如 `tencent,akshare_sina,efinance,akshare_em` | 见 .env.example | 可选 |
| `ENABLE_FUNDAMENTAL_PIPELINE` | 基本面聚合总开关；关闭时仅返回 `not_supported` 块，不改变原分析链路 | `true` | 可选 |
| `FUNDAMENTAL_STAGE_TIMEOUT_SECONDS` | 基本面阶段总时延预算（秒） | `1.5` | 可选 |
| `FUNDAMENTAL_FETCH_TIMEOUT_SECONDS` | 单能力源调用超时（秒） | `0.8` | 可选 |
| `FUNDAMENTAL_RETRY_MAX` | 基本面能力重试次数（含首次） | `1` | 可选 |
| `FUNDAMENTAL_CACHE_TTL_SECONDS` | 基本面聚合缓存 TTL（秒），短缓存减轻重复拉取 | `120` | 可选 |
| `FUNDAMENTAL_CACHE_MAX_ENTRIES` | 基本面缓存最大条目数（TTL 内按时间淘汰） | `256` | 可选 |

> 行为说明：
> - A 股：按 `valuation/growth/earnings/institution/capital_flow/dragon_tiger/boards` 聚合能力返回；
> - ETF：返回可得项，缺失能力标记为 `not_supported`，整体不影响原流程；
> - 美股/港股：返回 `not_supported` 兜底块；
> - 任何异常走 fail-open，仅记录错误，不影响技术面/新闻/筹码主链路。
> - 配置 `TICKFLOW_API_KEY` 后，仅 A 股大盘复盘会额外优先尝试 TickFlow 的主要指数行情；若当前套餐支持标的池查询，市场涨跌统计也会优先尝试 TickFlow。个股链路和实时行情优先级不变。
> - TickFlow 能力按套餐权限分层：有限权限套餐仍可使用主指数查询；支持 `CN_Equity_A` 标的池查询的套餐才会启用 TickFlow 市场统计。
> - 官方 quickstart 已文档化 `quotes.get(universes=["CN_Equity_A"])`，但线上 smoke test 进一步确认：`TICKFLOW_API_KEY` 不等于一定具备该权限，且 `quotes.get(symbols=[...])` 单次存在标的数量限制。
> - TickFlow 实际返回的 `change_pct` / `amplitude` 为比例值；系统已在接入层统一转换为百分比值，确保与现有数据源字段语义一致。
> - 字段契约：
>   - `fundamental_context.belong_boards` = 个股关联板块列表（当前仅 A 股写入；无数据时为 `[]`）；
>   - `fundamental_context.boards.data` = `sector_rankings`（板块涨跌榜，结构 `{top, bottom}`）；
>   - `fundamental_context.earnings.data.financial_report` = 财报摘要（报告期、营收、归母净利润、经营现金流、ROE）；
>   - `fundamental_context.earnings.data.dividend` = 分红指标（仅现金分红税前口径，含 `events`、`ttm_cash_dividend_per_share`、`ttm_dividend_yield_pct`）；
>   - `get_stock_info.belong_boards` = 个股所属板块列表；
>   - `get_stock_info.boards` 为兼容别名，值与 `belong_boards` 相同（未来仅在大版本考虑移除）；
>   - `get_stock_info.sector_rankings` 与 `fundamental_context.boards.data` 保持一致。
>   - `AnalysisReport.details.belong_boards` = 结构化报告详情中的关联板块列表；
>   - `AnalysisReport.details.sector_rankings` = 结构化报告详情中的板块涨跌榜（用于前端板块联动展示）。
> - 板块涨跌榜使用数据源顺序：与全局 priority 一致。
> - 超时控制为 `best-effort` 软超时：阶段会按预算快速降级继续执行，但不保证硬中断底层三方调用。
> - `FUNDAMENTAL_STAGE_TIMEOUT_SECONDS=1.5` 表示新增基本面阶段的目标预算，不是严格硬 SLA。
> - 若要硬 SLA，请在后续版本升级为子进程隔离执行并在超时后强制终止。

### 其他配置

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `STOCK_LIST` | 自选股代码（逗号分隔） | - |
| `ADMIN_AUTH_ENABLED` | Web 登录：设为 `true` 启用密码保护；首次访问在网页设置初始密码，可在「系统设置 > 修改密码」修改；忘记密码执行 `python -m src.auth reset_password` | `false` |
| `TRUST_X_FORWARDED_FOR` | 单层可信反向代理部署时设为 `true`，取 `X-Forwarded-For` 最右值作为真实客户端 IP（用于登录限流等）；直连公网时保持 `false` 防伪造。多级代理/CDN 场景下限流 key 可能退化为边缘代理 IP，需额外评估 | `false` |
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
运行中的 `server` 容器默认直接复用 `/app/static` 里的预构建产物，不要求容器内保留 `apps/dsa-web` 源码目录或运行时安装 `npm`；若 WebUI 无法打开，请优先确认 `/app/static/index.html` 是否存在。

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

**智能导入依赖**：`pypinyin`（名称→代码拼音匹配）和 `openpyxl`（Excel .xlsx 解析）已包含在 `requirements.txt` 中，执行上述 `pip install -r requirements.txt` 时会自动安装。若使用智能导入（图片/CSV/Excel/剪贴板）功能，请确保依赖已正确安装；缺失时可能报 `ModuleNotFoundError`。

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

> 说明：定时模式每次触发前都会重新读取当前保存的 `STOCK_LIST`。如果同时传入 `--stocks`，该参数不会锁定后续计划执行的股票列表；需要临时只跑指定股票时，请使用非定时的单次运行命令。
>
> 从 `python main.py --schedule`、`python main.py --serve --schedule` 或等价内置调度模式启动后，WebUI 保存新的 `SCHEDULE_TIME` 会在下一轮调度检查内自动重绑 daily job，无需重启进程；旧的执行时间不会继续保留。

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
- 断点续传和 `--dry-run` 的“数据已存在”判断共用同一套“最新可复用交易日”解析逻辑，不再直接使用服务器自然日
- `最新可复用交易日` 会按股票所属市场的本地时区解析：A 股使用 `Asia/Shanghai`，港股使用 `Asia/Hong_Kong`，美股使用 `America/New_York`
- 非交易日（周末 / 节假日）运行时，会回退到最近一个交易日检查本地数据；若该交易日数据已存在，则跳过重复抓取，否则继续补数
- 交易日盘中或收盘前运行时，会以上一个已完成交易日作为复用目标；交易日收盘后运行时，当日数据已存在则可直接跳过，不存在则继续抓取
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

> ⚠️ **关键区分**：`FEISHU_WEBHOOK_SECRET`（Webhook 签名密钥）和 `FEISHU_APP_SECRET`（飞书应用 Secret）是两个完全不同的配置，不能互换。

**最小可用配置（无安全限制）：**

```env
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/your_hook_token
```

**完整步骤：**

1. **在飞书群聊中创建自定义机器人**：
   - 打开目标群聊 → 右上角「群设置」→「群机器人」→「添加机器人」→「自定义机器人」
   - 填写机器人名称，复制生成的 **Webhook URL**（格式：`https://open.feishu.cn/open-apis/bot/v2/hook/...`）
2. 设置 `FEISHU_WEBHOOK_URL`（即上一步复制的 URL）。
3. 查看机器人**安全设置**，根据启用的安全项决定是否需要补充配置：
   - **无额外安全设置**：仅填 `FEISHU_WEBHOOK_URL` 即可。
   - **开启了「签名校验」**：把飞书显示的 secret 填到 `FEISHU_WEBHOOK_SECRET`。两端必须同时启用或同时不填，否则飞书返回签名校验失败。
   - **开启了「关键词」**：把同一个关键词填到 `FEISHU_WEBHOOK_KEYWORD`；系统会自动在每条消息前补上，无需手动修改报告模板。
   - **开启了 IP 白名单**：确保当前运行环境的出口 IP 在白名单中（本地/Docker/GitHub Actions 出口 IP 各不相同）。
4. `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 是飞书应用 / Stream Bot / 云文档模式专用，不会触发群 Webhook 推送，不要用它们替代 `FEISHU_WEBHOOK_URL`。

**常见失败原因：**
- 只填了 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`，没有配置 `FEISHU_WEBHOOK_URL`
- 飞书机器人开启了「签名校验」，但 `FEISHU_WEBHOOK_SECRET` 未配置（或误填为 `FEISHU_APP_SECRET`）
- 飞书机器人开启了「关键词」，但本地没有同步配置 `FEISHU_WEBHOOK_KEYWORD`
- 机器人没有被加入目标群，或群管理员限制了机器人发言
- 飞书侧额外配置了 IP 白名单，但当前运行环境 IP 不在白名单中
- 消息内容超长：飞书单条消息有长度限制，系统会自动分段发送；如需在一个文档内查看完整内容，可配置飞书云文档功能（`FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_FOLDER_TOKEN`）

更完整的图文排查请看 [docs/bot/feishu-bot-config.md](bot/feishu-bot-config.md)。
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
配置 `STOCK_GROUP_N` 与 `EMAIL_GROUP_N` 可实现不同股票组的报告发送到不同邮箱，例如多人共享分析时互不干扰。`STOCK_LIST` 仍决定本次实际分析的股票集合，`STOCK_GROUP_N` 应写成 `STOCK_LIST` 的子集；它只影响邮件收件人，不会改变 Telegram、企业微信、Webhook 等其他渠道收到的完整报告。大盘复盘会发往所有配置的邮箱。

> GitHub Actions 限制：截至 2026-03-29，仓库自带 `daily_analysis.yml` 不会自动导入任意编号的 `STOCK_GROUP_N` / `EMAIL_GROUP_N`。因此如果你只在仓库 Secrets / Variables 中新增这些变量，而没有修改 workflow 显式映射，它们不会进入运行进程，看起来就像“分组配置不生效”。

```bash
STOCK_LIST=600519,300750,002594,AAPL
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
DISCORD_MAIN_CHANNEL_ID=your_channel_id
```

如果你要接收 Discord Slash Command / Interaction 回调，而不仅是向 Discord 推送消息，还需要在 Discord Developer Portal 的 `General Information -> Public Key` 复制公钥并配置：

```bash
DISCORD_INTERACTIONS_PUBLIC_KEY=your_public_key
```

未配置该公钥时，系统会拒绝所有 Discord 入站 webhook 请求。

### Slack

Slack 支持两种方式推送，同时配置时优先使用 Bot API，确保文本与图片发送到同一频道：

**方式一：Bot API（推荐，支持图片上传）**

1. 创建 Slack App：https://api.slack.com/apps → Create New App
2. 添加 Bot Token Scopes：`chat:write`、`files:write`
3. 安装到工作区并获取 Bot Token (xoxb-...)
4. 获取频道 ID：频道详情 → 底部复制频道 ID
5. 配置环境变量：

```bash
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL_ID=C01234567
```

**方式二：Incoming Webhook（配置简单，仅文本）**

1. 在 Slack App 管理页面创建 Incoming Webhook
2. 复制 Webhook URL
3. 配置环境变量：

```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../xxx
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

配置 `MARKDOWN_TO_IMAGE_CHANNELS` 可将报告以图片形式发送至不支持 Markdown 的渠道（telegram, wechat, custom, email, slack）。

**依赖安装**：

1. **imgkit**：已包含在 `requirements.txt`，执行 `pip install -r requirements.txt` 时会自动安装
2. **wkhtmltopdf**（默认引擎）：系统级依赖，需手动安装：
   - **macOS**：`brew install wkhtmltopdf`
   - **Debian/Ubuntu**：`apt install wkhtmltopdf`
3. **markdown-to-file**（可选，emoji 支持更好）：`npm i -g markdown-to-file`，并设置 `MD2IMG_ENGINE=markdown-to-file`

未安装或安装失败时，将自动回退为 Markdown 文本发送。

**单股推送 + 图片发送**（Issue #455）：

单股推送模式（`SINGLE_STOCK_NOTIFY=true`）下，若希望 Telegram 等渠道以图片形式推送，需同时配置 `MARKDOWN_TO_IMAGE_CHANNELS=telegram` 并安装转图工具（wkhtmltopdf 或 markdown-to-file）。个股日报汇总同样支持转图，无需额外配置。

**故障排查**：若日志出现「Markdown 转图片失败，将回退为文本发送」，请检查 `MARKDOWN_TO_IMAGE_CHANNELS` 配置及转图工具是否已正确安装（`which wkhtmltoimage` 或 `which m2f`）。

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

### Longbridge（长桥）
- 美股/港股数据兜底，补充 YFinance 缺失的量比、换手率、PE 等字段
- 需从 [open.longbridge.com](https://open.longbridge.com/) 注册并获取 App Key / App Secret / Access Token
- 设置 `LONGBRIDGE_APP_KEY`、`LONGBRIDGE_APP_SECRET`、`LONGBRIDGE_ACCESS_TOKEN`
- 接入点可配 `LONGBRIDGE_HTTP_URL`、`LONGBRIDGE_QUOTE_WS_URL`、`LONGBRIDGE_TRADE_WS_URL`、`LONGBRIDGE_REGION`
- 其余可选参数见官方 [环境变量说明](https://open.longbridge.com/zh-CN/docs/getting-started#环境变量)
- 仅在 YFinance（美股）或 AkShare（港股）返回数据不完整时自动触发，不影响 A 股链路

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

### 高级模型路由（底层由 LiteLLM 驱动）

详见 [LLM 配置指南](LLM_CONFIG_GUIDE.md)。默认使用时你只需要理解主模型、备选模型和模型渠道；如果进入这一节，说明你要直接使用底层 [LiteLLM](https://github.com/BerriAI/litellm) 路由能力，无需单独启动 Proxy 服务。

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

**视觉模型（图片提取股票代码）**：详见 [LLM 配置指南 - Vision](LLM_CONFIG_GUIDE.md#41-vision-模型图片识别股票代码)。

从图片提取股票代码（如 `/api/v1/stocks/extract-from-image`）使用统一视觉模型接入，底层采用 LiteLLM Vision 与 OpenAI `image_url` 格式，支持 Gemini、Claude、OpenAI、DeepSeek 等 Vision-capable 模型。返回 `items`（code、name、confidence）及兼容的 `codes` 数组。

> 兼容性说明：`/api/v1/stocks/extract-from-image` 响应在原 `codes` 基础上新增 `items` 字段。若下游客户端使用严格 JSON Schema 且不接受未知字段，请同步更新 schema。

**智能导入**：除图片外，还支持 CSV/Excel 文件及剪贴板粘贴（`/api/v1/stocks/parse-import`），自动解析代码/名称列，名称→代码解析支持本地映射、拼音匹配及 AkShare 在线 fallback。依赖 `pypinyin`（拼音匹配）和 `openpyxl`（Excel 解析），已包含在 `requirements.txt` 中。

- **AkShare 名称解析缓存**：名称→代码解析使用 AkShare 在线 fallback 时，结果缓存 1 小时（TTL），避免频繁请求；首次调用或缓存过期后会自动刷新。
- **CSV/Excel 列名**：支持 `code`、`股票代码`、`代码`、`name`、`股票名称`、`名称` 等（不区分大小写）；无表头时默认第 1 列为代码、第 2 列为名称。
- **常见解析失败**：文件过大（>2MB）、编码非 UTF-8/GBK、Excel 工作表为空或损坏、CSV 分隔符/列数不一致时，API 会返回具体错误提示。

- **模型优先级**：`VISION_MODEL` > `LITELLM_MODEL` > 根据已有 API Key 推断（`OPENAI_VISION_MODEL` 已废弃，请改用 `VISION_MODEL`）
- **Provider 回退**：主模型失败时，按 `VISION_PROVIDER_PRIORITY`（默认 `gemini,anthropic,openai`）自动切换到下一个可用 provider
- **主模型不支持 Vision 时**：若主模型为 DeepSeek 等非 Vision 模型，可显式配置 `VISION_MODEL=openai/gpt-4o` 或 `gemini/gemini-2.0-flash` 供图片提取使用
- **配置校验**：若配置了 `VISION_MODEL` 但未配置对应 provider 的 API Key，启动时会输出 warning，图片提取功能将不可用

### 调试模式

```bash
python main.py --debug
```

日志文件位置：
- 常规日志：`logs/stock_analysis_YYYYMMDD.log`
- 调试日志：`logs/stock_analysis_debug_YYYYMMDD.log`

### SQLite 写入稳态配置

默认文件型 SQLite 会在连接建立时启用 `WAL` 并设置 `busy_timeout`，`save_daily_data()` 也已改为按 `(code, date)` 批量原子 upsert，以降低批量更新和并发回写时的锁竞争。

如需调整，可在 `.env` 中设置：

| 变量 | 默认值 | 说明 |
|------|-------|------|
| `SQLITE_WAL_ENABLED` | `true` | 文件型 SQLite 是否启用 `journal_mode=WAL` |
| `SQLITE_BUSY_TIMEOUT_MS` | `5000` | SQLite 等锁超时（毫秒） |
| `SQLITE_WRITE_RETRY_MAX` | `3` | 遇到 `database is locked` / `database table is locked` 时的最大重试次数 |
| `SQLITE_WRITE_RETRY_BASE_DELAY` | `0.1` | 写入重试基础退避时间（秒，按指数退避递增） |

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
- 📊 **实时进度** - 分析任务状态实时更新，支持多任务并行；普通分析链路在进入 LLM 阶段后会优先尝试 LiteLLM 流式生成，并通过任务 SSE 回灌更细粒度的 `message/progress`
- 📈 **回测验证** - 评估历史分析准确率，查询方向胜率与模拟收益
- 🔗 **API 文档** - 访问 `/docs` 查看 Swagger UI

### API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/analysis/analyze` | POST | 触发股票分析 |
| `/api/v1/analysis/tasks` | GET | 查询任务列表 |
| `/api/v1/analysis/tasks/stream` | GET (SSE) | 订阅任务实时状态流 |
| `/api/v1/analysis/status/{task_id}` | GET | 查询任务状态 |
| `/api/v1/history` | GET | 查询分析历史 |
| `/api/v1/backtest/run` | POST | 触发回测 |
| `/api/v1/backtest/results` | GET | 查询回测结果（分页） |
| `/api/v1/backtest/performance` | GET | 获取整体回测表现 |
| `/api/v1/backtest/performance/{code}` | GET | 获取单股回测表现 |
| `/api/v1/stocks/extract-from-image` | POST | 从图片提取股票代码（multipart，超时 60s） |
| `/api/v1/stocks/parse-import` | POST | 解析 CSV/Excel/剪贴板（multipart file 或 JSON `{"text":"..."}`，文件≤2MB，文本≤100KB） |
| `/api/health` | GET | 健康检查 |
| `/docs` | GET | API Swagger 文档 |

> 说明：`POST /api/v1/analysis/analyze` 在 `async_mode=false` 时仅支持单只股票；批量 `stock_codes` 需使用 `async_mode=true`。异步 `202` 响应对单股返回 `task_id`，对批量返回 `accepted` / `duplicates` 汇总结构。

> 进度流说明：`GET /api/v1/analysis/tasks/stream` 除 `task_created / task_started / task_completed / task_failed` 外，新增 `task_progress` 事件。普通分析链路会在“行情准备 / 新闻检索 / 上下文整理 / LLM 生成 / 报告保存”等阶段持续更新 `progress` 与 `message`。LiteLLM 流式返回仅在服务端累积完整文本，最终 JSON 解析成功后才会持久化历史报告；若流式在首个 chunk 前不可用，会自动回退到原非流式调用；若已产生部分 chunk 后失败，系统先尝试同模型非流式重试，失败后再按既有主模型->备用模型顺序继续尝试。  
> 如果任务进度回调异常，主链路不会中断，系统会提升告警为 warning 级别并在服务端日志中输出完整异常，便于排查 SSE 推送断点。
>  
> 说明：该特性属于运行时 SSE 与回退链路细节，优先记录于完整指南（`full-guide*.md`），不在 `README.md` 中展开详细行为分支。

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
| 北交所 | 8/4/92 开头 6 位 | `920748`、`838163`、`430047` |
| 港股 | hk + 5位数字 | `hk00700`、`hk09988` |
| 美股 | 1-5 字母（可选 .X 后缀） | `AAPL`、`TSLA`、`BRK.B` |
| 美股指数 | SPX/DJI/IXIC 等 | `SPX`、`DJI`、`NASDAQ`、`VIX` |

### 注意事项

- 浏览器访问：`http://127.0.0.1:8000`（或您配置的端口）
- 在云服务器上部署后，不知道浏览器该输入什么地址？请看 [云服务器 Web 界面访问指南](deploy-webui-cloud.md)
- 分析完成后自动推送通知到配置的渠道
- 此功能在 GitHub Actions 环境中会自动禁用
- 另见 [openclaw Skill 集成指南](openclaw-skill-integration.md)

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

## Portfolio P0 PR1 (Core Ledger and Snapshot)

### Scope
- Core portfolio domain models:
  - account, trade, cash ledger, corporate action, position cache, lot cache, daily snapshot, fx cache
- Core service capability:
  - account CRUD
  - event writes
  - read-time replay snapshot for one account or all active accounts

### Accounting semantics
- Cost method:
  - `fifo` (default)
  - `avg`
- Same-day event ordering:
  - `cash -> corporate action -> trade`
- Corporate action effective-date rule:
  - `effective_date` is treated as effective before market trading on that day.

### Error and stability semantics
- `trade_uid` unique conflict returns `409` (API conflict semantics).
- sell writes now validate available quantity before insert; oversell is rejected with `409 portfolio_oversell`.
- portfolio source-event writes now serialize through a SQLite write lock; direct write/delete endpoints may return `409 portfolio_busy` when another ledger mutation is in progress.
- Snapshot write path is atomic for positions/lots/daily snapshot.
- FX conversion keeps fail-open behavior (fallback 1:1 with stale marker) to avoid pipeline interruption.

### Test coverage in PR1
- FIFO/AVG partial sell replay
- Dividend and split replay
- Same-day ordering (dividend/trade, split/trade)
- API account/event/snapshot contract
- API duplicate trade_uid conflict

## Portfolio P0 PR2 (Import and Risk)

### CSV import
- Supported broker ids: `huatai`, `citic`, `cmb`.
- Unified workflow: parse CSV into normalized records, then commit into portfolio trades.
- Commit remains row-by-row instead of one long transaction; busy rows count into `failed_count` rather than converting the whole request to `409`.
- Dedup policy:
  - First key: `trade_uid` (account-scoped)
  - Fallback key: deterministic hash of date/symbol/side/qty/price/fee/tax/currency

### Risk report
- Concentration monitoring: top position weight alert by config threshold.
- Drawdown monitoring: max/current drawdown computed from daily snapshots.
- Stop-loss proximity warning: mark near-alert and triggered items with threshold echo.

### FX fail-open
- FX refresh first tries online source (YFinance).
- On online failure, fallback to latest cached rate and mark `is_stale=true`.
- Main snapshot/risk pipeline stays available even when online FX fetch is unavailable.

## Portfolio P0 PR3 (Web + Agent Consumption)

### Web consumption page
- Added Web page route: `/portfolio` (`apps/dsa-web/src/pages/PortfolioPage.tsx`).
- Data sources:
  - `GET /api/v1/portfolio/snapshot`
  - `GET /api/v1/portfolio/risk`
- Supports:
  - full portfolio / single account switch
  - cost method switch (`fifo` / `avg`)
  - concentration pie chart (Top Positions) with Recharts
  - snapshot KPI cards and risk summary cards

### Agent tool
- Added `get_portfolio_snapshot` data tool for account-aware LLM suggestions.
- Default behavior:
  - compact summary output (token-friendly)
  - includes optional compact risk block
- Optional parameters:
  - `account_id`
  - `cost_method` (`fifo` / `avg`)
  - `as_of` (`YYYY-MM-DD`)
  - `include_positions` (default `false`)
  - `include_risk` (default `true`)

### Stability and compatibility
- New capability is additive only; no removal of existing keys/routes.
- Fail-open semantics:
  - If risk block fails, snapshot is still returned.
  - If portfolio module is unavailable, tool returns structured `not_supported`.

## Portfolio P0 PR4 (Gap Closure)

### API query closure
- Added event query endpoints:
  - `GET /api/v1/portfolio/trades`
  - `GET /api/v1/portfolio/cash-ledger`
  - `GET /api/v1/portfolio/corporate-actions`
- Added event delete endpoints:
  - `DELETE /api/v1/portfolio/trades/{trade_id}`
  - `DELETE /api/v1/portfolio/cash-ledger/{entry_id}`
  - `DELETE /api/v1/portfolio/corporate-actions/{action_id}`
- Unified query parameters:
  - `account_id`, `date_from`, `date_to`, `page`, `page_size`
- Trade/cash/corporate-action specific filters:
  - trades: `symbol`, `side`
  - cash-ledger: `direction`
  - corporate-actions: `symbol`, `action_type`
- Unified response shape:
  - `items`, `total`, `page`, `page_size`

### CSV import framework
- Reworked parser logic into extensible parser registry.
- Built-in adapters remain: `huatai`, `citic`, `cmb` with alias mapping.
- Added parser discovery endpoint:
  - `GET /api/v1/portfolio/imports/csv/brokers`

### Web closure
- `/portfolio` page now includes:
  - inline account creation entry with empty-state guide and auto-switch to created account
  - manual event entry forms: trade / cash / corporate action
  - CSV parse + commit operations (supports `dry_run`)
  - event list panel with filters and pagination
  - single-account scoped event deletion for trade / cash / corporate action correction
  - broker selector fallback to built-in brokers (`huatai/citic/cmb`) when broker list API fails or returns empty
  - FX status card manual refresh action that calls existing `POST /api/v1/portfolio/fx/refresh`; if upstream FX fetch fails, the page may still show stale after refresh and will explain the result inline
  - when `PORTFOLIO_FX_UPDATE_ENABLED=false`, the refresh API now returns explicit disabled status and the page will show “汇率在线刷新已被禁用” instead of “当前范围无可刷新的汇率对”

### Risk sector concentration semantics
- Added `sector_concentration` in `GET /api/v1/portfolio/risk`.
- Mapping rules:
  - CN positions try board mapping from `get_belong_boards`.
  - Non-CN or mapping failure falls back to `UNCLASSIFIED`.
  - Uses single primary board per symbol to avoid duplicate weighting.
- Fail-open:
  - board lookup errors do not interrupt risk response.
  - response returns coverage/error details for explainability.
