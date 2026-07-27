# 多策略投资建议契约：Baseline 语义、Phase 1 收敛、Phase 2/3/4 边界

本页是 Issue #1964「多策略投资建议」的专题文档，用于记录 2 个及以上策略/技能（skill）观点在系统内的**语义收敛边界**：有效证据集合、无效观点隔离、阵营分组、共识度、跨消费面一致性。Baseline 负责契约边界和现状盘点；Phase 1 只在 Baseline 契约内完成有效证据集合分拣、`strategy_synthesis` 确定性合成、DecisionAgent prompt 收敛、四条 renderer 一致性以及 E2E 反例覆盖；Phase 1.5 在 Phase 1 契约上新增受控协同推理 v0（mediator_v0），只记录冲突议题、策略回应、softened 修正和置信度折减原因；Phase 1.6 新增可注入 LLM mediator v1（llm_mediator_v1），只允许 schema 合法的结构化修订，并在缺失、异常或越界时回退 v0；Phase 1.7 新增可注入 strategy self-review v2（self_review_v2），只允许冲突参与策略按固定 schema 自审，并在任一参与方越界时整轮回退 baseline；Phase 1.8 新增修订投影 v3（revision_projection），只预览采纳 softened 修订后的综合信号、置信度和冲突状态，不覆盖权威 `final_signal`；Phase 1.9 新增可配置多轮协同推理 v4（multi_round_v4），按 `max_rounds` 继续结构化修订并保留 `round_history`，任一轮越界时回到上一轮已验证结果；Phase 2 只在 Phase 1/1.5/1.6/1.7/1.8/1.9 契约下新增 2–4 策略并发调度与阶段调度；Phase 3 只在 Phase 2 之上补前端多语言完整展示；Phase 4 只在同一 `CONTRACT_VERSION = "1.0"` 内补权重回测反馈闭环。Baseline 的所有约束对后续 Phase 均永久生效，Phase N 不得静默降级 Baseline 中已经写死的边界。

## Skill opinion 样本边界（Issue #1904 P2 PR1）

`AgentRuntimeFacts.skill_opinions` 只投影 individual SkillAgent 的低敏字段：`skill_id`、canonical `signal`、`confidence` 和 opinion 时间。`skill_consensus` / `strategy_consensus`、DecisionAgent、基础 Agent 以及 Invalid Opinion 均不得进入该集合；同一次运行出现同一 `skill_id` 的多条有效观点时，只保留最后一条。SkillAgent 首次解析时必须拒绝非数字、非有限或超出 `[0, 1]` 的 confidence；AgentOpinion 保留输入合法性标记供 RuntimeFacts 防御校验，禁止将非法输入 clamp 后作为有效样本继续使用。

分析历史成功保存后，Pipeline 以 best-effort 方式写入 `skill_opinion_samples` sidecar。父历史存在性检查与样本插入必须位于同一个 SQLite 原子写事务中，历史删除复用相同的写事务与 locked retry；无论插入或删除谁先执行，均不得留下孤儿样本。幂等键为 `(analysis_history_id, skill_id, sample_schema_version)`；重复执行不得覆盖首次保存的不可变样本。写入失败只记录低敏错误类型，不得使报告、历史记录或 DecisionSignal 主流程失败。

当前 `sample_schema_version=skill-opinion-sample-v1`。`skill_version` 与 `horizon` 仅保留为空值兼容位：现有 Skill 定义和 SkillAgent 输出没有可信的版本与周期契约，因此本阶段不得从 LLM `raw_data` 猜测或伪造。PR1 不创建 outcome、不提供 skill 表现统计、不实现 `get_skill_summary()`，也不改变 `AgentMemory` / `SkillAggregator` 权重。

## 术语与边界

当前仓库里有多种名为 opinion / signal / consensus / synthesis 的数据面，Baseline 必须先消歧，避免把现有运行时结构误写成未来 phase。

| 术语 | 当前含义 | 当前主要消费方 | Baseline 边界 |
| --- | --- | --- | --- |
| `AgentOpinion` | `src/agent/protocols.py` 中所有 Agent（含 SkillAgent、TechnicalAgent、IntelAgent、RiskAgent、DecisionAgent）产出的观点数据类，含 `agent_name` / `signal` / `confidence` / `reasoning` / `key_levels` / `raw_data`。 | Orchestrator、Aggregator、DecisionAgent、Disagreement、Renderer | 记录为原始观点承载体；Baseline 不新增字段，也不把 `AgentOpinion` 分裂成两类。 |
| `StrategyOpinion` | `src/agent/protocols.py` 中的内部规范化视图，含 `skill_id` / `signal` / `original_signal` / `invalid_signal`；只在 Aggregator/Synthesizer 内部使用。 | `SkillAggregator`、`ConflictDetector`、`StrategySynthesizer` | 记录为内部计算的规范化视图，不进入 `ctx.opinions`、不进入公共 payload、不进入 DecisionAgent prompt。 |
| Signal / Canonical Signal | 交易信号规范化标签，Canonical 取值仅限 `strong_buy` / `buy` / `hold` / `sell` / `strong_sell` 五个小写字符串。 | 全链路 | 记录为下游所有计算的唯一允许输入形式；大写别名、`"strong buy"`、Signal 枚举原值都必须先经 `normalize_strategy_signal()` 转成 canonical 再参与计算。 |
| Valid Opinion / Invalid Opinion | 通过 `is_valid_strategy_signal(signal) == True` 且未标记 `invalid_signal=True` 的观点为 Valid，其余为 Invalid。 | Orchestrator 分拣、Aggregator、DecisionAgent | 记录为契约层的合法/非法判定；Baseline 只定义判定函数与语义，不预设分拣位置。 |
| Evidence Chain | 进入 DecisionAgent prompt 与 `strategy_synthesis` 数值计算的**有效观点集合**。 | DecisionAgent、Aggregator | 记录为决策输入面；Baseline 规定 Evidence Chain 只由 Valid Opinion 组成，Invalid 不得混入。 |
| Diagnostics | 无效观点的诊断收纳位，仅供日志、调试、用户可见的“另有 N 个策略解析失败”计数使用。 | Renderer 展示、日志 | 记录为诊断面；Baseline 规定 Invalid 必须落到 Diagnostics，不得被静默转成 `hold` 混入 Evidence Chain。 |
| `strategy_synthesis` | `dashboard.strategy_synthesis` 顶层 payload，含 `final_signal` / `consensus_level` / `conflict_severity` / `supporting_skills` / `opposing_skills` / `summary_params`。 | Markdown、WeChat、Notification、History 四条 renderer | 记录为公共低敏 payload；Baseline 规定该 payload 是**唯一权威合成来源**，LLM dashboard 不得反向覆盖。 |
| `disagreement_summary` | `ctx.meta["agent_disagreement_summary"]`，低敏跨 Agent 分歧摘要，来自 `build_agent_disagreement_summary()`。 | DecisionAgent prompt、日志 | 记录为决策路径提示面；Baseline 规定只从 Valid Opinion 建桶，Invalid 不得进入 `bullish_agents` / `bearish_agents` / `neutral_agents`。 |
| Consensus Level | `strategy_synthesis.consensus_level`，取值 `high` / `medium` / `low` / `insufficient`。 | Renderer 展示、Aggregator 内部判定 | 记录为共识度枚举；Baseline 规定 ≤ 1 valid 或 `sum(confidence) == 0` 时强制 `insufficient`，不得输出 `high`。 |

