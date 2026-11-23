# Repository Instructions

Canonical source: [`AGENTS.md`](../AGENTS.md). If any instruction here conflicts with `AGENTS.md`, follow `AGENTS.md`.

## Key Pointers

- Rules, directory boundaries, validation matrix, changelog/README boundaries, and merge blockers live in `AGENTS.md`.
- Claude compatibility entry: `CLAUDE.md` -> `AGENTS.md`; `.claude/skills/` contains copies of the repository skills for checkouts that cannot create symlinks.
- Repository collaboration skills live in `.agents/skills/` (`analyze-pr`, `analyze-issue`, `fix-issue`); keep them aligned with `AGENTS.md`.
- Path-specific guidance lives in `.github/instructions/*.instructions.md`.
- Local review artifacts default to chat output (optional local archive in `.reviews/`, gitignored).
- After changing AI governance assets, run `python scripts/check_ai_assets.py`.
