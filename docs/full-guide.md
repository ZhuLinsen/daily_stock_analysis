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

> *注：以上模型 Key / 渠道至少配置一个；推荐优先从 Anspire 或 AIHubMix 这类一 Key 多模型服务开始。启动时配置校验会在缺少可用 AI 模型 Key 或模型渠道时给出明确错误提示。

#### 通知渠道配置（可同时配置多个，全部推送）

> 通知渠道、minimal/advanced key 分层、Actions 映射、`--check-notify` 诊断、Web 一键测试和本地 / Docker / GitHub Actions / Desktop 场景说明详见 [通知专题文档](notifications.md)。

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `WECHAT_WEBHOOK_URL` | 企业微信 Webhook URL | 可选 |
| `FEISHU_WEBHOOK_URL` | 飞书 Webhook URL | 可选 |
| `FEISHU_WEBHOOK_SECRET` | 飞书 Webhook 签名密钥（开启“签名校验”时必填） | 可选 |
| `FEISHU_WEBHOOK_KEYWORD` | 飞书 Webhook 关键词（开启“关键词”时必填） | 可选 |
| `DINGTALK_WEBHOOK_URL` | 钉钉群机器人 Webhook URL | 可选 |
| `DINGTALK_SECRET` | 钉钉群机器人加签密钥 (SEC开头) | 可选 |
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

> *注：至少配置一个渠道，配置多个则同时推送。启动时配置校验会提示 Telegram / 邮件成对字段缺失，以及常见 Webhook URL 未以 `http://` 或 `https://` 开头的问题。
>
> 当前默认 `00-daily-analysis.yml` 只显式映射固定 Secret / Variable 名称，不会自动把 `STOCK_GROUP_1`、`EMAIL_GROUP_1` 这类任意编号变量导入运行环境，也不会自动导入 `NEWS_INTEL_AUTO_FETCH_ENABLED` 这类新增可选开关。所以分组邮箱功能和本地资讯自动刷新能力目前不适用于仓库自带默认 GitHub Actions workflow；它们适用于本地 `.env`、Docker，或你自行显式扩展过 `env:` 映射的运行环境。Actions 已显式映射 `CUSTOM_WEBHOOK_BODY_TEMPLATE`、`WEBHOOK_VERIFY_SSL`、`FEISHU_WEBHOOK_SECRET`、`FEISHU_WEBHOOK_KEYWORD`、`PUSHPLUS_TOPIC`、`NTFY_URL`、`NTFY_TOKEN`、`GOTIFY_URL`、`GOTIFY_TOKEN`、P3 通知路由键以及 P4 通知降噪键；`MARKDOWN_TO_IMAGE_CHANNELS` 和 `MERGE_EMAIL_NOTIFICATION` 仍作为行为开关不在默认 workflow 中自动映射。

#### 推送行为配置

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `SINGLE_STOCK_NOTIFY` | 单股推送模式：设为 `true` 则每分析完一只股票立即推送 | 可选 |
| `REPORT_TYPE` | 报告类型：`simple`(精简)、`full`(完整)、`brief`(3-5句概括)，Docker环境推荐设为 `full` | 可选 |
| `REPORT_LANGUAGE` | 报告输出语言：`zh`(默认中文) / `en`(英文) / `ko`(韩文)；会同步影响 Prompt、模板、通知 fallback 与 Web 报告页固定文案。`ko` 复用英文结构骨架并通过输出语言指令约束模型用韩文输出，通知按报告语言渲染本地化标签。仓库自带 `00-daily-analysis.yml` 已显式映射该变量，直接在 Actions Secrets/Variables 中配置即可生效 | 可选 |
| `REPORT_SUMMARY_ONLY` | 仅分析结果摘要：设为 `true` 时只推送汇总，不含个股详情；多股时适合快速浏览（默认 false，Issue #262） | 可选 |
| `REPORT_SHOW_LLM_MODEL` | 通知报告底部是否显示本次分析使用的 LLM 模型名称，默认 `true`；设为 `false` 可隐藏运行时模型信息。该变量仅调整展示，不影响 provider/model/Base URL、LiteLLM 路由或运行时模型保存/迁移/清理语义。 | 可选 |
| `REPORT_TEMPLATES_DIR` | Jinja2 模板目录（相对项目根，默认 `templates`） | 可选 |
| `REPORT_RENDERER_ENABLED` | 启用 Jinja2 模板渲染（默认 `false`，保证零回归） | 可选 |
| `REPORT_INTEGRITY_ENABLED` | 启用报告完整性校验，缺失必填字段时重试或占位补全（默认 `true`） | 可选 |
| `REPORT_INTEGRITY_RETRY` | 完整性校验重试次数（默认 `1`，`0` 表示仅占位不重试） | 可选 |
| `REPORT_HISTORY_COMPARE_N` | 历史信号对比条数，`0` 关闭（默认），`>0` 启用 | 可选 |
| `ANALYSIS_DELAY` | 个股分析和大盘分析之间的延迟（秒），避免API限流，如 `10` | 可选 |
| `SAVE_CONTEXT_SNAPSHOT` | 是否保存分析历史 `context_snapshot`，默认 `true`；设为 `false` 或使用 `--no-context-snapshot` 时不持久化整份上下文快照 | 可选 |
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

> 兼容性说明：`REPORT_SHOW_LLM_MODEL` 维持默认 `true` 的原始展示语义，关闭时只影响底部模型文案输出。该配置不会变更 provider/model/Base URL、LiteLLM 路由、模型保存、迁移或清理语义；回退方式为恢复或删除该变量，并设为 `true`。

> 说明：`REPORT_LANGUAGE` 只影响报告文本与 Web 报告页固定文案；WebUI 页面语言（导航、登录页、侧边栏、设置页、通用控件）使用独立状态，不与其联动。
> WebUI 语言状态保存在浏览器 `localStorage` 的 `dsa.uiLanguage`，启动顺序为：
> 1) 明确选择（`localStorage.dsa.uiLanguage`，仅支持 `zh`/`en`）
> 2) 浏览器语言检测（`navigator.languages` / `navigator.language`，`zh-*` 或 `en-*`）
> 3) 默认回退 `zh`。

#### 其他配置

