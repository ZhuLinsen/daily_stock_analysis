# Agent Trajectory 评估(最小版,Refs #1956)

## 定位

`evals/agent_trajectory/` 提供一套**离线可运行的最小轨迹评估管线**:用真实 `tool_calls_log + AgentResult` 跑一个 golden 样例,输出结构化 JSON 报告与简短可读文本摘要。评估结果是 **reporter 而非 gate** —— 指标违规只反映在报告里,不会让进程失败,也不进入 CI 门禁。

- 指标层(`metrics.py`)是纯函数:只消费轨迹日志与 golden 样例,不 import `src/`,不触网、不调 LLM,可离线单测。
- 入口(`run_eval.py`)通过 `build_agent_executor()` 构建真实执行器,与 `src/core/pipeline.py` 使用同一个执行捕获钩子,消费真实产物。
- 入口只支持**单 agent 运行**(`AGENT_ARCH=single`,默认):`AGENT_ARCH=multi` 时 factory 返回 orchestrator,其轨迹是各 stage 局部步号的拼接、`total_steps` 为 stage 数,与单 runner 指标契约不兼容——入口在构建前明确报错并退出(退出码 1)。
- 入口用真实工具注册表校验 golden:`expected_tools` 拼错或过期会被判为无效样例(退出码 1),而不是静默按低命中继续评分。
- 本次冻结**最小指标契约**,股票 guard、Codex `arguments_summary` 等扩展语义明确留给后续 PR(见文末「不在范围」)。

## 快速开始

```bash
# 跑单个样例(真实 LLM,依赖本地已配置的模型)
python evals/agent_trajectory/run_eval.py --sample 600519_technical

# 跑全部样例,并输出结构化 JSON(按样例 id 键控)
python evals/agent_trajectory/run_eval.py --all --json-out eval_report.json
```

参数:

| 参数 | 说明 |
| --- | --- |
| `--sample ID` / `--all` | 二选一必填:跑单个 golden 样例或全部 |
| `--golden-path PATH` | 自定义 golden JSON 路径(默认模块旁 `golden_samples.json`) |
| `--json-out PATH` | 写结构化 JSON 报告(`--all` 时为键控对象) |

退出码:`0` 运行成功(含违规);`1` golden 加载(含 `expected_tools` 不在真实工具注册表)/ 样例选择 / 工具注册表加载失败 / 执行器构建(含 `AGENT_ARCH=multi` 拒绝)/ 运行失败(含执行器返回 `success=false`,如 provider 未配置、LLM 错误、超时、max_steps 耗尽、dashboard 解析失败);`2` 用法错误。

## 冻结的最小指标契约

对每条 `tool_calls_log`(runner 契约:每项含 `step / tool / arguments / success / duration / result_length / cached`,可选 `timeout` / `guarded`),只统计:

| 指标 | 定义 |
| --- | --- |
| `expected_hit_rate` / `missing_expected` | 期望工具按**工具名**命中(本版不做股票维度判定);`expected_total` 为去重后的期望数 |
| `optional_tools_used` | 期望集合之外实际调用的工具;`allow_optional_tools=false` 时记为违规 |
| `redundant_calls` | 同一 (tool, args-key) 对在首次出现之后的每一次出现(不论成败)。args-key = `json.dumps(arguments, sort_keys=True, default=str)`,与运行时缓存键同思路 |
| `retries` | 紧跟**失败**之后重试同一 (tool, args-key) 对;`retries ⊆ redundant_calls`。成功会清除该对的失败态:`fail → success → success` 只计 1 次 retry(后一次 success 仅计冗余) |
| `failed_calls` | `success=false` 的条目数 |
| `cached_calls` | `cached=true` 的条目数(runner 语义:复用不可重试的失败结果) |
| `distinct_steps` / `max_steps_touched` | 日志 step 与 `AgentResult.total_steps` 取较大者(最后纯回答轮不产生工具调用,日志会低估);`max_steps_touched` 为 `max(step) >= allowed_max_steps` 的启发式 |

## Golden 样例 schema

`golden_samples.json` 是一个数组,字段:

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 唯一样例 id(必填) |
| `task_description` | string | 交给执行器的任务文本(必填) |
| `stock_code` | string | 原样传入 runner context(`{"stock_code": ...}`);空串 = 无 context;不参与打分 |
| `expected_tools` | string[] | 期望工具名(必填,非空、无重复) |
| `allowed_max_steps` | int | 步数预算启发式(默认 10,>= 1) |
| `allow_optional_tools` | bool | 是否容忍期望外工具(默认 true) |

校验:加载路径(`load_golden_samples`)直接拒绝非法样例;直接构造路径(`compute_trajectory_metrics`)以 validator 完全相同的措辞逐条上报违规,两条路径的契约按构造保持一致。`known_tool_names` 可注入真实工具注册表做成员校验(metrics 层自身不 import `src/`);`run_eval.py` 入口会自动注入真实工具注册表。

## JSON 报告 schema

单个样例:

```json
{
  "sample_id": "600519_technical",
  "task_description": "…",
  "stock_code": "600519",
  "metrics": { "expected_hit_rate": …, "expected_total": …, "…": "… 共 11 个字段" },
  "violations": ["…"]
}
```

`--all --json-out` 时外层为 `{sample_id: <上述对象>}` 键控对象。

## 不在范围(后续 PR)

- 股票维度命中判定与 guard 拦截语义(`guarded` / 越界调用违规)
- Codex App Server 的 `arguments_summary` 方言识别
- 任何 `.env` / 运行时配置与 CI 门禁(本 PR 零 `src/` 改动,不影响现有分析流程)
