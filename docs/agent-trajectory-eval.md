# Agent Trajectory 评估(最小版,Refs #1956)

## 定位

`evals/agent_trajectory/` 提供一套**离线可运行的最小轨迹评估管线**:用真实 `tool_calls_log + AgentResult` 跑一个 golden 样例,输出结构化 JSON 报告与简短可读文本摘要。评估结果是 **reporter 而非 gate** —— 指标违规只反映在报告里,不会让进程失败,也不进入 CI 门禁。

- 指标层(`metrics.py`)是纯函数:只消费轨迹日志与 golden 样例,不 import `src/`,不触网、不调 LLM,可离线单测。
- 入口(`run_eval.py`)通过 `build_agent_executor()` 构建真实执行器,与 `src/core/pipeline.py` 使用同一个执行捕获钩子,消费真实产物。
- 入口支持**单 agent 与多 Agent 运行**(`AGENT_ARCH=single|multi`,默认仍为 single):多 Agent 结果保留原有扁平 `tool_calls_log` 指标,并通过显式 `stage_trajectories` 快照增加阶段状态与局部/累计步数报告。没有阶段快照时,单 agent 命令与 JSON 结构保持不变。
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

退出码:`0` 运行成功(含违规);`1` golden 加载(含 `expected_tools` 不在真实工具注册表)/ 样例选择 / 工具注册表加载失败 / 执行器构建 / 运行失败(含执行器返回 `success=false`,如 provider 未配置、LLM 错误、超时、max_steps 耗尽、dashboard 解析失败);`2` 用法错误。Multi-Agent 结果若在失败时带有阶段快照,入口会先输出并写入可检查的失败轨迹报告,再以退出码 `1` 表示运行失败;单 Agent 失败行为不变。

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

## Multi-Agent 阶段轨迹

当执行器结果携带非空 `stage_trajectories` 时,入口在上述工具指标之外输出 `stage_metrics`。每个阶段快照是稳定的 JSON-safe 白名单对象:

| 字段 | 说明 |
| --- | --- |
| `stage_name` | 阶段或 specialist 名称 |
| `status` | `completed` / `failed` / `skipped` 等阶段状态 |
| `total_steps` | 该阶段自己的局部 agent-loop 步数,不是全局阶段计数 |
| `tool_calls_log` | 该阶段的原始工具调用日志;空日志也会保留阶段 |
| `failure_reason` | `stage_failure` / `timeout` / `budget_skip` 等降级原因 |

评估层按快照列表顺序把局部步数累加为 `cumulative_steps`,因此不同阶段从 1 重新计步不会碰撞。该累计值也作为整条 Multi-Agent 轨迹的 agent-loop 步数传给顶层指标；`AgentResult.total_steps` 在 orchestrator 中保留原有阶段数语义,不用于轨迹 loop 预算评分。报告同时包含期望阶段命中率、缺失/额外阶段、完成/失败/跳过计数,以及每个阶段的状态、失败原因、局部/累计步数和工具调用/失败/重试指标。阶段 `tool_metrics` 仅统计该阶段日志中的调用数、工具名、冗余、缓存、失败和重试,不含期望工具命中率、缺失工具、期望外工具违规或 max-steps 违规。Golden 的 `expected_tools`、`allow_optional_tools`、`allowed_max_steps` 属于整条样例,只对汇总工具轨迹评估一次；当前不支持按阶段定义工具合规期望。关键阶段失败后,仍使用已返回的快照生成阶段报告;配置了 `expected_stages` 时,尚未执行的后续阶段会列入缺失阶段。specialist 并发执行后的快照由 scheduler 恢复为选中顺序,不依赖完成先后。

golden 样例可选增加 `expected_stages` 字段:

```json
{
  "expected_stages": ["technical", "intel", "decision"]
}
```

未配置时仍会报告实际阶段和状态,但阶段命中率显示为未配置;这不会改变现有单 agent 样例的 JSON 字段。

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
| `expected_stages` | string[] | 多 Agent 阶段期望列表(可选、非空名称且不重复);用于统计命中与缺失阶段 |

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

含阶段快照的多 Agent 报告会在上述对象中追加 `run_status` (`completed` / `failed`) 与 `stage_metrics` 字段;原有 `metrics` 字段继续表示扁平工具轨迹指标。运行失败但携带阶段快照时,JSON 报告仍会写出,进程退出码为 1。

## 不在范围(后续 PR)

- 股票维度命中判定与 guard 拦截语义(`guarded` / 越界调用违规)
- Codex App Server 的 `arguments_summary` 方言识别
- 任何 `.env` / 运行时配置与 CI 门禁(本 PR 不改变现有分析流程、调度语义或 CI 阻断规则)
