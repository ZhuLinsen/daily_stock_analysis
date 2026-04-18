---
applyTo: "main.py,server.py,src/**/*.py,data_provider/**/*.py,api/**/*.py,bot/**/*.py,tests/**/*.py"
---

# Backend Instructions

- Preserve current pipeline boundaries and reuse existing services, repositories, schemas, and fallback logic instead of creating parallel paths.
- Changes touching config, CLI flags, schedule semantics, API behavior, auth, or report payloads must sync `.env.example` and assess Web/Desktop compatibility.
- Changes in `data_provider/` must preserve provider priority, normalization behavior, timeout/retry expectations, and graceful degradation.
- Prefer `./scripts/ci_gate.sh` when feasible; otherwise run `python -m py_compile` on changed files plus the closest deterministic tests.
- Do not let a single provider, notification channel, or optional integration failure break the main analysis flow unless the requirement explicitly demands fail-fast behavior.
