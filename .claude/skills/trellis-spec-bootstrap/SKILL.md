---
name: trellis-spec-bootstrap
description: "Bootstrap project-specific Trellis coding specs with a platform-neutral single-agent workflow. Use when creating or refreshing .trellis/spec guidelines, analyzing a codebase with GitNexus, ABCoder, or source inspection, decomposing package/layer spec work, and writing real codebase-backed spec docs without placeholder text."
---

# Trellis Spec Bootstrap

Use this skill to create or refresh `.trellis/spec/` guidelines from the real codebase. One capable agent owns the full loop: analyze the repository, choose the spec boundaries, write the docs, and verify the result. The workflow does not depend on a specific host, CLI, or agent brand.

## Workflow

1. Confirm Trellis is initialized and inspect the current `.trellis/spec/` tree.
2. Analyze the repository architecture with the best available tools: GitNexus, ABCoder, language tooling, and direct source reads.
3. Decompose the spec work by package and layer only when that reflects the actual codebase.
4. Fill or reshape the spec files with concrete patterns, file paths, examples, and anti-patterns from the project.
5. Verify that the final specs are internally consistent and contain no template placeholders.

## Reference Routing

| Need | Read |
|------|------|
| Repository architecture analysis | [references/repository-analysis.md](references/repository-analysis.md) |
| Spec work decomposition and task planning | [references/spec-task-planning.md](references/spec-task-planning.md) |
| Writing high-signal Trellis spec files | [references/spec-writing.md](references/spec-writing.md) |
| GitNexus and ABCoder MCP setup | [references/mcp-setup.md](references/mcp-setup.md) |

## Operating Rules

- Treat templates as starting points, not contracts. Delete, rename, split, or add spec files when the repository calls for it.
- Prefer source-backed rules over generic advice. Every important recommendation should point at a real file or repeated local pattern.
- Keep execution single-owner by default. Optional helper agents are an implementation detail, not a requirement or user-visible dependency.
- Do not write platform-specific instructions unless the target project already standardizes on that platform.
- Do not leave placeholder text, empty headings, or copied boilerplate in `.trellis/spec/`.

## Done Criteria

- `.trellis/spec/` describes the project as it exists now.
- Each relevant package or layer has practical coding guidance with real examples.
- Non-applicable template sections are removed.
- `index.md` files match the final spec file set.
- Any required setup or analysis assumptions are documented in the relevant spec or task notes.
