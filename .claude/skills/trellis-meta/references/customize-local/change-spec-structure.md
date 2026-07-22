# Change Local Spec Structure

When the user wants to change the engineering conventions AI follows, add new spec layers, or adjust monorepo package mapping, edit `.trellis/spec/` and `.trellis/config.yaml`.

## Read These Files First

1. `.trellis/config.yaml`
2. `.trellis/spec/`
3. `.trellis/workflow.md` planning artifact guidance and Phase 3.3
4. Current task `implement.jsonl` / `check.jsonl`

## Common Needs

| Need | Edit location |
| --- | --- |
| Add backend/frontend/docs/test spec layer | `.trellis/spec/<layer>/` or `.trellis/spec/<package>/<layer>/` |
| Add shared thinking guides | `.trellis/spec/guides/` |
| Adjust monorepo packages | `packages` in `.trellis/config.yaml` |
| Change default package | `default_package` in `.trellis/config.yaml` |
| Control spec scanning scope | `spec_scope` in `.trellis/config.yaml` |
| Make a task read a new spec | Task `implement.jsonl` / `check.jsonl` |

## Add A Spec Layer

Single-repository example:

```text
.trellis/spec/security/
├── index.md
└── auth.md
```

Monorepo example:

```text
.trellis/spec/webapp/security/
├── index.md
└── auth.md
```

`index.md` should include:

- What code this layer applies to.
- Pre-Development Checklist.
- Quality Check.
- Links to specific guideline files.

## Update Context

Adding a spec does not mean every task automatically reads it. The current task must reference it in JSONL:

```bash
python ./.trellis/scripts/task.py add-context <task> implement ".trellis/spec/webapp/security/index.md" "Security conventions"
python ./.trellis/scripts/task.py add-context <task> check ".trellis/spec/webapp/security/index.md" "Security review rules"
```

## Change Monorepo Packages

Example `.trellis/config.yaml`:

```yaml
packages:
  webapp:
    path: apps/web
  api:
    path: apps/api
default_package: webapp
```

After editing, run:

```bash
python ./.trellis/scripts/get_context.py --mode packages
```

Use this output to confirm AI can see the correct packages and spec layers.

## Notes

- Specs are user project conventions and can be changed according to project needs.
- Do not put temporary task information into specs; put temporary information in the task.
- Do not put long-term conventions only in agents or commands; preserve them in specs.
- After changing spec structure, check whether existing task JSONL files still point to files that exist.
