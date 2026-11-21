#!/usr/bin/env python3

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "AGENTS.md"
CLAUDE = ROOT / "CLAUDE.md"
COPILOT = ROOT / ".github" / "copilot-instructions.md"
INSTRUCTIONS_DIR = ROOT / ".github" / "instructions"
SKILLS_DIR = ROOT / ".agents" / "skills"
CLAUDE_SKILLS_LINK = ROOT / ".claude" / "skills"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

REQUIRED_INSTRUCTION_FILES = {
    "backend.instructions.md",
    "client.instructions.md",
    "governance.instructions.md",
}

REQUIRED_SKILLS = (
    "analyze-issue",
    "analyze-pr",
    "fix-issue",
)

PRODUCT_SKILL_ROOT = ROOT / "SKILL.md"
PRODUCT_SKILL_PLUGIN = ROOT / "plugin" / "skills" / "stock_analyzer" / "SKILL.md"

REQUIRED_GITIGNORE_SNIPPETS = (
    ".claude/*",
    "!.claude/skills",
    ".reviews/",
)

REQUIRED_CI_JOBS_IN_AGENTS = (
    "ai-governance",
    "backend-gate",
    "docker-build",
    "web-gate",
    "desktop-futu-package-windows",
    "desktop-futu-package-macos",
)


