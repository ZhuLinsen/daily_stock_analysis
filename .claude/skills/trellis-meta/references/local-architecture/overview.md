# Local Trellis Architecture Overview

`trellis-meta` is for user projects that have already run `trellis init`. The user's machine usually has only the npm-installed `trellis` command plus the Trellis files generated inside the project; it may not have the Trellis CLI source code.

Therefore, when an AI uses this skill, the default customization target is local files inside the user project:

- `.trellis/`: workflow, tasks, specs, memory, scripts, and runtime state.
- Platform directories: `.claude/`, `.codex/`, `.cursor/`, `.opencode/`, `.kiro/`, `.gemini/`, `.qoder/`, `.codebuddy/`, `.github/`, `.factory/`, `.pi/`, `.kilocode/`, `.agent/`, `.devin/`, `.reasonix/`, `.zcode/`, and similar directories.
- Shared skill layer: `.agents/skills/`.

Do not default to guiding the user to fork the Trellis CLI repository. Treat upstream source code as the operating target only when the user explicitly says they want to change Trellis upstream source, publish an npm package, or contribute a PR.

## Local System Model

Trellis provides three layers inside a user project:

1. **Workflow layer**: `.trellis/workflow.md` defines phases, routing, next actions, and prompt blocks.
2. **Persistence layer**: `.trellis/tasks/`, `.trellis/spec/`, and `.trellis/workspace/` store tasks, specs, and session memory.
3. **Platform integration layer**: hooks, settings, agents, skills, commands, prompts, and workflows in platform directories connect the Trellis workflow to different AI tools.

All three layers live inside the user project, so an AI can read and modify them directly.

## Core Paths

| Path | Purpose |
| --- | --- |
| `.trellis/workflow.md` | Workflow phases, skill routing, and workflow-state prompt blocks. |
| `.trellis/config.yaml` | Project configuration, task lifecycle hooks, monorepo package configuration, and journal configuration. |
| `.trellis/spec/` | The user's project-specific coding conventions and thinking guides. |
| `.trellis/tasks/` | Each task's PRD, technical notes, research files, and JSONL context. |
| `.trellis/workspace/` | Per-developer journals and cross-session memory. |
| `.trellis/scripts/` | Local Python runtime used by commands, hooks, and context injection. |
| `.trellis/.runtime/` | Session-level runtime state, such as the current task pointer. |
| `.trellis/.template-hashes.json` | Template hashes for Trellis-managed files, used by update to determine whether local files were modified by the user. |

## AI Customization Principles

1. **Find the local source of truth first**: Do not edit from memory. Read `.trellis/workflow.md`, `.trellis/config.yaml`, the relevant platform directory, and related task files first.
2. **Edit the user project, not the npm package cache**: Modify generated files inside the project, not `node_modules` or the global npm install directory.
3. **Keep platform files aligned with `.trellis/`**: If workflow routing changes, also check whether platform skills or commands still describe the same flow.
4. **Put project-specific rules in `.trellis/spec/` or a local skill**: Do not put team conventions into `trellis-meta`.
5. **Preserve user changes**: If a file was already modified locally, work from the current content instead of overwriting it with a default template.

## How To Use This Directory

- To understand which files exist after init, read `generated-files.md`.
- To change phases, routing, or next actions, read `workflow.md`.
- To change the task model, JSONL context, or active task behavior, read `task-system.md`.
- To change coding convention injection, read `spec-system.md`.
- To understand journals and cross-session memory, read `workspace-memory.md`.
- To change hooks or sub-agent context loading, read `context-injection.md`.
