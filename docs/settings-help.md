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

## 首批覆盖范围

本轮先覆盖代表性配置项：

- `STOCK_LIST`
- `LITELLM_MODEL`
- `LLM_CHANNELS`
- `FEISHU_WEBHOOK_URL`
- `WEBUI_HOST`

后续 PR 可以按模块继续覆盖 AI 模型、数据源、搜索、通知、WebUI、认证、调度、Agent、回测、报告、代理、日志、数据库和桌面端相关配置。

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
