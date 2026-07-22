# Change Local Task Lifecycle

Task lifecycle includes creation, start, context configuration, finish, archive, parent/child tasks, and lifecycle hooks. The default customization targets are `.trellis/tasks/`, `.trellis/config.yaml`, and `.trellis/scripts/`.

## Read These Files First

1. `.trellis/workflow.md`
2. `.trellis/config.yaml`
3. `.trellis/scripts/task.py`
4. `.trellis/scripts/common/task_store.py`
5. `.trellis/scripts/common/task_utils.py`
6. The current task's `.trellis/tasks/<task>/task.json`

## Common Needs And Edit Points

| Need | Edit point |
| --- | --- |
| Automatically sync an external system after task creation | `hooks.after_create` in `.trellis/config.yaml`. |
| Automatically update status after task start | `hooks.after_start` in `.trellis/config.yaml`. |
| Run a script after task finish | `hooks.after_finish` in `.trellis/config.yaml`. |
| Clean external resources after archive | `hooks.after_archive` in `.trellis/config.yaml`. |
| Change default task fields | `.trellis/scripts/common/task_store.py`. |
| Change task parsing/search | `.trellis/scripts/common/task_utils.py`. |
| Change active task behavior | `.trellis/scripts/common/active_task.py`. |

## lifecycle hooks

`.trellis/config.yaml` supports:

```yaml
hooks:
  after_create:
    - "python .trellis/scripts/hooks/my_sync.py create"
  after_start:
    - "python .trellis/scripts/hooks/my_sync.py start"
  after_finish:
    - "python .trellis/scripts/hooks/my_sync.py finish"
  after_archive:
    - "python .trellis/scripts/hooks/my_sync.py archive"
```

Hook commands receive the `TASK_JSON_PATH` environment variable, pointing to the current task's `task.json`. Hook failures should usually warn, but not block the main task operation.

## Change Task Fields

If the user wants to add project-local fields, prefer putting them under `meta` in `task.json` to avoid breaking existing scripts' assumptions about standard fields.

Example:

```json
"meta": {
  "linearIssue": "ENG-123",
  "risk": "high"
}
```

If standard fields really need to change, inspect every local script that reads `task.json`.

## Change Active Task

Active task is session-level state stored in `.trellis/.runtime/sessions/`. Do not fall back to a global `.current-task` model. If the user wants to change active task behavior, edit:

- `.trellis/scripts/common/active_task.py`
- platform hooks or shell session bridges
- active task descriptions in `.trellis/workflow.md`

### `task.py create` Sets the Active Pointer

`cmd_create` in `.trellis/scripts/common/task_store.py` calls `set_active_task` best-effort right after writing the new task directory. The behavior:

- When the calling shell carries session identity (`TRELLIS_CONTEXT_ID` env var, or any platform-specific session env that `resolve_context_key` recognizes — see `active_task.py:_ENV_SESSION_KEYS`), the per-session pointer at `.trellis/.runtime/sessions/<context_key>.json` is rewritten to point at the new task. The task's `status=planning` and `[workflow-state:planning]` fires on the very next `UserPromptSubmit`.
- When session identity is unavailable (raw CLI invocation outside an AI session, or a platform that doesn't propagate identity to shell), the task directory is still created and `status=planning` is still written, but the active pointer is left untouched. The user can attach the task later with `task.py start <dir>` once they're back in an AI session.

This makes `[workflow-state:planning]` the live breadcrumb during the brainstorm and JSONL curation work that follows `task.py create`. The pre-R7 behavior left the breadcrumb stuck on `no_task` until `task.py start`, so the planning block was effectively dead text.

If you fork `task.py` to add a new creation path (e.g. an external import that bypasses `cmd_create`), audit whether your path also calls `set_active_task`. Without that call, your created tasks will not surface as active. The full status writer table is in `.trellis/spec/cli/backend/workflow-state-contract.md`.

## Modification Steps

1. Confirm the current task with `python ./.trellis/scripts/task.py current --source`.
2. Read the current task's `task.json` and confirm status and fields.
3. For configuration needs, edit `.trellis/config.yaml` first.
4. For script behavior needs, then edit `.trellis/scripts/`.
5. If the AI flow changed, synchronize `.trellis/workflow.md`.

## Do Not

- Do not directly edit `.trellis/.runtime/sessions/` to "fix" business state.
- Do not hard-code project-private fields into scripts; prefer `meta`.
- Do not default to asking the user to fork Trellis CLI.
