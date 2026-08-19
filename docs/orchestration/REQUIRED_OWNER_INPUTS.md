> 状态：Phase 0 / Phase 1 设计预览草稿。未实现、未接入、未导入私有知识。
> 基线：DSA `ed848da6f0fc1080e1a61a1799b9c7d510a3eaca`；AI Berkshire `4ddc638fd5366e9779450e5685d7a2a3cdff5fd0`。

# 所需 Owner 输入

## 下一 Gate 必须决策
1. Phase 1 当前明确未批准。待 Phase 0.1 收口后，Owner 如重新开启 Gate，只能考虑契约、人工脱敏 fixture 与 MockResearchProvider，不接入 AI Berkshire、私有知识或生产编排。
2. 既存前端失败已选择 `fix_first`；Phase 0.1 必须先完成独立诊断和最小修复或报告扩权阻塞。
3. 确认时间尺度定义建议：短期 0–20 个交易日；中期 1–4 个季度；长期 3–10 年（可修改）。
4. 确认最终决策允许的 stance/action 枚举和“投资建议”合规措辞。
5. 确认 Provider 失败策略、默认总超时和输出预算。
6. 在未来知识接入 Gate 前提供：知识授权主体、允许用途、允许用户范围、保留期、撤销流程、可否产生脱敏摘要。
7. 在 AI Berkshire 接入 Gate 前确认升级流程：谁批准 revision 变更、许可证归属展示、工具联网白名单和报告资产是否完全排除。
8. AI Berkshire 接入、私有知识导入和 Web 产品开发分别需要独立 Owner Gate。

## 建议精确回复模板
```text
APPROVE_PHASE_1_CONTRACTS_ONLY=yes|no
FRONTEND_BASELINE_DECISION=fix_first|accept_known_failure
SHORT_HORIZON=<定义>
MEDIUM_HORIZON=<定义>
LONG_HORIZON=<定义>
PROVIDER_TOTAL_TIMEOUT_SECONDS=<整数>
PROVIDER_MAX_OUTPUT_BYTES=<整数>
ALLOWED_STANCES=<列表>
```
任何未回答项保持 fail-closed，不开始实现。
