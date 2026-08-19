> 状态：Phase 0 / Phase 1 设计预览草稿。未实现、未接入、未导入私有知识。
> 基线：DSA `ed848da6f0fc1080e1a61a1799b9c7d510a3eaca`；AI Berkshire `4ddc638fd5366e9779450e5685d7a2a3cdff5fd0`。

# 安全边界

## 信任区
1. DSA Git 区：代码、公开文档、人工脱敏 fixture；禁止私有知识和秘密。
2. AI Berkshire 参考区：独立 checkout、固定 SHA、只读；不得修改 canonical/generated skills。
3. 私有知识区：`/Volumes/future/projects/DSA Research OS/private-knowledge/xiaolonglong`；Git、镜像、日志、公开 API 默认禁止访问原文。
4. 运行时区：临时任务、缓存、数据库；按最小权限和保留期管理。
5. Hermes/Codex 区：Hermes 承担审批和验收；Codex 只能在独立 worktree 和显式允许列表中工作。

## 强制控制
- 路径 canonicalize 后再做 allowlist 检查，阻止符号链接逃逸；
- 外部 checkout 启动时验证 origin、HEAD、clean；revision mismatch fail-closed；
- Prompt、错误、工具结果统一脱敏并限制字节；
- 私有原文或可还原内容不得进入异常、日志、模型 trace、遥测；未经授权不得发送给外部模型或第三方服务；
- 私有 Provider 的授权上下文不可由用户输入自声明；
- 所有结论做 evidence 外键完整性校验；
- 禁止 Provider 返回交易执行命令；只允许研究建议边界；
- 后台任务使用 deadline、取消、并发上限和资源清理。

## Hermes 与 Codex
Hermes HTTP generation 是 loopback 文本通道，不支持工具调用。只有 AgentBackend 的真实工具记录可证明 tool roundtrip。Codex 的最终文本和自述测试仅为建议证据；Hermes 必须检查 diff 并复跑验证。

## Phase 0 声明
未创建 `.env`，未写入凭据，未读取私有知识原文，未接入任何 Provider，未修改实验性 `ai-berkshire-fork`。流程偏差 `P0-EXPERIMENTAL-REFERENCE-STAT-001` 已在基线审计登记；此后禁止再次访问该路径。依赖和前端产物只在正式 DSA 基线 checkout 中用于门禁，Git 状态复核干净。