## Baseline 范围与非目标

Baseline 的目标是让 Phase 1/2/3/4 都基于同一份语义契约设计运行时改动，而不是每一轮 PR 重新定义"有效观点"、"共识"、"支持方"。

- Baseline 覆盖 SkillAgent → Orchestrator → Aggregator → Synthesizer → DecisionAgent → Disagreement → Renderer 七条消费面的语义收敛边界。
- Baseline 固定 Canonical Signal 枚举、Valid/Invalid 判定函数、Evidence Chain / Diagnostics 分离原则、动态二分阵营语义、共识门槛梯度、`strategy_synthesis` payload schema、不变量清单和反例矩阵；Phase 1 是这些边界的第一版代码化实现。
- Baseline 不引入并发调度、不引入前端多语言完整展示、不引入权重回测反馈；这些留给 Phase 2/3/4。
- Baseline 不改变现有 `AgentOpinion` 字段、不新增数据库字段、不改变 API 返回结构（`strategy_synthesis` 已在此前 PR 加入）、不新增配置项。
- Baseline 不把契约扩展成通用 opinion registry；`AgentOpinion` 结构由现有代码维护，本契约只规范其**语义处置流程**。

## Baseline 内部契约

### Canonical Signal 与 Valid 判定

Canonical Signal 是 Baseline 允许的**唯一评分/加权/分组输入形式**。规范化入口是 `src/agent/protocols.py` 中的两个函数：

- `normalize_strategy_signal(signal)` 返回 `(canonical, invalid, original)` 三元组。它接受 `Signal` 枚举、大小写字符串、`"strong buy"` / `"strong-buy"` 别名，统一映射到 canonical 集合。无法映射时 `invalid=True`，`canonical` 退化为 `default`（默认 `"hold"`）但**必须**配合 `invalid=True` 一并传递到下游，不得被单独使用。
- `is_valid_strategy_signal(signal)` 是 Baseline 全链路合法性判定的**单一真源**：任何模块判断“这条 opinion 是否有资格进入 Evidence Chain”都必须调用此函数。

Baseline 禁止在 `_STRATEGY_SIGNAL_ALIASES` 之外再维护第二份 canonical 映射表；ConflictDetector 与 Synthesizer 内部的 `strategy_signal_score(canonical)` 只接受 canonical 值，禁止用 `op.original_signal` 或大小写变体查表。

### Evidence Chain 与 Diagnostics 分离

Baseline 规定：

- **Evidence Chain 是且仅是 Valid Opinion 集合**。DecisionAgent prompt、`strategy_synthesis` 数值计算、`disagreement_summary` 建桶都必须从同一个 Evidence Chain 读取。
- **Invalid Opinion 必须落到 Diagnostics**（`ctx.meta["invalid_opinions"]` 或等价字段），仅用于日志、诊断、用户可见的“另有 N 个策略解析失败”计数。
- 两个集合**互斥且并集穷尽**：一条 opinion 要么在 Evidence Chain，要么在 Diagnostics，不得同时出现或都不出现。
- Invalid Opinion **不得**被静默转换成 `hold` / `confidence` 保留原值 / 匿名混入 `bullish_agents` / `bearish_agents` / `neutral_agents` 桶。

Diagnostics 结构：

```python
ctx.meta["invalid_opinions"] = [
    {
        "agent_name": str,          # 原始 agent_name
        "raw_signal": str | None,   # 原始 signal 字面量（未归一化）
        "confidence": float,        # 原始 confidence，仅诊断，不参与任何计算
        "reason": str,              # "missing_signal" | "unrecognized_signal" | "invalid_flag"
    },
    ...
]
```

Baseline 只规定该结构，不规定分拣发生的**代码位置**——Phase 1 会把分拣落到 Orchestrator。

### 动态二分阵营（Supporting / Opposing）

给定最终信号 `final_signal` 与 canonical score `final_score = strategy_signal_score(final_signal)`，对每个 Valid Opinion `op` 计算 `op_score = strategy_signal_score(op.signal)`：

- **当 `final_signal == "hold"`（即 `final_score == 3.0`）时**：
  - `op_score == 3.0` → `supporting_skills`
  - `op_score != 3.0` → `opposing_skills`（作为异议与分歧收纳，保证观望与分歧观点不被静默丢弃，避免展示时丢失异议背景）

