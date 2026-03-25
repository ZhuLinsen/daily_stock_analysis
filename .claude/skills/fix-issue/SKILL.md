# Fix Issue

基于 issue 分析结果实现修复，并按仓库规则补齐验证、风险与回滚说明。

**Repository**: https://github.com/ZhuLinsen/daily_stock_analysis

## Usage

```text
/fix-issue <issue_number>
```

## Prerequisites

优先先完成 `/analyze-issue <issue_number>`，确保问题成立且边界清晰。

## Instructions

### Step 1: 确认分析基线

检查 `.claude/reviews/issues/issue-<number>.md` 是否存在；如果不存在，先补做 issue 分析或在本次修复中补齐最小分析结论。

### Step 2: 选择安全的工作方式

- 默认基于当前工作树做最小相关改动
- 不要默认执行 `git pull`
- 不要默认切换分支或改写用户当前工作状态
- 如果用户明确要求建分支，再执行最小必要的分支操作

### Step 3: 实施修复

- 根据 issue 结论定位相关文件
- 优先复用现有模块、配置入口、脚本和测试
- 保持默认行为向后兼容，避免破坏 fallback / fail-open
- 如果修复涉及用户可见行为、配置语义、CLI/API、部署、通知、报告结构，要同步更新相关文档、`docs/CHANGELOG.md`、`.env.example`
- `README.md` 主要承载入门、运行、部署和高层能力说明；更细的模块行为、页面交互或专题说明，优先更新对应 `docs/*.md`
- 如果没有更新 `README.md`，要在交付说明或 PR 描述里写清原因和实际文档落点

### Step 4: 按改动面验证

按 `AGENTS.md` 的验证矩阵执行最接近的检查：

- 后端优先：`./scripts/ci_gate.sh`
- 最低后端要求：`python -m py_compile <changed_python_files>`
- 前端：`cd apps/dsa-web && npm ci && npm run lint && npm run build`
- 桌面端：先构建 Web，再构建桌面端

如无法完成完整验证，必须记录缺口、原因与潜在风险。

### Step 5: 更新 issue 分析文档

在 `.claude/reviews/issues/issue-<number>.md` 中补充：

```markdown
## Fix Implementation

**Date**: YYYY-MM-DD

### Changes Made

- 文件与改动点：

### Validation

- 已执行：
- 未执行：

### Risks

- 风险点：

### Rollback

- 回滚方式：
```

### Step 6: 需要确认的后续动作

只有在用户明确确认后，才执行：

- 建分支
- `git commit`
- `git push`
- 创建 PR
- 在 issue 下回复或关闭 issue

## Allowed Auto-Actions (No Confirmation Needed)

- 阅读和分析代码
- 应用与当前任务直接相关的最小修复
- 运行非破坏性的本地验证
- 更新本地 issue 分析文档

## Actions Requiring Confirmation

1. 切换或创建分支
2. `git commit`
3. `git push`
4. 创建 PR
5. 回复或关闭 issue
