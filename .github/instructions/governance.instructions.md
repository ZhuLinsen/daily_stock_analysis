---
applyTo: "README.md,docs/**,AGENTS.md,CLAUDE.md,.github/**,.claude/skills/**,scripts/**,docker/**"
---

# Governance Instructions

- Keep commands, file paths, workflow names, config keys, release paths, and directory references aligned with the executable repository state.
- `AGENTS.md` is the canonical AI collaboration document; if its meaning changes, sync `CLAUDE.md`, `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`, and repository skills as needed.
- Root `SKILL.md` and `docs/openclaw-skill-integration.md` describe product or external integration behavior, not repository governance.
- Explain which pipeline, release path, deployment path, review automation, or governance asset is affected and what the rollback path is.
- Avoid widening permissions, secret exposure, or destructive automation without a clearly documented need.
- Preserve the repository's opt-in auto-tag behavior (`#patch`, `#minor`, `#major`) unless the change explicitly updates release policy.
- If only one language version of a document is updated, explain why the counterpart was not synchronized.