- **当 `final_signal` 为方向性信号（`strong_buy` / `buy` / `sell` / `strong_sell`）时**：
  - 同向（都看涨 或 都看跌）且 `abs(op_score - final_score) ≤ 1.0` → `supporting_skills`
  - 反向 且 `abs(op_score - final_score) ≥ 2.0` → `opposing_skills`
  - 其余（`abs(diff) < 2.0` 且非同向）→ `opposing_skills`（并入异议，杜绝第三阵营 `neutral_skills`）

Baseline 明确 **`neutral_skills` 不作为 payload 的正式字段**。每个 Valid Opinion 必须**恰好**落入 `supporting_skills` 或 `opposing_skills` 其一，分组结果总数必须等于 `summary_params.opinion_count`。

### 共识度门槛

Baseline 固定共识度按 valid 样本数梯度判定：

| valid 数量 | consensus_level | 说明 |
| --- | --- | --- |
| 0 | `insufficient` | 无证据可综合，final_signal 强制 `hold`，`confidence=0.0` |
| 1 | `insufficient` | 单样本不构成"共识"，即使与 final 完全一致也不得输出 `high` |
| ≥ 2，`sum(confidence) == 0` | `insufficient` | 有效证据的置信度为零，无从建立共识 |
| ≥ 2，`sum(confidence) > 0` | 进入 aligned_ratio 判定 | 见下表 |

Aligned Ratio 判定（valid ≥ 2 且 `sum(confidence) > 0`）：

| 条件 | consensus_level |
| --- | --- |
| `conflict_severity == "high"` | `low` |
| `aligned_ratio ≥ 2/3` 且 `conflict_count == 0`（等价 `conflict_severity == "none"`） | `high` |
| `conflict_severity == "medium"` 且 `aligned_ratio < 0.5` | `low` |
| 其余 | `medium` |

其中 `aligned = 与 final_signal 同向且 score 距离 ≤ 1.0 的 valid 数量`，`aligned_ratio = aligned / len(valid)`。

Baseline 禁止使用 `sum(...) or 1.0` 之类的兜底把零权重掩盖成分母 1；零权重必须显式走 `insufficient` 分支，并让 `final_signal` 退回 `hold`。

### `strategy_synthesis` Payload Schema

```json
{
  "final_signal": "hold",                 // canonical signal
  "weighted_score": 3.0,                  // 保留 4 位小数
  "confidence": 0.72,                     // 折减后的置信度
  "original_confidence": 0.80,            // 折减前的加权置信度
  "conflict_count": 0,
  "conflict_severity": "none",            // none | low | medium | high
  "conflicts": [ /* ConflictDetector 输出的 dict 列表 */ ],
  "supporting_skills": [ /* opinion item */ ],
  "opposing_skills":   [ /* opinion item */ ],
  "consensus_level": "high",              // high | medium | low | insufficient
  "summary_key": "strategy_synthesis.no_conflicts",   // 动态 i18n 摘要键名，随共识和冲突状态确定
  "summary_params": {
    "opinion_count": 2,                   // valid 样本数（Evidence Chain 大小）
    "total_opinion_count": 4,             // valid + invalid（分拣前原始输入总数）
    "invalid_opinion_count": 2,           // Diagnostics 长度
    "final_signal": "hold",
    "consensus_level": "high",
    "conflict_severity": "none",
    "conflict_count": 0
  },
  "deliberation": {                       // 可选；仅 material conflicts 触发
    "status": "completed",
    "mode": "multi_round_v4",
    "rounds": 2,
    "agenda": [ /* conflict agenda item */ ],
    "responses": [ /* per-agenda participant response */ ],
    "summary": {
      "resolution_status": "partially_resolved",
      "resolved_conflict_count": 0,
      "unresolved_conflict_count": 1,
      "minority_view_preserved": true,
      "confidence_adjustment": -0.06,
      "confidence_adjustment_reason_key": "deliberation.confidence.high_partially_resolved"
    },
    "round_history": [
      {
        "round": 1,
        "source_mode": "mediator_v0",
        "status": "baseline",
        "changed_response_count": 2,
        "confidence_adjustment": -0.06
      },
      {
        "round": 2,
        "source_mode": "multi_round_v4",
        "status": "accepted",
        "changed_response_count": 1,
        "confidence_adjustment": -0.09
      }
    ]
  },
  "revision_projection": {                // 可选；仅 deliberation 存在时生成的 preview
    "status": "computed",
    "mode": "preview_only",
    "source_mode": "mediator_v0",
    "projected_signal": "hold",
    "projected_weighted_score": 3.0,
    "projected_confidence": 0.6696,
    "projected_original_confidence": 0.72,
    "projected_conflict_count": 1,
    "projected_conflict_severity": "medium",
    "projected_consensus_level": "low",
    "changed_skill_count": 2,
    "changed_skills": ["trend_v1", "theme_v1"],
    "final_signal_overridden": false
  }
}
```

Opinion Item 结构（`supporting_skills` / `opposing_skills` 每个元素）：

```json
{
  "skill_id": "trend_v1",
  "agent_name": "skill_trend_v1",
  "signal": "hold",              // canonical
  "confidence": 0.80,            // 保留 4 位小数
  "reasoning": "...",
  "score_adjustment": 0,
  "conditions_met": []
}
```

Baseline 明确 `strategy_synthesis` 是**由 SkillAggregator 确定性算法产出的唯一权威合成结果**。Orchestrator 的 `_collect_strategy_synthesis()` 必须优先使用 `ctx.get_data("skill_consensus")` 中的 synthesis，只有在 SkillAggregator 未产出时才允许回退到 `ctx.opinions` 中的 `skill_consensus` opinion。**LLM 返回的 dashboard 不得覆盖或修改 `dashboard.strategy_synthesis`**；`normalize_dashboard_payload` 收到 LLM 输出时应剥离 LLM 侧的 `strategy_synthesis` 字段，避免 LLM 幻觉污染权威合成结果。

### Strategy Deliberation v0（Phase 1.5）

