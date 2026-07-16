#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "AGENTS.md"
CLAUDE = ROOT / "CLAUDE.md"
COPILOT = ROOT / ".github" / "copilot-instructions.md"
INSTRUCTIONS_DIR = ROOT / ".github" / "instructions"
REPO_SKILLS_DIR = ROOT / ".agents" / "skills"
CLAUDE_SKILLS = ROOT / ".claude" / "skills"

REQUIRED_INSTRUCTION_FILES = {
    "backend.instructions.md",
    "client.instructions.md",
    "governance.instructions.md",
}

REQUIRED_SKILLS = {
    "analyze-issue",
    "analyze-pr",
    "fix-issue",
}

REQUIRED_GITIGNORE_SNIPPETS = (
    ".claude/*",
    "!.claude/skills",
)


def fail(message: str) -> None:
    print(f"[ai-assets] ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def ensure_file_exists(path: Path, description: str) -> None:
    if not path.exists():
        fail(f"{description} is missing: {path.relative_to(ROOT)}")


def ensure_symlink(path: Path, target: Path, description: str) -> None:
    if not path.is_symlink():
        fail(f"{description} must be a symlink: {path.relative_to(ROOT)}")

    actual = path.readlink()
    if actual != target:
        fail(
            f"{path.relative_to(ROOT)} must point to {target}, "
            f"found: {actual}"
        )


def ensure_instruction_entrypoints() -> None:
    ensure_file_exists(AGENTS, "canonical AGENTS.md")
    agents_content = AGENTS.read_text(encoding="utf-8")
    for fragment in (".agents/skills/", ".claude/skills", ".codex/reviews/"):
        if fragment not in agents_content:
            fail(f"AGENTS.md is missing required AI asset text: {fragment!r}")

    ensure_symlink(CLAUDE, Path("AGENTS.md"), "Claude compatibility entry")
    ensure_symlink(
        CLAUDE_SKILLS,
        Path("../.agents/skills"),
        "Claude Skill compatibility entry",
    )


def ensure_copilot_entry() -> None:
    ensure_file_exists(COPILOT, "repository Copilot instructions")
    content = COPILOT.read_text(encoding="utf-8")
    required_fragments = (
        "Canonical source:",
        "AGENTS.md",
        "CLAUDE.md",
        ".agents/skills/",
        ".claude/skills",
    )
    for fragment in required_fragments:
        if fragment not in content:
            fail(
                ".github/copilot-instructions.md is missing required text: "
                f"{fragment!r}"
            )


def ensure_instruction_files() -> None:
    ensure_file_exists(INSTRUCTIONS_DIR, "instructions directory")
    actual = {path.name for path in INSTRUCTIONS_DIR.glob("*.instructions.md")}
    missing = REQUIRED_INSTRUCTION_FILES - actual
    if missing:
        fail(f"missing instruction files: {', '.join(sorted(missing))}")

    governance = (INSTRUCTIONS_DIR / "governance.instructions.md").read_text(
        encoding="utf-8"
    )
    for fragment in (".agents/skills/**", ".claude/skills"):
        if fragment not in governance:
            fail(
                "governance.instructions.md is missing required Skill text: "
                f"{fragment!r}"
            )


def ensure_skill_files() -> None:
    ensure_file_exists(REPO_SKILLS_DIR, "repository Skills directory")
    if REPO_SKILLS_DIR.is_symlink():
        fail(".agents/skills must be the real repository Skill source")

    for skill_name in sorted(REQUIRED_SKILLS):
        skill_dir = REPO_SKILLS_DIR / skill_name
        skill_file = skill_dir / "SKILL.md"
        metadata_file = skill_dir / "agents" / "openai.yaml"
        ensure_file_exists(skill_file, f"{skill_name} instructions")
        ensure_file_exists(metadata_file, f"{skill_name} UI metadata")

        content = skill_file.read_text(encoding="utf-8")
        if not content.startswith("---\n"):
            fail(f"{skill_file.relative_to(ROOT)} is missing YAML frontmatter")
        if f"name: {skill_name}\n" not in content:
            fail(
                f"{skill_file.relative_to(ROOT)} must declare "
                f"name: {skill_name}"
            )
        if "description:" not in content:
            fail(f"{skill_file.relative_to(ROOT)} is missing a description")
        if "AGENTS.md" not in content:
            fail(
                f"{skill_file.relative_to(ROOT)} must reference "
                "AGENTS.md as the rule source"
            )

        metadata = metadata_file.read_text(encoding="utf-8")
        for field in ("display_name:", "short_description:", "default_prompt:"):
            if field not in metadata:
                fail(
                    f"{metadata_file.relative_to(ROOT)} is missing "
                    f"{field.removesuffix(':')}"
                )
        prompt_token = "$" + skill_name
        if prompt_token not in metadata:
            fail(
                f"{metadata_file.relative_to(ROOT)} must provide a "
                f"default prompt containing {prompt_token}"
            )


def ensure_no_parallel_skill_roots() -> None:
    parallel_roots = (
        ROOT / "skills",
        ROOT / ".codex" / "skills",
    )
    for path in parallel_roots:
        if path.exists():
            fail(
                "parallel repository Skill tree is not allowed: "
                f"{path.relative_to(ROOT)}"
            )


def ensure_gitignore_rules() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for snippet in REQUIRED_GITIGNORE_SNIPPETS:
        if snippet not in gitignore:
            fail(f".gitignore is missing required AI asset rule: {snippet}")


def main() -> None:
    ensure_instruction_entrypoints()
    ensure_copilot_entry()
    ensure_instruction_files()
    ensure_skill_files()
    ensure_no_parallel_skill_roots()
    ensure_gitignore_rules()
    print("[ai-assets] OK")


if __name__ == "__main__":
    main()
