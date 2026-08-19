> 状态：Phase 0 / Phase 1 设计预览草稿。未实现、未接入、未导入私有知识。
> 基线：DSA `ed848da6f0fc1080e1a61a1799b9c7d510a3eaca`；AI Berkshire `4ddc638fd5366e9779450e5685d7a2a3cdff5fd0`。

# 验收矩阵

| 要求 | Phase 0 证据/判定 | 状态 |
|---|---|---|
| DSA 唯一产品主仓库 | 章程与架构明确 | 通过 |
| 固定 DSA SHA | `ed848da6...eaca` | 通过 |
| 固定 AI Berkshire SHA、只读干净 | `4ddc638f...5fd0`，sync `--check` 通过 | 通过 |
| 私有知识未读取/导入 | 仅记录边界路径 | 通过 |
| Generation/Agent/Research 分层 | 架构与契约文档 | 通过（设计） |
| 无证据 abstain | 契约和溯源政策 | 通过（设计） |
| 冲突不平均、分短中长期 | 契约明确 | 通过（设计） |
| 同步/后台/超时/取消/并发/预算 | 契约明确 | 通过（设计） |
| Provider fail-open/fail-closed | 契约逐 Provider 说明 | 通过（设计） |
| 版本化与可复现 | 架构记录字段 | 通过（设计） |
| 不实现自动下单 | 章程与安全边界 | 通过 |
| DSA 后端门禁 | 5740 passed | 通过 |
| DSA 前端测试 | 1 failed / 1090 passed / 2 skipped | **未通过（既存）** |
| DSA 前端 lint/build | 均 exit 0 | 通过 |
| 仅十份允许文档 | `git status --porcelain=v1 -uall` 精确匹配允许清单，tracked/staged diff 均为空 | 通过 |
| 无 commit/tag/push/PR | 最终状态验证：文档均为未跟踪文件，无暂存与新提交 | 通过 |
| 八类契约关键字段 | schema/run/request/provider/framework 版本、质量、告警、失效条件、partial/required/optional | 通过（设计预览） |
| 序列化往返 | JSON 往返不得静默丢字段或折叠后端语义 | 通过（设计预览） |
| 私有内容外发与 trace | 未授权外部模型发送和日志/异常/trace/遥测均 fail-closed | 通过（设计预览） |
| 流程偏差 | `P0-EXPERIMENTAL-REFERENCE-STAT-001` 已登记；禁止再次访问实验路径 | 已登记 |

## Phase 1 验收预览
- Schema 严格校验且向前版本化；
- 每条 FrameworkOpinion 声明均引用现存 EvidenceRef；
- 缺证据、过期、未授权、revision mismatch 覆盖失败测试；
- Mock fixture 人工制作并通过敏感信息扫描；
- 不接入任何真实 Provider；
- Owner 已决定 `fix_first`，须在 Phase 0.1 独立 worktree 完成契约诊断与最小收口后，才可考虑新的 Phase 1 Gate。

## Phase 1.2 验收
| 要求 | 实现/测试证据 | 状态 |
|---|---|---|
| 最终目录迁移 | `src/schemas/research_contracts.py`、`src/agent/research_provider.py`、`src/agent/research_orchestrator.py` | 通过 |
| 删除平行包 | `src/research/` 不存在，源码/测试无 `src.research` 导入 | 通过 |
| 无自动重试 | 单次调用实现；`test_retryable_error_is_not_retried` | 通过 |
| Protocol 接口 | `ResearchProvider(Protocol)` 结构化子类型 | 通过 |
| 取消无遗留任务 | 协作取消、等待线程退出、`active_task_ids()==()`、无活动 `research-provider:` 线程 | 通过 |
| 超时无迟到写入 | 超时调用 Provider cancel 并等待退出后返回 | 通过 |
| 完整脱敏 Mock | 正常/三尺度/abstain/冲突/坏证据/延迟/超时/取消/错误 | 通过 |
| 契约字段与序列化 | schema/版本/证据/声明/错误/角色/元组枚举确定性 JSON | 通过 |
| 零外部副作用 | 零网络、零真实 LLM、零私有导入、零自动交易 | 通过 |
| Phase 2 | 未创建 worktree，未实现 DSA Technical Provider | 未批准/未开始 |
