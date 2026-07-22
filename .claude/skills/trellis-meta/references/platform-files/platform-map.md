# Platform File Map

This page lists common Trellis file locations in a user project by platform. Whether a platform directory exists in an actual project depends on which `trellis init --<platform>` commands the user ran.

## Matrix

| Platform | CLI flag | Main directory | Skill directory | Agent directory | Hooks/extensions |
| --- | --- | --- | --- | --- | --- |
| Claude Code | `--claude` | `.claude/` | `.claude/skills/` | `.claude/agents/` | `.claude/hooks/` + `.claude/settings.json` |
| Cursor | `--cursor` | `.cursor/` | `.cursor/skills/` | `.cursor/agents/` | `.cursor/hooks.json` + `.cursor/hooks/` |
| OpenCode | `--opencode` | `.opencode/` | `.opencode/skills/` | `.opencode/agents/` | `.opencode/plugins/` |
| Codex | `--codex` | `.codex/` | `.agents/skills/` | `.codex/agents/` | `.codex/hooks/` + `.codex/hooks.json` |
| Kilo | `--kilo` | `.kilocode/` | `.kilocode/skills/` | Usually none | `.kilocode/workflows/` |
| Kiro | `--kiro` | `.kiro/` | `.kiro/skills/` | `.kiro/agents/` | `.kiro/hooks/` |
| Gemini CLI | `--gemini` | `.gemini/` | `.agents/skills/` | `.gemini/agents/` | `.gemini/settings.json` + `.gemini/hooks/` |
| Antigravity | `--antigravity` | `.agent/` | `.agent/skills/` | Usually none | `.agent/workflows/` |
| Devin | `--devin` | `.devin/` | `.devin/skills/` | Usually none | `.devin/workflows/` |
| Qoder | `--qoder` | `.qoder/` | `.qoder/skills/` | `.qoder/agents/` | `.qoder/hooks/` + `.qoder/settings.json` |
| CodeBuddy | `--codebuddy` | `.codebuddy/` | `.codebuddy/skills/` | `.codebuddy/agents/` | `.codebuddy/hooks/` + `.codebuddy/settings.json` |
| GitHub Copilot | `--copilot` | `.github/` | `.github/skills/` | `.github/agents/` | `.github/copilot/hooks/` + prompts |
| Factory Droid | `--droid` | `.factory/` | `.factory/skills/` | `.factory/droids/` | `.factory/hooks/` + settings |
| Pi Agent | `--pi` | `.pi/` | `.pi/skills/` | `.pi/agents/` | `.pi/extensions/trellis/` (native `trellis_subagent` tool) + `.pi/settings.json` |
| Trae IDE | `--trae` | `.trae/` | `.trae/skills/` | `.trae/agents/` | `.trae/hooks/` + `.trae/hooks.json` |
| Reasonix | `--reasonix` | `.reasonix/` | `.reasonix/skills/` | None — sub-agents are skills with `runAs: subagent` frontmatter | None |
| ZCode | `--zcode` | `.zcode/` | `.zcode/skills/` | `.zcode/agents/` | pull-based prelude (no hooks) |

## Capability Groups

### Trellis Sub-Agent Support

These platforms usually have `trellis-research`, `trellis-implement`, and `trellis-check` files:

- Claude Code
- Cursor
- OpenCode
- Codex
- Kiro
- Gemini CLI
- Qoder
- CodeBuddy
- GitHub Copilot
- Factory Droid
- Pi Agent
- Trae IDE
- Reasonix (delivered as skills with `runAs: subagent` under `.reasonix/skills/`, not as a separate `agents/` directory)
- ZCode

When changing implementation/check/research behavior, look for the corresponding platform agent files first.

### Native Trellis Sub-Agent Tool

Some platforms expose a first-class tool that the host runtime understands. The model calls it like any other tool and the host renders progress cards, validates the agent name against `.<platform>/agents/`, and enforces dispatch modes.

- Pi Agent — `trellis_subagent` tool, defined in `.pi/extensions/trellis/index.ts`. Supports `single` / `parallel` / `chain` dispatch modes and emits live `trellis-subagent-progress` events.

When changing sub-agent dispatch behavior on these platforms, edit the extension file, **not** the agent markdown — the agent markdown defines responsibilities, but the host extension owns dispatch, validation, and progress rendering.

### Main-Session Workflow Platforms

These platforms rely more on workflows/skills to guide the main session:

- Kilo
- Antigravity
- Devin

When changing behavior, inspect workflows and skills first. Do not assume Trellis sub-agents exist.

### Shared `.agents/skills/`

Codex and Gemini CLI write the shared `.agents/skills/` layer. Some tools that support agentskills.io can also read this directory. If the user wants multiple compatible tools to share one skill, consider `.agents/skills/` first, but do not assume every platform reads it. ZCode keeps Trellis-managed skills under `.zcode/skills/`.

## Decision Rules When Modifying Platform Files

1. User specified a platform: modify only that platform directory unless shared workflow/spec files must also change.
2. User says "all platforms should do this": synchronize equivalent entry points platform by platform; do not modify only one directory.
3. User only says "my AI": inspect the configuration directories that actually exist in the project and infer the current AI platform.
4. User wants project rules: prefer `.trellis/spec/` or a project-local skill.
5. User wants Trellis behavior: edit `.trellis/workflow.md` plus platform hooks/agents/skills/commands.

## When Paths Differ

Platform ecosystems change, and user projects may already be customized. If this table disagrees with local files, use the actual settings/config in the user project as authoritative:

- Check the hook that settings registers.
- Check the script that a command/prompt/workflow points to.
- Judge behavior by the read rules currently written in the agent file.

Do not delete a custom file just because it is not listed in this path table.

### `.omp/` — Oh My Pi (OMP)

Extension-backed platform. OMP native provider auto-discovers all subdirectories.

```
.omp/
├── commands/          # Slash commands (flat .md)
├── skills/            # Auto-triggered skills (SKILL.md per dir)
├── agents/            # Agent definitions (.md)
└── extensions/
    └── trellis/
        └── index.ts   # Trellis extension (context injection)
```

No `settings.json` — OMP scans `.omp/` subdirectories automatically.
No Python hooks — hook-equivalent behavior lives in the TypeScript extension.
