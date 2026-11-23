---
applyTo: "README.md,docs/**,AGENTS.md,CLAUDE.md,.github/**,.agents/**,.claude/skills,scripts/**,docker/**"
---

# Governance Instructions

- `AGENTS.md` is the canonical AI collaboration source; sync `CLAUDE.md`, `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`, `.agents/skills/**`, and `scripts/check_ai_assets.py` when governance contracts change, then run `python scripts/check_ai_assets.py`.
- Keep commands, file paths, workflow names, config keys, and release paths aligned with executable repository state.
- Root `SKILL.md` and `docs/openclaw-skill-integration.md` describe product/external integrations, not repository governance.
- Avoid widening CI/workflow permissions, secret exposure, or destructive automation without a clearly documented need; preserve opt-in auto-tag (`#patch`, `#minor`, `#major`).
- If only one language version of a bilingual doc is updated, state why the counterpart was not synchronized.
