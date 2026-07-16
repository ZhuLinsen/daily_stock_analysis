# Codex 仓库协作指南

本文说明如何让 Codex Desktop、CLI 或 IDE 在本仓库中加载正确规则、发现项目级 Skill，并按同一套验证边界工作。它不改变 DSA 产品中的 `codex_cli` 生成后端。

## 资产真源

| 资产 | 用途 |
| --- | --- |
| `AGENTS.md` | Codex 自动加载的仓库规则唯一真源，包含目录边界、验证矩阵、PR 与安全约束 |
| `.agents/skills/` | Codex 原生项目级 Skill 唯一真源 |
| `.claude/skills` | 指向 `.agents/skills/` 的兼容软链接，不单独维护内容 |
| `.github/copilot-instructions.md`、`.github/instructions/` | GitHub Copilot / Coding Agent 的镜像和路径补充 |
| `.codex/reviews/` | Issue / PR 分析的本地产物，默认不入库 |

根目录 `SKILL.md` 与 `docs/openclaw-skill-integration.md` 属于产品或外部集成说明，不是仓库协作 Skill。

## 开始使用

从仓库根目录打开 Codex。Codex 会自动读取 `AGENTS.md`，并发现 `.agents/skills/` 下的项目 Skill：

| 任务 | 调用方式 | 默认产物 |
| --- | --- | --- |
| 分析 GitHub Issue | `$analyze-issue <issue_number>` | `.codex/reviews/issues/issue-<number>.md` |
| 审查 GitHub PR | `$analyze-pr <pr_number>` | `.codex/reviews/prs/pr-<number>.md` |
| 修复已验证 Issue | `$fix-issue <issue_number>` | 代码、测试、文档与对应 Issue 分析记录 |

Codex 也可以根据 Skill 的 `description` 自动选择工作流。若桌面端未立即显示新 Skill，刷新 Skills 列表或重启 Codex。

普通开发任务不需要强制调用 Skill，直接描述目标即可。Codex 仍应先检查 `git status` 和当前实现，保护已有改动，并按 `AGENTS.md` 的改动面选择验证命令。

## 新增或修改 Skill

1. 只在 `.agents/skills/<skill-name>/` 中维护真实文件。
2. `SKILL.md` frontmatter 只声明 `name` 与清晰的 `description`。
3. 同步维护 `agents/openai.yaml`，其中 `default_prompt` 应显式包含 `$skill-name`。
4. 不新增根目录 `skills/`、`.codex/skills/` 或第二份 `.claude/skills/` 内容。
5. 运行治理校验：

   ```bash
   python3 scripts/check_ai_assets.py
   ```

## 配置边界

仓库不提供强制性的 `.codex/config.toml`。模型、推理强度、审批模式、沙箱权限、MCP 和个人偏好由使用者或受信任环境配置，避免把机器级选择写入版本库。

若改动协作规则、Skill、Copilot 镜像或治理脚本，还需在 `docs/CHANGELOG.md` 的 `[Unreleased]` 段记录变化，并在 PR 中说明影响面与回滚方式。