`strategy_synthesis.deliberation` 是可选协同推理块，只在中高强度冲突或明确关键冲突类型出现时生成。v0 使用确定性 `mediator_v0`，不调用 LLM、不让策略自由聊天、不修改原始 opinion、不重新计算 `final_signal`。它的职责是把冲突转成可审计议题，并记录策略回应、轻量修正与综合置信度折减原因。

触发条件：

- `len(valid_opinions) >= 2`
- 且存在 `severity in {"medium", "high"}` 的 conflict，或 conflict type 属于 `directional_opposition` / `high_confidence_dissent`

v0 revision 只允许：

- `unchanged`：坚持原观点。
- `softened`：仅降低 confidence，或将 `strong_buy -> buy`、`strong_sell -> sell`；`buy` / `sell` / `hold` 不反转，只可降低 confidence。

v0 明确禁止：

- `reversed`：不得反转观点。
- 重新计算 `final_signal`。
- 引入多轮 debate、并发调度、前端展示或新配置项。

`deliberation.summary.confidence_adjustment` 只作为 `StrategySynthesizer` 在原 conflict severity 折减后的额外保守折减。高冲突部分缓解时默认约 `-0.06`，未缓解时约 `-0.08`；中冲突部分缓解时默认约 `-0.04`，未缓解时约 `-0.05`。该字段必须保留在 payload 中，方便后续 renderer 或 Web UI 展示“为什么置信度被继续下调”。

### LLM Mediator v1（Phase 1.6）

`llm_mediator_v1` 是 `StrategyDeliberation` 的可注入增强模式，不是默认运行时行为。调用方可以向 `StrategySynthesizer(deliberation_mediator=...)` 注入 `LLMDeliberationMediator`，由它先生成 v0 baseline agenda，再把低敏结构化 opinions/conflicts/baseline payload 发送给 LLM callable。LLM 只能返回同 schema 的 JSON 对象；返回文本、坏 JSON、缺字段、ID 漂移或越界 revision 时，必须无条件回退 v0。

v1 schema guard：

- `agenda` 必须保留 v0 的 `agenda_id` 集合；不得新增、删除或替换参与方。
- `responses` 必须覆盖 v0 的 `(agenda_id, skill_id)` 集合；不得新增未参与策略。
- `revision` 只允许 `unchanged` / `softened`；`reversed` 继续禁止。
- v0 baseline 已经 `softened` 的 response 必须继续保持 `softened`，不得恢复 original signal，且 `revised_confidence` 不得高于 baseline 的已验证值。
- v0 baseline 为 `unchanged` 的 response 可以保持不变，也可以按原规则继续 `softened`；不得反转 signal 或提高 confidence。
- `summary.confidence_adjustment` 不得比 v0 baseline 更乐观，且单次额外折减下限为 `-0.10`，避免 LLM 撤销确定性折减。

v1 输出通过校验时 `deliberation.mode="llm_mediator_v1"`；否则保持 `mediator_v0` 输出。v1 仍不调用策略 agent 自审、不多轮 debate、不重算 `final_signal`，也不新增配置项。

### Strategy Self-Review v2（Phase 1.7）

`self_review_v2` 是 `StrategyDeliberation` 的可注入自审模式，不是默认运行时行为。调用方可以向 `StrategySynthesizer(deliberation_mediator=...)` 注入 `StrategySelfReviewMediator`，由它先获取 baseline deliberation（可以是 `mediator_v0` 或通过校验的 `llm_mediator_v1`），再按每个 baseline response 的 `(agenda_id, skill_id)` 调用自审 callable。未来该 callable 可以由真实冲突参与 strategy agent 执行；当前契约只规定输入/输出与降级行为。

v2 self-review guard：

- 每个 baseline response 必须返回且只返回自己的 response JSON；不得修改其它策略回应。
- 返回的 `agenda_id` / `skill_id` 必须与 baseline response 完全一致。
- `revision` 仍只允许 `unchanged` / `softened`；`reversed` 继续禁止。
- baseline 已经 `softened` 时不得改回 `unchanged`、恢复 original signal 或提高 baseline `revised_confidence`。
- baseline 为 `unchanged` 时可以保持不变，也可以按原规则继续 `softened`；不得反转 signal 或提高 confidence。
- v2 根据通过校验的 responses 重算 summary 时，最终 `confidence_adjustment` 不得比输入 baseline 更乐观。
- 任一参与方缺失、坏 JSON、ID 漂移、越权修改或试图 `reversed`，整轮 self-review 回退到 baseline deliberation，禁止混合部分有效自审。

v2 输出通过校验时 `deliberation.mode="self_review_v2"`。v2 仍只做一轮、不新增并发调度、不重算 `final_signal`、不改变原始 opinion，也不新增配置项。

### Revision Projection v3（Phase 1.8）

`strategy_synthesis.revision_projection` 是可选预览块，只在 `deliberation` 存在时由 `StrategySynthesizer` 计算。它读取已经通过 v0/v1/v2 schema guard 的 `responses`，把 `revision="softened"` 的回应应用到临时 `StrategyOpinion` 副本上，再用 confidence-weighted score 预览新的综合结果。

v3 输出边界：

- `revision_projection.mode` 固定为 `preview_only`。
- `source_mode` 记录投影来源：`mediator_v0` / `llm_mediator_v1` / `self_review_v2`。
- `projected_signal` / `projected_weighted_score` / `projected_confidence` 只描述采纳 softened 修订后的预览结果。
- `projected_conflict_count` / `projected_conflict_severity` / `projected_consensus_level` 基于临时修订副本重新检测，不改写原始 conflicts。
- `changed_skill_count` / `changed_skills` 只统计实际 softened 的策略。
- `final_signal_overridden` 必须固定为 `false`，用于明确 v3 不覆盖权威最终信号。

v3 明确禁止：

- 把 `projected_signal` 回写到顶层 `final_signal`。
- 把 `projected_weighted_score` 回写到顶层 `weighted_score`。
- 把 `projected_confidence` 回写到顶层 `confidence`。
- 在没有 `deliberation` 的场景输出空 projection。
- 接受未经 v0/v1/v2 guard 的自由文本、反转信号或新增策略回应。

