# Local Task System

The Trellis task system is stored entirely under `.trellis/tasks/` in the user project. Each task is a directory containing requirements, context, research, state, and relationship information.

## Task Directory Structure

```text
.trellis/tasks/
├── 04-28-example-task/
│   ├── task.json
│   ├── prd.md
│   ├── design.md
│   ├── implement.md
│   ├── implement.jsonl
│   ├── check.jsonl
│   └── research/
└── archive/
    └── 2026-04/
```

| File | Purpose |
| --- | --- |
| `task.json` | Task metadata: status, assignee, priority, branch, parent/child tasks, and similar fields. |
| `prd.md` | Requirements, constraints, and acceptance criteria. Lightweight tasks may be PRD-only. |
| `design.md` | Technical design for complex tasks: boundaries, contracts, data flow, compatibility, tradeoffs. |
| `implement.md` | Execution plan for complex tasks: ordered checklist, validation commands, review gates, rollback points. |
| `implement.jsonl` | List of spec/research files the implement agent must read first. |
| `check.jsonl` | List of spec/research files the check agent must read first. |
| `research/` | Research artifacts. Complex findings should not live only in chat. |

## `task.json`

`task.json` records task status and metadata. Common fields:

| Field | Meaning |
| --- | --- |
| `id` / `name` / `title` | Task identity and title. |
| `status` | Status such as `planning`, `in_progress`, `review`, or `completed`. |
| `priority` | `P0`, `P1`, `P2`, `P3`. |
| `creator` / `assignee` | Creator and assignee. |
| `package` | Target package in a monorepo; may be empty. |
| `branch` / `base_branch` | Working branch and PR target branch. |
| `children` / `parent` | Parent/child task relationships. |
| `commit` / `pr_url` | Commit and PR information after completion. |
| `meta` | Extension fields. |

## Parent / Child Task Trees

Parent/child task relationships are for work structure. A parent task groups related deliverables under one source requirement set; it is not a dependency scheduler and does not replace the child task's own planning artifacts.

Use a parent task when a request has multiple independently verifiable deliverables. The parent owns:

- Source requirements and user-facing scope.
- The map of child tasks and their responsibility boundaries.
- Cross-child acceptance criteria and final integration review.

Use child tasks for deliverables that can move through planning, implementation, check, and archive independently. If one child depends on another, write that dependency in the child `prd.md` / `implement.md`; do not rely on tree position to imply ordering.

Create new children with:

```bash
python ./.trellis/scripts/task.py create "<child title>" --slug <child-slug> --parent <parent-dir>
```

Link or unlink existing tasks with:

```bash
python ./.trellis/scripts/task.py add-subtask <parent-dir> <child-dir>
python ./.trellis/scripts/task.py remove-subtask <parent-dir> <child-dir>
```

`children` on the parent is a historical list. When a child is archived, Trellis keeps that child name in the parent so progress like `[2/3 done]` remains meaningful after completed children move to `archive/`.

The AI should not treat phase numbers as task status. Task progress is mainly determined by `status`, artifact presence (`prd.md`, optional `design.md` / `implement.md`), whether JSONL context is configured for sub-agent mode, and the phase descriptions in `workflow.md`.

## Active Task

The user sees a "current task," but Trellis stores active task state per session.

```text
.trellis/.runtime/sessions/<context-key>.json
```

`task.py start` writes the task path into the runtime session file for the current session. `task.py current --source` shows the current task and where it came from. Different AI windows can point to different tasks without overwriting each other.

If the platform or shell environment has no stable session identity, `task.py start` may be unable to set the active task. The AI should read the error, inspect the platform hook/session environment, and not fall back to a shared global pointer.

## JSONL Context

`implement.jsonl` and `check.jsonl` are context manifests for sub-agents to read first. They do not replace `implement.md`; `implement.md` is the human-readable execution plan.

Format:

```jsonl
{"file": ".trellis/spec/cli/backend/index.md", "reason": "Backend conventions"}
{"file": ".trellis/tasks/04-28-example/research/api.md", "reason": "API research"}
```

Rules:

- Include spec and research files.
- Do not include code files that are about to be modified.
- Do not treat temporary conclusions in chat as the only context.
- Seed rows have no `file` field; they only prompt the AI to fill in real entries.

## Common Commands

```bash
python ./.trellis/scripts/task.py create "<title>" --slug <slug>
python ./.trellis/scripts/task.py start <task>
python ./.trellis/scripts/task.py current --source
python ./.trellis/scripts/task.py add-context <task> implement <file> <reason>
python ./.trellis/scripts/task.py validate <task>
python ./.trellis/scripts/task.py finish
python ./.trellis/scripts/task.py archive <task>
```

When modifying the task system, the AI should prefer script commands to maintain structure. Edit JSON/Markdown directly only when scripts do not cover the need.

## Local Customization Points

| Need | Edit location |
| --- | --- |
| Change the default task template | `.trellis/scripts/common/task_store.py` and task creation instructions. |
| Change status semantics | `.trellis/workflow.md`, workflow-state hook logic, and task usage conventions. |
| Add task lifecycle actions | `hooks.after_*` in `.trellis/config.yaml`. |
| Change context rules | Planning artifact guidance in `.trellis/workflow.md` and related platform agent/hook instructions. |
| Change archive policy | `.trellis/scripts/common/task_store.py` / `task_utils.py`. |

These are local files in the user project. Do not default to editing Trellis CLI source code unless the user wants to contribute upstream.
