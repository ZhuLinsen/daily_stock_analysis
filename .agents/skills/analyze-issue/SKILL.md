---
name: analyze-issue
description: 分析 daily_stock_analysis 仓库的 GitHub Issue，核实版本基线、真实性、根因定位、影响面与仓库责任边界，给出优先级和处置建议。用户给出 Issue 号或链接并要求分析时使用。
---

# Analyze Issue

规则真源：仓库根目录 [`AGENTS.md`](../../../AGENTS.md)（基线同步规则见 §7）。

- 输出语言：简洁中文。
- 产物策略：**默认直接在对话中输出**；仅当用户明确要求存档时，写入 `.reviews/issues/issue-<number>.md`。

## Step 1: 同步基线并拉取 Issue

按 `AGENTS.md` §7 同步远端基线并记录本地 HEAD 与远端基线，然后执行：

```bash
gh issue view <number> --repo ZhuLinsen/daily_stock_analysis
gh issue view <number> --repo ZhuLinsen/daily_stock_analysis --comments
```

如为 bug，核对是否提供了版本/commit hash、运行环境、复现步骤与报错日志。

## Step 2: 代码证据核查

- 阅读相关源码、配置、测试、工作流与文档，不凭 issue 描述直接下结论。
- 回答 4 个核心问题：版本是否明确、问题是否真实可验证、是否属于仓库责任边界、是否值得立即处理。
- 区分：真实代码 bug / 配置或环境问题 / 使用方式问题 / 外部数据源或三方依赖问题 / 已在主干修复。
- 明确排查受影响模块与运行路径（本地 CLI / Docker / GitHub Actions / API / Web / Desktop）。

## Step 3: 输出格式

```markdown
# Issue #<number> Analysis

## 1. 结论摘要
- 版本基线：最新 / 非最新 / 未提供
- 结论：成立 / 部分成立 / 不成立
- 分类：bug / feature / docs / question / external
- 优先级：P0 / P1 / P2 / P3 | 难度：easy / medium / hard
- 建议动作：立即修复 / 排期修复 / 文档澄清 / 关闭

## 2. 证据与根因
- 代码同步基线：
- 关键 Issue 信息：
- 源码 / 配置 / 工作流证据（`path:line`）：
- 根因或主要判断依据：

## 3. 影响面
- 受影响模块与既有运行时文件：
- 受影响运行路径（本地 / Docker / GitHub Actions / API / Web / Desktop）：
- 是否涉及配置/环境变量、UI/Web、报告结构、通知或持久化变更：

## 4. 处置建议
- 修复方案 / 澄清要点 / 关闭理由：
- 若后续提 PR，标题建议遵循 `AGENTS.md` §1.1（`<type>: <修改内容>`，不含工具前缀）。

## 5. 不可逆变更（如计划修复）
- 仅在修复涉及数据库/配置迁移/外部状态写入时说明；否则写“无”。

## 6. 建议回复草稿
<可直接回复到 Issue 的简洁中文内容>
```

## 需用户确认的动作

添加/修改标签、发表评论、关闭 Issue、开始写代码修复前必须先询问用户。