| Secret 名称 | 说明 | 必填 |
|------------|------|:----:|
| `STOCK_LIST` | 自选股代码，如 `600519,300750,002594,7203.T,005930.KS`；推荐使用英文逗号，中文逗号、顿号、分号、空格和换行会被识别并规范为英文逗号 | ✅ |
| `ANSPIRE_API_KEYS` | [Anspire AI Search](https://aisearch.anspire.cn/) 针对中文内容特别优化；同一 Key 可用于搜索与 Anspire 大模型网关的兜底示例（是否可用以控制台与账号权限为准） | 推荐 |
| `SERPAPI_API_KEYS` | [SerpAPI](https://serpapi.com/baidu-search-api?utm_source=github_daily_stock_analysis) 搜索引擎结果补强，适合实时金融新闻 | 推荐 |
| `TAVILY_API_KEYS` | [Tavily](https://tavily.com/) 搜索 API（新闻搜索） | 可选 |
| `BOCHA_API_KEYS` | [博查搜索](https://open.bocha.cn/) Web Search API（中文搜索优化，支持AI摘要，多个key用逗号分隔） | 可选 |
| `BRAVE_API_KEYS` | [Brave Search](https://brave.com/search/api/) API（隐私优先，美股优化，多个key用逗号分隔） | 可选 |
| `MINIMAX_API_KEYS` | [MiniMax](https://platform.minimax.io/) Coding Plan Web Search（结构化搜索结果） | 可选 |
| `SEARXNG_BASE_URLS` | SearXNG 自建实例（无配额兜底，需在 settings.yml 启用 format: json）；留空时默认自动发现公共实例 | 可选 |
| `SEARXNG_PUBLIC_INSTANCES_ENABLED` | 是否在 `SEARXNG_BASE_URLS` 为空时自动从 `searx.space` 获取公共实例（默认 `true`） | 可选 |
| `TUSHARE_TOKEN` | [Tushare Pro](https://tushare.pro/weborder/#/login?reg=834638 ) Token | 可选 |
| `TICKFLOW_API_KEY` | [TickFlow](https://tickflow.org) API Key；可选，用于 A 股日 K、实时行情、股票列表/名称与大盘复盘增强；失败或权限不足时自动回退。 | 可选 |
| `LONGBRIDGE_OAUTH_CLIENT_ID` | [Longbridge OpenAPI](https://open.longbridge.com/) OAuth client_id；留空且无 Legacy Access Token 时会兼容使用 `LONGBRIDGE_APP_KEY` | 可选 |
| `LONGBRIDGE_OAUTH_TOKEN_CACHE_B64` | OAuth token 缓存文件的 base64 内容，供 GitHub Actions / Docker 等 headless 环境恢复 SDK token 缓存 | 可选 |
| `LONGBRIDGE_APP_KEY` | Longbridge Legacy App Key；无 `LONGBRIDGE_ACCESS_TOKEN` 时也可作为 OAuth client_id 兼容别名 | 可选 |
| `LONGBRIDGE_APP_SECRET` | Longbridge App Secret | 可选 |
| `LONGBRIDGE_ACCESS_TOKEN` | Longbridge Legacy Access Token（不是 OAuth access token） | 可选 |
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

> **GitHub Actions：** 仓库自带 `00-daily-analysis.yml` 已把 `TUSHARE_TOKEN`、`TICKFLOW_API_KEY` / `TICKFLOW_*` 和上表中的 `LONGBRIDGE_*` 映射到任务环境。TickFlow 的 API Key 建议放在 **Secrets**，优先级、复权和批量开关可放在 **Variables** 或 **Secrets**。Longbridge OAuth 方式需要一个 client_id（优先 `LONGBRIDGE_OAUTH_CLIENT_ID`；留空且无 Legacy Access Token 时使用 `LONGBRIDGE_APP_KEY` 兼容），并把本机 `~/.longbridge/openapi/tokens/<client_id>` 文件 base64 后保存为 Secret `LONGBRIDGE_OAUTH_TOKEN_CACHE_B64`；Legacy 方式仍可配置 `LONGBRIDGE_APP_KEY`、`LONGBRIDGE_APP_SECRET`、`LONGBRIDGE_ACCESS_TOKEN`。可选接入点变量（如 `LONGBRIDGE_REGION`）可放在 **Variables** 或 **Secrets**。

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
> 兼容性说明（Issue #1306/#1391，顺带确认 #1381）：本节相关改动只复用已有历史写入链路展示大盘复盘结果，不新增 API/API 参数、Web 阶段结果独立展示、日报四阶段结构化持久化或日报状态表，不修改 `provider` / `model` / `base_url` 运行时路由与默认模型行为；#1381 同样仅为后端 runtime 复用，不新增配置迁移/清理/回写分支。若 Issue #1381 的 API/Web/日报结构化验收未同步落地，本 PR 不应作为完整交付收口，需留待后续 PR 继续交付。回退路径为发布回滚（可直接 revert 当前提交，或按现有配置回退链路）。兼容验证主要沿用既有约束检查（`requirements.txt`：`litellm` 版本约束）与既有配置回归测试：`tests/test_system_config_service.py`、`tests/test_system_config_api.py`、`tests/test_llm_channel_config.py`、`tests/test_market_review_runtime.py`；官方源参考：[LiteLLM OpenAI-compatible](https://docs.litellm.ai/docs/providers/openai_compatible)、[OpenAI Chat Completion API](https://platform.openai.com/docs/api-reference/chat)。
> #1391 Phase 2 的结构化检测风险来自 `src/agent/factory.py` 的 `agent_max_steps` / `agent_orchestrator_timeout_s` int 安全兜底，属于配置读取侧的类型兼容增强，不会改写 `litellm_model`、`agent_litellm_model`、`openai_base_url` 或 `LLM_*` 路由状态；回归可复核 `tests/test_agent_pipeline.py::TestAgentConfig::test_build_agent_executor_does_not_mutate_llm_route_config` 与 `tests/test_agent_pipeline.py::TestAgentConfig::test_build_agent_executor_multi_arch_does_not_mutate_llm_route_config`。当配置值非法（如非数字）时，`src.agent.factory` 会记录 warning 并回退到默认值，便于排障与避免误判配置已生效。
> #1815 Phase 3 的兼容边界说明：本轮仅收敛 JP/KR 与 Market Light 的服务边界，不新增 LLM provider/model/base_url 迁移逻辑，不改写 `.env` 主路由模型持久化语义。`MarketSymbol`、告警枚举与快照 `data_quality/limitations` 调整按已有 `.env` 原子 upsert 语义写入保存配置；未显示提交的键不会被清空。
> 本节仅同步模型/渠道配置清单，不额外引入新的外部 provider / Base URL 兼容约定；兼容语义以当前仓库 `requirements.txt` 依赖约束和相关测试为准，历史回退路径见上述两份文档中“回退/恢复”说明。

| 变量名 | 说明 | 默认值 | 必填 |
|--------|------|--------|:----:|
| `GENERATION_BACKEND` | 普通分析生成后端；支持 `litellm` 或显式 opt-in 的 `codex_cli` / `claude_code_cli` / `opencode_cli`（experimental/limited） | `litellm` | 否 |
| `OPENCODE_CLI_MODEL` | `GENERATION_BACKEND=opencode_cli` 时可选传给 OpenCode `--model` 的模型覆盖；留空则使用本机 OpenCode 默认模型，认证和模型可用性由本机 OpenCode 配置负责 | 空 | 否 |
| `GENERATION_FALLBACK_BACKEND` | backend 级 fallback；未配置默认 `litellm`，空值禁用，self fallback 解析为 no-op | `litellm` | 否 |
| `GENERATION_BACKEND_TIMEOUT_SECONDS` | 单次 generation backend 调用超时秒数，主要用于本地 CLI backend；范围 `1-3600` | `300` | 否 |
| `GENERATION_BACKEND_MAX_OUTPUT_BYTES` | 单次本地 CLI backend 诊断 stdout/stderr 与最终响应捕获总上限；`--output-last-message` 重复打印到 stdout 的最终响应不重复计入；范围 `1-33554432` | `1048576` | 否 |
| `GENERATION_BACKEND_MAX_CONCURRENCY` | generation backend 全局并发上限；范围 `1-16`，不改变 LiteLLM Router / `MAX_WORKERS` 行为 | `1` | 否 |
| `LOCAL_CLI_BACKEND_MAX_CONCURRENCY` | 本地 CLI backend 并发上限；范围 `1-4`，有效并发取它与 `GENERATION_BACKEND_MAX_CONCURRENCY` 的较小值 | `1` | 否 |
| `AGENT_GENERATION_BACKEND` | Agent Chat 生成后端；Web 设置页仅暴露 `auto|litellm`，手写 local CLI backend 会返回 unsupported tool-calling 诊断 | `auto` | 否 |
| `LITELLM_MODEL` | 主模型，格式 `provider/model`（如 `gemini/gemini-3.1-pro-preview`），推荐优先使用 | - | 否 |
| `AGENT_LITELLM_MODEL` | Agent 主模型（可选）；留空继承主模型，无 provider 前缀按 `openai/<model>` 解析 | - | 否 |
| `AGENT_CONTEXT_COMPRESSION_ENABLED` | 问股可见对话上下文压缩开关；默认关闭，开启后仅压缩 `session_id` 下 user/assistant 文本历史 | `false` | 否 |
| `AGENT_CONTEXT_COMPRESSION_PROFILE` | 问股上下文压缩策略：`cost` / `balanced` / `long_context_raw_first` | `balanced` | 否 |
| `AGENT_CONTEXT_COMPRESSION_TRIGGER_TOKENS` | 历史 token 估算超过该值时触发压缩；留空则跟随 profile preset | - | 否 |
| `AGENT_CONTEXT_PROTECTED_TURNS` | 压缩时最近 N 个用户轮次及其后的回复保留原文；留空则跟随 profile preset | - | 否 |
| `LITELLM_FALLBACK_MODELS` | 备选模型，逗号分隔 | - | 否 |
| `LLM_CHANNELS` | 渠道名称列表（逗号分隔），配合 `LLM_{NAME}_*` 使用，详见 [LLM 配置指南](LLM_CONFIG_GUIDE.md) | - | 否 |
| `LLM_HERMES_API_KEY` | Hermes reserved 本地 HTTP generation 的单一 API Key；只应来自 `.env`、运行时配置或 Secrets | - | Hermes 使用时必填 |
| `LLM_HERMES_BASE_URL` | Hermes 本地 loopback `/v1` 地址；默认 `http://127.0.0.1:8642/v1`，不支持远程地址 | `http://127.0.0.1:8642/v1` | 否 |
| `LLM_HERMES_MODELS` | Hermes 原始模型列表；Phase 3 默认 `hermes-agent`，运行时 route 为 `openai/hermes-agent`，不支持 Vision / stream / tools / Agent tools | `hermes-agent` | 否 |
| `LITELLM_CONFIG` | 高级模型路由 YAML 配置文件路径（高级） | - | 否 |
| `LLM_PROMPT_CACHE_TELEMETRY_ENABLED` | Provider prompt cache usage / diagnostics 遥测；不控制 provider implicit cache | `true` | 否 |
| `LLM_PROMPT_CACHE_HINTS_ENABLED` | 主分析路径是否主动发送已验证的 provider-specific prompt cache hints；Agent 路径当前仅记录 diagnostics，不主动发 hints；默认关闭 | `false` | 否 |
| `LLM_PROMPT_CACHE_DIAGNOSTICS_LEVEL` | Prompt cache 诊断级别：`off` / `basic` / `debug`；basic/debug 仅在 debug 日志和测试可观察对象中提供脱敏诊断，不作为公开 Usage API 或普通设置页输出 | `off` | 否 |
| `LLM_USAGE_HMAC_SECRET` | LLM 用量遥测 message HMAC 密钥；留空时自动使用数据目录中的本地密钥文件 | - | 否 |
| `LLM_USAGE_HMAC_KEY_VERSION` | LLM 用量遥测 HMAC 密钥版本标签，轮换密钥时同步更新 | `local-v1` | 否 |
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

> GitHub Actions 说明：仓库自带 `00-daily-analysis.yml` 在 `GENERATION_FALLBACK_BACKEND` 未配置时显式使用 `litellm`，避免未设置的 Secret/Variable 被导出为空值并意外禁用 backend fallback。若要在 Actions 中禁用 backend fallback，请将 fallback 设为 primary backend，让 resolver 走 self no-op。

> 生成后端状态说明：Web 设置页的快速检查只读取已保存配置、未保存草稿，并检查本地 CLI 可执行文件是否可见，不发起真实模型请求；JSON 冒烟测试是单独的显式操作，会使用服务端固定的 JSON 提示词和 schema 发起一次真实请求。`health_status` 与 `last_error_code/message` 只表示本次状态计算或冒烟测试结果，不是历史持久健康状态。

> *注：`ANSPIRE_API_KEYS`、`AIHUBMIX_KEY`、`GEMINI_API_KEY`、`ANTHROPIC_API_KEY`、`OPENAI_API_KEY` 或 `OLLAMA_API_BASE` 至少配置一个。`ANSPIRE_API_KEYS` 与 `AIHUBMIX_KEY` 无需配置 `OPENAI_BASE_URL`，系统自动适配。

> 问股 single-agent 路径会在后台为 DeepSeek V4 thinking + tool-call 保存最近 3 条 provider trace，并按原时序回放 `reasoning_content` / tool 结果；该能力不新增配置项，不进入 Web 历史 API，Claude extended thinking 仅覆盖离线 plumbing，multi-agent trace 注入留作后续增强。

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
| `DISCORD_MAX_WORDS` | Discord 单条消息 content 上限（默认 2000；运行时不会超过 Discord 2000 字符限制，长报告会自动分片并对 429 限流做有限重试） | 可选 |
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

> 说明：默认 `00-daily-analysis.yml` GitHub Actions workflow 只映射固定变量名，不会自动导入任意编号的 `STOCK_GROUP_N` / `EMAIL_GROUP_N`。因此分组邮箱目前仅在本地 `.env`、Docker 或其他已显式注入这些环境变量的运行环境中生效；若你要在自己的 GitHub Actions 中使用，需在 workflow 的 job `env:` 中逐组显式映射。

#### 飞书云文档配置（可选，解决消息截断问题）

| 变量名 | 说明 | 必填 |
|--------|------|:----:|
| `FEISHU_APP_ID` | 飞书应用 ID | 可选 |
| `FEISHU_APP_SECRET` | 飞书应用 Secret | 可选 |
| `FEISHU_FOLDER_TOKEN` | 飞书云盘文件夹 Token | 可选 |
| `FEISHU_SEND_AS_FILE` | 飞书 App Bot 以文件形式发送报告（默认 `false`） | 可选 |

> 飞书云文档配置步骤：
> 1. 在 [飞书开发者后台](https://open.feishu.cn/app) 创建应用
> 2. 配置 GitHub Secrets
> 3. 创建群组并添加应用机器人
> 4. 在云盘文件夹中添加群组为协作者（可管理权限）
>
> 说明：`FEISHU_APP_ID` / `FEISHU_APP_SECRET` 用于飞书应用、云文档或 Stream Bot 模式，不会直接启用群 Webhook 推送。只想简单收群通知时，请优先配置 `FEISHU_WEBHOOK_URL`。
>
> 补充：若同时配置 `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 和 `FEISHU_CHAT_ID`，则可启用飞书 App Bot 主动通知渠道，无需 Webhook 即可主动向指定 chat 或用户推送；`FEISHU_RECEIVE_ID_TYPE` 默认 `chat_id`，私聊时改为 `open_id`。该方式走飞书 OpenAPI Bot 会话，与群 Webhook 是两条独立链路。

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

### 新闻检索可解释排序（Issue #1356）

`search_stock_news` 对每条候选新闻会计算「可解释相关度」并落地为 3 类标签：

- `direct_company_news`：命中目标代码、公司名（含官方/交易所来源加权）；
- `sector_related_news`：命中行业板块语义；
- `macro_market_news`：未命中目标主体时的宏观/市场语境新闻。

排序策略为：先按类别优先级（direct > sector > macro）排序，再按语言偏好（中文优先）再按分数排序，因此当同一时窗内存在明确标的命中的新闻时会优先展示。

排序后还会执行一层域名无关的准入过滤：明显的下载/安装包/应用评分页、成人/招嫖服务垃圾页会被剔除；当同一批次已经存在直接标的或有分数的行业/市场候选时，`score=0` 的背景填充项不会进入 `news_context`、Agent 工具输出或历史情报缓存。该规则不内置具体网站黑名单，避免靠穷举域名维护。

调试入口：

- 每条返回会保留 `relevance_score` / `relevance_category` / `relevance_reasons` 元数据，最终 `to_text()` 与情报上下文会附带对应「关联度」说明；
- 搜索链路日志会输出 `[新闻相关度]` 统计，便于复盘为何该批次触发了 direct/sector/macro 分层。

兼容与回退说明：该改动不新增/修改模型、provider、Base URL、LiteLLM route、配置清理或回写逻辑；若出现异常，只能通过回滚本次提交恢复旧排序行为，不涉及历史配置迁移。

### 数据源配置

| 变量名 | 说明 | 默认值 | 必填 |
|--------|------|--------|:----:|
| `TUSHARE_TOKEN` | Tushare Pro Token | - | 可选 |
| `TICKFLOW_API_KEY` | TickFlow API Key；可选，用于 A 股日 K、实时行情、股票列表/名称与大盘复盘增强；失败或权限不足时自动回退。 | - | 可选 |
| `TICKFLOW_PRIORITY` | TickFlow 日 K 数据源优先级；数字越小越早尝试，默认 `2`；未配置 API Key 时不启用；不影响实时行情，实时行情顺序由 `REALTIME_SOURCE_PRIORITY` 控制。 | `2` | 可选 |
| `TICKFLOW_KLINE_ADJUST` | TickFlow 日 K 复权模式：`none`、`forward`、`backward`、`forward_additive`、`backward_additive`。 | `none` | 可选 |
| `TICKFLOW_BATCH_DAILY_ENABLED` | 是否启用 TickFlow 批量日 K 预取；权限不足会短期缓存失败状态，并继续走常规回退。 | `true` | 可选 |
| `TICKFLOW_BATCH_SIZE` | TickFlow 日 K 与实时行情批量请求的单批最大标的数。 | `100` | 可选 |
| `LONGBRIDGE_OAUTH_CLIENT_ID` | Longbridge OAuth client_id；留空且无 Legacy Access Token 时会兼容使用 `LONGBRIDGE_APP_KEY` | - | 可选 |
| `LONGBRIDGE_OAUTH_TOKEN_CACHE_B64` | OAuth token 缓存文件的 base64 内容，供 GitHub Actions / Docker 等 headless 环境使用 | - | 可选 |
| `LONGBRIDGE_APP_KEY` | Longbridge Legacy App Key；无 `LONGBRIDGE_ACCESS_TOKEN` 时也可作为 OAuth client_id 兼容别名 | - | 可选 |
| `LONGBRIDGE_APP_SECRET` | Longbridge App Secret | - | 可选 |
| `LONGBRIDGE_ACCESS_TOKEN` | Longbridge Legacy Access Token（不是 OAuth access token） | - | 可选 |
| `LONGBRIDGE_*`（可选） | 见官方 [环境变量](https://open.longbridge.com/zh-CN/docs/getting-started#环境变量)；另有 `LONGBRIDGE_STATIC_INFO_TTL_SECONDS` 与 `LONGBRIDGE_CONNECTION_COOLDOWN_SECONDS` | - | 可选 |
| `ENABLE_REALTIME_QUOTE` | 启用实时行情（关闭后使用历史收盘价分析） | `true` | 可选 |
| `ENABLE_REALTIME_TECHNICAL_INDICATORS` | 盘中实时技术面：启用时用实时价计算 MA5/MA10/MA20 与多头排列（Issue #234）；关闭则用昨日收盘 | `true` | 可选 |
| `ENABLE_CHIP_DISTRIBUTION` | 启用筹码分布分析（该接口不稳定，云端部署建议关闭）。GitHub Actions 用户需在 Repository Variables 中设置 `ENABLE_CHIP_DISTRIBUTION=true` 方可启用；workflow 默认关闭。 | `true` | 可选 |
| `ENABLE_EASTMONEY_PATCH` | 东财接口补丁：东财接口频繁失败（如 RemoteDisconnected、连接被关闭）时建议设为 `true`，注入 NID 令牌与随机 User-Agent 以降低被限流概率 | `false` | 可选 |
| `REALTIME_SOURCE_PRIORITY` | 实时行情源优先级，逗号分隔，例如 `tencent,akshare_sina,efinance,akshare_em`；需要显式加入 `tickflow` 才会使用 TickFlow 实时行情。 | 见 `.env.example` | 可选 |
| `ENABLE_FUNDAMENTAL_PIPELINE` | 基本面聚合总开关；关闭时仅返回 `not_supported` 块，不改变原分析链路 | `true` | 可选 |
| `FUNDAMENTAL_STAGE_TIMEOUT_SECONDS` | 基本面阶段总时延预算（秒） | `8.0` | 可选 |
| `FUNDAMENTAL_FETCH_TIMEOUT_SECONDS` | 单能力源调用超时（秒）；市场结构行业/概念排行也复用该预算 | `8.0` | 可选 |
| `FUNDAMENTAL_RETRY_MAX` | 基本面能力重试次数（含首次） | `1` | 可选 |
| `FUNDAMENTAL_CACHE_TTL_SECONDS` | 基本面聚合缓存 TTL（秒），短缓存减轻重复拉取 | `120` | 可选 |
| `FUNDAMENTAL_CACHE_MAX_ENTRIES` | 基本面缓存最大条目数（TTL 内按时间淘汰） | `256` | 可选 |

> 行为说明：
> - A 股：按 `valuation/growth/earnings/institution/capital_flow/dragon_tiger/boards` 聚合能力返回；
> - ETF：返回可得项，缺失能力标记为 `not_supported`，整体不影响原流程；
> - 美股/港股：通过 yfinance 适配器返回 `valuation/growth/earnings/belong_boards`（来源 `info.sector`/`industry`），`institution/capital_flow/dragon_tiger/boards` 暂无对应数据源仍标记 `not_supported`；yfinance 不可用或字段缺失时整体降级回 `not_supported`，仍走 fail-open；
> - 日股/韩股：当前仅走 Yfinance 基础路径获取日线与实时行情；`institution`、`capital_flow`、`dragon_tiger`、`boards` 等依赖 A 股专属源/离岸完整版的能力会降级为 `not_supported`（详见 [市场支持与边界](market-support.md)）；
> - 台股：在美股/港股 offshore 基础路径之外，`institution` 区块额外展示三大法人原始买卖超净额（TWSE T86 / TPEx，默认开启、fail-open，取不到数据时维持 `not_supported`）；`capital_flow`、`dragon_tiger`、`boards` 仍为 `not_supported`；
> - 任何异常走 fail-open，仅记录错误，不影响技术面/新闻/筹码主链路。
> - 配置 `TICKFLOW_API_KEY` 后，TickFlow 会作为可选 A 股日 K 数据源和大盘复盘增强源实例化；`TICKFLOW_PRIORITY` 只影响日 K/通用数据源回退链。实时行情优先级由 `REALTIME_SOURCE_PRIORITY` 单独控制，只有显式包含 `tickflow` 时才会使用 TickFlow 实时行情。`REALTIME_SOURCE_PRIORITY` 中排在 `tickflow` 前面的数据源会先被尝试。
> - TickFlow 日 K 默认 `TICKFLOW_KLINE_ADJUST=none`；日线 `volume` 从手统一转为股，`amount` 保持元口径。
> - TickFlow 日 K 区间请求会显式传入 `start_time` / `end_time` / `count`；官方 quickstart 明确说明时间范围查询仍受 `count` 限制。若返回非空但行数打满 `count` 且首个返回交易日晚于请求起始交易日，系统会判定为疑似截断，不写入缓存并让 manager 继续回退。
> - 批量分析时，`prefetch_daily_klines()` 会在逐股 `get_daily_data()` 之前预热进程内缓存，不改变对外调用路径。
> - TickFlow 能力按套餐权限分层：有限权限套餐仍可使用主指数查询；支持 `CN_Equity_A` 标的池查询的套餐才会启用 TickFlow 市场统计。
> - TickFlow 可通过申万一级行业标的池与全 A 股行情生成行业涨跌排行，并优先参与市场结构行业主线 fallback；概念题材排行仍由现有 AkShare / Tushare / Efinance 链路提供。
> - TickFlow 官方 quickstart 提供了 `quotes.get(universes=["CN_Equity_A"])` 用法，但不同 API Key 不一定拥有对应权限；批量日 K、深度和财务等能力也按权限 fail-open。
> - TickFlow 实际返回的 `change_pct` / `amplitude` 为比例值；系统已在接入层统一转换为百分比值，确保与现有数据源字段语义一致。
> - A 股大盘复盘报告采用盘后工作台式结构：固定包含盘面信号、指数明细、板块 Top 表、近三日市场线索、明日交易计划和风险提示；盘面信号以 `66/100（偏暖，可进攻）` 这类纯文本分数表达，避免色块进度条在不同终端显示不一致；近三日市场线索只列标题、来源和链接，不再展示搜索摘要片段；若部分数据源缺失，则保留可用区块并在对应位置降级展示。
> - 字段契约：
>   - `fundamental_context.belong_boards` = 个股关联板块列表；A 股从 AkShare 板块名单写入，美股/港股从 yfinance `info.sector` / `info.industry` 写入，无数据时为 `[]`；
>   - `fundamental_context.boards.data` = `sector_rankings`（板块涨跌榜，结构 `{top, bottom}`，HK/US 当前不提供）；
>   - `fundamental_context.concept_boards.data` = `concept_rankings`（概念/题材涨跌榜，结构 `{top, bottom}`，当前仅 A 股提供；不可用时 fail-open 为空或缺失）；
>   - `fundamental_context.earnings.data.financial_report` = 财报摘要（报告期、营收、归母净利润、经营现金流、ROE，及 `currency` 来源 `info.financialCurrency`，HK ADR 常见为 CNY）；
>   - `fundamental_context.earnings.data.dividend` = 分红指标（仅现金分红税前口径，含 `events`、`ttm_cash_dividend_per_share`、`ttm_dividend_yield_pct`、`currency`）。`currency` 独立读取自 `info.currency`，与 `financial_report.currency` 可能不同（HK ADR 财报 CNY、分红 HKD）；TTM yield 默认按 `ttm_cash / latest_price * 100`（同币种）即时重算，仅在 TTM cash 或 latest price 缺失时回退到 yfinance `trailingAnnualDividendYield` 或 `dividendYield`；
>   - `get_stock_info.belong_boards` = 个股所属板块列表；
>   - `get_stock_info.boards` 为兼容别名，值与 `belong_boards` 相同（未来仅在大版本考虑移除）；
>   - `get_stock_info.sector_rankings` 与 `fundamental_context.boards.data` 保持一致。
>   - `AnalysisReport.details.belong_boards` = 结构化报告详情中的关联板块列表；
>   - `AnalysisReport.details.sector_rankings` = 结构化报告详情中的板块涨跌榜（用于前端板块联动展示）。
>   - `AnalysisReport.details.concept_rankings` = 结构化报告详情中的概念/题材涨跌榜（用于前端关联板块信号匹配，以及通知表格按类型区分行业/概念）。
> - 板块涨跌榜使用数据源顺序：与全局 priority 一致。
> - 超时控制为 `best-effort` 软超时：阶段会按预算快速降级继续执行，但不保证硬中断底层三方调用。
> - `FUNDAMENTAL_STAGE_TIMEOUT_SECONDS=8.0` 表示新增基本面阶段的目标预算，不是严格硬 SLA；Windows、Docker 或免费数据源被限流时可继续调高到 `12-15s`。
> - 若要硬 SLA，请在后续版本升级为子进程隔离执行并在超时后强制终止。

### 其他配置

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `STOCK_LIST` | 自选股代码（逗号分隔） | - |
| `ADMIN_AUTH_ENABLED` | Web 登录：设为 `true` 启用密码保护；首次访问在网页设置初始密码，可在「系统设置 > 修改密码」修改；忘记密码执行 `python -m src.auth reset_password`。Web 的 `.env` 备份导入导出仅在开启该开关后可用（桌面端不受此限制）。 | `false` |
| `TRUST_X_FORWARDED_FOR` | 单层可信反向代理部署时设为 `true`，取 `X-Forwarded-For` 最右值作为真实客户端 IP（用于登录限流等）；直连公网时保持 `false` 防伪造。多级代理/CDN 场景下限流 key 可能退化为边缘代理 IP，需额外评估 | `false` |
| `MAX_WORKERS` | 并发线程数 | `3` |
| `MARKET_REVIEW_ENABLED` | 启用大盘复盘 | `true` |
| `DAILY_MARKET_CONTEXT_ENABLED` | 将当日大盘环境摘要注入个股分析 Prompt，并在高风险/退潮环境下软化激进买入建议；默认开启，设为 `false` 后仍可运行大盘复盘 | `true` |
| `MARKET_REVIEW_REGION` | 大盘复盘市场区域：cn(A股)、hk(港股)、us(美股)、jp(日股)、kr(韩股)、both(五市场)，us/jp/kr 适合仅关注单区域用户 | `cn` |
| `MARKET_REVIEW_COLOR_SCHEME` | 大盘复盘指数涨跌颜色：`green_up`=绿涨红跌（默认），`red_up`=红涨绿跌 | `green_up` |
| `TRADING_DAY_CHECK_ENABLED` | 交易日检查：默认 `true`，非交易日跳过执行；设为 `false` 或使用 `--force-run` 可强制执行（Issue #373） | `true` |
| `SCHEDULE_ENABLED` | 启用定时任务 | `false` |
| `SCHEDULE_TIME` | 定时执行时间 | `18:00` |
| `SCHEDULE_TIMES` | 多个定时执行时间，逗号分隔；为空时使用 `SCHEDULE_TIME` | 空 |
| `LOG_DIR` | 日志目录 | `./logs` |
| `SAVE_CONTEXT_SNAPSHOT` | 保存分析历史 `context_snapshot`；设为 `false` 时新历史不保存 enhanced_context、market_phase_summary、AnalysisContextPack overview 或诊断快照，但不关闭当次 Prompt 低敏摘要 | `true` |

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

默认 Compose 为每个服务设置 `limits.memory: 1G`、`reservations.memory: 512M`。`512M` 仅建议用于轻量 Web/API、单股、低并发场景，并将 `MAX_WORKERS=1`；常规完整分析建议 `1G`，同时启动 `server + analyzer`、多股票、大盘复盘、新闻扩展、图片报告或 AlphaSift 建议 `2G+`。如果只能使用 `512M`，请避免同时启动两个服务并减少重型功能。

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
  zhulinsen/daily_stock_analysis:latest \
  python main.py --serve-only --host 0.0.0.0 --port 8000

# 定时任务模式
docker run -d \
  --name dsa-analyzer \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/reports:/app/reports" \
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
    - ../strategies:/app/strategies:ro
  deploy:
    resources:
      limits:
        memory: 1G
      reservations:
        memory: 512M

services:
  # 定时任务模式
  analyzer:
    <<: *common
    container_name: stock-analyzer

  # FastAPI 模式
  server:
    <<: *common
    container_name: stock-server
    command: ["python", "main.py", "--serve-only", "--host", "0.0.0.0", "--port", "${API_PORT:-8000}"]
    ports:
      - "${API_PORT:-8000}:${API_PORT:-8000}"
```

### `.env` 与数据目录映射说明

无论你使用 `docker run` 还是 Compose，都需要区分启动环境变量注入和运行时文件写入：

- 环境变量注入：`--env-file .env` 或 Compose 的 `env_file`
  作用：把 `.env` 中的键值作为容器启动时的环境变量传入 Python 进程。
- 运行时配置写入：不要把宿主机 `.env` 作为单文件 bind mount 覆盖容器内 `.env` 路径。Docker 会把单文件挂载目标作为 mount point，配置保存时的 `os.replace()` 原子更新可能失败并报 `Device or resource busy`，回退写入也可能受权限限制。

默认 Compose 和 `docker run` 示例仅使用 `env_file` / `--env-file` 注入启动配置，不再把宿主机 `.env` 单文件挂载进容器。WebUI 设置页会在当前活跃 `.env` 文件缺少某些键时展示启动注入的同名环境变量作为兜底，避免 Docker 用户误以为配置完全未读取；但“导出 `.env`”仍只导出当前活跃配置文件内容。

WebUI 中保存的运行时配置默认写入容器内部配置文件，不等同于回写宿主机 `.env`；删除或重建容器后仍以启动时注入的 `.env` 为准。若需要持久化运行时配置，请将写入目标放到可写数据卷中（例如通过 `ENV_FILE=/app/data/runtime.env` 指向 `data` volume 中的文件），不要使用 `.env` 单文件 bind mount。注意：如果启动时的 `env_file`、`--env-file`、`docker run -e` 或 Compose `environment:` 中仍保留同名旧值，容器重启时这些进程环境变量仍可能覆盖运行时文件中的保存值；要让 WebUI 保存值接管，请同步更新或移除启动环境中的同名覆盖。

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

Windows PowerShell 若仍使用系统默认代码页，首次安装依赖或运行环境检查前建议先启用 UTF-8，避免第三方工具或终端输出在中文字符上失败：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
python -m pip install -r requirements.txt
python scripts/check_env.py --config
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

编辑 `.github/workflows/00-daily-analysis.yml`:

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

`00-daily-analysis.yml` 支持两种控制方式：

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
> 从 `python main.py --schedule` 或等价纯 CLI 调度模式启动后，WebUI 保存新的 `SCHEDULE_TIME` / `SCHEDULE_TIMES` 会在下一轮调度检查内自动重绑 daily jobs，无需重启进程；旧的执行时间不会继续保留。`python main.py --serve --schedule` 会由 Web/API runtime scheduler 接管定时任务，WebUI/API/Desktop 长运行进程保存 `SCHEDULE_ENABLED`、`SCHEDULE_TIME` 或 `SCHEDULE_TIMES` 后会按当前配置启停或重建 runtime scheduler。
>
> Web/API runtime scheduler 的立即执行入口只会在没有分析任务运行时接受请求；如果已有分析在执行，会返回忙碌状态而不是假装排队成功。

#### 环境变量方式

你也可以通过环境变量配置定时行为（适用于 Docker 或 .env）：

| 变量名 | 说明 | 默认值 | 示例 |
|--------|------|:-------:|:-----:|
| `SCHEDULE_ENABLED` | 是否启用定时任务 | `false` | `true` |
| `SCHEDULE_TIME` | 每日执行时间 (HH:MM) | `18:00` | `09:30` |
| `SCHEDULE_TIMES` | 多个每日执行时间，逗号分隔；为空时使用 `SCHEDULE_TIME` | 空 | `09:20,12:30,15:10,18:00` |
| `SCHEDULE_RUN_IMMEDIATELY` | 定时模式启动时是否立即运行一次；未显式设置时沿用 `RUN_IMMEDIATELY` 的运行时覆盖语义 | `true` | `false` |
| `RUN_IMMEDIATELY` | 非定时模式启动时是否立即运行一次；同时作为未显式设置 `SCHEDULE_RUN_IMMEDIATELY` 时的 legacy 回退 | `true` | `false` |
| `TRADING_DAY_CHECK_ENABLED` | 交易日检查：非交易日跳过执行；设为 `false` 可强制执行 | `true` | `false` |

例如在 Docker 中配置：

```bash
# 设置启动时不立即分析
docker run -e SCHEDULE_ENABLED=true -e SCHEDULE_RUN_IMMEDIATELY=false ...
```

> 兼容说明：如果运行时显式传入 `RUN_IMMEDIATELY`，但没有单独传 `SCHEDULE_RUN_IMMEDIATELY`，内置调度模式会继续继承前者，避免被 `.env` 中持久化的 `SCHEDULE_RUN_IMMEDIATELY` 旧值反向覆盖。

> 兼容说明（Issue #1815）：`MARKET_REVIEW_REGION=cn|hk|us|jp|kr|both` 仅扩展大盘复盘输入集合；JP/KR 仅供复盘上下文消费，不会放开 Market Light 告警。
> - `src/config.py`、`src/core/config_registry.py`、`src/services/system_config_service.py` 的改动仅是配置语义扩展，不改 `provider`/`model`/`base_url` 的运行时路由，也不触发 provider/model/base URL 迁移或清理逻辑。
> - 本轮实际受控配置项：`MARKET_REVIEW_REGION`、`MARKET_REVIEW_COLOR_SCHEME`；`LITELLM_MODEL`、`AGENT_LITELLM_MODEL`、`LITELLM_FALLBACK_MODELS`、`VISION_MODEL`、`OPENAI_BASE_URL` 等旧值保持原子 upsert 语义，不会在更新其他字段时被静默清空或覆盖。
> - 可核验证据摘要：官方 provider / Base URL / 模型命名来源沿用 [LLM 配置指南](LLM_CONFIG_GUIDE.md#常用官方文档来源用于核对预设-provider--base-url--模型命名)，当前运行时依赖窗口沿用 `requirements.txt` 中的 `litellm>=1.80.10,!=1.82.7,!=1.82.8,<2.0.0`；本轮不新增配置迁移脚本或清理分支，保存/导入仍只写本次提交键。`tests/test_system_config_service.py::SystemConfigServiceTestCase::test_update_market_review_region_does_not_trigger_runtime_model_cleanup` 覆盖只保存 `MARKET_REVIEW_REGION` 时不清空或改写 `LITELLM_CONFIG`、`LLM_CHANNELS`、`LLM_OPENAI_*`、`LITELLM_MODEL`、`AGENT_LITELLM_MODEL`、`LITELLM_FALLBACK_MODELS`、`VISION_MODEL`、`OPENAI_*` 等旧配置。
> - 旧值回退策略：先恢复备份 `MARKET_REVIEW_REGION` 与配置文件即可回到旧边界，未提交的模型/路由键保留原值；必要时 `revert` PR 并按 `.env` 备份完成回退。
> - 可回滚路径：恢复提交前 `.env` / 配置备份中的 `MARKET_REVIEW_REGION` 与相关运行时变量，或直接 revert 本 PR。

#### 交易日判断（Issue #373）

默认根据自选股市场（A 股 / 港股 / 美股 / 日股 / 韩股）和 `MARKET_REVIEW_REGION` 判断是否为交易日：
- 使用 `exchange-calendars` 区分 A 股 / 港股 / 美股 / 日股 / 韩股各自的交易日历（含节假日）
- 混合持仓时，每只股票只在其市场开市日分析，休市股票当日跳过
- 全部相关市场均为非交易日时，整体跳过执行（不启动 pipeline、不发推送）
- 断点续传和 `--dry-run` 的“数据已存在”判断共用同一套“最新可复用交易日”解析逻辑，不再直接使用服务器自然日
- `最新可复用交易日` 会按股票所属市场的本地时区解析：A 股使用 `Asia/Shanghai`，港股使用 `Asia/Hong_Kong`，美股使用 `America/New_York`，日股使用 `Asia/Tokyo`，韩股使用 `Asia/Seoul`
- 非交易日（周末 / 节假日）运行时，会回退到最近一个交易日检查本地数据；若该交易日数据已存在，则跳过重复抓取，否则继续补数
- 交易日盘中或收盘前运行时，会以上一个已完成交易日作为复用目标；交易日收盘后运行时，当日数据已存在则可直接跳过，不存在则继续抓取
- 覆盖方式：`TRADING_DAY_CHECK_ENABLED=false` 或 命令行 `--force-run`

#### 市场阶段基线（Issue #1386 P0）

P0 只新增内部市场阶段推断基线，不改变现有每日收盘报告、交易日跳过、断点续传、API、Web、Bot、Agent 或 GitHub Actions 默认行为。阶段推断用于后续 P1+ 的上下文契约准备；未安装 `exchange-calendars` 或日历异常时，阶段返回 `unknown`，但现有交易日判断和最新可复用交易日逻辑仍保持原来的 fail-open 行为。

阶段枚举基于 regular session 语义：

| 阶段 | 含义 |
| --- | --- |
| `premarket` | 常规交易时段开盘前；不代表已经获取盘前扩展时段行情 |
| `intraday` | 常规交易时段内，且不处于午休或临近收盘窗口 |
| `lunch_break` | 市场日历提供的午间休市窗口；无午休市场不会进入此阶段 |
| `closing_auction` | 临近收盘启发式窗口：A 股 3 分钟、港股 10 分钟、美股 5 分钟、台股 5 分钟（13:25–13:30）；不代表完整交易所竞价制度 |
| `postmarket` | 常规交易时段收盘后；不代表已经获取盘后扩展时段行情 |
| `non_trading` | 当前市场本地日期不是交易日 |
| `unknown` | 未知市场、日历不可用或日历异常，无法可靠推断阶段 |

当前入口现状：

- 普通个股分析、Agent 分析、Web 手动分析、Bot `/analyze` / `/ask`、schedule、GitHub Actions 仍沿用既有分析路径和盘后复盘口径，不会因为 P0 阶段基线自动切换 Prompt 或输出结构。
- 大盘复盘仍按 `MARKET_REVIEW_REGION` 与交易日过滤运行，不消费市场阶段标签。
- 跨市场混合自选股应按每个 symbol 自身市场分别推断阶段；聚合报告展示“多市场阶段不一致”留给 P1+。

已知问题基线：

- 盘中触发时，报告仍可能把尚未收盘的日内行情写成完整交易日复盘。
- 输出仍可能偏向“今日走势复盘 / 明日关注”，而不是“当前盘中下一步观察”。
- 实时行情时间戳、数据源、缓存和 stale 状态还没有统一进入阶段上下文。
- 午间休市、临近收盘、非交易日强制运行等场景还没有被 Prompt 和报告结构显式表达。

P0 不做：不接入 pipeline / Agent / API / Web / Bot，不修改报告 schema，不改告警 technical indicator 的 partial bar 判断，也不新增配置项。

#### 运行态市场阶段上下文（Issue #1386 P1a）

P1a 在普通个股分析 pipeline、legacy Agent context 和 multi-agent `ctx.meta` 中构造并传递内部 `market_phase_context`。该上下文包含市场、阶段、市场本地日期、最新可复用日线日期、交易日/开市/partial bar 三态标记、开收盘分钟数 best-effort 估算，以及 `unknown_market`、`calendar_unavailable`、`calendar_error` 等降级 warning code。

P1a 本身不改变 Prompt 文案、API/Web/Bot 参数、报告结构、history/task status 稳定 metadata 或 quote freshness/data quality 语义；普通分析 history snapshot 和 Agent history snapshot 会剥离该运行态字段。后续 P1b 再定义可持久化 metadata 与任务状态展示契约。

#### 市场阶段低敏 Metadata（Issue #1386 P1b）

P1b 将 P1a 的 runtime `market_phase_context` 投影为稳定、低敏、可公开的 `market_phase_summary`，并写入 `analysis_history.context_snapshot` 顶层。历史详情、同步分析响应和 completed `/api/v1/analysis/status/{task_id}` 都通过 `report.meta.market_phase_summary` 返回同一份市场阶段元信息；completed 任务状态不新增 `TaskStatus` 顶层字段，只通过 `status.result.report.meta.market_phase_summary` 间接暴露。

`market_phase_summary` 只包含市场、阶段、市场本地时间、session date、effective daily-bar date、交易日/开市/partial-bar 标记、开收盘分钟数、触发来源、分析意图和 warning code。它不暴露完整 `market_phase_context`，也不加入 quote freshness、fallback、stale 或 data_quality scoring 字段。`report.details.analysis_context_pack_overview` 仍表示 #1389 输入数据块质量摘要；API 返回的 `details.context_snapshot` 会剥离顶层 `market_phase_summary` 和 `analysis_context_pack_overview`，避免 raw snapshot 重复展示这些稳定公开字段。`SAVE_CONTEXT_SNAPSHOT=false` 时不持久化整份 `analysis_history.context_snapshot`，旧历史记录缺少 summary 时字段为空，报告仍正常返回。

P1b 不改 Prompt、不新增 `analysis_phase` 请求参数、不做 Web 阶段标签或页面展示，也不覆盖 pending/processing TaskPanel、SSE 进行中事件、Bot、通知、`market_review` 或 P3 盘中数据质量字段。

#### 市场阶段 Prompt 注入（Issue #1386 P2-min）

P2-min 开始在已获得 `market_phase_context` 的分析路径中，把运行态市场阶段渲染为 LLM 可读的 Prompt 区块。普通分析、single Agent 和 multi-agent 会在 Prompt 中看到当前阶段、市场本地时间、最新可复用完整日线日期以及最小阶段约束：盘前不得描述“今日走势已经发生”，盘中 / 午间 / 临近收盘需说明最后一根日线可能未完成，盘后保留完整交易日复盘语义，非交易日或未知阶段保持保守表述。

P2-min 仍不新增 API/Web/Bot 参数，不写入 history/task status/report metadata，不改变报告 JSON schema，也不引入完整 quote freshness、fallback、stale 或 data_quality 契约。Bot/API 直连 Agent 若未经过 P1a pipeline 构建 `market_phase_context`，仍保持旧行为；入口透传和可见展示留给后续 P4+。

#### 盘中数据包与实时质量控制（Issue #1386 P3）

P3 补齐普通分析主路径使用的实时行情质量元数据，但仍不新增 `analysis_phase` 参数，不改 API/Web/Bot 阶段入口，不改变报告 JSON schema，也不做 #1389 P5 数据质量评分或模型置信度限制。实时 quote 会带上 `fetched_at`、`provider_timestamp`、`is_stale`、`stale_seconds`、`fallback_from`；其中 `fetched_at` 是系统获取时间，`provider_timestamp` 只在 provider 真实提供行情时间时填写。缺少 provider 时间时不会伪造 fresh，`stale_seconds` 和 `is_stale` 保持空值。

整源 fallback 的语义固定为：`source` 保留实际成功的数据源 token，`fallback_from` 记录本轮失败的最高优先级整源 token；首选源成功后只从后续源补字段时不写 `fallback_from`。`AnalysisContextBuilder` 只映射这些上游 artifact，不重新取数、不做质量评分；quote block 状态按 `STALE > FALLBACK > AVAILABLE` 归并。盘中实时价覆盖 `today` 时会标记 `is_partial_bar`、`is_estimated`、`estimated_fields`、`realtime_source` 和 quote 元数据；`daily_bars` block 仍表示 storage 中完整日线窗口，partial/estimated 只进入 technical block。freshness scoring、盘中 cache TTL 分级、Agent 工具级复用和 API/Web 展示留给后续阶段。

#### 分析阶段入口与任务队列透传（Issue #1386 P4a）

P4a 新增 `analysis_phase=auto|premarket|intraday|postmarket` 请求参数，默认 `auto`，用于让 API 调用方显式覆盖本次分析阶段。该参数目前接入 `POST /api/v1/analysis/analyze`、异步任务队列、`AnalysisService`、普通分析 pipeline 和市场阶段上下文；Web 前端类型和 API mapper 已承接该字段，但不新增页面 selector，Bot、schedule、GitHub Actions 和 DB migration 也不在本阶段范围内。

`analysis_phase` 是请求覆盖值；最终报告阶段仍以 `report.meta.market_phase_summary.phase` 为准。异步 accepted response、内存任务 status、任务列表和 SSE payload 会回显请求阶段；历史 DB fallback 不新增持久化字段，旧记录仍可能为空。同股不同 phase 仍按同一个股票任务去重，避免并发重复分析。

内部阶段上下文构造仍兼容旧参数 `analysis_intent`：仅当 `analysis_phase` 保持 `auto` 时，非 `auto` 的 `analysis_intent` 会被归一为本次请求阶段；外部调用方应优先使用 `analysis_phase`。

`auto` 保持既有交易日历推断；非 `auto` 只覆盖 phase 并重算 `is_trading_day`、`is_market_open_now`、`is_partial_bar`、`minutes_to_open` 和 `minutes_to_close`。覆盖不会改写真实 `market_local_time` 或 `effective_daily_bar_date`；如果当前日期不是交易日或日历不支持对应 session，分钟字段可以为空。

#### Web 阶段标签展示（Issue #1386 P4b）

P4b 在 Web 端补齐阶段可见性，但不新增阶段覆盖 selector。进行中的任务面板只展示 P4a 回显的请求阶段 `analysis_phase`，其中 `auto` 明确显示为“自动阶段”，不伪装成最终推断阶段。最终报告页以 `report.meta.market_phase_summary.phase` 展示实际市场阶段标签，并在 `is_partial_bar=true` 时提示“日线未完成”。

数据质量摘要继续复用 `report.details.analysis_context_pack_overview.data_quality` 和现有 `AnalysisContextSummary`；Web 会在同一报告详情页展示阶段标签，并继续复用低敏数据质量摘要，不暴露完整 `AnalysisContextPack`、Prompt summary、raw payload 或已剥离的 snapshot 内部字段。历史列表、Bot、schedule、GitHub Actions、Desktop、通知摘要和高级阶段覆盖入口仍为后续工作。

#### AnalysisContextPack Prompt 摘要（Issue #1389 P3）

P3 在普通分析和 Agent 初始上下文中接入 `AnalysisContextPack` 低敏摘要。Pipeline 会用已获取的行情、日线、趋势、筹码、基本面、新闻和市场阶段 artifacts 组装 pack，再把 `analysis_context_pack_summary` 插入 Prompt；在这个新增的 pack 摘要区块中，LLM 只看到 subject、版本、各数据块的状态/来源/warning/missing reason 和新闻结果数，不会通过该区块看到完整 `news.content`、`trend_result`、筹码或基本面原始 payload。既有 `news_context`、Agent pre-fetched JSON 和 `enhanced_context` 原始数据通道保持 P3 前行为，不由本摘要替代或脱敏。

P3 当时不新增 API/Web/Bot 参数，不写入 history/task status/report metadata，不改变报告 JSON schema，也不把完整 pack 暴露到历史、通知或 Web。Agent 工具级复用 pack 数据和 P5 数据质量评分留给后续阶段。

#### Multi-Agent 决策分歧摘要输入（Issue #1904 P1 plumbing）

Multi-agent 在进入 `DecisionAgent` 前会构造内部低敏 `agent_disagreement_summary`，用于提示前序 Agent opinion 的方向分歧、风险 override 证据、风险 override 是否受当前 `AGENT_RISK_OVERRIDE` 配置启用，以及非关键阶段降级信息。该摘要只包含 agent name、signal、confidence、conflict type、decision path hint、低敏 risk control 状态和 degraded stage marker，不包含 reasoning、raw_data、原始错误文本、token 或私密 payload。

该能力当前只是 `DecisionAgent` 的内部 Prompt 输入管线：摘要写入运行态 `ctx.meta`，不进入 Agent pre-fetched data，不新增 public API、Web/Desktop 展示、history/task status/report metadata、dashboard schema 或最终解释字段。`risk_level=high` 只作为风险证据，不会单独触发 override；summary 与最终 `_apply_risk_override()` 复用同一套 override 判断，并尊重 `AGENT_RISK_OVERRIDE=false`。非关键降级阶段沿用 orchestrator 的 `intel`、`risk` 和 specialist/skill agent 降级契约，避免把单一方向意见误描述成 multi-agent 共识。#1904 的用户可见最终解释输出仍属于后续阶段。

#### AnalysisContextPack 低敏可见性（Issue #1389 P4）

P4 新增 `report.details.analysis_context_pack_overview`，历史详情和 completed `/api/v1/analysis/status/{task_id}` 会从已持久化的 `context_snapshot` 返回同一份低敏 overview；同步分析响应也会读取本次已落库的 `analysis_history.context_snapshot` 提取 overview，因此 `SAVE_CONTEXT_SNAPSHOT=false` 时新记录不保证返回该字段。Web 端报告页在“策略点位”和“资讯”之后展示默认折叠的数据块摘要，折叠头部展示可用数、缺失数、非零的其他状态计数和触发来源，展开后展示数据块状态、来源、warning、missing reason、状态计数和新闻结果数。API 返回的 `details.context_snapshot` 会剥离顶层 `analysis_context_pack_overview`，避免透明度面板重复展示 raw snapshot。

该 overview 不包含完整 pack、`analysis_context_pack_summary` Prompt 字符串、`items.value`、新闻正文、`trend_result`、筹码或基本面原始 payload。`SAVE_CONTEXT_SNAPSHOT=false` 时不持久化整份 `analysis_history.context_snapshot`，因此不会从新历史记录读取 overview；旧历史记录缺少 overview 时字段为空，报告仍正常返回。本阶段不覆盖 pending/processing TaskPanel、SSE 进行中事件、通知摘要、Bot/Desktop 专属展示、`market_review` overview 或数据质量评分。

#### AnalysisContextPack 数据质量评分与 Prompt 数据限制（Issue #1389 P5）

P5 在不修改 `PACK_VERSION = "1.0"`、不新增数据源和不改变报告 JSON schema 的前提下，给 `AnalysisContextPack` 增加轻量数据质量评分与模型可读的数据限制区块。`ContextFieldStatus` 新增 `fetch_failed`，只表示字段或数据块本次抓取明确失败；首版仅把 `fundamental_context.status == "failed"` 映射为 `fetch_failed`，空新闻、未配置搜索、无实时 quote 或 chip 缺失仍按既有 `missing` / `not_supported` 处理。

`DataQuality` 现在包含 `overall_score`、`level`、`block_scores`、`limitations`，并保留旧 `warnings` / `metadata`。评分固定覆盖 `quote`、`daily_bars`、`technical`、`news`、`fundamentals`、`chip` 六块，不因辅助块缺失重归一化；核心块降级会在 Prompt 的“数据限制”区块中要求模型不要输出高置信度，辅助块缺失只限制对应分析段落，不应被解释为利好或利空。该 Prompt 区块由 `format_analysis_context_pack_prompt_section()` 统一生成，普通分析、single Agent 和 multi-agent 沿用同一低敏 summary，不暴露 raw payload、新闻正文、趋势原始值、secret、token 或 webhook。

历史详情、同步分析响应和 completed 任务状态继续只通过 `report.details.analysis_context_pack_overview` 暴露低敏字段；P5 只在该 overview 下新增 `data_quality`，包含 score、level、block_scores 和 limitations，不重复公开 `warnings`。Web 报告页仍默认折叠展示数据块摘要，折叠头部新增质量分/等级，展开后展示限制说明和 `fetch_failed` 状态；`details.context_snapshot` 继续剥离顶层 `analysis_context_pack_overview`。

#### AnalysisContextPack 文档、迁移与回滚（Issue #1389 P6）

P6 只做文档与配置可见性收口，不新增 pack runtime、不新增 pack enable/disable feature flag、不修改 `PACK_VERSION = "1.0"`、不新增 API 参数、不改变报告 JSON schema，也不做数据库迁移。完整契约、字段状态、低敏摘要可见性、脱敏边界、迁移和回滚说明见 [AnalysisContextPack 专题文档](analysis-context-pack.md)。

`SAVE_CONTEXT_SNAPSHOT` 是既有环境变量，P6 只是把它同步到 `.env.example`、配置注册表和 Web 设置帮助。默认 `true`；设为 `false` 或 CLI 使用 `--no-context-snapshot` 时，新历史记录不再持久化整份 `analysis_history.context_snapshot`，包括 `enhanced_context`、`market_phase_summary`、`analysis_context_pack_overview`、诊断快照和 raw snapshot 字段。该设置不关闭当次 `AnalysisContextPack` 构建，不移除 Prompt 中的低敏 `analysis_context_pack_summary`，也不改变分析结果 JSON schema 或 API 请求参数。

当前没有运行时 pack 总开关；如果需要关闭 P3-P5 的 pack Prompt 摘要、overview 或数据质量接入，只能通过发布回滚或代码回滚完成。旧历史记录没有 `analysis_context_pack_overview` / `data_quality` 时继续返回空字段，报告读取保持兼容。

#### 市场结构上下文（Issue #1909）

个股分析现在新增低敏 `market_structure_context`，并通过 `AnalysisReport.details.market_structure` 对历史详情、同步分析响应和 completed 任务状态暴露。该字段采用两层结构：`market_theme_context` 表示大盘/题材层，包含 A 股行业/概念榜单、活跃题材、领涨行业/概念、题材宽度和数据质量；`stock_market_position` 表示个股位置层，包含个股所属板块、主关联题材、题材阶段、个股位置、风险标签和缺失证据。

首版市场结构由 DSA 原生服务基于 `DataFetcherManager.get_sector_rankings()`、`get_concept_rankings()` 和 `fundamental_context.belong_boards` 生成，不依赖 AlphaSift runtime。AlphaSift 中已有的热点详情、发酵路线、成分股和 leader stocks 可作为后续可选数据源迁移，但在未迁移前不会被普通个股分析隐式调用。缺少成分股或 leader 证据时，`stock_role` 默认保持 `follower/edge/unknown`，并在 `missing_fields` 中标记 `hotspot_constituents`、`leader_stocks`，避免把普通关联股误写成题材龙头。

兼容性边界：`market_structure_context` 中的 provider / model 快照字段（含 `model_used`、`market_structure_context.*.source.provider` 等）仅用于历史回溯和页面展示，不构成 LLM provider 路由、`base URL`、`provider/model` 运行时配置输入；不会触发 `.env` 配置清理、回写、迁移或静默变更。

普通 LLM、single Agent 和 multi-agent prompt 会注入市场结构低敏摘要；DecisionSignal 自动提取会把 `primary_theme`、`theme_phase`、`stock_role`、版本号和风险标签写入 metadata，不改变主字段、去重键或生命周期规则。Web 报告页在概览后展示“市场位置”卡片，分别呈现大盘题材层和个股位置层；旧历史记录缺少该字段时不展示。非 A 股市场首版返回 `not_supported`，不影响原有报告。

#### 盘中决策护栏与质量校验（Issue #1386 P5）

P5 在个股分析报告的 `dashboard.phase_decision` 中追加阶段化决策字段：`phase_context`、`action_window`、`immediate_action`、`watch_conditions`、`next_check_time`、`confidence_reason` 和 `data_limitations`。该字段只作为报告 JSON 的向后兼容扩展进入历史 `raw_result`；不新增 `analysis_phase` API 参数、不改变 Web 阶段入口、不新增配置项，也不影响每日收盘复盘默认行为。

普通分析与 Agent 分析会在保存历史前复用当次 `market_phase_summary` 和 `analysis_context_pack_overview.data_quality` 执行轻量护栏：核心 quote / daily_bars / technical 数据 stale、fallback、missing、fetch_failed、partial 或 estimated 时，不允许高置信结论；盘前、非交易日或未知阶段不得输出高置信盘中买卖；盘中、午间和临近收盘会检查主结论里的盘后复盘口吻，并把明显的"今日收盘后复盘显示""明日重点关注"类措辞改为阶段安全的观察/等待表述。护栏只补低敏 `phase_context` 和数据限制，不编造观察条件或下一次检查时间；通知摘要、告警、持仓和回测联动留给后续 P6。

#### 信号归因分析（Issue #1742）

Issue #1742 在个股分析报告的 `dashboard.signal_attribution` 中新增信号归因分析字段：`technical_indicators`、`news_sentiment`、`fundamentals`、`market_conditions`（四个贡献度；有效非零贡献度归一化到 100；全零表示无有效信号）、`strongest_bullish_signal` 和 `strongest_bearish_signal`。该字段解释推荐理由的构成，帮助用户理解 AI 决策的归因权重。

信号归因分析在所有报告渲染路径中同步展示：
- `generate_dashboard_report()`（默认通知报告）
- `generate_single_stock_report()`（单股推送报告）
- `templates/report_markdown.j2`（Jinja2 模板）
- `HistoryService._generate_single_stock_markdown()`（Web 历史抽屉）

归一化函数在 `_parse_response()` 和 `parse_dashboard_json()` 中显式调用，确保：
- 字符串百分比转为 int（如 `"35%"` → `35`）
- 负数转为 0
- 总和≠100 时归一化为总和=100
- 值裁剪到 [0, 100] 范围

`signal_attribution` 是可选展示字段（非必填）。缺失不会失败完整性检查，也不会写入 `missing` 列表或触发补全 prompt；存在时会被归一化并在支持的报告路径展示。

#### 告警、持仓和历史联动（Issue #1386 P6）

P6 将既有 `market_phase_summary` 与 `analysis_context_pack_overview` 复用到告警、持仓、历史、回测和通知链路，不新增 phase/pack 协议，也不做数据库迁移。告警触发记录仍使用现有 `diagnostics` 文本字段；当 diagnostics 可 JSON 化时，worker 会在 `status=triggered` 记录中合并写入 `analysis_visibility.market_phase_summary`、`analysis_visibility.analysis_context_pack_overview` 和 `analysis_visibility.source`。旧纯文本 diagnostics 继续保留原文，Alert API 派生字段为空且 `analysis_visibility_source=legacy_text`。

告警 phase 摘要来自触发时上下文：symbol 目标按股票市场推断，`target_scope=market` 直接使用 `cn|hk|us|jp|kr` 市场区域，账户级无法唯一定位时允许落为 `unknown`。pack overview 只来自评估器已带 overview 或最近 30 天历史 snapshot 的低敏 overview，缺失时返回 `null`，不伪造 pack，不自动触发轻量 LLM 分析。公开 source 取值为 `alert_trigger_market_context`、`analysis_history_snapshot`、`evaluator_snapshot`、`legacy_text` 或 `null`。

持仓页新增手动单股分析入口，对应 `POST /api/v1/portfolio/positions/{symbol}/analysis`。请求字段为 `account_id`、`analysis_phase=auto|premarket|intraday|postmarket` 和 `force`；只有当前持仓快照中非零持仓可提交，无持仓返回 404，多账户同持一只股票但未传 `account_id` 返回 `400 ambiguous_position_account`。该入口沿用异步任务 accepted / duplicate 语义，`force` 只影响分析刷新，不绕过 in-flight duplicate。后端只把低敏 `portfolio_context` 传入内部 pipeline 和 context pack 的可选 `portfolio` block；该 block 不参与既有六块数据质量总分，也不会出现在任务列表或 SSE payload 中。

历史列表、单股历史、StockBar 和详情会从 `context_snapshot` 提取 `market_phase_summary`；旧记录、缺失 snapshot 或解析失败返回 `null`。回测结果项增加 `market_phase` 与 `market_phase_summary`，结果列表和 performance/summary 查询支持 `analysis_phase=premarket|intraday|postmarket|unknown`；统计统一把 `intraday`、`lunch_break`、`closing_auction` 归入 intraday，把 `non_trading`、缺失和非法值归入 unknown。带 phase 过滤的回测查询会在 repository 层按 SQL 条件批量读取结果和 snapshot，先 bucket 再分页，并在 summary diagnostics 中返回 `phase_breakdown` 与 `raw_phase_counts`。

通知摘要复用统一公开格式化 helper，只输出阶段标签、trigger source、partial-bar warning、数据质量等级和前两条 limitations；不会输出 raw context pack、Prompt、新闻正文或持仓敏感明细。Web 告警历史、持仓、历史列表、StockBar 和回测页同步展示阶段 badge、质量摘要、phase filter 与 breakdown。

#### 文档、配置与迁移说明（Issue #1386 P7）

P7 只做盘前 / 盘中 / 盘后分析的用户可见说明收口，不新增运行时能力、配置项、API 参数、数据库迁移、Web 阶段覆盖 selector、Bot phase 参数或 GitHub Actions 盘中 workflow。默认每日收盘分析、默认 GitHub Actions 和现有 schedule 行为保持不变。

推荐使用方式：

| 场景 | 推荐用途 | 说明 |
| --- | --- | --- |
| 盘前 | 生成开盘计划和观察条件 | 不能把尚未发生的今日走势写成事实；重点看上一完整交易日、隔夜信息和开盘触发条件。 |
| 盘中 / 午间 / 临近收盘 | 做实时状态判断、风险和机会提醒 | 关注当前价、实时行情新鲜度、partial bar、数据限制和下一步观察条件，不替代盘后完整复盘。 |
| 盘后 | 保留完整复盘和次日计划 | 使用完整交易日语义，是默认每日分析最接近的场景。 |

入口与可见性：

| 入口 | 阶段行为 |
| --- | --- |
| `POST /api/v1/analysis/analyze` | 支持 `analysis_phase=auto|premarket|intraday|postmarket`；不传时默认 `auto`。 |
| Web 主分析 / 重新分析 / 持仓手动分析 | 当前没有阶段覆盖 selector；前端调用默认传 `auto`。进行中任务面板展示请求阶段，最终报告页展示最终阶段标签。 |
| Bot / CLI / schedule / 默认 GitHub Actions | 不传 `analysis_phase`，继续走 `auto` 推断；默认收盘分析行为不变。 |
| 历史 / 回测 / 通知 / 告警 | 只消费公开 `market_phase_summary` 和低敏 `analysis_context_pack_overview`；不公开完整 pack、Prompt summary、新闻正文或持仓敏感明细。 |

`analysis_phase` 是请求覆盖值，最终报告阶段仍以 `report.meta.market_phase_summary.phase` 为准。旧调用不传 `analysis_phase` 时保持兼容；旧历史缺少 `market_phase_summary` 或 `analysis_context_pack_overview` 时返回空字段，不影响报告读取。回测查询支持 `analysis_phase=premarket|intraday|postmarket|unknown` 过滤，并按 P6 规则把午间和临近收盘归入 intraday。

`SAVE_CONTEXT_SNAPSHOT=false` 或 CLI `--no-context-snapshot` 只停止新历史持久化整份 `context_snapshot`，因此新历史不再公开 phase summary / pack overview / diagnostics snapshot 等持久化摘要；它不关闭当次 `AnalysisContextPack` 构建，不移除 Prompt 中的低敏 `analysis_context_pack_summary`，也不改变报告 JSON schema。调用方若要临时回到更接近旧盘后口径的输出，可固定传 `analysis_phase=postmarket`；若要彻底移除 P0-P6 阶段/pack runtime 接入，需要发布回滚或代码回滚。

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
4. `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 是飞书应用 / Stream Bot / 云文档模式专用，不会触发群 Webhook 推送，不要只用它们替代 `FEISHU_WEBHOOK_URL`。
5. 若已配置 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`，再配置 `FEISHU_CHAT_ID`，则可通过飞书 App Bot 直接向指定群聊或用户推送通知，无需依赖群 Webhook；`FEISHU_RECEIVE_ID_TYPE` 默认 `chat_id`，私聊时改为 `open_id`。该方式走飞书 OpenAPI Bot 会话，与群 Webhook 是两条独立链路。
6. App Bot 发送路径复用 `requirements.txt` 中已有的 `lark-oapi>=1.0.0`，标准源码安装、Docker、GitHub Actions daily workflow 和桌面构建链路都会通过 `pip install -r requirements.txt` 安装，不需要单独安装新库。参考：[Feishu message create OpenAPI](https://open.feishu.cn/document/server-docs/im-v1/message/create)、[lark-oapi PyPI](https://pypi.org/project/lark-oapi/)、[SDK repo](https://github.com/larksuite/oapi-sdk-python)。

**常见失败原因：**
- 只填了 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`，既没有配置 `FEISHU_WEBHOOK_URL`，也没有配置 App Bot 主动推送所需的 `FEISHU_CHAT_ID`
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

> GitHub Actions 限制：截至 2026-03-29，仓库自带 `00-daily-analysis.yml` 不会自动导入任意编号的 `STOCK_GROUP_N` / `EMAIL_GROUP_N`。因此如果你只在仓库 Secrets / Variables 中新增这些变量，而没有修改 workflow 显式映射，它们不会进入运行进程，看起来就像“分组配置不生效”。

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

Docker Compose 部署中，通过 Web 设置页保存时会把这些应用占位符写成 `$$content_json` / `$$title_json` 等形式，避免 Compose 重新部署时将其展开为空；应用运行时会还原为单个 `$`。如果手动编辑 Docker 使用的 `.env`，请同样使用 `$$content_json` 这类写法。

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

长报告会按 Discord 单条 content 2000 字符上限自动分片发送；如果某一片遇到 429 限流，发送器会按 Discord 返回的 `retry_after` 或 `Retry-After` 做有限重试，并继续尝试后续分片。`DISCORD_MAX_WORDS` 可调低单片长度，但运行时不会允许超过 2000。

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
- 新接入推荐使用 Longbridge 官方 OAuth 2.0：client_id 优先使用 `LONGBRIDGE_OAUTH_CLIENT_ID`，留空且没有 Legacy Access Token 时兼容使用 `LONGBRIDGE_APP_KEY`；先在可交互环境执行 `python scripts/generate_longbridge_oauth_token.py --client-id <client_id>` 生成 SDK token 缓存
- GitHub Actions / Docker 等 headless 环境不能在分析任务里等待浏览器授权；可将本机 `~/.longbridge/openapi/tokens/<client_id>` 文件 base64 后配置为 `LONGBRIDGE_OAUTH_TOKEN_CACHE_B64`
- OAuth 运行时依赖 SDK 提供 `OAuthBuilder` / `Config.from_oauth`；若当前 Linux/Docker 环境只能安装旧版 SDK，日志会明确提示并自动跳过 Longbridge，不影响 YFinance / AkShare 兜底
- Legacy API Key 仍兼容：设置 `LONGBRIDGE_APP_KEY`、`LONGBRIDGE_APP_SECRET`、`LONGBRIDGE_ACCESS_TOKEN`；其中 Access Token 是旧版 API Key 凭证，不是 OAuth access token
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

### 建议动作 Taxonomy（#1390 P0）

个股报告在保留 `operation_advice` 自由文本的同时，新增可选 `action` / `action_label` 字段，作为 Web 历史列表、同股历史、StockBar 和回测结果行的结构化展示辅助。`decision_type` 仍保持旧的 `buy|hold|sell` 三态统计口径；`action` 为空时不会改写既有 `decision_type` 推断链。

| `action` | 常见来源文本 | `decision_type` 桥接 |
| --- | --- | --- |
| `buy` | `strong_buy`、`强烈买入`、`买入`、`布局`、`建仓` | `buy` |
| `add` | `add`、`加仓`、`增持`、`accumulate` | `buy` |
| `hold` | `hold`、`持有`、`持有观察`、`洗盘观察` | `hold` |
| `watch` | `watch`、`观望`、`等待`、`wait` | `hold` |
| `reduce` | `reduce`、`减仓`、`trim` | `sell` |
| `sell` | `sell`、`卖出`、`清仓`、`strong_sell`、`强烈卖出` | `sell` |
| `avoid` | `avoid`、`回避`、`规避`、`不建议买入`、`避免买入`、`do not buy` | `hold` |
| `alert` | `alert`、`风险预警`、`警惕`、`触发告警`、`risk alert` | `hold` |

上表的 `decision_type` 桥接只说明八态 action 与旧三态统计口径的兼容关系；#1390 P0 不会把 `action` 自动反写到既有 `decision_type`。若上游显式 `action` 与 `decision_type` 同时存在但语义不一致，三态统计、回测和旧报表口径仍以 `decision_type` / 原有推断链为准，`action/action_label` 只承担结构化展示辅助。

未知或歧义建议不会兜底成 `watch` 或 `hold`，而是返回空 `action/action_label`。Web 历史卡片、StockBar、同股历史抽屉和回测结果行会在旧记录缺少 `action/action_label` 时从 `operation_advice` 做展示级 fallback；该 fallback 只影响前端标签，不等价于稳定 API action 或后续信号资产。Web 展示层在同时收到 `action` 与 `action_label` 时，会优先按当前界面语言从 `action` 生成标签；API 中的 `action_label` 仍按报告语言生成，供非 Web 客户端或无 `action` 的兼容展示使用。大盘复盘和其他非个股报告不会产生交易 `action`，只保留 `operation_advice` 文本。`dashboard.phase_decision.immediate_action` 属于市场阶段护栏报告字段，不参与 #1390 P0 的八态 action 派生；最终市场阶段仍来自 `report.meta.market_phase_summary.phase`。

#1390 P0 不会把后续信号资产字段平铺到现有 summary、历史列表、StockBar 或回测响应。#1390 P1 开始通过独立 `DecisionSignal` 资源承接 `horizon`、`plan_quality`、`status` 等更细粒度计划字段，仍不改变既有报告主契约、不回填历史、不新增配置项。

### 决策信号资产（#1390 P1/P2/P3/P4/P5）

`DecisionSignal` 是独立后端资源，用于把 AI 建议沉淀为可查询、可去重、可更新状态的信号资产。它不替换 `operation_advice`、不扩展 `decision_type=buy|hold|sell`。#1390 P2 开始，普通个股分析和 Agent 个股分析在分析历史保存成功后，会从最终 `AnalysisResult` best-effort 提取一条 `source_type=analysis` 的信号；显式 API 或 service 调用仍然保留。

自动提取只消费已生成报告中的结构化字段，不重新解析 Markdown，也不回填旧历史、不新增配置项、不改变报告主契约。提取失败、建议动作未知或歧义、非个股报告、无法识别市场时会跳过写入，不影响分析报告保存。`source_report_id` 使用刚保存的 `AnalysisHistory.id`；`trace_id` 优先使用运行诊断 trace，缺失时降级到 pipeline trace 或 `query_id`；`stock_name` 来自 `AnalysisResult.name`；`trigger_source` 来自运行入口，缺失时为 `system`。

P2 自动提取的市场阶段优先读取保存快照中的 `market_phase_summary.phase`，其次读取 `AnalysisResult.market_phase_summary.phase`；数据质量优先读取保存快照中的 `analysis_context_pack_overview.data_quality`，其次读取 `AnalysisResult.analysis_context_pack_overview.data_quality`。价格计划复用历史保存的狙击点解析规则，从 `dashboard.battle_plan.sniper_points.ideal_buy/secondary_buy/stop_loss/take_profit` 映射到 `entry_low/entry_high/stop_loss/target_price`；只有 `ideal_buy` 时写入 `entry_low`，只有 `secondary_buy` 时写入 `entry_high`，两者同时存在时按有效价格排序为 `entry_low <= entry_high`。缺失止损或目标价只会降低 service 自动计算的 `plan_quality`，不会编造字段。`watch_conditions` 优先读取 `dashboard.phase_decision.watch_conditions`，没有时才读取 `dashboard.battle_plan.action_checklist`；`catalyst_summary` 仅在 `dashboard.intelligence.positive_catalysts` 存在且为列表时写入。`confidence` 由报告置信等级做保守映射：`高/high=0.8`、`中/medium/mid=0.6`、`低/low=0.4`，原始置信等级保留在 `metadata`。

P3 开始，生命周期由 `DecisionSignalService` 统一补齐：显式传入的 `horizon` / `expires_at` 永远优先；未传 `horizon` 时，`alert` 或 `premarket/intraday/lunch_break/closing_auction` 默认 `intraday`，`postmarket/non_trading/unknown` 或无阶段上下文时默认 `3d`；未传 `expires_at` 时，`intraday` 优先读取 `metadata.market_phase_summary.minutes_to_close/minutes_to_open`，无上下文时使用确定性 TTL fallback（A 股 4h、港股 5.5h、美股 6.5h、未知 4h），`1d/3d/5d/10d` 按自然日，`swing/long` 不自动过期。fallback TTL 只是缺少交易日历上下文时的降级策略，不等价于真实交易所收盘时间。自动提取只把 `market_phase_summary.phase/session_date/minutes_to_open/minutes_to_close` 作为低敏 hint 写入 `metadata.market_phase_summary`，最终 `horizon/expires_at` 仍由 service 计算。

核心字段包括 `stock_code`、`stock_name`、`market`、`source_type`、`source_agent`、`source_report_id`、`trace_id`、`decision_profile`、`market_phase`、`trigger_source`、`action`、`action_label`、`confidence`、`score`、`horizon`、`entry_low`、`entry_high`、`stop_loss`、`target_price`、`invalidation`、`watch_conditions`、`reason`、`risk_summary`、`catalyst_summary`、`evidence`、`data_quality_summary`、`plan_quality`、`status`、`expires_at`、`created_at`、`updated_at` 和 `metadata`。`action` 复用八态建议动作；`decision_profile` 支持 `conservative|balanced|aggressive`，数据库 `NULL` 仅表示 legacy/unknown；`market_phase` 复用市场阶段枚举；`source_type` 支持 `analysis|agent|alert|market_review|manual`；`status` 支持 `active|expired|invalidated|closed|archived`；`horizon` 支持 `intraday|1d|3d|5d|10d|swing|long`。

`confidence` 为 `0.0-1.0`，`score` 为 `0-100`，与历史报告的 `sentiment_score` 解耦。价格计划字段 `entry_low`、`entry_high`、`stop_loss`、`target_price` 必须是有限正数，且同时传入 `entry_low` 和 `entry_high` 时要求 `entry_low <= entry_high`。`plan_quality` 支持 `complete|partial|minimal|unknown`：调用方显式传入合法值时直接保存；未传时由 service 计算，入场区间（`entry_low` 或 `entry_high` 任一有值）算 1 项，`stop_loss`、`target_price`、`invalidation`、`watch_conditions` 各算 1 项，满足 2 项为 `partial`，满足 4 项及以上为 `complete`，仅有 action/reason 为 `minimal`。

新增 API：

- `POST /api/v1/decision-signals`：创建或按同源键去重，返回 `{ item, created }`，HTTP 200。新写入可省略 `decision_profile` 并默认 `balanced`，也可传合法 `conservative|balanced|aggressive`；顶层显式 `null`、空值或非法值会被拒绝。顶层缺失时才 fallback 合法 `metadata.decision_profile`，写入前会同步 `metadata.decision_profile` 为正式字段值；metadata 省略或显式 `null` 均按无 metadata 处理，object 会浅复制，非 object 会被拒绝。精确去重键为 `(source_report_id, source_type, market, stock_code, decision_profile, action, horizon, market_phase)`；没有 report 但有 `trace_id` 时使用 `(trace_id, source_type, market, stock_code, decision_profile, action, horizon, market_phase)`；两者皆无则不去重。精确匹配、relaxed fallback、horizon/phase fill、expired refresh、active invalidation 和 stale backfill invalidation 都遵循 same-profile 语义：`NULL` 只匹配 `NULL`，非空 profile 只匹配相同 profile；expired duplicate refresh 不会改写 `decision_profile`。精确匹配失败后，会按同源 + `source_type/market/stock_code/decision_profile/action` 做窄 relaxed fallback，只填补旧记录为空的 `horizon/market_phase`，且 `horizon` 只有在新值由 service 默认生成时才可填补；显式不同期限、已有不同阶段或不同 profile 仍保留多条。若命中同源 expired 同 profile 记录，且新请求为 active 并携带未来 `expires_at`，会原地刷新该记录并返回 `created=false`，这次续期按新的 active 激活事件处理。active 新建或 expired 续期后的 bullish 信号（`buy/add`）会把更早同 profile 的 active defensive 信号（`reduce/sell/avoid`）标记为 `invalidated`，反向同理；不同非空 profile 可并存，即使动作相反。active duplicate retry 也会重跑同 profile 失效修复，以恢复上次创建成功但失效写入失败的 partial create；普通旧 duplicate/replay 不作为新的激活事件。`hold/watch/alert` 不触发自动失效。刷新或重复命中都对外返回 `created=false`；本功能不提供并发唯一性保证。
- `GET /api/v1/decision-signals`：分页查询，支持 `market`、`stock_code`、`action`、`market_phase`、`decision_profile`、`source_type`、`source_report_id`、`trace_id`、`trigger_source`、`status`、时间范围、`holding_only`、`account_id`。省略或传空 `decision_profile` 不加 profile 条件，返回所有 profile；`decision_profile=unknown` 查询 legacy `NULL` 行；合法 profile 精确匹配。
- `GET /api/v1/decision-signals/{signal_id}`：查询单条，不存在返回 404。
- `PATCH /api/v1/decision-signals/{signal_id}/status`：更新合法状态和可选 `metadata`；省略 metadata 时保留原值，显式 `null` 时清空为 SQL `NULL`，object 时整包替换。正式 `decision_profile` 非 `NULL` 时会覆盖 metadata 中的冲突 profile；正式字段为 legacy `NULL` 时会移除请求 object 中的 profile key，且不会提升正式字段。`expired/invalidated/closed/archived` 等 terminal 状态不能直接 PATCH 回 `active`，expired 续期仍只能重新 `POST` active + 未来 `expires_at`。
- `GET /api/v1/decision-signals/latest/{stock_code}`：按股票查询最新 active 信号，默认 `limit=1`。

读取入口会懒过期：列表、详情和 latest 查询前会把已到 `expires_at` 的 active 信号标为 expired；创建时已过期的 active 信号会直接保存为 expired；同源 expired 信号只能通过重新 `POST` active + 未来 `expires_at` 的方式延展，`PATCH /status` 不接受 `expires_at`。`expired|invalidated|closed|archived` 不会被 PATCH 直接复活，`closed|invalidated|archived` 也不会被 create 路径复活。相反信号自动失效会合并写入旧信号 `metadata`：`invalidated_by_signal_id`、`invalidated_reason`、`invalidated_at`、`previous_status`；正式 profile 非 `NULL` 时同步 metadata profile，正式 profile 为 legacy `NULL` 时保留原 metadata profile 且不提升正式字段。旧 metadata JSON 损坏或不是 object 时会替换为失效 metadata 并写入对应 replacement marker，不阻断新信号创建。时间字段按 UTC 归一化为无时区 `datetime` 保存和比较；带时区输入会先转为 UTC 后去掉 `tzinfo`，无时区输入按 UTC 处理，API 响应继续返回不带时区后缀的 ISO 字符串。股票代码入库与查询按 `market` 确定性归一化：A 股 `600519`、`SH600519`、`600519.SH` 等常见变体按同一代码匹配；港股 `00700`、`HK00700`、`00700.HK` 按 `HK00700` 匹配；美股 ticker 统一大写。`holding_only=true` 只读取 active 账户下 `portfolio_positions` 中 `quantity > 0` 的缓存持仓，并按持仓 `(market, stock_code)` 匹配信号，可选 active `account_id`；该查询不会调用组合 snapshot replay，无缓存时返回空结果，需先通过 portfolio snapshot API 刷新缓存。

`source_report_id` 可为空且不强制校验历史记录存在；删除历史记录时只显式清理 `source_type=analysis` 且 `source_report_id` 命中实际删除 ID 的历史绑定信号，`manual/agent/alert/market_review` 等弱引用信号不会仅因 ID 碰撞被删除；列表接口支持按 `source_report_id` 和 `trace_id` 做 typed filter。`task_id`、`alert_trigger_id` 等后续关联字段先放入 `metadata`，P1 不新增独立列，也不提供 typed filter，后续联动阶段再提升为独立契约。JSON 字段、长文本字段和展示型短文本字段（`stock_name/source_agent/trigger_source/action_label`）会在写入前执行信号专用脱敏，覆盖敏感 key、Bearer、Authorization/Cookie header 或赋值、token-like 字符串、其他敏感赋值、webhook URL、URL userinfo 以及带敏感 query/fragment 参数的 URL；普通证据 URL 会保留以保证来源可追溯，且长文本不会套用诊断文本的 300 字符截断。`trace_id` 是同源去重身份字段，若包含会被脱敏的敏感 credential，API 会拒绝请求而不是保存有损 redaction 后的值。

这些接口继承现有 `/api/v1/*` 管理员鉴权：`ADMIN_AUTH_ENABLED=true` 时必须携带有效管理员会话 Cookie；本功能不新增独立认证方式。

#1390 P4 在 Web 端接入已有 `DecisionSignal` API。#1756 后侧边栏“AI 建议”入口 `/decision-signals` 仍是结构化决策信号的集中查询入口，默认展示 `status=active` 的信号，并支持按市场、股票代码、动作、市场阶段、来源、来源报告 ID 和状态筛选；时间线区域新增 profile filter，复用 list API 的 server-side `decision_profile` 查询，`unknown` 仅用于筛选和展示 legacy `NULL` 行，普通高级列表不新增 profile filter。页面还提供按股票代码查询最新 active 信号的入口。卡片、详情和时间线展示优先读取正式 `decision_profile` 字段，只有字段缺失时才 fallback legacy metadata；显式 `null`、历史缺失或非法 profile 显示为 unknown。信号详情展示动作、风格、置信度/评分、horizon、plan_quality、market_phase、价格计划、风险、观察条件、来源报告和数据质量；Web 只允许把信号标记为 `closed`、`invalidated` 或 `archived`，不提供 terminal 状态恢复为 active。

#1390 P5 新增信号级反馈、后验评估和统计 sidecar，不扩展 `decision_signals` 主表，也不复用绑定 `analysis_history_id` 的 `BacktestResult`。`decision_signal_feedback` 按 `signal_id` 保存最新 `useful|not_useful` 反馈、可选原因/备注和来源；`decision_signal_outcomes` 按 `(signal_id, horizon, engine_version)` 幂等保存后验结果，当前 `engine_version=decision-signal-v1`。Outcome 在评估时冻结 `action/market/market_phase/source_type/source_agent/plan_quality/data_quality_level/holding_state` 等统计维度，历史统计不依赖后续 live join 改写。删除历史报告时，会先找出 `source_type=analysis` 且绑定被删历史 ID 的信号，再清理对应 feedback/outcome 子表。

P5 后验评估只支持日线可验证的 `1d/3d/5d/10d`，窗口语义是 anchor 后 1/3/5/10 根 `StockDaily` 交易 bar，不复用 `DecisionSignalService._horizon_days()` 的自然日过期语义。`anchor_date` 优先读取 `metadata.market_phase_summary.session_date`，否则使用 `created_at.date()`；anchor 当日必须存在 `StockDaily.close`，不会回退到前一交易日。动作映射为 `buy/add -> up`、`hold -> not_down`、`reduce/sell/avoid -> not_up`；`watch/alert`、`intraday/swing/long`、缺 anchor 价、forward bars 不足等会写入 `eval_status=unable` 和明确 `unable_reason`。缺 anchor 价、非法 anchor 价、forward bars 不足、缺/非法窗口收盘价属于可恢复 unable，后续默认重跑会在数据补齐后重新评估；非方向动作、不支持 horizon 和缺 anchor date 属于终态 unable，默认保持幂等跳过。自动提取运行时可额外接收 `portfolio_context.quantity`，只把低敏 `holding_state=holding|empty|unknown` 写入 metadata 供后验快照使用，不保存数量、账户或成本。

P5 在 Web `/decision-signals` 页面筛选区下方展示当前 outcome engine 的整体统计卡片；详情抽屉按需读取该信号 outcomes，并可提交 useful/not useful 反馈。该页面不新增导航页，不进入 BacktestPage，也不新增后台定时任务；后验计算由 `POST /api/v1/decision-signals/outcomes/run` 显式触发。批量运行默认优先推进缺失 outcome 的信号，再重试可恢复 unable，不会让已完成或终态 unable 的最新信号长期占满 `limit`。

持仓页会把 AI 建议作为非阻断增强异步加载：组合快照和风险模块先按原逻辑渲染，随后按当前快照中的唯一持仓调用 `GET /api/v1/decision-signals/latest/{stock_code}?market=<market>&limit=1` 查询 latest active 信号；不再通过 `holding_only=true` 通用列表分页扫描，也不存在固定页数截断。单个持仓 latest 查询失败时，页面保留其他已加载信号并显示可见降级提示；无匹配信号时持仓行显示空占位。匹配逻辑复用 Web 端股票代码等价规则，覆盖 A 股 `600519/SH600519/600519.SH`、港股 `00700/HK00700/00700.HK` 和美股大小写 ticker。

#1390 P6 将 `DecisionSignal` 复用到告警、通知和组合风险，不新增表、迁移或配置。真实股票级告警触发会优先关联同标的 latest active 信号，并把低敏 `decision_signal_summary` 写入 `alert_triggers.diagnostics`；没有 active 信号时，worker 只创建最小 `source_type=alert`、`action=alert` 信号，`trace_id=alert-rule-<hash>` 仅用于同源重试的 best-effort 幂等去重，不覆盖 active 信号本体，且不写 `market_phase` 避免跨阶段重复。告警通知和分析通知只引用摘要中的 `action/horizon/reason/watch_conditions/risk_summary/source_report_id` 等公开字段，通知失败不影响 trigger 或信号写入。`GET /api/v1/portfolio/risk` 追加 `decision_signal_risk` 聚合块，只统计当前持仓中的 active `sell/reduce/alert` 信号，明确排除 `avoid/buy/add/hold/watch`；信号查询失败时风险接口 fail-open，Web 风险区显示降级状态。

#1390 P7 的收口文档见 [DecisionSignal 决策信号专题](decision-signals.md)。#1756 不新增 `DECISION_SIGNAL_*` 配置或运行时开关，但会为 `decision_signals` 增加 nullable `decision_profile` 字段、API 请求/响应字段和 profile-aware index；existing SQLite 只在缺列时 `ALTER TABLE ADD COLUMN`，不会 drop/rebuild 表，也不会删除旧 index。迁移会幂等创建 profile-aware index，并 row-by-row 防御解析 `metadata_json`，仅合法 `metadata.decision_profile` 回填，invalid JSON、非 object 或非法 profile 保持 `NULL`。当前回滚方式为 revert 对应代码。回滚后信号提取和写入停止，既有报告保存、告警触发、通知发送和组合风险主流程不依赖信号池继续运行；历史 signal、feedback 和 outcome 数据不会自动清理。

普通个股历史报告详情不再内嵌展示该报告提取出的 `source_type=analysis` 信号，也不会因打开报告详情而发起 `source_report_id=<recordId>` 的信号查询；需要查看结构化 AI 建议时统一进入 `/decision-signals` 页面筛选来源报告 ID、打开 `/decision-signals?sourceReportId=<recordId>` deep link，或按股票查询。填写来源报告 ID 或使用该 URL 参数时，Web 会发起 `source_type=analysis + source_report_id=<recordId>` 的精确查询，不叠加默认 `status=active` 等其他列表筛选，以保留旧报告 best-effort 懒回填语义。

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
- 🗂️ **首页三视图** - 首页新增「历史 / 自选 / 今日」工作区，默认进入历史视图；自选页支持批量提交全部或仅提交“今日未分析”股票
- 🧭 **界面语言切换** - 登录态与退出态均支持界面语言快速切换（`zh` / `en`），独立于 `REPORT_LANGUAGE`，用于静态 UI 文案与导航骨架
- 🚀 **快速分析** - 通过 API 接口触发个股分析；首页也提供“大盘复盘”按钮，可在 Docker/server 模式下后台触发大盘复盘
- 🎯 **策略选择** - 首页支持显式选择分析策略 skill；不传 `skills` 时按系统默认策略运行，便于保持与历史行为兼容
- 🧪 **今日状态/任务刷新防抖** - 首页「今日」与「自选」通过带有时区感知的历史区间判断并发起分页历史查询；任务完成后由最新一次 stock bar 刷新成功才清除失败态，避免旧请求乱序覆盖新状态导致重复提交
- 🧭 **首次配置提示** - 首页会读取只读配置状态，缺少 LLM 主渠道、自选股等基础项时提示缺口并引导进入系统设置
- 📊 **实时进度** - 分析任务状态实时更新，支持多任务并行；普通分析链路在进入 LLM 阶段后会优先尝试 LiteLLM 流式生成，并通过任务 SSE 回灌更细粒度的 `message/progress`
- 🧪 **AlphaSift 选股任务可恢复** - 选股页提交后台任务后轮询状态，切换页面再返回会恢复当前任务进度或最终结果，避免外部快照/行情/LLM 变慢时丢失反馈
- 🗂️ **大盘复盘任务可见性** - 首页触发大盘复盘后会返回 `task_id` 并轮询 `GET /api/v1/analysis/status/{task_id}`，在进行中/完成/失败场景给出可见反馈，失败时直接透出报错内容
- 🗂️ **市场复盘历史独立入口** - 大盘复盘历史通过专用入口与普通个股历史隔离；建议通过 `stock_code=MARKET` + `report_type=market_review` 直接查询与回放大盘复盘记录
- 🧾 **市场复盘历史可复用** - 大盘复盘任务会持久化到分析历史，`report_type` 为 `market_review`，可直接通过历史列表/详情打开对应 Markdown 或详情页，不会重新触发分析重算
- 🧭 **市场位置卡片** - A 股普通分析报告会展示市场题材层和个股位置层，区分大盘主线、主关联题材、题材阶段、个股位置和缺失证据
- 🧩 **输入数据块可见** - 普通分析报告会在历史详情、同步响应和 completed 任务状态中返回低敏 `AnalysisContextPack` overview，Web 报告页在策略点位和资讯之后默认折叠展示数据块状态、来源、缺失原因和降级摘要
- 💬 **问股追问上下文** - 从历史报告进入问股后，后续追问会持续携带当前 `stock_code/stock_name`；切回或重载已有问股会话时，会从已加载的历史用户消息恢复基础当前标的；只有用户明确切换标的时才切换上下文，含比较/对比/vs/差异/相比等明确比较意图或多个非当前明确股票代码的问题不会污染当前标的
- 📈 **回测验证** - 评估历史分析准确率，查询方向胜率与模拟收益
- 🔗 **API 文档** - 访问 `/docs` 查看 Swagger UI

### 与本变更相关的产品行为

- Web 语言状态采用两层机制：`dsa.uiLanguage`（浏览器持久化）与 `REPORT_LANGUAGE`（报告输出）解耦。
  - `dsa.uiLanguage` 只决定 WebUI 文案与导航语言（`zh` / `en`），取值优先级为本地持久化值 -> 浏览器语言 -> 默认 `zh`。
  - `REPORT_LANGUAGE` 控制报告文本、股票简称本地化与报告页固定文案（`zh` / `en` / `ko`）。
- 页面语言切换为用户体验增强，不属于回归验证证据记录范围；截图与命令请按 PR 流程在 PR 描述中单独维护。
- 本改动仅新增请求级报告语言覆盖参数，不改变 `provider`/`model`/`base_url` 的配置迁移与清理逻辑。

### API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/analysis/analyze` | POST | 触发股票分析 |
| `/api/v1/analysis/market-review` | POST | 后台触发大盘复盘；请求体可传 `{"send_notification": true}`；与 `main.py --market-review` 与 `bot` 复用同一套 `GeminiAnalyzer/SearchService/NotificationService` 组装语义 |
| `/api/v1/analysis/tasks` | GET | 查询任务列表 |
| `/api/v1/analysis/tasks/stream` | GET (SSE) | 订阅任务实时状态流；`task_progress` 可选携带 `flow_event` 增量运行流事件 |
| `/api/v1/analysis/tasks/{task_id}/flow` | GET | 查询 active task 的运行流快照 |
| `/api/v1/analysis/status/{task_id}` | GET | 查询任务状态 |
| `/api/v1/alphasift/screen/tasks` | POST | 后台提交 AlphaSift 选股任务（需先开启 `ALPHASIFT_ENABLED`） |
| `/api/v1/alphasift/screen/tasks/{task_id}` | GET | 查询 AlphaSift 选股任务状态与完成结果 |
| `/api/v1/history` | GET | 查询分析历史 |
| `/api/v1/history/{record_id}/diagnostics` | GET | 查询历史报告运行诊断摘要与脱敏复制文本 |
| `/api/v1/history/{record_id}/flow` | GET | 查询历史报告运行流快照，普通个股和 `MARKET/market_review` 大盘复盘复用同一契约 |
| `/api/v1/decision-signals` | POST | 显式创建或按同源键去重决策信号，返回 `{ item, created }` |
| `/api/v1/decision-signals` | GET | 分页查询决策信号，支持股票、市场、动作、阶段、风格、来源、状态、时间范围和 cache-only 持仓过滤 |
| `/api/v1/decision-signals/outcomes/run` | POST | 显式触发信号后验评估，默认跳过 completed/终态 unable、重算可恢复 unable，`force=true` 重算覆盖 |
| `/api/v1/decision-signals/outcomes` | GET | 分页查询信号后验结果 |
| `/api/v1/decision-signals/outcomes/stats` | GET | 查询当前后验引擎统计，默认排除 archived 信号 |
| `/api/v1/decision-signals/{signal_id}/outcomes` | GET | 查询单个信号在当前后验引擎下的结果 |
| `/api/v1/decision-signals/{signal_id}/feedback` | GET | 查询单个信号的用户反馈；无反馈时返回 `feedback_value=null` |
| `/api/v1/decision-signals/{signal_id}/feedback` | PUT | 写入或更新单个信号的 `useful|not_useful` 反馈 |
| `/api/v1/decision-signals/{signal_id}` | GET | 查询单条决策信号，读取前执行懒过期 |
| `/api/v1/decision-signals/{signal_id}/status` | PATCH | 更新决策信号状态和可选 metadata |
| `/api/v1/decision-signals/latest/{stock_code}` | GET | 查询指定股票最新 active 决策信号 |
| `/api/v1/usage/summary?period=today|month|all` | GET | 按调用类型与模型维度汇总 LLM 调用次数和 Token 用量 |
| `/api/v1/usage/dashboard?period=today|month|all&limit=50` | GET | 返回 Token 用量看板数据：总量、Prompt/Completion 拆分、模型用量、调用类型分布和最近调用明细；Web 侧入口为左侧导航“用量” |
| `/api/v1/backtest/run` | POST | 触发回测 |
| `/api/v1/backtest/results` | GET | 查询回测结果（分页） |
| `/api/v1/backtest/performance` | GET | 获取整体回测表现 |
| `/api/v1/backtest/performance/{code}` | GET | 获取单股回测表现 |
| `/api/v1/stocks/extract-from-image` | POST | 从图片提取股票代码（multipart，超时 60s） |
| `/api/v1/stocks/parse-import` | POST | 解析 CSV/Excel/剪贴板（multipart file 或 JSON `{"text":"..."}`，文件≤2MB，文本≤100KB） |
| `/api/health` | GET | 健康检查 |
| `/docs` | GET | API Swagger 文档 |

> 说明：`POST /api/v1/analysis/analyze` 在 `async_mode=false` 时仅支持单只股票；批量 `stock_codes` 需使用 `async_mode=true`。异步 `202` 响应对单股返回 `task_id`，对批量返回 `accepted` / `duplicates` 汇总结构。
> 说明：`POST /api/v1/analysis/analyze` 支持使用 `skills` 传入策略 skill ID 列表；若未传则按服务端默认策略执行。为兼容历史调用，`strategies` 字段仍作为兼容别名保留。
> 说明：`POST /api/v1/analysis/analyze` 支持 `analysis_phase=auto|premarket|intraday|postmarket`，默认 `auto`。非 `auto` 只覆盖本次分析阶段与派生阶段标记，不改写真实交易日历时间；accepted response、内存 task status、任务列表和 SSE 会回显请求阶段，最终报告阶段以 `report.meta.market_phase_summary.phase` 为准。
> 说明：`POST /api/v1/analysis/analyze` 支持 `report_language=zh|en|ko`，并兼容 `reportLanguage` 作为别名；未传时回退到全局 `REPORT_LANGUAGE`（或环境中的 `Config.report_language`）。该字段仅影响本次分析的报告文本、`report.meta.report_language` 与持久化展示，不会持久化为运行时配置。
> 说明：Web 侧首页策略下拉为显式可选策略入口。用户未手动选择时不会携带 `skills`，与历史客户端行为一致；选择策略后将透传到该接口并在任务状态与历史快照中保留。
> 说明：`POST /api/v1/analysis/market-review` 采用后端与 CLI/Bot 共用的配置路径（`GeminiAnalyzer(config=...)` 与同样的搜索/提示词构造入口）。Provider 兼容路由会优先识别并使用 `litellm_model`、`llm_model_list`，若未配置则回退 legacy `GEMINI_*`、`OPENAI_*`、`ANTHROPIC_*`、`DEEPSEEK_*` 键；不会新增/调整 provider、Base URL 或 LiteLLM 路由语义。
> 说明：`POST /api/v1/analysis/market-review` 额外支持 `report_language=zh|en|ko`（支持别名 `reportLanguage`）。未传时同样回退到全局 `REPORT_LANGUAGE`。该参数仅影响本次复盘报告文本与结构化返回字段中的语言相关内容；Bot、schedule、CLI 或按钮触发的 `main.py --market-review` 仍沿用全局配置，未新增请求级覆盖能力。
> 说明：`POST /api/v1/analysis/market-review` 是 Web / 桌面端的人工触发入口，点击后会直接提交大盘复盘任务，不会因 `TRADING_DAY_CHECK_ENABLED=true` 或当日相关市场休市而短路跳过；定时任务、GitHub Actions 手动运行和 CLI 默认入口仍遵循交易日检查，可用 `--force-run` 或 workflow `force_run` 覆盖。
> 审计依据：优先级与回退语义以 `src/config.py` 的 `Config._load_from_env()` 为准（`LITELLM_CONFIG` > `LLM_CHANNELS` > legacy）。配套回归见 `tests/test_llm_channel_config.py`（配置源解析）与 `tests/test_market_review_runtime.py`（共享装配路径）。该接口当前仅提供单进程/单机级防重复能力，若为多实例部署需通过外部任务队列或分布式锁补齐全局幂等。
> 说明：`POST /api/v1/analysis/market-review` 触发后，报告会以 `report_type=market_review` 写入历史库；你可直接查询 `/api/v1/history` 或 `/api/v1/history/{record_id}` 获取历史 Markdown，避免再次触发分析重算。
> 说明：历史列表新增 `report_type` 查询参数；通过 `stock_code=MARKET&report_type=market_review` 可单独读取大盘复盘历史集合，与普通个股历史逻辑完全隔离。
> 说明：`POST /api/v1/analysis/market-review` 的返回与历史持久化都会包含 `market_review_payload`：`market_scope`、`sections`、`sectors`、`concepts`、`news`、`market_light`、`indices` 等结构化字段。Web 端 Markdown 渲染与历史详情会复用该结构化字段；若结构化字段为空则回退到原始 Markdown。
> 说明：运行流快照接口返回 `lanes/nodes/edges/events/summary` 统一契约。active task 缺少 diagnostics 时返回 skeleton flow；若任务 SSE 已收到真实 `flow_event`，快照会包含最近增量事件。completed history 优先使用 `context_snapshot.diagnostics` 与 `analysis_context_pack_overview` 构建完整拓扑。`cancel_requested/cancelled` 是合法状态，不会映射为 failed。
> 说明：`market_review_payload` 中的 `breadth` 仅在行情宽度数据真实可用时下发；当美股/港股或接口暂不可用时不下发该字段。前端显示层需按“字段缺失”降级为“暂无数据”而不是展示 0。
> 说明：该端点若返回 `task_id`，WebUI 会轮询 `GET /api/v1/analysis/status/{task_id}` 展示状态。状态为 `completed` 时给出完成提示（报告已生成并按配置推送），状态为 `failed` 时在前端错误区域显示 `error` 原因。
> 说明：`GET /api/v1/history/{record_id}/diagnostics` 支持历史记录主键 ID 或 `query_id`，返回 `normal/degraded/failed/unknown` 摘要、关键链路组件和可复制的脱敏 `copy_text`；旧报告缺少诊断快照时返回 `unknown`，不影响报告读取。
> 说明：`GET /api/v1/history` 的列表摘要可按 `stock_code` 分页查询同一股票历史，并返回趋势判断、分析摘要、模型名与分析时价格/涨跌幅等可选字段；旧记录缺少快照字段时返回空值。`created_at` 与 `/api/v1/history/stocks` 的 `last_analysis_time` 使用带服务器时区偏移的 ISO 8601 时间戳；日期筛选仍按服务器本地日期解释。Web 报告页的“历史趋势”抽屉复用该接口加载同股历史。
> 说明：`GET /api/v1/usage/dashboard` 复用 `llm_usage` 审计表，不新增配置项或数据库迁移。接口仅返回已落库的调用次数、Prompt/Completion/Total Token 聚合、模型维度用量和最近调用记录，不推导模型上下文窗口或 provider 元数据。
> 说明（Issue #1520）：列表中的模型名展示字段仅来源于历史快照中的 `model_used`，仅用于历史回溯展示，不影响运行时模型模型路由（`litellm_model`、`llm_model_list`）、Provider、Base URL 与配置迁移/清理语义。回退方式为回退本次提交，现网历史查询/抽屉/接口链路兼容性保持不变。
> 说明：历史详情、同步分析响应和 completed 任务状态会在 `report.details.analysis_context_pack_overview` 返回低敏输入数据块 overview；其中同步分析响应依赖本次已持久化的 `analysis_history.context_snapshot`，`SAVE_CONTEXT_SNAPSHOT=false` 时新记录不保证返回 overview。`details.context_snapshot` 会剥离该顶层字段，不返回完整 `AnalysisContextPack` 或 Prompt summary。
> 说明：`POST /api/v1/agent/chat` 与 `POST /api/v1/agent/chat/stream` 会把前端传入的 `context.stock_code` 作为问股当前标的基线，但服务端会先重新判定 stock scope。前端从历史报告进入问股后会持续发送 active stock context；切回或重载已有会话时，会根据已加载的历史用户消息恢复基础 `{stock_code, stock_name: null}`。服务端会在每轮消息中重新判定 `maintain` / `switch` / `compare`：未明确切换时，带 `stock_code` 的股票工具调用只能访问当前标的；显式切换会清理旧标的历史摘要和预取数据；含比较/对比/vs/差异/相比等明确比较意图或多个非当前明确股票代码的问题允许本轮明确出现的多个代码，但不改写当前标的。若模型误把 TTM、PE、MACD、KDJ 等金融缩写、移动均线语境下的 `MA` 指标词，或 SH/SZ/BJ/HK/SS 等交易所片段当成股票代码调用工具，后端会返回不可重试的 `stock_scope_violation` 工具结果，而不会执行对应股票工具。工具名只解析注册表中的精确名称；任何 provider namespace 或 suffix 都不会路由到已有工具。
> 说明：`POST /api/v1/backtest/run` 新增 `analysis_date_from` / `analysis_date_to`（`YYYY-MM-DD`）请求参数用于按历史分析日期筛选候选；若 `analysis_date_from > analysis_date_to`，接口返回 400 `invalid_params`。
> 说明：回测执行成功但无新入库结果时，`BacktestRunResponse.message` 返回可读诊断说明，`diagnostics` 返回排查上下文（示例：`empty_reason`、`analysis_date_from`、`analysis_date_to`、`eval_window_days`、`min_age_days`、`limit`）。
> 说明：`GET /api/v1/backtest/results`、`GET /api/v1/backtest/performance`、`GET /api/v1/backtest/performance/{code}` 同步支持 `analysis_date_from`、`analysis_date_to`；不传时保持历史行为。

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

# 透传策略（可选）
curl -X POST http://127.0.0.1:8000/api/v1/analysis/analyze \
  -H 'Content-Type: application/json' \
  -d '{"stock_code": "600519", "skills": ["bull_trend", "growth_quality"]}'

# 查询任务状态
curl http://127.0.0.1:8000/api/v1/analysis/status/<task_id>

# 查询今日 LLM 用量
curl "http://127.0.0.1:8000/api/v1/usage/summary?period=today"

# 查询今日 LLM 用量看板
curl "http://127.0.0.1:8000/api/v1/usage/dashboard?period=today&limit=50"

# 触发回测（全部股票）
curl -X POST http://127.0.0.1:8000/api/v1/backtest/run \
  -H 'Content-Type: application/json' \
  -d '{"force": false}'

# 触发回测（指定股票）
curl -X POST http://127.0.0.1:8000/api/v1/backtest/run \
  -H 'Content-Type: application/json' \
  -d '{"code": "600519", "force": false}'

# 触发回测（按分析日期范围）
curl -X POST http://127.0.0.1:8000/api/v1/backtest/run \
  -H 'Content-Type: application/json' \
  -d '{"analysis_date_from": "2026-05-01", "analysis_date_to": "2026-05-31", "limit": 100}'

# 触发回测（指定股票 + 日期范围 + 强制重跑）
curl -X POST http://127.0.0.1:8000/api/v1/backtest/run \
  -H 'Content-Type: application/json' \
  -d '{"code": "600519", "force": true, "analysis_date_from": "2026-05-01", "analysis_date_to": "2026-05-31"}'

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
| 日股 | Yahoo 后缀 `.T` | `7203.T`、`6758.T` |
| 韩股 | Yahoo 后缀 `.KS` / `.KQ` | `005930.KS`、`035720.KQ` |
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
A: 修改 `STOCK_LIST` 环境变量，多个代码推荐用英文逗号分隔。系统也会识别中文逗号、顿号、分号、空格和换行，并在 Web 设置页保存或自选增删后规范为英文逗号。

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

`AGENT_EVENT_MONITOR_ENABLED=true` 后，schedule 模式会按 `AGENT_EVENT_MONITOR_INTERVAL_MINUTES` 运行告警 worker。worker 每轮读取 Alert API 创建并启用的持久化规则，同时继续兼容 `AGENT_EVENT_ALERT_RULES_JSON` 中的 legacy 规则；触发后仍发送到现有通知渠道。Alert API / Web 持久化规则支持实时价、涨跌幅、成交量、日线技术指标、`watchlist`、`portfolio_holdings`、`portfolio_account`，以及 `market` 大盘红绿灯目标；legacy JSON 仍仅支持三类基础规则。

> 兼容与迁移说明：本节记录当前事件告警规则（含 `price_change_percent`）运行时行为，未变更模型名、provider、Base URL、LiteLLM、`OPENAI_*`、`DEEPSEEK_*`、`GEMINI_*` 等外部模型/API 配置语义。legacy JSON 不会被自动迁移、删除或改写；若需回退，删除或关闭 `AGENT_EVENT_MONITOR_ENABLED` 即可停止后台告警 worker。

| `alert_type` | 方向字段 | 阈值字段 | 说明 |
| --- | --- | --- | --- |
| `price_cross` | `above` / `below` | `price` | 当前价上破或下破指定价格 |
| `price_change_percent` | `up` / `down` | `change_pct` | 涨跌幅达到指定百分比 |
| `volume_spike` | - | `multiplier` | 最新成交量超过近 20 日均量的指定倍数 |
| `ma_price_cross` | `above` / `below` | `window` | 日线 close 相对 MA(window) 边缘上穿或下穿 |
| `rsi_threshold` | `above` / `below` | `period`、`threshold` | RSI 边缘上穿或下穿阈值 |
| `macd_cross` | `bullish_cross` / `bearish_cross` | `fast_period`、`slow_period`、`signal_period` | DIF/DEA 边缘金叉或死叉 |
| `kdj_cross` | `bullish_cross` / `bearish_cross` | `period`、`k_period`、`d_period` | K/D 边缘金叉或死叉 |
| `cci_threshold` | `above` / `below` | `period`、`threshold` | CCI 边缘上穿或下穿阈值 |
| `portfolio_stop_loss` | `mode=near|breach` | - | 账户级止损接近或触发 |
| `portfolio_concentration` | - | - | 账户级 symbol 集中度 |
| `portfolio_drawdown` | - | - | 账户级最大回撤告警 |
| `portfolio_price_stale` | - | - | 持仓价格 stale 或 missing |
| `market_light_status` | - | `statuses` | 当前大盘红绿灯状态命中 `red/yellow` 列表 |
| `market_light_score_drop` | - | `min_drop` | 相比上一交易日 Market Light score 下降达到阈值 |

示例：

```env
AGENT_EVENT_MONITOR_ENABLED=true
AGENT_EVENT_MONITOR_INTERVAL_MINUTES=5
AGENT_EVENT_ALERT_RULES_JSON=[{"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800},{"stock_code":"300750","alert_type":"price_change_percent","direction":"down","change_pct":3.0},{"stock_code":"000858","alert_type":"volume_spike","multiplier":2.5}]
```

worker 会把 `triggered`、`skipped`、`degraded`、`failed` 写入 `alert_triggers` 作为评估历史；正常未触发不写历史。DB 持久化规则的 `triggered` 历史按 `rule_id + target + data_source + data_timestamp` 对同一数据点做 best-effort 去重，重复命中会复用最早一条触发记录，`data_timestamp` 缺失时不去重。真实触发后会把每个通知渠道的 attempt 写入 `alert_notifications`，并为 Alert API 创建的持久化规则写入 `alert_cooldowns` 业务冷却状态；若读取持久化冷却失败，worker 会临时使用进程内 fingerprint 防止 DB 异常期间重复推送。legacy `AGENT_EVENT_ALERT_RULES_JSON` 规则继续使用进程内 fingerprint 抑制，不写持久化冷却；通知基础设施的 `notification_noise.py` 降噪仍独立生效。Web 规则列表使用后端返回的 `cooldown_active` 判断冷却状态，避免浏览器本地时区解析影响展示。

技术指标规则只使用日线 close 的边缘触发，partial bar 处理是服务器本地时区 + 16:00 的启发式，不做市场日历精确判定。`watchlist` 每轮刷新 `STOCK_LIST` 后展开，`portfolio_holdings` 从持仓快照的非零持仓按 symbol 去重展开，`portfolio_account` 复用持仓风险服务做账户级聚合评估。`market` 规则的 target 仅支持 `cn|hk|us|jp|kr`，使用结构化 `MarketLightSnapshot`；`trade_date` 来自当次 market overview，`data_quality=unavailable` 会跳过触发，非交易日会被交易日 gate 跳过，`market_light_score_drop` 只比较跨交易日 score。WebUI 的“告警”页面可以管理持久化规则、执行一次性 dry-run 测试，并查看触发历史、通知尝试结果和只读冷却状态；批量规则的列表冷却状态是父规则摘要，子目标冷却以触发历史为准。详细边界见 [实时告警中心](alerts.md)。

## 持仓管理说明

### `/portfolio` 页面可做什么

- 查看全量持仓或切换到单个账户视角。
- 在 `fifo` / `avg` 两种成本法之间切换，查看快照 KPI、风险摘要和 Top Positions 集中度图表。
- 直接在 Web 页面新增账户、删除误建账户，或录入交易、现金流水、公司行动等事件。
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
| `/api/v1/portfolio/accounts/{account_id}` | DELETE | 删除/归档持仓账户 |
| `/api/v1/portfolio/trades/{trade_id}` | DELETE | 删除交易记录 |
| `/api/v1/portfolio/cash-ledger/{entry_id}` | DELETE | 删除现金流水 |
| `/api/v1/portfolio/corporate-actions/{action_id}` | DELETE | 删除公司行动 |

> 查询类接口统一支持 `account_id`、`date_from`、`date_to`、`page`、`page_size` 等常见筛选参数；事件列表会返回统一的 `items`、`total`、`page`、`page_size` 结构。

### 使用行为说明

- CSV 导入内建 `huatai`、`citic`、`cmb` 解析器；若券商列表接口失败，Web 端会自动回退到这些内建选项。
- 导入流程会先把 CSV 解析成标准化记录，再逐条提交到持仓账本；遇到忙碌行会计入 `failed_count`，不会因为单行冲突让整批请求整体失败。
- 删除账户使用软删除语义：默认账户列表、快照、风险、录入入口和事件列表不再显示该账户，但交易、现金流水和公司行动不会被物理清理；如需纠正单条流水，需在账户归档前使用事件列表里的删除修正入口。
- 交易去重优先使用账户内唯一的 `trade_uid`，缺失时回退到基于日期、代码、方向、数量、价格、费用、税费、币种的确定性哈希。
- 卖出会先校验可用数量，超卖返回 `409 portfolio_oversell`；并发写入冲突时可能返回 `409 portfolio_busy`。
- 持仓快照的 `positions[]` 会返回 `price_source`、`price_date`、`price_stale`、`price_available` 等价格元信息；当天快照默认会先尝试实时行情，实时价不可用或非正值时再回退到 `as_of` 当天或之前最近的历史收盘价；传入 `include_realtime=false` 时会跳过实时行情并直接使用本地历史收盘价回退路径，Web 持仓页用该模式优先渲染持仓列表，避免外部实时行情源变慢时阻塞首屏。历史 `as_of` 快照不会拉取实时价，也不会再把成本价静默当作现价；缺价持仓会标记 `price_available=false` 并从市值与未实现盈亏汇总中排除。
- 汇率刷新会先尝试在线源；若在线获取失败，则回退到最近一次缓存并标记 `is_stale=true`，避免快照和风险页整体不可用。
- 当 `PORTFOLIO_FX_UPDATE_ENABLED=false` 时，手动刷新接口会明确返回“在线刷新已禁用”，页面不会误导为“当前没有可刷新的汇率对”。
- 风险摘要包含集中度、回撤、止损接近度等信息；`sector_concentration` 会优先尝试按板块归类，失败时降级到 `UNCLASSIFIED`，不会阻断风险结果返回。

### Agent 读取持仓

- Agent 可通过 `get_portfolio_snapshot` 获取面向账户的紧凑持仓摘要，默认包含精简风险块，适合控制 Token 开销。
- 可选参数包括 `account_id`、`cost_method`、`as_of`、`include_positions`、`include_risk`。
- 若风险块生成失败，快照仍会返回；若当前环境未启用持仓模块，工具会返回结构化 `not_supported`。
