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
  <img src="assets/secret_config.png" alt="GitHub Secrets 配置示意图" width="600">
</div>

#### AI 模型配置（至少配置一个）

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `ANSPIRE_API_KEYS` | [Anspire](https://open.anspire.cn/?share_code=QFBC0FYC) API Key，一 Key 同时启用大模型和中文优化联网搜索，含本项目免费额度 | 推荐 |
| `AIHUBMIX_KEY` | [AIHubMix](https://aihubmix.com/?aff=CfMq) API Key，一 Key 切换使用全系模型，本项目可享 10% 优惠 | 推荐 |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/) 获取免费 Key | 可选 |
| `ANTHROPIC_API_KEY` | Anthropic Claude API Key | 可选 |
| `OPENAI_API_KEY` | OpenAI 兼容 API Key（支持 DeepSeek、通义千问等） | 可选 |
| `OPENAI_BASE_URL` | OpenAI 兼容 API 地址（如 `https://api.deepseek.com`） | 可选 |
| `OPENAI_MODEL` | 模型名称（如 `gemini-3.1-pro-preview`、`deepseek-v4-flash`、`gpt-5.5`） | 可选 |

> *注：以上模型 Key / 渠道至少配置一个；推荐优先从 Anspire 或 AIHubMix 这类一 Key 多模型服务开始。

#### 通知渠道配置（可同时配置多个，全部推送）

> 通知渠道、minimal/advanced key 分层、Actions 映射、`--check-notify` 诊断、Web 一键测试和本地 / Docker / GitHub Actions / Desktop 场景说明详见 [通知专题文档](notifications.md)。

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
| `ASTRBOT_URL` | AstrBot Webhook URL | 可选 |
| `ASTRBOT_TOKEN` | AstrBot Bearer Token（可选） | 可选 |
| `NTFY_URL` | ntfy 完整 topic endpoint，必须包含 topic path，例如 `https://ntfy.sh/my-topic` | 可选 |
| `NTFY_TOKEN` | ntfy Bearer Token（可选） | 可选 |
| `GOTIFY_URL` | Gotify server base URL，不包含 `/message`；系统会自动拼接 `/message` | 可选 |
| `GOTIFY_TOKEN` | Gotify application token，通过 `X-Gotify-Key` Header 发送 | 可选 |
| `CUSTOM_WEBHOOK_URLS` | 自定义 Webhook（支持钉钉等，多个用逗号分隔） | 可选 |
| `CUSTOM_WEBHOOK_BEARER_TOKEN` | 自定义 Webhook 的 Bearer Token（用于需要认证的 Webhook） | 可选 |
| `CUSTOM_WEBHOOK_BODY_TEMPLATE` | 自定义 Webhook JSON body 模板，适配 AstrBot、NapCat、自建服务等特殊 payload | 可选 |
| `WEBHOOK_VERIFY_SSL` | 读取该配置的 webhook-style HTTPS 通知请求证书校验（默认 true）。设为 false 可支持自签名证书。警告：关闭有严重安全风险（MITM），仅限可信内网 | 可选 |

> *注：至少配置一个渠道，配置多个则同时推送
>
> 当前默认 `daily_analysis.yml` 只显式映射固定 Secret / Variable 名称，不会自动把 `STOCK_GROUP_1`、`EMAIL_GROUP_1` 这类任意编号变量导入运行环境。所以分组邮箱功能目前不适用于仓库自带默认 GitHub Actions workflow；它适用于本地 `.env`、Docker，或你自行显式扩展过 `env:` 映射的运行环境。Actions 已显式映射 `CUSTOM_WEBHOOK_BODY_TEMPLATE`、`WEBHOOK_VERIFY_SSL`、`FEISHU_WEBHOOK_SECRET`、`FEISHU_WEBHOOK_KEYWORD`、`PUSHPLUS_TOPIC`、`NTFY_URL`、`NTFY_TOKEN`、`GOTIFY_URL`、`GOTIFY_TOKEN`、P3 通知路由键以及 P4 通知降噪键；`MARKDOWN_TO_IMAGE_CHANNELS` 和 `MERGE_EMAIL_NOTIFICATION` 仍作为行为开关不在默认 workflow 中自动映射。

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
| `NOTIFICATION_REPORT_CHANNELS` | report 路由渠道（单股推送、聚合日报、大盘复盘、合并推送等）；留空表示所有已配置渠道 | 可选 |
| `NOTIFICATION_ALERT_CHANNELS` | alert 路由渠道（EventMonitor 告警）；留空表示所有已配置渠道 | 可选 |
| `NOTIFICATION_SYSTEM_ERROR_CHANNELS` | system_error 预留路由渠道；当前不新增自动系统错误生产者，留空表示所有已配置渠道 | 可选 |
| `NOTIFICATION_DEDUP_TTL_SECONDS` | 通知去重 TTL 秒数，`0` 关闭；同一稳定去重 key 在 TTL 内只发送一次 | 可选 |
| `NOTIFICATION_COOLDOWN_SECONDS` | 通知冷却秒数，`0` 关闭；同一冷却 key 在窗口内限频 | 可选 |
| `NOTIFICATION_QUIET_HOURS` | 通知静默时段，格式 `HH:MM-HH:MM`，支持跨午夜；留空关闭 | 可选 |
| `NOTIFICATION_TIMEZONE` | 静默时段使用的 IANA 时区，如 `Asia/Shanghai`；留空跟随 `TZ` 或系统本地时区 | 可选 |
| `NOTIFICATION_MIN_SEVERITY` | 最低通知级别：`info`、`warning`、`error`、`critical`；留空保持现状 | 可选 |
| `NOTIFICATION_DAILY_DIGEST_ENABLED` | 每日摘要预留开关；当前不会发送摘要或持久化摘要内容 | 可选 |
| `MARKDOWN_TO_IMAGE_MAX_CHARS` | 超过此长度不转图片，避免超大图片（默认 15000） | 可选 |
| `MD2IMG_ENGINE` | 转图引擎：`wkhtmltoimage`（默认，需 wkhtmltopdf）或 `markdown-to-file`（emoji 更好，需 `npm i -g markdown-to-file`） | 可选 |
| `PREFETCH_REALTIME_QUOTES` | 设为 `false` 可禁用实时行情预取，避免 efinance/akshare_em 全市场拉取（默认 true） | 可选 |

#### 其他配置

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `STOCK_LIST` | 自选股代码，如 `600519,300750,002594` | ✅ |
| `ANSPIRE_API_KEYS` | [Anspire AI Search](https://aisearch.anspire.cn/) 针对中文内容特别优化；同一 Key 可用于搜索与 Anspire 大模型网关的兜底示例（是否可用以控制台与账号权限为准） | 推荐 |
| `SERPAPI_API_KEYS` | [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis) 搜索引擎结果补强，适合实时金融新闻 | 推荐 |
| `TAVILY_API_KEYS` | [Tavily](https://tavily.com/) 搜索 API（新闻搜索） | 可选 |
| `BOCHA_API_KEYS` | [博查搜索](https://open.bocha.cn/) Web Search API（中文搜索优化，支持AI摘要，多个key用逗号分隔） | 可选 |
| `BRAVE_API_KEYS` | [Brave Search](https://brave.com/search/api/) API（隐私优先，美股优化，多个key用逗号分隔） | 可选 |
| `MINIMAX_API_KEYS` | [MiniMax](https://platform.minimax.io/) Coding Plan Web Search（结构化搜索结果） | 可选 |
| `SEARXNG_BASE_URLS` | SearXNG 自建实例（无配额兜底，需在 settings.yml 启用 format: json）；留空时默认自动发现公共实例 | 可选 |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED` | 是否在 `SEARXNG_BASE_URLS` 为空时自动从 `searx.space` 获取公共实例（默认 `true`） | 可选 |
| `TUSHARE_TOKEN` | [Tushare Pro](https://tushare.pro/weborder/#/login?reg=834638 ) Token | 可选 |
| `LONGBRIDGE_APP_KEY` | [Longbridge OpenAPI](https://open.longbridge.com/) App Key（美股/港股量比、换手率、PE 兜底） | 可选 |
| `LONGBRIDGE_APP_SECRET` | Longbridge App Secret | 可选 |
| `LONGBRIDGE_ACCESS_TOKEN` | Longbridge Access Token | 可选 |
| `LONGBRIDGE_STATIC_INFO_TTL_SECONDS` | 长桥 `static_info` 进程内缓存秒数（默认 86400，0=不缓存） | 可选 |
| `LONGBRIDGE_CONNECTION_COOLDOWN_SECONDS` | 长桥连接关闭类异常后的冷却秒数（默认 15；冷却期内临时跳过 Longbridge，避免频繁重连） | 可选 |
| `LONGBRIDGE_HTTP_URL` | HTTP 接口地址（默认 `https://openapi.longbridge.com`） | 可选 |
| `LONGBRIDGE_QUOTE_WS_URL` | 行情 WebSocket 地址（默认 `wss://openapi-quote.longbridge.com/v2`） | 可选 |
| `LONGBRIDGE_TRADE_WS_URL` | 交易 WebSocket 地址（默认 `wss://openapi-trade.longbridge.com/v2`） | 可选 |
| `LONGBRIDGE_REGION` | 覆盖接入点；SDK 会按网络自动选择，默认 `hk`，若判断不正确可设置（如 `cn`、`hk`） | 可选 |
| `LONGBRIDGE_ENABLE_OVERNIGHT` | 是否开启夜盘行情 `true` / `false`，默认 `false` | 可选 |
| `LONGBRIDGE_PUSH_CANDLESTICK_MODE` | K 线推送模式：`realtime` 或 `confirmed`（默认 `realtime`） | 可选 |
| `LONGBRIDGE_PRINT_QUOTE_PACKAGES` | 连接时是否打印行情包（未设置时默认 `false`；设为 `1`/`true`/`yes` 开启） | 可选 |
| `ENABLE_CHIP_DISTRIBUTION` | 启用筹码分布（Actions 默认 false；需筹码数据时在 Variables 中设为 true，接口可能不稳定） | 可选 |

> **GitHub Actions：** 仓库自带 `daily_analysis.yml` 已把上表中的 `LONGBRIDGE_*` 映射到任务环境。若未在 **Settings → Secrets and variables → Actions** 中配置 `LONGBRIDGE_APP_KEY`、`LONGBRIDGE_APP_SECRET`、`LONGBRIDGE_ACCESS_TOKEN`，CI 内不会调用长桥（日志中一般看不到 `[Longbridge]` 相关行情行）。可选接入点变量（如 `LONGBRIDGE_REGION`）可放在 **Variables** 或 **Secrets**。

> **Longbridge 运行时行为：** 未配置凭据时不会实例化 Longbridge 这个可选 fetcher；若运行时遇到 `client is closed`、`context closed`、`connection closed` 等连接关闭类异常，会进入冷却期（默认 15 秒，可用 `LONGBRIDGE_CONNECTION_COOLDOWN_SECONDS` 调整），冷却期内美股/港股的实时与日线请求会自动跳过 Longbridge，退回 YFinance / AkShare 等兜底链路。

> 补充说明
- TUSHARE_TOKEN，当此参数配置后，但不具备港股日线接口权限时，也会出现港股数据查询不出来或者错误的情况，和老版本提示不支持港股效果相同

#### ✅ 最小配置示例

如果你想快速开始，最少需要配置以下项：

1. **AI 模型**：`ANSPIRE_API_KEYS`（一 Key 同时启用大模型和搜索）、`AIHUBMIX_KEY`（[AIHubmix](https://aihubmix.com/?aff=CfMq)，一 Key 多模型）、`GEMINI_API_KEY` 或 `OPENAI_API_KEY`
2. **通知渠道**：至少配置一个，如 `WECHAT_WEBHOOK_URL` 或 `EMAIL_SENDER` + `EMAIL_PASSWORD`
3. **股票列表**：`STOCK_LIST`（必填）
4. **搜索 API**：`ANSPIRE_API_KEYS` 或 `SERPAPI_API_KEYS`（推荐，用于新闻与舆情搜索）

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

> 完整说明见 [LLM 配置指南](LLM_CONFIG_GUIDE.md)（三层配置、渠道模式、Vision、Agent、排错）；常用服务商预设、Actions 变量对照和错误排障见 [LLM 服务商配置指南](llm-providers.md)。
> 本节仅同步模型/渠道配置清单，不额外引入新的外部 provider / Base URL 兼容约定；兼容语义以当前仓库 `requirements.txt` 依赖约束和相关测试为准，历史回退路径见上述两份文档中“回退/恢复”说明。

| 变量名 | 说明 | 默认值 | 必填 |
|--------|------|--------|:----:|
| `LITELLM_MODEL` | 主模型，格式 `provider/model`（如 `gemini/gemini-3.1-pro-preview`），推荐优先使用 | - | 否 |
| `AGENT_LITELLM_MODEL` | Agent 主模型（可选）；留空继承主模型，无 provider 前缀按 `openai/<model>` 解析 | - | 否 |
| `LITELLM_FALLBACK_MODELS` | 备选模型，逗号分隔 | - | 否 |
| `LLM_CHANNELS` | 渠道名称列表（逗号分隔），配合 `LLM_{NAME}_*` 使用，详见 [LLM 配置指南](LLM_CONFIG_GUIDE.md) | - | 否 |
| `LITELLM_CONFIG` | 高级模型路由 YAML 配置文件路径（高级） | - | 否 |
| `ANSPIRE_API_KEYS` | [Anspire](https://open.anspire.cn/?share_code=QFBC0FYC) API Key，一 Key 同时启用大模型网关和搜索 | - | 可选 |
| `AIHUBMIX_KEY` | [AIHubmix](https://aihubmix.com/?aff=CfMq) API Key，一 Key 切换使用全系模型，无需额外配置 Base URL | - | 可选 |
| `GEMINI_API_KEY` | Google Gemini API Key | - | 可选 |
| `GEMINI_MODEL` | 主模型名称（legacy，`LITELLM_MODEL` 优先） | `gemini-3.1-pro-preview` | 否 |
| `GEMINI_MODEL_FALLBACK` | 备选模型（legacy） | `gemini-3-flash-preview` | 否 |
| `OPENAI_API_KEY` | OpenAI 兼容 API Key | - | 可选 |
| `OPENAI_BASE_URL` | OpenAI 兼容 API 地址 | - | 可选 |
| `OLLAMA_API_BASE` | Ollama 本地服务地址（如 `http://localhost:11434`），详见 [LLM 配置指南](LLM_CONFIG_GUIDE.md) | - | 可选 |
| `OPENAI_MODEL` | OpenAI 模型名称（legacy，AIHubmix 用户可填如 `gemini-3.1-pro-preview`、`gpt-5.5`） | `gpt-5.5` | 可选 |
| `ANTHROPIC_API_KEY` | Anthropic Claude API Key | - | 可选 |
| `ANTHROPIC_MODEL` | Claude 模型名称 | `claude-sonnet-4-6` | 可选 |
| `ANTHROPIC_TEMPERATURE` | Claude 温度参数（0.0-1.0） | `0.7` | 可选 |
| `ANTHROPIC_MAX_TOKENS` | Claude 响应最大 token 数 | `8192` | 可选 |

> *注：`ANSPIRE_API_KEYS`、`AIHUBMIX_KEY`、`GEMINI_API_KEY`、`ANTHROPIC_API_KEY`、`OPENAI_API_KEY` 或 `OLLAMA_API_BASE` 至少配置一个。`ANSPIRE_API_KEYS` 与 `AIHUBMIX_KEY` 无需配置 `OPENAI_BASE_URL`，系统自动适配。

### 通知渠道配置

更多通知配置基线、诊断和部署场景说明见 [通知专题文档](notifications.md)。

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
| `WEBHOOK_VERIFY_SSL` | 读取该配置的 webhook-style HTTPS 通知请求证书校验（默认 true）。设为 false 可支持自签名。警告：关闭有严重安全风险 | 可选 |
| `PUSHOVER_USER_KEY` | Pushover 用户 Key | 可选 |
| `PUSHOVER_API_TOKEN` | Pushover API Token | 可选 |
| `NTFY_URL` | ntfy 完整 topic endpoint，必须包含 topic path，例如 `https://ntfy.sh/my-topic` | 可选 |
| `NTFY_TOKEN` | ntfy Bearer Token（可选） | 可选 |
| `GOTIFY_URL` | Gotify server base URL，不包含 `/message` | 可选 |
| `GOTIFY_TOKEN` | Gotify application token，通过 `X-Gotify-Key` Header 发送 | 可选 |
| `PUSHPLUS_TOKEN` | PushPlus Token（国内推送服务） | 可选 |
| `SERVERCHAN3_SENDKEY` | Server酱³ Sendkey | 可选 |
| `ASTRBOT_URL` | AstrBot Webhook URL | 可选 |
| `ASTRBOT_TOKEN` | AstrBot Bearer Token（可选） | 可选 |
| `NOTIFICATION_REPORT_CHANNELS` | report 路由渠道，逗号分隔；允许值：wechat,feishu,telegram,email,pushover,ntfy,gotify,pushplus,serverchan3,custom,discord,slack,astrbot | 可选 |
| `NOTIFICATION_ALERT_CHANNELS` | alert 路由渠道，逗号分隔；留空保持全渠道 | 可选 |
| `NOTIFICATION_SYSTEM_ERROR_CHANNELS` | system_error 预留路由渠道，逗号分隔；留空保持全渠道 | 可选 |
| `NOTIFICATION_DEDUP_TTL_SECONDS` | 通知去重 TTL 秒数，`0` 关闭 | 可选 |
| `NOTIFICATION_COOLDOWN_SECONDS` | 通知冷却秒数，`0` 关闭 | 可选 |
| `NOTIFICATION_QUIET_HOURS` | 静默时段，格式 `HH:MM-HH:MM`，支持跨午夜 | 可选 |
| `NOTIFICATION_TIMEZONE` | 静默时段时区，如 `Asia/Shanghai`；留空跟随 `TZ` 或系统本地时区 | 可选 |
| `NOTIFICATION_MIN_SEVERITY` | 最低通知级别：info, warning, error, critical；留空保持现状 | 可选 |
| `NOTIFICATION_DAILY_DIGEST_ENABLED` | 每日摘要预留开关；当前不会发送摘要 | 可选 |

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
| `ANSPIRE_API_KEYS` | Anspire Open API Key（可用于搜索与大模型网关共享场景的配置示例；是否可用取决于账号权限与网关可见性，可有效增强 A 股分析效果） | 推荐 |
| `SERPAPI_API_KEYS` | SerpAPI 搜索引擎结果补强，适合实时金融新闻 | 推荐 |
| `TAVILY_API_KEYS` | Tavily 搜索 API Key | 可选 |
| `BOCHA_API_KEYS` | 博查搜索 API Key（中文优化） | 可选 |
| `BRAVE_API_KEYS` | Brave Search API Key（美股优化） | 可选 |
| `MINIMAX_API_KEYS` | MiniMax Coding Plan Web Search（结构化搜索结果） | 可选 |
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
| `LONGBRIDGE_*`（可选） | 见官方 [环境变量](https://open.longbridge.com/zh-CN/docs/getting-started#环境变量)；另有 `LONGBRIDGE_STATIC_INFO_TTL_SECONDS` 与 `LONGBRIDGE_CONNECTION_COOLDOWN_SECONDS` | - | 可选 |
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
> - A 股大盘复盘报告采用盘后工作台式结构：固定包含大盘红绿灯、盘面温度、指数明细、板块 Top 表、新闻催化、明日交易计划和风险提示；若部分数据源缺失，则保留可用区块并在对应位置降级展示。
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
| `ADMIN_AUTH_ENABLED` | Web 登录：设为 `true` 启用密码保护；首次访问在网页设置初始密码，可在「系统设置 > 修改密码」修改；忘记密码执行 `python -m src.auth reset_password`。Web 的 `.env` 备份导入导出仅在开启该开关后可用（桌面端不受此限制）。 | `false` |
| `TRUST_X_FORWARDED_FOR` | 单层可信反向代理部署时设为 `true`，取 `X-Forwarded-For` 最右值作为真实客户端 IP（用于登录限流等）；直连公网时保持 `false` 防伪造。多级代理/CDN 场景下限流 key 可能退化为边缘代理 IP，需额外评估 | `false` |
| `MAX_WORKERS` | 并发线程数 | `3` |
| `MARKET_REVIEW_ENABLED` | 启用大盘复盘 | `true` |
| `MARKET_REVIEW_REGION` | 大盘复盘市场区域：cn(A股)、hk(港股)、us(美股)、both(三市场)，us 适合仅关注美股的用户 | `cn` |
| `TRADING_DAY_CHECK_ENABLED` | 交易日检查：默认 `true`，非交易日跳过执行；设为 `false` 或使用 `--force-run` 可强制执行（Issue #373） | `true` |
| `SCHEDULE_ENABLED` | 启用定时任务 | `false` |
| `SCHEDULE_TIME` | 定时执行时间 | `18:00` |
| `LOG_DIR` | 日志目录 | `./logs` |

---

## Docker 部署

Dockerfile 使用多阶段构建，前端会在构建镜像时自动打包并内置到 `static/`。
如需覆盖静态资源，可挂载本地 `static/` 到容器内 `/app/static`。
运行中的 `server` 容器默认直接复用 `/app/static` 里的预构建产物，不要求容器内保留 `apps/dsa-web` 源码目录或运行时安装 `npm`；若 WebUI 无法打开，请优先确认 `/app/static/index.html` 是否存在。

当前官方镜像发布地址：

- GHCR：`ghcr.io/zhulinsen/daily_stock_analysis:<tag>`
- Docker Hub：`<DOCKERHUB_USERNAME>/daily_stock_analysis:<tag>`（由发布者的 `DOCKERHUB_USERNAME` secret 决定，官方发布为 `zhulinsen/daily_stock_analysis`）

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

### 直接拉官方镜像运行

如果你不打算在目标机器上保留源码，可以直接拉取官方镜像：

```bash
# Web/API 模式
docker pull zhulinsen/daily_stock_analysis:latest
docker run -d \
  --name dsa-server \
  --env-file .env \
  -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/reports:/app/reports" \
  -v "$(pwd)/.env:/app/.env" \
  zhulinsen/daily_stock_analysis:latest \
  python main.py --serve-only --host 0.0.0.0 --port 8000

# 定时任务模式
docker run -d \
  --name dsa-analyzer \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/reports:/app/reports" \
  -v "$(pwd)/.env:/app/.env" \
  zhulinsen/daily_stock_analysis:latest
```

如需固定版本或便于回滚，请将 `latest` 替换为具体版本 tag，例如 `v3.13.0`。

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

### `.env` 与数据目录映射说明

无论你使用 `docker run` 还是 Compose，建议同时保留下面两种映射：

- 环境变量注入：`--env-file .env` 或 Compose 的 `env_file`
  作用：把 `.env` 中的键值作为容器启动时的环境变量传入 Python 进程。
- 文件映射：`-v "$(pwd)/.env:/app/.env"` 或 Compose 的 `../.env:/app/.env`
  作用：让容器内的 Web 设置页和后端读写同一份 `.env` 文件，修改后可持久化到宿主机。

推荐同时映射这几个目录：

- `./data:/app/data`：数据库、缓存和运行时数据
- `./logs:/app/logs`：日志输出
- `./reports:/app/reports`：生成的分析报告
- `./strategies:/app/strategies:ro`：自定义策略 YAML（只读挂载）

官方 Docker 镜像启动时会自动创建并修复 `/app/data`、`/app/logs`、`/app/reports` 的挂载目录权限，然后降权为容器内非 root 用户 `dsa`（UID/GID `1000:1000`）运行应用。普通 Docker / Compose 部署不需要手动 `chown` 或 `chmod` 宿主机目录。

如果你通过 `--user` 或 Compose `user:` 指定了其他运行用户，或使用只读挂载、rootless Docker、NFS 等限制 `chown` 的存储环境，自动修复可能无法生效。此时请确保实际运行用户对 `data`、`logs`、`reports` 具备写入权限，或改用可写卷。

如果你需要覆盖内置静态资源，还可以额外挂载：

- `./static:/app/static:ro`

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
docker run -d \
  --name dsa-server-local \
  --env-file .env \
  -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/reports:/app/reports" \
  -v "$(pwd)/.env:/app/.env" \
  stock-analysis \
  python main.py --serve-only --host 0.0.0.0 --port 8000
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
| `SCHEDULE_RUN_IMMEDIATELY` | 定时模式启动时是否立即运行一次；未显式设置时沿用 `RUN_IMMEDIATELY` 的运行时覆盖语义 | `true` | `false` |
| `RUN_IMMEDIATELY` | 非定时模式启动时是否立即运行一次；同时作为未显式设置 `SCHEDULE_RUN_IMMEDIATELY` 时的 legacy 回退 | `true` | `false` |
| `TRADING_DAY_CHECK_ENABLED` | 交易日检查：非交易日跳过执行；设为 `false` 可强制执行 | `true` | `false` |

例如在 Docker 中配置：

```bash
# 设置启动时不立即分析
docker run -e SCHEDULE_ENABLED=true -e SCHEDULE_RUN_IMMEDIATELY=false ...
```

> 兼容说明：如果运行时显式传入 `RUN_IMMEDIATELY`，但没有单独传 `SCHEDULE_RUN_IMMEDIATELY`，内置调度模式会继续继承前者，避免被 `.env` 中持久化的 `SCHEDULE_RUN_IMMEDIATELY` 旧值反向覆盖。

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

通知渠道矩阵、minimal/advanced key 分层、`--check-notify` 诊断口径和场景化配置说明见 [通知专题文档](notifications.md)。

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

如需适配 AstrBot、NapCat 或自建服务的特殊 body，可设置 `CUSTOM_WEBHOOK_BODY_TEMPLATE`。这是全局模板，会先于 Bark、Slack、Discord 等 URL 自动识别 payload 生效；如果渲染后不是 JSON object，系统会回退默认 payload。推荐使用 `$content_json` / `$title_json` 避免换行和引号破坏 JSON：

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"msg_type":"text","content":$content_json}
```

可用占位符：`$content_json`、`$content`、`$title_json`、`$title`。其中 `$content` / `$title` 是裸字符串，不做 JSON 转义；正文含双引号或换行时可能触发 fallback。

Bark 使用全局模板时需显式写出 Bark body：

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$title_json,"body":$content_json,"group":"stock"}
```

NapCat / OneBot 示例需按实际 endpoint、`user_id` 或 `group_id` 调整：

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"user_id":123456,"message":$content_json}
```

### ntfy / Gotify

ntfy 和 Gotify 都是一等通知渠道，只发送文本 / JSON，不参与 Markdown 转图片。

ntfy 使用完整 topic endpoint，最后一个 path segment 会作为 topic：

```env
NTFY_URL=https://ntfy.sh/my-topic
NTFY_TOKEN=
```

Gotify 使用 server base URL，系统会自动拼接固定 `/message` API，并通过 `X-Gotify-Key` Header 发送 application token。`GOTIFY_URL` 可包含反向代理 path prefix，但不要包含 `/message`：

```env
GOTIFY_URL=https://gotify.example
GOTIFY_TOKEN=app-token
```

```env
# 实际请求会发送到 https://example.com/gotify/message
GOTIFY_URL=https://example.com/gotify
GOTIFY_TOKEN=app-token
```

`NTFY_URL` 与 `GOTIFY_URL` 的语义不同是两个服务 API 设计不同导致的刻意选择：ntfy 由用户 topic 构成 endpoint，Gotify 的 `/message` 是固定服务 API。

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
- 可选设置 `LONGBRIDGE_CONNECTION_COOLDOWN_SECONDS` 控制连接关闭类异常后的冷却秒数（默认 15）
- 接入点可配 `LONGBRIDGE_HTTP_URL`、`LONGBRIDGE_QUOTE_WS_URL`、`LONGBRIDGE_TRADE_WS_URL`、`LONGBRIDGE_REGION`
- 其余可选参数见官方 [环境变量说明](https://open.longbridge.com/zh-CN/docs/getting-started#环境变量)
- 仅在 YFinance（美股）或 AkShare（港股）返回数据不完整时自动触发，不影响 A 股链路
- 未配置凭据时不会实例化该可选数据源；若运行时出现连接关闭类异常，会在冷却期内临时跳过 Longbridge，避免请求级频繁重连

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

港股日线会跳过 efinance、pytdx、baostock 等不支持港股日线的数据源，避免把港股代码错配到非港股市场；默认改由 AkShare/Tushare/YFinance/Longbridge 等港股路径继续兜底。

### ETF 与指数分析

针对指数跟踪型 ETF 和美股指数（如 VOO、QQQ、SPY、510050、SPX、DJI、IXIC），分析仅关注**指数走势、跟踪误差、市场流动性**，不纳入基金管理人/发行方的公司层面风险（诉讼、声誉、高管变动等）。风险警报与业绩预期均基于指数成分股整体表现，避免将基金公司新闻误判为标的本身利空。详见 Issue #274。

### 多模型切换

配置多个模型，系统自动切换：

```bash
# Gemini（主力）
GEMINI_API_KEY=xxx
GEMINI_MODEL=gemini-3.1-pro-preview

# OpenAI 兼容（备选）
OPENAI_API_KEY=xxx
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-flash
# deepseek-chat / deepseek-reasoner 仍兼容，但官方已标记为 2026/07/24 后废弃
```

### 高级模型路由（底层由 LiteLLM 驱动）

详见 [LLM 配置指南](LLM_CONFIG_GUIDE.md)。默认使用时你只需要理解主模型、备选模型和模型渠道；如果进入这一节，说明你要直接使用底层 [LiteLLM](https://github.com/BerriAI/litellm) 路由能力，无需单独启动 Proxy 服务。

**两层机制**：同一模型多 Key 轮换（Router）与跨模型降级（Fallback）分层独立，互不干扰。

**多 Key + 跨模型降级配置示例**：

```env
# 主模型：3 个 Gemini Key 轮换，任一 429 时 Router 自动切换下一个 Key
GEMINI_API_KEYS=key1,key2,key3
LITELLM_MODEL=gemini/gemini-3.1-pro-preview

# 跨模型降级：主模型全部 Key 均失败时，按序尝试 Claude → GPT
# 需配置对应 API Key：ANTHROPIC_API_KEY、OPENAI_API_KEY
LITELLM_FALLBACK_MODELS=anthropic/claude-sonnet-4-6,openai/gpt-5.4-mini
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
- **主模型不支持 Vision 时**：若主模型为 DeepSeek 等非 Vision 模型，可显式配置 `VISION_MODEL=openai/gpt-5.5` 或 `gemini/gemini-3.1-pro-preview` 供图片提取使用
- **配置校验**：若配置了 `VISION_MODEL` 但未配置对应 provider 的 API Key，启动时会输出 warning，图片提取功能将不可用

### 调试模式

```bash
python main.py --debug
```

日志文件位置：
- 常规日志：`logs/stock_analysis_YYYYMMDD.log`
- 调试日志：`logs/stock_analysis_debug_YYYYMMDD.log`

调试日志默认保留项目自身 DEBUG 信息，但会将 LiteLLM 内部日志压低到 `WARNING`，避免流式生成时按 token 写入大量第三方调试日志；如需排查 LiteLLM 内部细节，可在 `.env` 中临时设置 `LITELLM_LOG_LEVEL=DEBUG`。

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

## 分析决策可操作性

个股报告的操作建议会结合支撑位、压力位、量能/筹码、主力资金流向和风险事件进行校准，避免仅因单日涨跌或评分跨线在“买入/卖出”之间剧烈切换。若价格处在支撑与压力之间且资金流不明确，报告会优先给出“持有、震荡观望、洗盘观察”等中性可执行建议；只有接近支撑确认、有效突破压力且量价/资金配合时才给出买入，跌破关键支撑或主力资金持续流出时才给出卖出/减仓。
该项调整会影响可操作决策的运行时落盘与提示词约束链路，但不变更 LLM 模型、LiteLLM 路由、Provider/Key 及其兼容边界，不影响配置保存/清理语义。
兼容性核验结论：除配置和模型侧语义外，该决策稳定性链路覆盖 `src/analyzer.py`、`src/core/pipeline.py`、`src/core/backtest_engine.py`、`src/report_language.py` 及 `src/agent` 决策路径的运行时行为，建议复核报告决策类型映射与回测入口联动。
核验路径：相关逻辑在上述运行时路径与对应测试（`tests/test_backtest_engine.py`、`tests/test_analyzer_news_prompt.py`、`tests/test_decision_stability.py`、`tests/test_agent_pipeline.py` 等）中生效；未在 `src/config.py`、`src/report.py`、存储/持久化链路新增配置字段或清理逻辑。

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
| 持有/持有观察/震荡观望/洗盘观察/hold/hold and watch/range-bound watch/shakeout watch | long | not_down | 未显著下跌 |
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

## 本地 WebUI 管理界面

WebUI 与 FastAPI API 服务共用同一服务进程，启动后可在浏览器中完成配置管理、手动分析、任务进度查看、历史报告、回测、持仓管理和智能导入等操作。认证、云服务器访问和 API 调用细节见下方说明。

### FastAPI API 服务

FastAPI 提供 RESTful API 服务，支持配置管理和触发分析。

### 启动方式

| 命令 | 说明 |
|------|------|
| `python main.py --serve` | 启动 API 服务 + 执行一次完整分析 |
| `python main.py --serve-only` | 仅启动 API 服务，手动触发分析 |

### 功能特性

- 📝 **配置管理** - 查看/修改自选股列表
- 🚀 **快速分析** - 通过 API 接口触发个股分析；首页也提供“大盘复盘”按钮，可在 Docker/server 模式下后台触发大盘复盘
- 🧭 **首次配置提示** - 首页会读取只读配置状态，缺少 LLM 主渠道、自选股等基础项时提示缺口并引导进入系统设置
- 📊 **实时进度** - 分析任务状态实时更新，支持多任务并行；普通分析链路在进入 LLM 阶段后会优先尝试 LiteLLM 流式生成，并通过任务 SSE 回灌更细粒度的 `message/progress`
- 🗂️ **大盘复盘任务可见性** - 首页触发大盘复盘后会返回 `task_id` 并轮询 `GET /api/v1/analysis/status/{task_id}`，在进行中/完成/失败场景给出可见反馈，失败时直接透出报错内容
- 📈 **回测验证** - 评估历史分析准确率，查询方向胜率与模拟收益
- 🔗 **API 文档** - 访问 `/docs` 查看 Swagger UI

### API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/analysis/analyze` | POST | 触发股票分析 |
| `/api/v1/analysis/market-review` | POST | 后台触发大盘复盘；请求体可传 `{"send_notification": true}`；与 `main.py --market-review` 与 `bot` 复用同一套 `GeminiAnalyzer/SearchService/NotificationService` 组装语义 |
| `/api/v1/analysis/tasks` | GET | 查询任务列表 |
| `/api/v1/analysis/tasks/stream` | GET (SSE) | 订阅任务实时状态流 |
| `/api/v1/analysis/status/{task_id}` | GET | 查询任务状态 |
| `/api/v1/history` | GET | 查询分析历史 |
| `/api/v1/usage/summary?period=today|month|all` | GET | 按调用类型与模型维度汇总 LLM 调用次数和 Token 用量 |
| `/api/v1/backtest/run` | POST | 触发回测 |
| `/api/v1/backtest/results` | GET | 查询回测结果（分页） |
| `/api/v1/backtest/performance` | GET | 获取整体回测表现 |
| `/api/v1/backtest/performance/{code}` | GET | 获取单股回测表现 |
| `/api/v1/stocks/extract-from-image` | POST | 从图片提取股票代码（multipart，超时 60s） |
| `/api/v1/stocks/parse-import` | POST | 解析 CSV/Excel/剪贴板（multipart file 或 JSON `{"text":"..."}`，文件≤2MB，文本≤100KB） |
| `/api/health` | GET | 健康检查 |
| `/docs` | GET | API Swagger 文档 |

> 说明：`POST /api/v1/analysis/analyze` 在 `async_mode=false` 时仅支持单只股票；批量 `stock_codes` 需使用 `async_mode=true`。异步 `202` 响应对单股返回 `task_id`，对批量返回 `accepted` / `duplicates` 汇总结构。
> 说明：`POST /api/v1/analysis/market-review` 采用后端与 CLI/Bot 共用的配置路径（`GeminiAnalyzer(config=...)` 与同样的搜索/提示词构造入口）。Provider 兼容路由会优先识别并使用 `litellm_model`、`llm_model_list`，若未配置则回退 legacy `GEMINI_*`、`OPENAI_*`、`ANTHROPIC_*`、`DEEPSEEK_*` 键；不会新增/调整 provider、Base URL 或 LiteLLM 路由语义。
> 审计依据：优先级与回退语义以 `src/config.py` 的 `Config._load_from_env()` 为准（`LITELLM_CONFIG` > `LLM_CHANNELS` > legacy）。配套回归见 `tests/test_llm_channel_config.py`（配置源解析）与 `tests/test_market_review_runtime.py`（共享装配路径）。该接口当前仅提供单进程/单机级防重复能力，若为多实例部署需通过外部任务队列或分布式锁补齐全局幂等。
> 说明：该端点若返回 `task_id`，WebUI 会轮询 `GET /api/v1/analysis/status/{task_id}` 展示状态。状态为 `completed` 时给出完成提示（报告已生成并按配置推送），状态为 `failed` 时在前端错误区域显示 `error` 原因。

> 兼容性审计证据：
> - 官方来源：LiteLLM OpenAI-compatible provider 文档 <https://docs.litellm.ai/docs/providers/openai_compatible>；OpenAI Chat API 文档 <https://platform.openai.com/docs/api-reference/chat/create>；DeepSeek API 文档 <https://api-docs.deepseek.com/>。
> - 依赖版本：项目约束为 `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`（见 `requirements.txt`），以上兼容语义回归测试在该版本窗口内执行。
> - 可复核测试：
>   - `tests/test_llm_channel_config.py`（配置源优先级与 provider/base url 映射）
>   - `tests/test_market_review_runtime.py`（`build_market_review_runtime` 复用装配路径）
>   - `tests/test_analysis_api_contract.py`（`/api/v1/analysis/market-review` 合约与任务状态链路）
> - 回滚/回退：若新路径有问题，可先恢复历史 `LITELLM_MODEL`、`LITELLM_FALLBACK_MODELS` 与 legacy `GEMINI_*` / `OPENAI_*` / `ANTHROPIC_*` / `DEEPSEEK_*`，或通过桌面端备份或已启用管理员鉴权的 Web 端 `POST /api/v1/system/config/import` 回滚并重启；在运行时级别可暂时清空 `LITELLM_CONFIG` / `LLM_CHANNELS` 触发 legacy 回退。

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

# 查询今日 LLM 用量
curl "http://127.0.0.1:8000/api/v1/usage/summary?period=today"

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
| 北交所 | 8/4/92 开头 6 位，支持 `BJ` 前缀或 `.BJ` 后缀 | `920748`、`BJ920493`、`920493.BJ` |
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

## Agent 工具数据缓存与持久化

- `get_daily_history` 会先尝试复用本地 `stock_daily` 日线缓存；缓存新鲜且至少覆盖首页默认的 30 条记录时，不再重复请求外部数据源。
- 当 Agent 请求的天数多于本地缓存记录数时，工具会返回实际可用记录，并通过 `partial_cache=true`、`requested_days`、`actual_records` 标明这是部分缓存命中。
- 缓存缺失或过期时，工具仍会按原逻辑从数据源获取日线数据；获取成功后会 best-effort 写回 `stock_daily`，保存失败不会阻断 Agent 回复。
- `search_stock_news` 与 `search_comprehensive_intel` 成功返回后会 best-effort 写入 `news_intel`，复用现有 URL / fallback key 去重逻辑。
- `get_realtime_quote` 不复用 `stock_daily` 作为实时行情缓存，也不会把盘中实时行情写入日线表；如需实时行情缓存，应单独设计实时行情存储。

## Agent 事件告警监控

`AGENT_EVENT_MONITOR_ENABLED=true` 后，schedule 模式会按 `AGENT_EVENT_MONITOR_INTERVAL_MINUTES` 轮询 `AGENT_EVENT_ALERT_RULES_JSON` 中的规则，并把触发结果发送到现有通知渠道。当前运行时支持三类规则：

> 兼容与迁移说明：本节记录当前事件告警规则（含 `price_change_percent`）运行时行为，未变更模型名、provider、Base URL、LiteLLM、`OPENAI_*`、`DEEPSEEK_*`、`GEMINI_*` 等外部模型/API 配置语义。若需回退，删除或关闭 `AGENT_EVENT_MONITOR_ENABLED` 即可恢复到旧行为。

| `alert_type` | 方向字段 | 阈值字段 | 说明 |
| --- | --- | --- | --- |
| `price_cross` | `above` / `below` | `price` | 当前价上破或下破指定价格 |
| `price_change_percent` | `up` / `down` | `change_pct` | 涨跌幅达到指定百分比 |
| `volume_spike` | - | `multiplier` | 最新成交量超过近 20 日均量的指定倍数 |

示例：

```env
AGENT_EVENT_MONITOR_ENABLED=true
AGENT_EVENT_MONITOR_INTERVAL_MINUTES=5
AGENT_EVENT_ALERT_RULES_JSON=[{"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800},{"stock_code":"300750","alert_type":"price_change_percent","direction":"down","change_pct":3.0},{"stock_code":"000858","alert_type":"volume_spike","multiplier":2.5}]
```

## 持仓管理说明

### `/portfolio` 页面可做什么

- 查看全量持仓或切换到单个账户视角。
- 在 `fifo` / `avg` 两种成本法之间切换，查看快照 KPI、风险摘要和 Top Positions 集中度图表。
- 直接在 Web 页面新增账户，或录入交易、现金流水、公司行动等事件。
- 通过 CSV 导入持仓记录，支持先 `dry_run` 预览，再决定是否正式写入。
- 在事件列表中按账户、日期、方向、代码等条件筛选，并对单账户事件做删除修正。

### 相关接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/portfolio/snapshot` | GET | 查询持仓快照 |
| `/api/v1/portfolio/risk` | GET | 查询风险摘要 |
| `/api/v1/portfolio/trades` | GET | 分页查询交易记录 |
| `/api/v1/portfolio/cash-ledger` | GET | 分页查询现金流水 |
| `/api/v1/portfolio/corporate-actions` | GET | 分页查询公司行动 |
| `/api/v1/portfolio/imports/csv/brokers` | GET | 查询内建 CSV 券商解析器 |
| `/api/v1/portfolio/fx/refresh` | POST | 手动刷新汇率缓存 |
| `/api/v1/portfolio/trades/{trade_id}` | DELETE | 删除交易记录 |
| `/api/v1/portfolio/cash-ledger/{entry_id}` | DELETE | 删除现金流水 |
| `/api/v1/portfolio/corporate-actions/{action_id}` | DELETE | 删除公司行动 |

> 查询类接口统一支持 `account_id`、`date_from`、`date_to`、`page`、`page_size` 等常见筛选参数；事件列表会返回统一的 `items`、`total`、`page`、`page_size` 结构。

### 使用行为说明

- CSV 导入内建 `huatai`、`citic`、`cmb` 解析器；若券商列表接口失败，Web 端会自动回退到这些内建选项。
- 导入流程会先把 CSV 解析成标准化记录，再逐条提交到持仓账本；遇到忙碌行会计入 `failed_count`，不会因为单行冲突让整批请求整体失败。
- 交易去重优先使用账户内唯一的 `trade_uid`，缺失时回退到基于日期、代码、方向、数量、价格、费用、税费、币种的确定性哈希。
- 卖出会先校验可用数量，超卖返回 `409 portfolio_oversell`；并发写入冲突时可能返回 `409 portfolio_busy`。
- 持仓快照的 `positions[]` 会返回 `price_source`、`price_date`、`price_stale`、`price_available` 等价格元信息；当天快照优先使用历史收盘价，仅在收盘价缺失时尝试实时价 fallback，历史 `as_of` 快照不会拉取实时价，也不会再把成本价静默当作现价；缺价持仓会标记 `price_available=false` 并从市值与未实现盈亏汇总中排除。
- 汇率刷新会先尝试在线源；若在线获取失败，则回退到最近一次缓存并标记 `is_stale=true`，避免快照和风险页整体不可用。
- 当 `PORTFOLIO_FX_UPDATE_ENABLED=false` 时，手动刷新接口会明确返回“在线刷新已禁用”，页面不会误导为“当前没有可刷新的汇率对”。
- 风险摘要包含集中度、回撤、止损接近度等信息；`sector_concentration` 会优先尝试按板块归类，失败时降级到 `UNCLASSIFIED`，不会阻断风险结果返回。

### Agent 读取持仓

- Agent 可通过 `get_portfolio_snapshot` 获取面向账户的紧凑持仓摘要，默认包含精简风险块，适合控制 Token 开销。
- 可选参数包括 `account_id`、`cost_method`、`as_of`、`include_positions`、`include_risk`。
- 若风险块生成失败，快照仍会返回；若当前环境未启用持仓模块，工具会返回结构化 `not_supported`。