v3 在投影入口还会重新核对 `original_signal`、允许的 softened signal 与 `revised_confidence` 上界；即使调用方注入了未使用内置 mediator guard 的自定义结果，也不会把更激进的 response 应用到临时 opinion 副本。

### Configurable Multi-Round Deliberation v4（Phase 1.9）

`multi_round_v4` 是 `StrategyDeliberation` 的可注入多轮增强模式，不是默认运行时行为。调用方可以向 `StrategySynthesizer(deliberation_mediator=...)` 注入 `MultiRoundDeliberationMediator`，并通过构造参数配置：

- `fallback`：第一轮 baseline mediator，可为 `mediator_v0`、`llm_mediator_v1` 或 `self_review_v2`。
- `max_rounds`：总轮数上限，范围 `1–4`；`1` 等价只保留 fallback baseline。
- `stop_when_stable`：当某轮没有任何 response 变化时是否提前停止，默认开启。
- `round_completion(round_index, messages)`：下一轮结构化修订 callable，只能返回同 schema JSON。

v4 round guard：

- 每轮必须保留上一轮的 `agenda_id` 集合和 `(agenda_id, skill_id)` response 集合；不得新增、删除或替换参与方。
- `revision` 仍只允许 `unchanged` / `softened`；`reversed` 继续禁止。
- 上一轮已经 `softened` 的 response 不能回到 `unchanged`。
- 上一轮已经 `softened` 的 response 不能更换 `revised_signal`，也不能提高 `revised_confidence`。
- 上一轮 `unchanged` 的 response 可以继续 `unchanged`，也可以按原规则 `softened`。
- `summary.confidence_adjustment` 不能为正数，也不能比上一轮更乐观；单轮下限仍按 v1 guard 钳制到 `-0.10`。
- 任一轮坏 JSON、ID 漂移、越界 revision、撤销 softened 或提高 confidence 时，停止后续轮次并返回上一轮已验证结果；如果第 2 轮即失败，则保持 fallback baseline。

v4 输出：

- 至少接受一轮额外修订时，`deliberation.mode="multi_round_v4"`。
- `deliberation.rounds` 记录实际接受到的总轮数。
- `deliberation.round_history` 记录 baseline 与每个已接受轮次的 `round`、`source_mode`、`status`、`changed_response_count` 和 `confidence_adjustment`。
- v4 仍不重算顶层 `final_signal`，不改变原始 opinion，不直接覆盖顶层 `weighted_score` 或 `confidence`；顶层 confidence 只继续读取最终 `deliberation.summary.confidence_adjustment` 做保守折减。

### 关键不变量

Baseline 的语义边界收敛为九条不变量。所有 Phase N 的实现必须同时满足这九条，任一违反视为契约破坏。

| ID | 不变量 | 场景 | 期望 |
| --- | --- | --- | --- |
| I-1 | Evidence Chain 排他性 | 任何模块读取 Evidence Chain | 集合内每一条都必须 `is_valid_strategy_signal == True`；Invalid 不允许出现 |
| I-2 | 禁止静默转换 | 缺失或无法识别的 signal | 归入 Diagnostics，不得转换成 `hold` 后混入 Evidence Chain 或建桶 |
| I-3 | 零证据 → insufficient | 任意有效信号但 `sum(confidences) == 0`，或 valid 数量 = 0 | `final_signal="hold"`, `weighted_confidence=0.0`, `consensus_level="insufficient"`；禁止输出 `strong_sell` 或任何方向性信号 |
| I-4 | 单样本 → insufficient | 恰好 1 个 valid opinion | `consensus_level="insufficient"`，即使与 final 完全一致 |
| I-5 | Hold-final 一致性 | `final_signal == "hold"` 且存在 ≥ 2 个 hold valid opinion | 全部 hold opinion 必须归入 `supporting_skills`；consensus_level 与 supporting_skills 数量关系必须自洽（`high` 时 supporting 覆盖 ≥ 2/3） |
| I-6 | Payload 与 renderer 语义一致 | `dashboard.strategy_synthesis` 值 | 四条 renderer（Markdown / WeChat / Notification / History）实际文本必须与 payload 完全一致，不得出现"共识度：高 + 支持策略：无"等自相矛盾组合 |
| I-7 | Canonical-First 评分 | Aggregator / ConflictDetector / Synthesizer 内部的评分、加权、冲突判定、分组 | 必须使用 `normalize_strategy_signal()` 返回的 canonical 小写值；禁止用大写 `"BUY"`、别名等原始字符串直接查 `strategy_signal_score` |
| I-8 | 多语言空占位符 | `supporting_skills` / `opposing_skills` 为空时的展示 | 必须通过 `labels.none_label` 按 `report_language` 查表；禁止在代码或模板中硬编码中文 `"无"` / 英文 `"None"` / 韩文 `"없음"` 字面量 |
| I-9 | Deliberation 单调保守 | v1/v2/v4 基于上一层已验证 baseline 修订，v3 应用 projection | 不得撤销已有 `softened`、恢复 original signal、提高 baseline revised confidence 或提高 baseline confidence adjustment；越界结果回退上一层 |

## Phase 1 语义收敛（本 PR 交付范围）

Phase 1 是 Baseline 契约的第一版代码化实现。Phase 1 **不新增契约条款**，只把 Baseline 已经写死的边界落到具体代码：Orchestrator 分拣、Aggregator/Synthesizer 计算收敛、DecisionAgent prompt 收敛、Disagreement 收敛、四条 renderer 一致性、E2E 反例覆盖。

Phase 1 涉及的入口：

