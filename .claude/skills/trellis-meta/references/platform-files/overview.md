# Platform Files Overview

Trellis connects the same local architecture to different AI tools. `.trellis/` stores the shared runtime; platform directories store adapter files that define how each AI tool enters Trellis.

When a local AI modifies Trellis, it should distinguish two file categories first:

- **Shared files**: `.trellis/workflow.md`, `.trellis/tasks/`, `.trellis/spec/`, `.trellis/scripts/`.
- **Platform files**: `.claude/`, `.codex/`, `.cursor/`, `.opencode/`, `.kiro/`, `.gemini/`, `.qoder/`, `.codebuddy/`, `.github/`, `.factory/`, `.pi/`, `.trae/`, `.kilocode/`, `.agent/`, `.devin/`, `.reasonix/`, `.zcode/`, and similar directories.

Platform files do not store business state. They let the corresponding AI tool read Trellis state, call Trellis scripts, and load Trellis skills/agents/hooks.

## Platform File Categories

| Category | Common paths | Purpose |
| --- | --- | --- |
| settings/config | `.claude/settings.json`, `.codex/hooks.json`, `.qoder/settings.json`, `.trae/hooks.json` | Register hooks, plugins, extensions, or platform behavior. |
| hooks/plugins/extensions | `.claude/hooks/`, `.opencode/plugins/`, `.pi/extensions/` | Inject context at session start, user input, agent startup, shell execution, and similar events. |
| agents | `.claude/agents/`, `.codex/agents/`, `.kiro/agents/`, `.zcode/agents/` | Define `trellis-research`, `trellis-implement`, and `trellis-check`. |
| skills | `.claude/skills/`, `.agents/skills/`, `.qoder/skills/`, `.zcode/skills/` | Capability descriptions that auto-trigger or can be read on demand. |
| commands/prompts/workflows | `.cursor/commands/`, `.github/prompts/`, `.devin/workflows/`, `.zcode/commands/` | Entry points explicitly invoked by the user. |

## Three Platform Integration Modes

### 1. Hook / Extension Driven

These platforms can trigger scripts or plugins on specific events and actively inject Trellis context into AI.

Common capabilities:

- session-start injection of a `.trellis/` overview.
- workflow-state hints for each user turn.
- PRD/spec/research injection when sub-agents start.
- Shell commands inheriting session identity.

To change "when the AI knows what," inspect hooks/plugins/extensions and settings first.

### 2. Agent Prelude / Pull-Based

Some platforms cannot reliably let hooks rewrite sub-agent prompts, so the agent file itself instructs the agent to read the active task, PRD, and JSONL context after startup.

To change how sub-agents load context, inspect the agent files themselves.

### 3. Main-Session Workflow

Some platforms do not have Trellis sub-agent or hook capabilities. They rely on workflows/skills/commands to guide the main-session AI to read files, run scripts, and move tasks forward.

To change behavior, inspect platform workflows/skills/commands and `.trellis/workflow.md`.

## Local Modification Order

When the user asks to customize behavior for a platform, the AI should inspect files in this order:

1. Read `.trellis/workflow.md` to confirm the shared flow.
2. Read the target platform's settings/config to see which hooks/agents/skills/commands are registered.
3. Read the target platform's agents/skills/commands/hooks.
4. Modify the local file closest to the user's need.
5. If the change affects the shared flow, synchronize `.trellis/workflow.md` or `.trellis/spec/`.

Do not modify only platform files and forget the shared workflow. Do not modify only `.trellis/workflow.md` and forget that platform entry points may still contain old descriptions.
