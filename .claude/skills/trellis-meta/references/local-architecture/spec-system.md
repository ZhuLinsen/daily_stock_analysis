# Local Spec System

`.trellis/spec/` is the user's project-specific engineering spec library. Trellis is not about making AI memorize conventions; it injects relevant specs or requires the AI to read them at the right time.

## Directory Model

A common single-repository structure:

```text
.trellis/spec/
├── backend/
│   ├── index.md
│   └── ...
├── frontend/
│   ├── index.md
│   └── ...
└── guides/
    ├── index.md
    └── ...
```

A common monorepo structure:

```text
.trellis/spec/
├── cli/
│   ├── backend/
│   │   ├── index.md
│   │   └── ...
│   └── unit-test/
│       ├── index.md
│       └── ...
├── docs-site/
│   └── docs/
│       ├── index.md
│       └── ...
└── guides/
    ├── index.md
    └── ...
```

`index.md` is the entry point for each layer. It should list the Pre-Development Checklist and Quality Check. Specific guidelines live in other Markdown files in the same directory.

## Package Configuration

`.trellis/config.yaml` can declare packages:

```yaml
packages:
  cli:
    path: packages/cli
  docs-site:
    path: docs-site
    type: submodule
default_package: cli
```

The AI can run:

```bash
python ./.trellis/scripts/get_context.py --mode packages
```

This command lists packages and spec layers for the current project. Use this output as the reference when configuring context JSONL.

## How Specs Enter Tasks

Before a task enters implementation, planning may write relevant specs into `implement.jsonl` / `check.jsonl` when the task needs spec or research context beyond the task artifacts:

```jsonl
{"file": ".trellis/spec/cli/backend/index.md", "reason": "CLI backend conventions"}
{"file": ".trellis/spec/cli/unit-test/conventions.md", "reason": "Test expectations"}
```

Sub-agents or platform preludes read these JSONL files and load the referenced specs. On platforms without sub-agent support, the AI should read the relevant specs directly according to the workflow.

## What Specs Should Contain

Specs should contain executable engineering conventions for the project, not generic best practices:

- Where files should live.
- How error handling should be expressed.
- Input/output contracts for APIs, hooks, and commands.
- Patterns that are forbidden.
- Cases that require tests.
- Project-specific pitfalls and how to avoid them.

When the AI learns a new rule during implementation or debugging, it should update `.trellis/spec/` rather than only summarizing it in chat.

## Local Customization Points

| Need | Edit location |
| --- | --- |
| Add a new spec layer | `.trellis/spec/<package>/<layer>/index.md` and corresponding guideline files. |
| Change monorepo spec mapping | `packages` / `default_package` / `spec_scope` in `.trellis/config.yaml`. |
| Change which specs AI reads before implementation | The task's `implement.jsonl`. |
| Change which specs AI reads during checking | The task's `check.jsonl`. |
| Change when specs should be updated | Phase 3.3 in `.trellis/workflow.md` and the `trellis-update-spec` skill. |

## Boundaries

`.trellis/spec/` is the user's project specification, not a permanent copy of Trellis built-in templates. The AI should encourage the user to update it according to the actual project code instead of treating Trellis default templates as immutable documents.