- `src/agent/protocols.py`：新增 `is_valid_strategy_signal()` 单一真源，`normalize_strategy_signal()` 保留 invalid 状态位。
- `src/agent/skills/engine.py`：`StrategyEngine.process()` 通过 `partition_only()` 完成唯一权威分拣，再由 `process_partition()` 驱动聚合与合成；Valid 保留在 Evidence Chain，Invalid 写入 Diagnostics。
- `src/agent/orchestrator.py`：在 DecisionAgent 运行前调用 `_run_strategy_engine(ctx)`；timeout / budget-skip 早退路径调用 `_apply_partition_fallback(ctx)`，只分拣、不合成，避免 Invalid 回流证据链。
- `src/agent/skills/aggregator.py`：`StrategyEngine` 把 `valid_skill_opinions` 交给 `SkillAggregator.calculate()`；数学计算只使用 valid opinion，对 `valid_weight_sum == 0` 显式走 `insufficient` 分支。
- `src/agent/skills/synthesis.py`：`ConflictDetector` / `StrategySynthesizer` 使用 canonical signal 计算；`_group_opinions()` 按 §"动态二分阵营" 实现；`_consensus_level()` 按 §"共识度门槛" 实现；`summary_params` 补齐 `invalid_opinion_count` / `total_opinion_count`。
- `src/agent/agents/decision_agent.py`：`build_user_message()` 直接消费 `ctx.opinions`，不再二次过滤；在 prompt 中如实展示 `ctx.meta["invalid_opinions"]` 数量。
- `src/agent/disagreement.py`：`build_agent_disagreement_summary()` 直接消费 `ctx.opinions`（因 StrategyEngine 已完成分拣并由 Orchestrator 写回），Invalid 完全不出现在 `bullish_agents` / `bearish_agents` / `neutral_agents` 三桶中。
- `src/services/report_renderer.py`、`templates/report_markdown.j2`、`templates/report_wechat.j2`、`src/notification.py`、`src/services/history_service.py`：读取 `strategy_synthesis.supporting_skills` / `opposing_skills` / `consensus_level` / `summary_params.invalid_opinion_count`；空列表通过 `labels.none_label` 输出；不再消费 `neutral_skills`。
- `src/report_language.py`：`labels.none_label` 在 zh/en/ko 三语中完备；共识度、诊断计数文案完备。
- `tests/test_multi_agent.py`：新增 E2E-A..G 反例矩阵，从 SkillAgent 输入 → StrategyEngine 分拣/聚合 → DecisionAgent prompt → dashboard payload → renderer 实际文本全链路断言。

Phase 1 不改变 `AgentOpinion` 字段、不改变 API 返回结构、不改变数据库 schema、不新增配置项、不改变现有 skill 的执行方式。

## Phase 2 并发调度

Phase 2 只在 Phase 1/1.5/1.6/1.7/1.8/1.9 契约下新增 2–4 策略并发调度与阶段调度：

- `src/agent/skills/scheduler.py::AgentSkillScheduler` 使用 thread pool 并发执行 specialist skill agents；每个 skill 使用 `AgentContext` 副本运行，并通过独立的 `copy_context()` 把主管线冻结的 target date 等 `ContextVar` 状态传播到 worker，主线程按路由顺序合并结构化 opinion，避免多个 skill 同时写共享 `ctx.opinions`。
- specialist 最终入口最多选择 4 个策略；`AGENT_SKILL_CONCURRENCY` 控制同时运行的 worker 数，默认 `3`，范围 `1–4`。默认值下第 4 个策略进入下一 concurrency wave，不会被路由层静默丢弃。
- `AGENT_SKILL_AGENT_TIMEOUT_S` 继续作为单个 skill 的独立超时上限；Pipeline 总预算开启时，`_run_stage_agent()` 仍取 Pipeline 剩余预算与 skill 独立上限的较小值。
- 单个 skill 超时或异常，走 Diagnostics 路径（`reason="skill_timeout"` / `"skill_error"`），进入 `ctx.meta["invalid_opinions"]`，不阻塞其他 skill 与主流程。
- Phase 2 不改变 Baseline Evidence Chain / Diagnostics 分离原则、不改变阵营语义、不改变共识门槛、不改变 `strategy_synthesis` payload schema。
- Phase 2 不改变 renderer 展示逻辑；scheduler timeout/error/no-opinion 与 signal 校验失败统一进入 StrategyEngine 的 authoritative Diagnostics，`invalid_opinion_count` / `total_opinion_count` 覆盖这些失败 skill。
- `ctx.meta["skill_scheduler"]` 仅作为运行时诊断，记录调度模式、并发数、单 skill timeout、调度数量、完成数量和 invalid 数量；不得参与综合评分。

## Phase 3 前端多语言完整展示（本 PR 不做）

Phase 3 只在 Phase 2 之上补前端（`apps/dsa-web/`、`apps/dsa-desktop/`）对 `strategy_synthesis` 的完整多语言展示：

- Web 报告详情页展示 `final_signal` / `consensus_level` / `supporting_skills` / `opposing_skills` / `conflicts` / `invalid_opinion_count`。
- 桌面端复用 Web 展示逻辑。
- 多语言 label 表复用 `src/report_language.py` 已有的 zh/en/ko 三语；前端只做投影，不重新定义。
- Phase 3 不改变 Baseline 契约、不新增 payload 字段、不新增 API 端点。

## Phase 4 权重回测反馈闭环（本 PR 不做）

Phase 4 在同一 `CONTRACT_VERSION = "1.0"` 内补权重回测反馈：

- `SkillAggregator._compute_weight()` 已有 `perf_weight` / `_backtest_factor()` 接线，Phase 4 只补自动权重更新的闭环。
- Phase 4 不改变 Baseline canonical signal / valid 判定 / 共识门槛 / 阵营语义；权重变化只影响 `weighted_score` 与 `confidence`，不影响 `consensus_level` 判定路径。

## 消费面盘点

Baseline 的七条消费面必须严格按下表分工，不得越界互相消费对方的内部数据。

### SkillAgent

各 skill 通过 `src/agent/skills/skill_agent.py` 产出 `AgentOpinion`。Baseline 允许 skill 输出任意 signal 字面量（含大写、别名、`Signal` 枚举），也允许 skill 因数据不足产出 `signal=None` / 缺失字段——这些情况由下游分拣处理，skill 本身不做自我过滤。