def fail(message: str) -> None:
    print(f"[ai-assets] ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def ensure_file_exists(path: Path, description: str) -> None:
    if not path.exists():
        fail(f"{description} is missing: {path.relative_to(ROOT)}")


def _normalize_link_target(target: str) -> str:
    return target.strip().replace("\\", "/")


def ensure_symlink_target(path: Path, expected_target: str, description: str) -> None:
    if not path.exists() and not path.is_symlink():
        fail(f"{description} is missing: {path.relative_to(ROOT)}")

    if path.is_symlink():
        actual = _normalize_link_target(str(path.readlink()))
        if actual != expected_target:
            fail(
                f"{description} must point to {expected_target}, found: {actual}"
            )
        return

    if path.is_file():
        actual = _normalize_link_target(path.read_text(encoding="utf-8"))
        if actual == expected_target:
            fail(
                f"{description} was checked out as a plain text symlink stub "
                f"(likely Windows core.symlinks=false), so tools cannot traverse it. "
                f"Enable symlinks and re-checkout: "
                f"git config core.symlinks true && git checkout -- CLAUDE.md .claude/skills"
            )

    fail(f"{description} must be a symlink to {expected_target}")


def ensure_symlinks() -> None:
    ensure_file_exists(AGENTS, "canonical AGENTS.md")
    ensure_symlink_target(CLAUDE, "AGENTS.md", "CLAUDE.md")
    if CLAUDE_SKILLS_LINK.is_symlink():
        ensure_symlink_target(CLAUDE_SKILLS_LINK, "../.agents/skills", ".claude/skills")
    elif CLAUDE_SKILLS_LINK.is_dir():
        for skill_name in REQUIRED_SKILLS:
            compatibility_skill = CLAUDE_SKILLS_LINK / skill_name / "SKILL.md"
            canonical_skill = SKILLS_DIR / skill_name / "SKILL.md"
            if not canonical_skill.is_file():
                fail(f"canonical skill is missing: {canonical_skill.relative_to(ROOT)}")
            if not compatibility_skill.is_file():
                fail(
                    "skill not accessible via .claude/skills compatibility entry: "
                    f"{compatibility_skill.relative_to(ROOT)}"
                )
            if compatibility_skill.read_bytes() != canonical_skill.read_bytes():
                fail(f".claude/skills compatibility entry is stale: {compatibility_skill.relative_to(ROOT)}")
    else:
        fail(".claude/skills must be a symlink or a materialized compatibility directory")
    if not CLAUDE.is_file():
        fail("CLAUDE.md symlink does not resolve to a readable file")
    if not CLAUDE_SKILLS_LINK.is_dir():
        fail(".claude/skills compatibility entry does not resolve to a readable directory")
    for skill_name in REQUIRED_SKILLS:
        via_link = CLAUDE_SKILLS_LINK / skill_name / "SKILL.md"
        if not via_link.is_file():
            fail(
                f"skill not accessible via .claude/skills compatibility entry: "
                f"{via_link.relative_to(ROOT)}"
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
            fail(f".github/copilot-instructions.md is missing required text: {fragment!r}")


def ensure_instruction_files() -> None:
    ensure_file_exists(INSTRUCTIONS_DIR, "instructions directory")
    actual = {path.name for path in INSTRUCTIONS_DIR.glob("*.instructions.md")}
    missing = REQUIRED_INSTRUCTION_FILES - actual
    if missing:
        fail(f"missing instruction files: {', '.join(sorted(missing))}")


def _parse_frontmatter(content: str) -> dict[str, str]:
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", content, re.DOTALL)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def ensure_skill_files() -> None:
    ensure_file_exists(SKILLS_DIR, "Agents skills directory")
    for skill_name in REQUIRED_SKILLS:
        path = SKILLS_DIR / skill_name / "SKILL.md"
        if not path.is_file():
            fail(f"missing repository skill asset: {path.relative_to(ROOT)}")
        content = path.read_text(encoding="utf-8")
        frontmatter = _parse_frontmatter(content)
        if frontmatter.get("name") != skill_name:
            fail(
                f"{path.relative_to(ROOT)} frontmatter name must be {skill_name!r}, "
                f"found: {frontmatter.get('name')!r}"
            )
        if not frontmatter.get("description"):
            fail(f"{path.relative_to(ROOT)} frontmatter must include non-empty description")
        if "AGENTS.md" not in content:
            fail(f"{path.relative_to(ROOT)} must reference AGENTS.md as the rule source")


def ensure_product_skill_copies() -> None:
    """Root SKILL.md must be a plain-file copy of the plugin skill (not a symlink)."""
    ensure_file_exists(PRODUCT_SKILL_PLUGIN, "plugin stock_analyzer skill")
    if PRODUCT_SKILL_ROOT.is_symlink():
        fail(
            "SKILL.md must be a regular file (not a symlink) so core.symlinks=false "
            "checkouts and OpenClaw root-path imports still receive the skill body"
        )
    if not PRODUCT_SKILL_ROOT.is_file():
        fail(f"product skill entry is missing: {PRODUCT_SKILL_ROOT.relative_to(ROOT)}")
    root_bytes = PRODUCT_SKILL_ROOT.read_bytes()
    plugin_bytes = PRODUCT_SKILL_PLUGIN.read_bytes()
    if root_bytes != plugin_bytes:
        fail(
            "SKILL.md is out of sync with plugin/skills/stock_analyzer/SKILL.md; "
            "keep both as identical regular files"
        )


def ensure_gitignore_rules() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for snippet in REQUIRED_GITIGNORE_SNIPPETS:
        if snippet not in gitignore:
            fail(f".gitignore is missing required AI asset rule: {snippet}")
    for skill_name in REQUIRED_SKILLS:
        rel_skill = f".agents/skills/{skill_name}/SKILL.md"
        ignored = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", rel_skill],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if ignored.returncode == 0:
            fail(f"{rel_skill} must not be ignored by .gitignore")
        if ignored.returncode != 1:
            fail(
                f"git check-ignore failed for {rel_skill} "
                f"(exit={ignored.returncode})"
            )


def ensure_no_tracked_local_artifacts() -> None:
    result = subprocess.run(
        ["git", "ls-files", "--", ".claude", ".reviews"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    allowed = {".claude/skills"}
    for path in tracked:
        if path in allowed or path.startswith(".claude/skills/"):
            continue
        fail(f"tracked local AI artifact outside allowed symlink: {path}")


def ensure_no_stale_claude_reviews_refs() -> None:
    check_paths = [
        AGENTS,
        COPILOT,
        *INSTRUCTIONS_DIR.glob("*.instructions.md"),
        *(SKILLS_DIR / s / "SKILL.md" for s in REQUIRED_SKILLS),
        ROOT / "docs" / "CONTRIBUTING.md",
        ROOT / "docs" / "CONTRIBUTING_EN.md",
    ]
    for path in check_paths:
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        if ".claude/reviews" in content:
            fail(f"stale '.claude/reviews' reference found in {path.relative_to(ROOT)}")


def ensure_ci_table_alignment() -> None:
    ensure_file_exists(CI_WORKFLOW, "CI workflow")
    agents_text = AGENTS.read_text(encoding="utf-8")
    ci_text = CI_WORKFLOW.read_text(encoding="utf-8")
    for job_name in REQUIRED_CI_JOBS_IN_AGENTS:
        if job_name not in ci_text:
            fail(f"expected CI job {job_name!r} missing from .github/workflows/ci.yml")
        if job_name not in agents_text:
            fail(f"CI job {job_name!r} missing from AGENTS.md verification matrix")


def ensure_pr_review_skill_path_alignment() -> None:
    expected = ".agents/skills/analyze-pr/SKILL.md"
    legacy = ".claude/skills/analyze-pr/SKILL.md"
    for rel_path in (".github/workflows/pr-review.yml", ".github/scripts/ai_review.py"):
        path = ROOT / rel_path
        ensure_file_exists(path, rel_path)
        content = path.read_text(encoding="utf-8")
        if legacy in content:
            fail(f"stale {legacy!r} reference found in {rel_path}")
        if expected not in content:
            fail(f"{rel_path} must reference {expected!r}")


def main() -> None:
    ensure_symlinks()
    ensure_copilot_entry()
    ensure_instruction_files()
    ensure_skill_files()
    ensure_product_skill_copies()
    ensure_gitignore_rules()
    ensure_no_tracked_local_artifacts()
    ensure_no_stale_claude_reviews_refs()
    ensure_ci_table_alignment()
    ensure_pr_review_skill_path_alignment()
    print("[ai-assets] OK")


if __name__ == "__main__":
    main()
