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
- 向 `docs/CHANGELOG.md` 写入条目时，在 `[Unreleased]` 段追加一行，格式为 `- [类型] 描述`，其中 `[类型]` 从 `[新功能]/[改进]/[修复]/[文档]/[测试]/[chore]` 中按本次变更内容选择；只有修复 bug 时才使用 `[修复]`；**不要**在 `[Unreleased]` 内新增 `### 类目标题`
- `README.md` 只承载项目定位、核心能力、快速开始、主要入口、赞助/合作等首页级信息；非必要不更新 README，避免持续膨胀
- 更细的模块行为、页面交互、专题配置、排障说明、字段契约、实现语义和边界条件，优先更新对应 `docs/*.md`

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

如用户要求创建 PR、生成 PR 标题或整理 PR 描述，PR title 建议遵循 `AGENTS.md`：

- 使用 `<类型>: <修改内容>` 格式，例如 `fix: 修复大盘分析历史记录丢失`
- 类型优先使用 `fix`/`feat`/`refactor`/`docs`/`chore`/`test`/`ci`
- 标题只描述实际改动，建议不添加 `[codex]`、`codex`、`autocode`、`copilot` 或其他工具/agent 来源前缀
- 该约定仅用于协作一致性，不应被单独当作 process blocker

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