### StrategyEngine / Orchestrator（分拣与接线）

Phase 1 在 DecisionAgent 运行前由 Orchestrator 调用 `_run_strategy_engine(ctx)`：

- `StrategyEngine.partition_only()` 遍历所有 `agent_name` 命中 `is_skill_agent_name()` 的观点，并使用 `normalize_strategy_signal()` 保留 canonical signal。
- Invalid 从 Evidence Chain 移除，写入 `StrategyResult.invalid_records`；Orchestrator 再把它赋给 `ctx.meta["invalid_opinions"]`。
- `StrategyEngine.process_partition()` 只把 `valid_skill_opinions` 交给 Aggregator/Synthesizer；产出的 consensus opinion 和 `skill_consensus` 由 `_run_strategy_engine()` 一次写回 context。
- timeout / budget-skip 发生在完整 engine 运行前时，`_apply_partition_fallback()` 复用 `partition_only()`，只完成分拣和 Diagnostics 写回，不生成 consensus。

Baseline 规定 `StrategyEngine.partition_only()` 是**唯一权威分拣实现**。Aggregator / DecisionAgent / Disagreement 不再各自定义 Valid/Invalid 规则，直接消费 engine 收敛后的 Evidence Chain；Orchestrator 中保留的旧 wrapper 仅用于兼容现有内部调用/测试，不属于正常运行时链路。

### SkillAggregator

正常运行时由 `StrategyEngine` 调用 `SkillAggregator.calculate(valid_skill_opinions)`。Aggregator 把输入转换为内部 `StrategyOpinion`，数学计算只使用 valid opinion，并严格使用 canonical signal 查 `strategy_signal_score`；兼容入口即使收到未分拣输入也不得让 Invalid 参与权重。对以下三种状态显式走 `insufficient` 分支：

- `len(valid) == 0`：`final_signal="hold"`, `confidence=0.0`。
- `len(valid) == 1`：按该 opinion 的 canonical signal 输出 `final_signal`，但 `consensus_level="insufficient"`。
- `len(valid) ≥ 2` 且 `sum(confidence) == 0`：`final_signal="hold"`, `confidence=0.0`。

产出的 `strategy_synthesis` 由 `StrategyEngine` 装入 `StrategyResult.skill_consensus_data`，再由 Orchestrator 挂到 `ctx.set_data("skill_consensus", {...})`；`_collect_strategy_synthesis()` 从这里读取，作为 dashboard 的权威合成源。

### DecisionAgent

`build_user_message()` 从 `ctx.opinions` 读取观点写入 prompt。因为 Orchestrator 分拣已保证 `ctx.opinions` 只含 Valid，DecisionAgent **不再**做二次过滤。Prompt 中"另有 N 个策略解析失败"的展示直接读取 `ctx.meta["invalid_opinions"]` 长度。

DecisionAgent 输出的 dashboard JSON 不得覆盖 `dashboard.strategy_synthesis`；如果 LLM 返回中含有该字段，`normalize_dashboard_payload()` 必须剥离，保留 Aggregator 侧的权威合成。

### Disagreement

`build_agent_disagreement_summary()` 只从 `ctx.opinions` 建 `bullish_agents` / `bearish_agents` / `neutral_agents` 三桶。因为 `ctx.opinions` 已只含 Valid，Invalid 完全不出现在三桶中，也不会被 `_normalize_signal()` 静默兜底为 `hold`。

`ctx.meta["invalid_opinions"]` 长度作为 `disagreement_summary.diagnostics.invalid_count` 单独暴露给 DecisionAgent prompt，供 LLM 生成 `data_limitations` 文案参考。

### Renderer（四条）

所有 renderer 读取 `dashboard.strategy_synthesis` 展示：

- `final_signal` / `consensus_level` / `conflict_severity` / `conflict_count`。
- `supporting_skills` / `opposing_skills`（不再消费 `neutral_skills`）。
- `summary_params.invalid_opinion_count` → 按语言展示"另有 N 个策略无效/解析失败"。

空列表占位符必须通过 `labels.none_label`（按 `report_language` 查表）输出。四条 renderer 展示的最终文本必须与 payload 完全一致，不得出现"共识度：高 + 支持策略：无"这类内部矛盾。

历史记录和外部调用方可能保留契约落地前的宽松 shape。四条 renderer 必须先通过 `normalize_strategy_synthesis_payload()` 把非 dict 顶层值视为缺失，并过滤非 dict 的策略/冲突列表项；`strategy_invalid_opinion_count()` 统一读取诊断计数，只对纯十进制正整数字符串做窄转换，其余坏值降级为 0。禁止在 History、Notification 或模板中保留平行的手写读取逻辑。

### Diagnostics

`ctx.meta["invalid_opinions"]` 只允许被以下三类消费：

- 日志：记录 `agent_name` / `raw_signal` / `reason`，供排障。
- DecisionAgent prompt：作为"另有 N 个策略解析失败"的计数来源。
- Renderer：作为 `summary_params.invalid_opinion_count` 的来源。

禁止把 Diagnostics 里的 `confidence` 参与任何加权计算；禁止把 `raw_signal` 塞回 `ctx.opinions`。

## 反例矩阵

Phase 1 必须提供如下 E2E 反例覆盖。E2E 定义为：从 SkillAgent 输入进，穿过 Orchestrator 分拣 → SkillAggregator → DecisionAgent prompt → 最终 dashboard payload → 四条 renderer 实际文本输出。禁止用局部单元测试冒充 E2E。

