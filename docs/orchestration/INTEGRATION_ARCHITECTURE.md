> 状态：Phase 0 / Phase 1 设计预览草稿。未实现、未接入、未导入私有知识。
> 基线：DSA `ed848da6f0fc1080e1a61a1799b9c7d510a3eaca`；AI Berkshire `4ddc638fd5366e9779450e5685d7a2a3cdff5fd0`。

# 集成架构预览

## 边界
```text
Scheduled / Interactive Request
          |
          v
Hermes Research Orchestrator ---- Task state / cancellation / audit
          |
          +--> DsaTechnicalProvider ------ DSA services + Tool Surface
          +--> AiBerkshireProvider ------- read-only pinned checkout
          +--> XiaolonglongKnowledgeProvider -> private boundary, authorized retrieval only
          +--> HermesResearchProvider ---- Hermes research capability (not HTTP generation disguise)
          +--> MockResearchProvider ------- deterministic sanitized fixtures
          |
          v
Conflict-aware Integrator -> IntegratedDecision(short/mid/long + evidence)
```

## 契约分层
| 层 | 职责 | 不负责 |
|---|---|---|
| GenerationBackend | prompt 到生成文本、模型和用量 | 研究证据、Provider 生命周期、工具闭环 |
| AgentBackend | 多轮交互和真实 DSA 工具调用 | 外部研究框架版本化、统一研究意见契约 |
| ResearchProvider | 从 ResearchRequest 产出带证据的 FrameworkOpinion | 通用聊天、隐式下单 |
| Hermes 编排 | 任务状态、并发、取消、重试、证据校验、冲突综合 | 冒充 Provider 的原始结论来源 |

Hermes HTTP generation channel 仍是 `supports_tools=False` 的本地文本生成通道。Codex 最终文本只有在其 `tool_calls_log` 和 DSA tool roundtrip 被验证时，才能声明使用了 DSA 工具。

## 调用形态
- scheduled analysis：确定性批次、固定截止时间、幂等键、后台任务、允许局部 Provider 降级；产物必须可复现。
- interactive Agent：用户会话、渐进事件、显式取消、较短等待预算；只有 AgentBackend 可宣称工具回合。
- 同步：仅用于低延迟、可在请求时限内完成的 Provider。
- 后台：长期价值研究和知识检索默认进入任务状态机 `queued/running/succeeded/partial/failed/cancelled/timed_out`。

## 版本和复现
每次运行记录 DSA SHA、AI Berkshire SHA、Provider 版本、契约版本、请求规范化摘要、模型/工具版本、证据抓取时间和截止时间。不得记录私有原文或秘密。Phase 1 仅设计后的实现需另获批准。
