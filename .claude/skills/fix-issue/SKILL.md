---
name: fix-issue
description: 基于 Issue 分析结论实施最小化修复，按 AGENTS.md 验证矩阵执行验证并输出行为变化、影响面与验证证据。用户明确要求修复某个 Issue 时使用。
---

# Fix Issue

规则真源：仓库根目录 [`AGENTS.md`](../../../AGENTS.md)（硬规则见 §1，验证矩阵见 §5，基线同步见 §7）。

## Step 1: 确认分析基线与同步代码

1. 若对话上下文或 `.reviews/issues/issue-<number>.md` 已有分析结论则复用；否则先按 `analyze-issue` 补齐最小根因与影响面分析。
2. 按 `AGENTS.md` §7 同步远端基线；不擅自 `stash`、`reset` 或切换用户当前分支，需要建分支时先确认。

## Step 2: 实施最小修复

- 优先复用现有模块、配置入口、脚本和测试，不新增平行实现。
- 保持默认行为向后兼容，避免破坏 fallback / fail-open。
- 检查同语义涉及的所有入口（CLI / API / Bot / Web / Desktop / Docs / Tests），不打局部补丁。
- 若涉及用户可见能力、配置项、CLI/API、通知或报告变化，按 `AGENTS.md` §1 同步 `.env.example` 与相关 `docs/*.md`。

## Step 3: 按改动面验证

按 `AGENTS.md` §5 验证矩阵执行对应检查：
- 后端：优先 `./scripts/ci_gate.sh`（Windows 可在 Git Bash/WSL 运行），最低要求 `python -m py_compile` + 最近确定性 pytest。
- Web：`cd apps/dsa-web && npm ci && npm run lint && npm run build`。
- Desktop：先构建 Web，再构建 `apps/dsa-desktop`。
- 治理资产：`python scripts/check_ai_assets.py`。

无法执行的检查必须明确说明原因与缺口。

## Step 4: 交付输出

按 `AGENTS.md` §8 输出交付说明（默认直接输出在对话中；若存在 `.reviews/issues/issue-<number>.md` 可按需追加）：
- 改了什么（含修改的既有文件 `path:line`）
- 行为变化（改前 vs 改后）
- 影响面（配置/环境变量、API/CLI、UI/Web/Desktop、报告/通知、不可逆变更）
- 验证情况与未验证项

## 需用户确认的动作

切换/新建分支、`git commit`、`git push`、创建 PR、在 Issue 下回复或关闭 Issue 前必须先征得用户确认。
