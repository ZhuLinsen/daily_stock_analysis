# 设置页配置帮助维护说明

设置页配置帮助用于把配置项的关键说明放到 WebUI 内部，减少用户在设置页和文档之间反复切换。页面上仍保留短描述，详细说明通过配置项标题旁的 help icon 打开。

本文只说明帮助系统的维护规则，不替代完整配置文档。配置语义、默认值、运行时优先级和排障细节仍以 `.env.example`、`docs/full-guide.md` 及对应专题文档为事实源。

## 数据结构

后端配置注册表在 `src/core/config_registry.py` 中为字段追加帮助元数据：

- `help_key`：前端多语言帮助文案的稳定 key。
- `examples`：可直接展示的配置样例。敏感字段只能使用占位符，例如 `sk-xxxx`、`your_token`。
- `docs`：相关文档链接，优先指向仓库内已有专题文档或完整指南。
- `warning_codes`：面向前端或后续校验扩展的稳定提示 code。

前端长文案维护在 `apps/dsa-web/src/locales/settingsHelp.ts`：

- 默认展示中文文案。
- 英文文案保留同样结构，便于后续扩展语言切换。
- 文案应解释用途、取值说明、影响范围、注意事项和相关文档，不应复制完整专题文档。

## 覆盖范围

PR1 覆盖基础设施与首批代表性配置项：

- `STOCK_LIST`
- `LITELLM_MODEL`
- `LLM_CHANNELS`
- `FEISHU_WEBHOOK_URL`
- `WEBUI_HOST`

PR2 继续覆盖高频、易填错配置项：

- AI 模型运行时：Agent 主模型、fallback 模型、高级 YAML 路由、temperature、provider API Key、OpenAI-compatible Base URL。
- LLM Channels 编辑器内部字段：渠道名、协议、Base URL、API Key、模型列表、运行时能力检测、主模型、Agent 主模型、fallback、Vision 和 temperature。
- 数据源与搜索：Tushare、实时行情优先级、实时技术指标、搜索 API Key、SearXNG、筹码分布、新闻窗口。
- 通知：Webhook、Telegram、邮件、Discord/Slack 等聊天平台、报告输出、Webhook SSL 校验。
- WebUI / auth / schedule / proxy：Host、Port、登录保护、可信反向代理、定时任务、交易日检查、网络代理。

后续 PR 可以继续覆盖 Agent、回测、报告高级字段、日志、数据库、桌面端和更细分部署配置。

### 覆盖边界

- `settingsHelp.ts` 中的 `settings.llm_channel.*` 系列为 LLM 渠道编辑器内部字段说明，仅用于前端渲染，不对应 `.env` 的单独配置项；这是 PR2 中刻意的“内置扩展”设计，用于提升编辑器可用性。
- 其余 help 文案均应能从 `src/core/config_registry.py` 中某个字段的 `help_key` 映射到后端注册元数据，便于与文档源、`warning_codes` 一起统一维护。

## 事实源优先级

新增或修改帮助文案时，优先从以下位置核对：

1. `.env.example`：配置键名、默认值、样例格式和敏感占位符。
2. `docs/full-guide.md`：主要配置说明、运行入口和部署上下文。
3. `docs/LLM_CONFIG_GUIDE.md`、`docs/llm-providers.md`：LLM 优先级、Channels、provider/model、兼容边界和排障说明。
4. 专题文档：例如 `docs/bot/feishu-bot-config.md`、`docs/deploy-webui-cloud.md`、`docs/desktop-package.md`。
5. 代码实现和测试：当文档与代码不一致时，先以可执行实现为准，并同步修正文档。

## 维护边界

- 帮助文案不能改变配置保存、校验、运行时优先级、`.env` 写回或环境变量覆盖语义。
- 不展示真实密钥、账号、token、Webhook 完整值或本机绝对路径。
- LLM 相关示例如果写入具体 provider 前缀、模型名或 Base URL，必须能追溯到当前仓库文档或官方来源；否则应使用占位符或链接到事实源。
- 对第三方模型/API 的可用性、LiteLLM 兼容窗口或 provider fallback 规则，不在设置帮助中单独承诺；需要变更时必须同步更新专题文档和 PR 兼容性说明。
- 中英双语文案应保持同一语义范围。若只更新一种语言，需要在交付说明中写明原因。
- 首屏短描述保持简洁，详细说明放在 help dialog 中，避免 hover tooltip 与常驻短描述重复。

## 重启语义

设置页保存通常只写入 `.env` 并触发可运行时重载的配置刷新。帮助文案和 `warning_codes` 必须显式区分以下情况：

- `WEBUI_HOST`、`WEBUI_PORT`：监听地址和端口只在进程启动时绑定，保存后必须重启当前进程、Docker 容器或服务管理器才会生效。
- `RUN_IMMEDIATELY`：非 schedule 模式启动期单次运行配置，保存后不会让已运行的 WebUI/API 进程立即触发分析。
- `SCHEDULE_ENABLED`、`SCHEDULE_RUN_IMMEDIATELY`：schedule 模式启动行为，保存后不会启动、停止或重建当前 scheduler，需要以 schedule 模式重启后生效。
- `SCHEDULE_TIME`：不是重启必需项。已运行的 schedule 模式会在下一轮调度检查中读取新时间并重建 daily job；但如果当前进程未以 schedule 模式启动，保存该字段不会自动创建 scheduler。
