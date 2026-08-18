# Grok Bot 集成说明

本文说明 [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis)（DSA）如何对接 **2026-08-11** 上线的 [Grok Bot](https://x.ai/bot)（xAI 的 AI teammate 产品，不是普通 Grok 聊天）。

不新增 API、环境变量、provider 或运行时分支。Grok Bot 只消费现有 REST / Skill 契约。

## 先分清两条路径

| 路径 | 是什么 | 怎么配 | 不是什么 |
| --- | --- | --- | --- |
| **Grok 当分析模型** | LiteLLM 直连 `xai/*`，DSA 用 Grok 写报告 | `XAI_API_KEY` + `LITELLM_MODEL=xai/<官方模型ID>`，见 [LLM 配置指南](LLM_CONFIG_GUIDE.md) | 不是 Grok Bot 产品 |
| **Grok Bot 当队友** | 带持久云电脑、Skills、Routines、MCP/Connectors、computer use 的 teammate | Bot 调 DSA 已部署的 HTTP API，或在其电脑上跑 `python main.py` | 不要把 Bot 配成 `LITELLM_MODEL` |

两条路径可以同时用：DSA 用 `xai/grok-*` 做分析，Grok Bot 再来读报告 / `DecisionSignal`。

## 推荐对接顺序

1. 先让 DSA API 长期可访问：`python main.py --serve-only` 或 Docker。GitHub Actions 只做定时任务，不长期暴露 API。
2. 在 Grok Bot 里放一条 Skill（可直接改 [openclaw Skill](openclaw-skill-integration.md) 的 `SKILL.md` 示例，或用 [`docs/examples/grok_bot/SKILL.md`](examples/grok_bot/SKILL.md)）。
3. 需要盘中盯盘 / 早报时，用 Bot Routine 调 `DecisionSignal` 查询，而不是反复跑完整分析。
4. 只有 Bot 已经能稳定调通 HTTP 之后，才考虑把同一组接口挂到 MCP Connector。本仓库 **P0 不提供 MCP server**。

## Skill：触发个股分析

与 openclaw 相同的主入口。Bot / Routine **默认 `async_mode: true`**：

```http
POST {DSA_BASE_URL}/api/v1/analysis/analyze
Content-Type: application/json

{
  "stock_code": "600519",
  "report_type": "detailed",
  "force_refresh": true,
  "async_mode": true
}
```

- 异步：返回 202 + `task_id`，再 `GET /api/v1/analysis/status/{task_id}` 直到 `status: completed`。完成报告在 `result.report`（`TaskStatus.result` 是 `AnalysisResultResponse`），不要读响应根上的 `report`。
- 不要在同步超时后改发异步重跑。同步超时后服务端 `_handle_sync_analysis` 仍会继续跑且不进 `TaskQueue`，再发 `async_mode: true` 会绕过队列去重，造成重复 LLM 费用与推送。
- 仅当 HTTP 超时 ≥300 秒且用户在等单次结果时，才用 `async_mode: false`。同步响应的报告在根级 `report`。
- 健康检查：`GET /api/health`。
- 问股 Agent（需 `AGENT_MODE=true`）：`POST /api/v1/agent/chat`。

结果读取约定（与 openclaw Skill 一致，避免平行字段）：

- 自由文本：`report.summary.operation_advice`、`trend_prediction`、`analysis_summary`（异步前缀 `result.`）
- 结构化动作：可选 `action` / `action_label`（八态 `buy|add|hold|reduce|sell|watch|avoid|alert`）
- 旧历史缺字段时回退 `operation_advice`；旧三态统计仍以 `decision_type` 为准

Grok Bot Skill 正文见 [`docs/examples/grok_bot/SKILL.md`](examples/grok_bot/SKILL.md)，也可复用 [openclaw Skill](openclaw-skill-integration.md) 示例。环境变量统一为 `DSA_BASE_URL`。

## Skill：大盘复盘

`POST {DSA_BASE_URL}/api/v1/analysis/market-review` 固定返回 202 接受体 + `task_id`，不是复盘正文。请求体可传 `send_notification`、`region`。

轮询 `GET /api/v1/analysis/status/{task_id}` 直到 `status: completed`，从 `TaskStatus` 顶层读 `market_review_report` 或 `market_review_payload`（不在 `result.report`）。

## Routine：消费 DecisionSignal

不要让 Routine 每次都重跑分析。公开查询口：

| 用途 | 接口 |
| --- | --- |
| 某股最新 active 信号 | `GET /api/v1/decision-signals/latest/{stock_code}` |
| 分页筛选 | `GET /api/v1/decision-signals` |
| 后验统计 | `GET /api/v1/decision-signals/outcomes/stats` |
| 有用 / 无用反馈 | `GET/PUT /api/v1/decision-signals/{signal_id}/feedback` |

字段与生命周期见 [DecisionSignal 专题](decision-signals.md)。`DecisionSignal` 只记录建议，不执行下单或调仓。

需要给 Bot 低敏上下文时，用 [AnalysisContextPack](analysis-context-pack.md) 的公开 overview，不要把完整 `context_snapshot` 塞进 Skill 提示词。

## MCP / Connector / computer use

- **MCP**：把上表 REST 包成 tool 即可（`analyze_stock`、`get_latest_signal`、`market_review`）。本仓库暂不内置 MCP server，以免和 FastAPI 契约双源漂移。
- **Connectors**：Grok Bot 可登录飞书 / 邮件等；DSA 自己的通知渠道仍走 `.env` 里已有的 webhook，不必经 Bot 转发。
- **Computer use**：仅当 Bot 的云电脑里已经 clone 并配好 `.env` 时，才适合跑 `python main.py --stocks 600519,AAPL` 或 `python main.py --market-review`。默认仍推荐 HTTP，便于鉴权、超时和异步任务。

## 认证

默认 DSA API 无需认证。若 `ADMIN_AUTH_ENABLED=true`，当前只支持登录后的 Cookie，**不支持 Bearer Token**。Grok Bot 若只能带 `Authorization: Bearer`，先保持 API 不鉴权并限制监听网段，或在反代层做独立鉴权；不要把 `XAI_API_KEY` 当成 DSA API 的鉴权密钥。

## 明确不做的事

- 不把 Grok Bot 注册成 LiteLLM managed channel。
- 不新增 `GROK_BOT_*` 环境变量。
- 不复制一套平行 `DecisionSignal` / `AnalysisContextPack` schema。
- 不在本页承诺某个 `grok-*` 型号在当前 `litellm` 约束内一定可用。型号以 [xAI 文档](https://docs.x.ai/docs) 为准，并用 `python scripts/check_env.py --llm` 实测。

## 最小验收

1. DSA：`python scripts/check_env.py --config`；若走 xAI 模型再跑 `python scripts/check_env.py --llm`。
2. `GET {DSA_BASE_URL}/api/health` 成功。
3. Bot Skill 对一只真实代码（如 `AAPL` 或 `600519`）拿到 `operation_advice` 或 `action`（异步路径从 `result.report` 读）。
4. 大盘复盘能从 status 拿到 `market_review_report` 或 `market_review_payload`，而不是只拿到 202 accepted。
5. Routine 能读到 `GET /api/v1/decision-signals/latest/{stock_code}` 的 JSON，而无需重跑分析。
