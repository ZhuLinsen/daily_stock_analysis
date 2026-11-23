# 运行诊断与数据可靠性 1.0（Phase 1）

本文档记录 #1391 Phase 1 的最小运行时落地范围：统一 `trace_id`，并为首批关键数据链路记录结构化 provider 尝试。

## 本轮范围

- API / Web 异步任务创建时，`TaskInfo` 使用 `task_id` 作为默认 `trace_id`。
- 任务列表、任务状态与 SSE 事件追加 `trace_id` 字段；旧客户端可忽略该字段。
- 同步分析使用本次 `query_id` 作为默认 `trace_id`。
- pipeline 运行时建立轻量诊断上下文，贯穿日线准备与单股分析。
- `data_provider/base.py` 对以下链路记录 `ProviderRun` 风格事件：
  - `daily_data`
  - `realtime_quote`
- 诊断记录写入内存上下文，随分析 `context_snapshot.diagnostics` 保存；旧历史记录缺少该字段时保持兼容。

## `ProviderRun` 字段

首版字段保持最小：

- `trace_id`
- `data_type`
- `provider`
- `operation`
- `success`
- `latency_ms`
- `error_type`
- `error_message_sanitized`
- `fallback_to`
- `record_count`
- `created_at`

错误摘要会做基础脱敏，避免输出 token、API key、Authorization、Cookie、包含敏感参数的 webhook URL 等内容。

## 稳定性边界

- 诊断记录失败只记录 warning，不影响主分析、数据源 fallback 或历史保存。
- 本轮不新增配置项，不改变数据源优先级，不改变 fallback 策略。
- 本轮不新增 Web 展示组件；`trace_id` 和 provider runs 先进入 API/SSE/历史快照，供后续 Phase 2/3 聚合与展示复用。

## 验证建议

```bash
python -m pytest tests/test_run_diagnostics_p1.py tests/test_analysis_api_contract.py::AnalysisApiContractTestCase::test_get_analysis_status_normalizes_completed_queue_result_contract
python -m py_compile src/services/run_diagnostics.py src/services/task_queue.py src/services/analysis_service.py src/core/pipeline.py data_provider/base.py api/v1/schemas/analysis.py api/v1/endpoints/analysis.py
```
