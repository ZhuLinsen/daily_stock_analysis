# Codex Repository Collaboration Guide

This guide explains how Codex Desktop, CLI, and IDE load the repository rules, discover project Skills, and use one verification contract. It does not change the DSA product's `codex_cli` generation backend.

## Sources Of Truth

| Asset | Purpose |
| --- | --- |
| `AGENTS.md` | The single repository rule source loaded automatically by Codex, including directory boundaries, validation, PR, and safety rules |
| `.agents/skills/` | The single Codex-native source for repository Skills |
| `.claude/skills` | A compatibility symlink to `.agents/skills/`; it must not carry separately maintained content |
| `.github/copilot-instructions.md` and `.github/instructions/` | Mirrors and path-specific additions for GitHub Copilot / Coding Agent |
| `.codex/reviews/` | Local Issue and PR analysis artifacts, ignored by default |

The root `SKILL.md` and `docs/openclaw-skill-integration.md` describe product or external integration behavior. They are not repository collaboration Skills.

## Start Using Codex

Open Codex from the repository root. Codex automatically loads `AGENTS.md` and discovers the Skills under `.agents/skills/`:

| Task | Invocation | Default artifact |
| --- | --- | --- |
| Analyze a GitHub Issue | `$analyze-issue <issue_number>` | `.codex/reviews/issues/issue-<number>.md` |
| Review a GitHub PR | `$analyze-pr <pr_number>` | `.codex/reviews/prs/pr-<number>.md` |
| Fix a validated Issue | `$fix-issue <issue_number>` | Code, tests, docs, and the corresponding Issue analysis record |

Codex may also select a Skill automatically from its `description`. If a new Skill does not appear immediately in Desktop, refresh the Skills list or restart Codex.

Ordinary development tasks do not require a Skill invocation. Describe the outcome directly; Codex should still inspect `git status` and the current implementation, preserve existing changes, and choose validation from the matrix in `AGENTS.md`.

## Add Or Update A Skill

1. Maintain real files only under `.agents/skills/<skill-name>/`.
2. Keep `SKILL.md` frontmatter to `name` and a clear `description`.
3. Keep `agents/openai.yaml` aligned and include `$skill-name` in its `default_prompt`.
4. Do not add a root `skills/`, `.codex/skills/`, or a second maintained `.claude/skills/` tree.
5. Run the governance check:

   ```bash
   python3 scripts/check_ai_assets.py
   ```

## Configuration Boundary

The repository does not enforce a `.codex/config.toml`. Model choice, reasoning effort, approval mode, sandbox permissions, MCP, and personal preferences belong to the user or trusted environment rather than version control.

When changing collaboration rules, Skills, Copilot mirrors, or the governance script, also add a flat entry under `[Unreleased]` in `docs/CHANGELOG.md` and describe impact and rollback in the PR.
