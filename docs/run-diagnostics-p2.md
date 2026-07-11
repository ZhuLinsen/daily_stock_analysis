# 运行诊断与数据可靠性 1.0（Phase 2）

本文档记录 #1391 Phase 2 的后端落地范围：基于 Phase 1 的 `trace_id` 与 provider run 记录，生成用户可读的运行诊断摘要，并提供可复制的脱敏排障文本。

## 本轮范围

- 新增 `RunDiagnosticSummary` 聚合逻辑，输出总体状态：
  - `normal` / 正常
  - `degraded` / 部分降级
  - `failed` / 失败
  - `unknown` / 未知
- 摘要覆盖以下关键链路：
  - 实时行情
  - 日线数据
  - 新闻搜索
  - LLM
  - 通知
  - 历史保存
- `AnalysisService` 同步/异步任务结果追加可选 `diagnostic_summary`。
- 新增历史报告诊断 API：

```http
GET /api/v1/history/{record_id}/diagnostics
```

`record_id` 支持历史记录主键 ID 或 `query_id`，返回诊断摘要与 `copy_text`。

## 复制排障信息

`copy_text` 是面向 issue/排障的纯文本，包含：

- `trace_id`
- `query_id`
- `stock_code`
- `trigger_source`
- 总体 `data_status`
- 实时行情、日线、新闻、LLM、通知、历史保存的简短状态
- 首要原因

生成前会复用运行诊断脱敏规则，避免输出 token、API key、Authorization、Cookie、webhook URL、邮箱密码、代理凭据等敏感信息。

## 兼容性边界

- 本轮不新增配置项，不改变数据源优先级，不改变 fallback 策略。
- 本轮不改变任何 LLM/provider/Base URL/配置迁移语义，仅新增历史快照中的诊断字段与查询接口。
- API 只追加可选字段和新增只读接口；旧客户端可忽略。
- 旧报告没有 `context_snapshot.diagnostics` 时返回 `unknown`，不报错。
- 通知诊断在当前任务上下文中记录；历史报告如果保存时尚无通知证据，会在摘要中显示通知结果未知。
- 诊断摘要生成失败不得影响报告读取或分析主流程。

### 结构化检测告警澄清

- 自动化检测命中的“模型/provider/base URL 兼容风险”来源是：`src/agent/factory.py` 新增了 `agent_max_steps` 与 `agent_orchestrator_timeout_s` 的 **数字安全兜底**（`_coerce_config_int`），因此扫描可能将其误识别为配置敏感路径；该命中属于测试与路由保护触发，不是运行时配置或兼容语义变更。
- 当数值配置存在非法值时，系统会记录 `warning` 到 `src.agent.factory` 日志（示例：`[AgentFactory] Invalid value for agent_max_steps...`），并回退到默认值；日志用于定位“参数未生效”类问题，与模型/provider/base URL 兼容性独立。
- 本轮确认无静默迁移/清空/改写：
  - `src/core/pipeline.py` 与 `src/services/analysis_service.py` 仅新增诊断记录，不修改 `Config` 中任何 `litellm_model`、`agent_litellm_model`、`openai_base_url` 或 channel `LLM_*` 字段。
  - `src/agent/factory.py` 的 `_coerce_config_int` 只在构建执行参数时计算 `max_steps` 与 `timeout_seconds`，并且不写回到 `config` 对象；`litellm_model`、`agent_litellm_model`、`openai_base_url` 原值在构造链路中完整透传。
  - 本轮不触发 `Config` 的运行时清理、持久化回写或迁移流程，因此不存在写回导致运行时配置被重写的风险。
- 回归验证：`tests/test_agent_pipeline.py::TestAgentConfig::test_build_agent_executor_does_not_mutate_llm_route_config` 与 `tests/test_agent_pipeline.py::TestAgentConfig::test_build_agent_executor_multi_arch_does_not_mutate_llm_route_config` 明确断言上述字段在 `build_agent_executor` 后保持原值。
- 回退路径：如需恢复到旧行为，移除本轮相关提交；或将 `diag_*` 字段从 `context_snapshot`/`RunDiagnosticSummary` 的反序列化链路中移除。主链路与模型/provider 配置无需额外迁移或修复。

## 验证建议

```bash
python -m pytest tests/test_run_diagnostics_p2.py tests/test_run_diagnostics_p1.py
python -m py_compile src/services/run_diagnostics.py src/services/history_service.py api/v1/endpoints/history.py api/v1/schemas/history.py
```
