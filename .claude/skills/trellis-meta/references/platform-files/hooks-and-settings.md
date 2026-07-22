# Hooks And Settings

Hooks/settings are the entry layer that connects a platform to Trellis. They decide which scripts, plugins, or extensions a platform runs for which events.

## Settings Responsibilities

settings/config files usually register:

- session-start hook: injects a Trellis overview when a new session starts or context resets.
- workflow-state hook: parses `[workflow-state:STATUS]` blocks from `.trellis/workflow.md` and emits the body matching the current task `status` on each user input. Parser-only; the script does not embed fallback content.
- sub-agent context hook: injects task context when implementation/check/research agents start.
- shell/session bridge: lets shell commands see the same Trellis session identity.
- platform plugin or extension entry points.

Common files:

| Platform | settings/config |
| --- | --- |
| Claude Code | `.claude/settings.json` |
| Cursor | `.cursor/hooks.json` |
| Codex | `.codex/hooks.json`, `.codex/config.toml` |
| OpenCode | `.opencode/package.json`, `.opencode/plugins/*` |
| Kiro | `.kiro/hooks/` + platform config |
| Gemini CLI | `.gemini/settings.json` |
| Qoder | `.qoder/settings.json` |
| CodeBuddy | `.codebuddy/settings.json` |
| GitHub Copilot | `.github/copilot/hooks.json` |
| Factory Droid | `.factory/settings.json` |
| Pi Agent | `.pi/settings.json`, `.pi/extensions/trellis/` |
| Trae IDE | `.trae/hooks.json` |

Reasonix and ZCode are pull-based platforms that do not use hooks or settings files; their agent files contain prelude instructions to read context after startup.

Whether these files exist in a project depends on which `trellis init --<platform>` flags the user ran.

## Hook Script Types

| Script | Purpose |
| --- | --- |
| `session-start.py` | Generates session-start context. |
| `inject-workflow-state.py` | Parses `[workflow-state:STATUS]` blocks in `.trellis/workflow.md` and emits the body matching the current task status. Falls back to `Refer to workflow.md for current step.` when no matching block exists. |
| `inject-subagent-context.py` | Injects PRD, JSONL context, and related spec/research into sub-agents. |
| `inject-shell-session-context.py` | Lets shell commands inherit Trellis session identity. |

Not every platform has every hook. Do not copy files from another platform just because a platform lacks a hook; first confirm whether that platform supports the corresponding event.

## Local Change Scenarios

| User need | Edit location |
| --- | --- |
| AI should see more/less context in a new session | Platform `session-start` hook. |
| Per-turn hint policy should change | `[workflow-state:STATUS]` block in `.trellis/workflow.md`. The hook parses workflow.md verbatim — no script edit required. |
| Sub-agent cannot read PRD/spec | `inject-subagent-context` hook or agent prelude. |
| `task.py current` in shell has no active task | Shell/session bridge hook or platform environment variable configuration. |
| Disable an automatic injection | The corresponding hook registration in settings/config. |

## Modification Principles

1. **Settings wire things up; hooks define behavior**. If only the hook changes, the platform may never call it. If only settings change, behavior may not change.
2. **Confirm platform event names first**. Different platforms use different names for SessionStart, UserPromptSubmit, AgentSpawn, shell execution, and similar events.
3. **Hooks read local `.trellis/`, not upstream source**. `.trellis/scripts/` and `.trellis/workflow.md` in the user project are the default targets.
4. **Errors must be visible**. Hook failures should tell the user what was not injected instead of silently leaving the AI without context.

## Troubleshooting Path

If the user says "AI did not read Trellis state":

1. Check whether the platform settings register the hook.
2. Check whether the hook file exists.
3. Manually run the `.trellis/scripts/get_context.py` or `task.py current --source` command that the hook depends on.
4. Check whether active task state exists in `.trellis/.runtime/sessions/`.
5. Check whether the platform shell passes session identity.
