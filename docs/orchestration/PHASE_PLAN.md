> 状态：Phase 0 / Phase 1 设计预览草稿。未实现、未接入、未导入私有知识。
> 基线：DSA `ed848da6f0fc1080e1a61a1799b9c7d510a3eaca`；AI Berkshire `4ddc638fd5366e9779450e5685d7a2a3cdff5fd0`。

# 阶段计划

| 阶段 | 目标 | 允许变更 | 退出条件 | Owner Gate |
|---|---|---|---|---|
| Phase 0 | 基线、风险、设计预览 | 本目录十份文档 | 身份/门禁/差异复核完成 | 条件通过 |
| Phase 0.1 | 十文档一致性与前端既存失败收口 | 原十份文档；独立前端 worktree 的直接相关文件 | 文档一致、前端门禁收口或报告扩权阻塞 | 当前已批准 |
| Phase 1 | 契约与 Mock 设计/实现 | 若未来另获批准，仅限 schema、人工脱敏 fixture、MockResearchProvider 和直接测试 | 契约测试、序列化往返、无运行时接入 | **未批准（Phase 0.1 再次明确拒绝）** |
| Phase 2 | DSA Technical Provider | 最小适配层 | 真实 evidence、超时取消 | 未批准 |
| Phase 3 | AI Berkshire Provider | 只读 revision 适配 | SHA 锁定、工具依赖审计 | 未批准，需独立 Gate |
| Phase 4 | 小龙龙知识 Provider | 私有索引和授权检索 | 无原文泄露、可撤销 | 未批准，需独立 Gate |
| Phase 5 | Hermes 编排与综合 | 状态机、冲突、输出 | 分尺度决策和 evidence 校验 | 未批准 |
| Phase 6 | 产品化 | API/Web/调度/运维；Web 产品开发须独立 Gate | 完整安全与回归门禁 | 未批准 |

## Phase 1 预期但未授权
若未来重新批准，只定义 `ResearchRequest`、`EvidenceRef`、`FrameworkOpinion`、`ConflictItem`、`IntegratedDecision`、`ResearchProvider`、`ProviderCapabilities`、`ProviderError`，并仅用人工脱敏 fixture 实现 MockResearchProvider。不得接入外部仓库、私有知识或真实 Provider。

## 路线外
IntegratedDecision 第一版不得生成真实交易订单；整个当前路线不连接券商、不执行自动下单、账户控制或实盘交易。

## 每阶段标准流程
只读侦察 → 风险报告 → Owner 批准 → 独立 worktree → 最小变更 → Hermes 独立验收 → 停止。任何基线失败先分类，不直接修产品代码。
