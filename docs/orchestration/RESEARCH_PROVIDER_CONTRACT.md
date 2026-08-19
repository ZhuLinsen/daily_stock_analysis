> 状态：Phase 0 / Phase 1 设计预览草稿。未实现、未接入、未导入私有知识。
> 基线：DSA `ed848da6f0fc1080e1a61a1799b9c7d510a3eaca`；AI Berkshire `4ddc638fd5366e9779450e5685d7a2a3cdff5fd0`。

# ResearchProvider 契约预览

## 设计类型（暂不实现）

### ResearchRequest
- `schema_version`、`request_id`、`run_id`、`subject`、`market`、`as_of`、`horizons`；
- 允许的数据域、授权上下文、语言；
- 每 Provider 超时、总截止时间、最大输出字节/证据数；
- `reproducibility`（DSA SHA、外部 revision、契约版本）；
- `redaction_profile`、`idempotency_key`、取消句柄。

### EvidenceRef
- `schema_version`、稳定 `evidence_id`、`source_type`、`source_uri`/内部不透明引用；
- `title`、`publisher`、`published_at`、`observed_at`、`as_of`；
- 内容摘要/哈希、授权、敏感级别、许可、时效状态；
- `claim_ids`（支持的 claim）和可复核定位；私有证据对未授权消费者只返回不透明引用。

### FrameworkOpinion
- `schema_version`、`request_id`、`run_id`、`provider_id`、`provider_version`、`framework`、`framework_version`、`as_of`、`horizon`；
- `stance`（bullish/bearish/neutral/abstain）、`confidence`、`data_quality`、`warnings`、`invalidation_conditions`；
- 声明必须逐项关联 `evidence_ids`；
- 每项声明标记 `claim_kind`（fact/opinion/inference）；推断必须列出所依赖的事实 claim，观点不得伪装为事实；
- 风险、假设、反证、缺口、数据截止时间；
- 不允许只有总分而没有可审计推理。

### ConflictItem
包含 `schema_version`、`request_id`、`run_id`；记录冲突声明、相关 Provider、证据集合、冲突类型（时间尺度/口径/事实/价值判断）、处理状态和不能平均的原因。

### IntegratedDecision
- 包含 `schema_version`、`request_id`、`run_id`、`as_of`，并分别保存 `short_term`、`medium_term`、`long_term`；
- 每个时间尺度有结论、行动边界、置信度、证据、风险、abstain 原因；
- `conflicts` 原样保留；不计算跨时间尺度简单平均；
- 任一实质性声明缺证据时整体校验失败或对该尺度 abstain。

### ProviderCapabilities
包含 `schema_version`、`provider_id`、`provider_version`；声明市场、时间尺度、证据类型、同步/后台、取消、最大预算、最大输出字节、联网要求、私有数据处理、可复现等级，以及该 Provider 在一次请求中为 `required` 或 `optional`。required Provider 失败时整体 fail-closed；optional Provider 失败可形成显式 partial result，但受影响时间尺度必须降级或 abstain。

### ProviderError
结构化字段：`schema_version`、`request_id`、`run_id`、`code`、`stage`、`retryable`、`fallbackable`、`fail_mode`、`provider_id`、`provider_version`、`partial`、安全化详情；至少覆盖 timeout、cancelled、unauthorized、stale_evidence、insufficient_evidence、revision_mismatch、output_too_large、dependency_unavailable。

### ResearchProvider
```text
provider_id
capabilities()
validate(request)
research(request, context) -> FrameworkOpinion | ProviderError
cancel(task_id)
health()  # 不应隐式联网或泄露秘密
```
同步接口可由编排层包装成后台任务；Provider 不自行越权扩展请求。

## 计划 Provider
| Provider | 作用 | 默认失败策略 |
|---|---|---|
| MockResearchProvider | 脱敏、确定性测试 | fail-closed（契约错误） |
| DsaTechnicalProvider | 短中期技术/市场上下文 | 局部 fail-open，但对应尺度 abstain |
| AiBerkshireProvider | 固定 revision 的长期价值研究 | revision 不匹配 fail-closed；不可用时长期 abstain |
| XiaolonglongKnowledgeProvider | 授权产业事件知识 | 未授权/来源缺失 fail-closed |
| HermesResearchProvider | Hermes 编排式研究/检索 | 必须真实能力声明；不能以 HTTP 生成通道冒充 Agent |

## 并发、取消与预算
编排层设置总截止时间、每 Provider semaphore、最大并发、输出字节、证据数量和 token 预算。取消向下传播；不支持安全取消的 Provider 不进入交互路径。超时后不得接受迟到结果写入最终决策。

## 证据与冲突规则
- 证据新鲜度按 evidence type + horizon 配置，不使用单一固定天数；
- 过期证据可作为历史背景，但不能支持“当前”声明；
- 不同尺度冲突保留并解释，不平均；
- 长期价值优秀不能自动覆盖短期风险；技术过热也不能自动否定长期价值；
- 事实冲突优先核对口径和一手来源；无法消解则 abstain；
- 无 evidence 的意见不能进入 IntegratedDecision。

## 序列化与往返
所有八类契约必须有确定性的 JSON 表示；`serialize -> deserialize -> serialize` 必须保持 schema_version、标识、枚举、时间、证据关联、warnings、未知字段处理策略和 abstain 语义，不得静默丢字段或把三类后端语义折叠到同一字段。
