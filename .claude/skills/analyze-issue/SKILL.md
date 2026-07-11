# Analyze Issue

分析 GitHub Issue，判断其真实性、优先级、仓库责任边界与建议动作。

**Repository**: https://github.com/ZhuLinsen/daily_stock_analysis/issues

## Usage

```text
/analyze-issue <issue_number>
```

## Instructions

分析时使用简洁中文，优先遵循仓库根目录 `AGENTS.md`。

### Step 1: 同步最新代码基线

分析 issue 前必须先刷新远端状态，并尽量把本地安全推进到最新基线：

```bash
git status --short
git fetch --all --prune
# 仅当工作区干净且当前分支可 fast-forward 时执行：
git pull --ff-only
```

- 只有在工作区干净、当前分支有可 fast-forward 的上游时，才执行并接受 `git pull --ff-only` 的结果。
- 如存在本地改动、冲突状态、未跟踪风险文件、无上游分支或无法 fast-forward，不要执行 `stash`、`reset`、强制切分支或覆盖本地状态；改用已 fetch 的 `origin/main` 或相关远端 refs 做分析。
- 在输出文档的 `Evidence` 中记录同步结果：本地 HEAD、使用的远端基线，以及未更新本地工作树的原因（如有）。

### Step 2: 拉取 Issue 信息

```bash
gh issue view <issue_number> --repo ZhuLinsen/daily_stock_analysis
gh issue view <issue_number> --repo ZhuLinsen/daily_stock_analysis --comments
```

如为 bug，优先核对 issue 模板中是否提供了以下信息：

- 是否已同步到最新版本
- commit hash / 版本基线
- 运行环境与复现步骤
- 日志或报错信息

### Step 3: 回答 4 个核心问题

1. 版本是否明确
2. 问题是否真实且可验证
3. 是否属于仓库责任边界
4. 是否值得立即处理

### Step 4: 结合仓库现状做证据检查

- 阅读相关代码、配置、测试、脚本、工作流与文档
- 如果问题涉及 API、数据源 fallback、报告生成、通知发送、认证、桌面端、发布流程，明确写出影响面
- 判断是实际 bug、环境配置问题、使用方式问题、还是外部依赖问题
- 如怀疑已被修复，检查当前代码而不是只看 issue 描述

### Step 5: 形成结论

至少给出以下字段：

- `版本基线`：最新 / 非最新 / 未提供
- `是否合理`：是/否 + 理由
- `是否是 issue`：是/否 + 理由
- `是否好解决`：是/否 + 难点
- `结论`：`成立 / 部分成立 / 不成立`
- `分类`：`bug / feature / docs / question / external`
- `优先级`：`P0 / P1 / P2 / P3`
- `难度`：`easy / medium / hard`
- `建议动作`：`立即修复 / 排期修复 / 文档澄清 / 关闭`

### Step 6: 生成分析文档

保存到 `.claude/reviews/issues/issue-<number>.md`

## Output Document Format

```markdown
# Issue #<number> Analysis

**Date**: YYYY-MM-DD
**Status**: Pending Review

## Summary

- 版本基线：
- 是否合理：
- 是否是 issue：
- 是否好解决：
- 结论：
- 分类：
- 优先级：
- 难度：
- 建议动作：

## Evidence

- 代码同步基线：
- 关键 issue 信息：
- 关键代码/脚本/工作流证据：

## Impact Scope

- 受影响模块：
- 受影响运行路径（本地 / Docker / GitHub Actions / API / Web / Desktop）：

## Root Cause / Main Reasoning

<根因或主要判断依据>

## Proposed Handling

<建议修复、澄清或关闭方式>

若建议后续创建 PR，给出的 PR title 建议符合 `AGENTS.md`：使用 `<类型>: <修改内容>`，不添加 `[codex]`、`codex`、`autocode`、`copilot` 或其他工具/agent 来源前缀；该约定仅用于协作一致性提醒，不应单独作为 review process blocker。

## Risks And Rollback

- 风险点：
- 若修复，回滚方式：

## Draft Reply

<建议回复内容>
```

## Allowed Auto-Actions (No Confirmation Needed)

- 拉取 issue 详情与评论
- 执行 `git fetch --all --prune`，并在工作区干净且可 fast-forward 时执行 `git pull --ff-only`
- 阅读相关代码、配置、脚本、工作流和文档
- 生成分析文档

## Actions Requiring Confirmation

执行以下动作前，先询问用户：

1. 添加或修改标签
2. 在 issue 下评论
3. 关闭 issue
4. 开始修复 issue
