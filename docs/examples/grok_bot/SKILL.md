---
name: daily-stock-analysis
description: 调用 daily_stock_analysis API 做股票分析。当用户说「分析茅台」「analyze AAPL」「帮我看看 600519」或要大盘复盘时使用。优先用股票代码。
---

# daily_stock_analysis

本 Skill 供 Grok Bot（2026-08-11 AI teammate）使用。通过 HTTP 调用已部署的 DSA，不要把 Bot 配成 LiteLLM provider。

需要环境变量 `DSA_BASE_URL`（DSA API 根地址，无尾斜杠）。

## 何时使用

- 分析单只或多只股票
- 查询某股最新 DecisionSignal（早报 / 盯盘 Routine）
- 大盘复盘

## 工作流程

1. 提取股票代码：A股 6 位（`600519`）、港股 `hk00700`、美股 `AAPL`、台股 `.TW` / `.TWO`。只有中文名时先提示用户给代码，或使用常见映射（茅台 → `600519`）。
2. 需要完整分析时 POST `{DSA_BASE_URL}/api/v1/analysis/analyze`。**Routine 或预计超过 Bot HTTP 超时的分析，从一开始用异步**，不要先同步再改发异步：同步超时后服务端 `_handle_sync_analysis` 仍会继续跑且不进 `TaskQueue`，再发 `async_mode: true` 会绕过队列去重，重复计费和推送。

```json
{
  "stock_code": "<code>",
  "report_type": "detailed",
  "force_refresh": true,
  "async_mode": true
}
```

返回 202 + `task_id` 后轮询 `GET {DSA_BASE_URL}/api/v1/analysis/status/{task_id}`，直到 `status: completed`。完成报告在 `result.report`，不要读响应根上的 `report`。

仅当 Bot HTTP 超时 ≥300 秒、且用户在等单次同步结果时，才用 `async_mode: false`。同步超时后不要改发异步重跑；先查询该股是否已有进行中任务（409 / status），或读最新 DecisionSignal。

3. 只需最新建议、不要重跑分析时：`GET {DSA_BASE_URL}/api/v1/decision-signals/latest/{stock_code}`。
4. 大盘复盘：`POST {DSA_BASE_URL}/api/v1/analysis/market-review` 固定返回 202 + `task_id`，不是复盘正文。轮询同一条 status 接口，完成后读顶层 `market_review_report` 或 `market_review_payload`（不在 `result.report`）。
5. 健康检查失败先 `GET {DSA_BASE_URL}/api/health`。

## 如何呈现结果

- 同步分析：`report.summary.operation_advice`、`trend_prediction`、`analysis_summary`
- 异步分析：`result.report.summary.operation_advice`、`result.report.summary.trend_prediction`、`result.report.summary.analysis_summary`
- 结构化动作：`action` / `action_label`（`buy|add|hold|reduce|sell|watch|avoid|alert`）；异步时在 `result.report.summary`
- 计划：同步 `report.strategy.ideal_buy` / `stop_loss` / `take_profit`；异步 `result.report.strategy.*`
- 大盘复盘：`market_review_report`（文本）或 `market_review_payload`（结构化）
- 缺字段时回退 `operation_advice`；旧三态统计仍看 `decision_type`
- DecisionSignal 只展示建议，不下单、不调仓

## 错误

| 状态 | 处理 |
| --- | --- |
| 连接失败 | 检查 DSA 是否在跑、`DSA_BASE_URL` 是否正确 |
| 400 | 检查 `stock_code` |
| 409 | 该股正在分析，查已有 `existing_task_id` 的 status；不要另开一条分析 |
| 500 | 看 DSA 日志；确认 `LITELLM_MODEL` 与对应 Key（含可选 `XAI_API_KEY`） |

若 `ADMIN_AUTH_ENABLED=true`，当前 API 只认 Cookie，不认 Bearer。不要把 `XAI_API_KEY` 当作 DSA API 密钥。
