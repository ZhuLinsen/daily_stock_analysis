> 状态：Phase 0 / Phase 1 设计预览草稿。未实现、未接入、未导入私有知识。
> 基线：DSA `ed848da6f0fc1080e1a61a1799b9c7d510a3eaca`；AI Berkshire `4ddc638fd5366e9779450e5685d7a2a3cdff5fd0`。

# DSA Research OS 项目章程

## 使命
在 `daily_stock_analysis` 唯一产品主仓库内演进 DSA Research OS：保留现有日常分析能力，以可审计的研究 Provider 契约组合技术分析、版本锁定的长期价值研究、经授权的产业事件知识与 Hermes 编排。系统只辅助研究，不自动下单。

## 不可变原则
1. DSA 是唯一产品主仓库和集成边界；外部仓库不复制进 `src/`。
2. AI Berkshire 是独立、只读、固定 SHA 的 Provider 输入。
3. 私有知识必须带日期、出处、授权和敏感级别；原文不进入 Git、镜像、日志或测试样例。
4. 每个实质性结论必须引用 `EvidenceRef`；无证据则 abstain。
5. 短期、中期、长期分别输出，不以简单平均掩盖冲突。
6. Hermes 负责编排、任务状态、检索与独立验收；Codex 仅做有边界实现。
7. GenerationBackend、AgentBackend 与 ResearchProvider 保持不同契约。
8. 不实现实盘交易、券商下单或账户控制。

## Phase 0 范围
仅完成基线核查、风险登记、架构与契约预览，以及本目录十份文档草稿。不得修改运行时代码、测试、配置、工作流、README、AI Berkshire 或私有知识边界。

## 成功定义
- 基线身份和门禁结果可复核；
- Provider 契约支持证据、时效、版本、错误、取消与预算；
- 安全边界默认拒绝泄露和无证据结论；
- 后续每阶段均需 Owner Gate。