| 编号 | 输入 | 断言点 | 覆盖的不变量 |
| --- | --- | --- | --- |
| E2E-A | 1 valid `buy/0.8` + 2 invalid `moon/0.9` | ① DecisionAgent prompt 不含 `moon` 字面量、不含 invalid `agent_name`、不含 `0.9` 上下文；② `ctx.meta["invalid_opinions"]` 长度 = 2；③ `strategy_synthesis.summary_params.opinion_count == 1`、`invalid_opinion_count == 2`；④ `consensus_level == "insufficient"`；⑤ 四条 renderer 输出文本包含"另有 2 个策略无效/解析失败"（按语言）；⑥ `disagreement_summary.bullish_agents` / `neutral_agents` / `bearish_agents` 中都不出现 moon 转成的 hold/0.9 | I-1, I-2, I-4 |
| E2E-B | 2 valid `hold/0.0` | `final_signal="hold"`、`weighted_confidence=0.0`、`consensus_level="insufficient"`、**绝不**出现 `strong_sell`；所有 renderer 展示"证据不足（观望）"（按语言） | I-3 |
| E2E-C | 1 valid `buy/0.0` + 1 valid `hold/0.0` | 混合零权重场景：`final="hold"`、`confidence=0.0`、`consensus="insufficient"`、无 `strong_sell` | I-3 |
| E2E-D | 2 valid `hold/0.8` | ① `final_signal="hold"`、`consensus_level="high"`；② `supporting_skills` 长度 = 2、`opposing_skills` 长度 = 0；③ 四条 renderer 实际文本同时包含"高共识"和两个 skill 名，不得出现"支持策略：无"配"共识度：高"的组合 | I-5, I-6 |
| E2E-E | 1 valid `buy/0.8` + 9 invalid | `consensus_level="insufficient"`（**不得** high）；四条 renderer 展示"基于 1 个有效策略判断（另有 9 个策略无效/解析失败）" | I-4, I-6 |
| E2E-F | 2 valid opinion，其中一个 `signal="BUY"`（大写） | Aggregator 内部计算 `weighted_score` 时使用 canonical `buy` 查分（4.0），**不得**因大写查表失败得到 0；`strategy_synthesis.final_signal` 输出 canonical 小写 | I-7 |
| E2E-G | 空 `supporting_skills` + `report_language="en"` | 四条 renderer 输出中不出现中文 `"无"`，而是 `"None"`（或对应语言 `labels.none_label`） | I-8 |

## 源码锚点

| 域 | 锚点 |
| --- | --- |
| Signal 规范化与 Valid 判定 | `src/agent/protocols.py::normalize_strategy_signal`, `is_valid_strategy_signal`, `strategy_signal_score` |
| StrategyEngine 分拣与合成门面 | `src/agent/skills/engine.py::StrategyEngine.partition_only`, `process`, `process_partition` |
| Orchestrator 接线与早退分拣 | `src/agent/orchestrator.py::_run_strategy_engine`, `_apply_partition_fallback` |
| SkillAggregator | `src/agent/skills/aggregator.py::SkillAggregator.calculate`, `aggregate`（兼容入口） |
| ConflictDetector / StrategySynthesizer | `src/agent/skills/synthesis.py::ConflictDetector`, `StrategySynthesizer` |
| DecisionAgent prompt | `src/agent/agents/decision_agent.py::build_user_message` |
| Disagreement | `src/agent/disagreement.py::build_agent_disagreement_summary` |
| Dashboard 合成挂载 | `src/agent/orchestrator.py::_collect_strategy_synthesis` |
| Renderer · Markdown | `src/services/report_renderer.py::render`, `templates/report_markdown.j2` |
| Renderer · WeChat | `templates/report_wechat.j2` |
| Renderer · Notification | `src/notification.py`（策略综合行渲染） |
| Renderer · History | `src/services/history_service.py`（历史详情策略综合块） |
| 多语言与宽松 payload 防腐 | `src/report_language.py::_REPORT_LABELS`, `normalize_strategy_synthesis_payload`, `strategy_invalid_opinion_count`, `localize_strategy_synthesis_summary`, `labels.none_label` |
| E2E 反例矩阵 | `tests/test_multi_agent.py::TestP1SemanticConvergence`, `TestStrategyEngineE2E` |

## 兼容与回滚

### 已废弃行为（Phase 1 落地后）

| 旧行为 | 契约后 |
| --- | --- |
| `normalize_strategy_signal` 对未知信号静默返回 `default="hold"` 并混入证据链 | 未知信号必须归入 Diagnostics，`ctx.opinions` 中不允许出现 |
| Aggregator 通过 `sum(...) or 1.0` 掩盖零权重 | 显式判 `valid_weight_sum == 0`，走 `insufficient` 分支，`final_signal="hold"` |
| Renderer 硬编码 `"无"` 展示空阵营 | 通过 `labels.none_label` 按语言查表 |
| DecisionAgent 在 prompt 层自己过滤 invalid | 分拣在 Orchestrator 完成，DecisionAgent 直接消费 `ctx.opinions` |
| `strategy_synthesis` 输出 `neutral_skills` | 契约后该字段不存在，renderer 不再消费 |
| LLM dashboard 覆盖 `strategy_synthesis` | 权威合成来自 Aggregator，LLM 侧字段被 `normalize_dashboard_payload` 剥离 |

### 已新增字段

- `ctx.meta["invalid_opinions"]`：Diagnostics 收纳位（结构见"Evidence Chain 与 Diagnostics 分离"）。
- `strategy_synthesis.summary_params.invalid_opinion_count`：Diagnostics 长度。
- `strategy_synthesis.summary_params.total_opinion_count`：valid + invalid 的原始总数。

### 回滚方式

| 手段 | 作用 | 不能做什么 |
| --- | --- | --- |
| 版本回退 Phase 1 相关提交 | 移除 Orchestrator 分拣、Aggregator/Synthesizer 收敛、renderer 一致性改动 | 无法只回退部分不变量；契约是整体收敛 |
| 只保留契约文档、回退代码 | 保留 Baseline 文本、回到旧行为 | 只有文档意义，无运行时收益；不推荐 |
| Phase 2/3/4 独立回退 | 各自 Phase 的运行时改动独立回退 | 不能回退 Baseline，任何 Phase 都必须始终满足 Baseline 八条不变量 |

Baseline 不新增配置项，因此无 env-level 回滚开关；这是刻意选择——契约边界应在代码中恒定生效，不通过环境变量降级。
