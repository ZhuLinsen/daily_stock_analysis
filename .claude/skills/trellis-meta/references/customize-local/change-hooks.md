# Change Local Hooks

Hooks are the automation layer that connects a platform to Trellis. When the user wants to change "when context is injected," "how shell commands inherit a session," or "which files are read before an agent starts," hooks are usually the edit point.

## Read These Files First

1. Target platform settings/config, such as `.claude/settings.json`, `.codex/hooks.json`, `.cursor/hooks.json`, `.trae/hooks.json`
2. Target platform hooks directory
3. `.trellis/scripts/common/active_task.py`
4. `.trellis/scripts/common/session_context.py`
5. `.trellis/workflow.md`

## Common Hook Types

| Hook | Purpose |
| --- | --- |
| session-start | Injects a Trellis overview when a session starts, clears, or compacts. |
| workflow-state | Injects a state hint on each user input. |
| sub-agent context | Injects PRD/spec/research before an agent starts. |
| shell session bridge | Lets `task.py` commands in shell see the same session identity. |

## Modification Steps

1. Find the hook registration in settings/config.
2. Confirm the registered script path exists.
3. Read the hook script and identify inputs, outputs, and called `.trellis/scripts/`.
4. Modify hook behavior.
5. If the hook depends on workflow content, synchronize `.trellis/workflow.md`.

## Example: Change New-Session Injection Content

First find the session-start hook:

```text
.claude/settings.json
.claude/hooks/session-start.py
```

If the hook ultimately calls `.trellis/scripts/get_context.py` or `session_context.py`, editing the local script is usually more robust than hard-coding content in the hook.

## Example: Agent Did Not Read JSONL

First confirm:

```bash
python ./.trellis/scripts/task.py current --source
python ./.trellis/scripts/task.py validate <task>
```

If the task and JSONL are correct, determine whether the platform uses hook push or agent pull. For hook push, edit `inject-subagent-context`; for agent pull, edit the agent file.

## Notes

- Settings handle registration, hook scripts handle behavior; inspect both together.
- Different platforms support different hook events. Do not directly copy another platform's settings.
- Hooks should read project-local `.trellis/`; they should not depend on Trellis upstream source paths.
- Hook failures should produce visible errors so AI does not silently lose context.
