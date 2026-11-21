# -*- coding: utf-8 -*-
"""Regression tests for scripts/check_ai_assets.py."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_ai_assets.py"
SPEC = importlib.util.spec_from_file_location("check_ai_assets_script", SCRIPT_PATH)
assert SPEC and SPEC.loader
check_ai_assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_ai_assets)


def test_ensure_symlink_target_rejects_windows_text_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_ai_assets, "ROOT", tmp_path)
    stub = tmp_path / ".claude" / "skills"
    stub.parent.mkdir(parents=True)
    stub.write_text("../.agents/skills", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        check_ai_assets.ensure_symlink_target(stub, "../.agents/skills", ".claude/skills")
    assert exc_info.value.code == 1


def test_materialized_claude_skills_compatibility_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_ai_assets, "ROOT", tmp_path)
    check_ai_assets.SKILLS_DIR = tmp_path / ".agents" / "skills"
    check_ai_assets.CLAUDE_SKILLS_LINK = tmp_path / ".claude" / "skills"
    for skill_name in check_ai_assets.REQUIRED_SKILLS:
        canonical = check_ai_assets.SKILLS_DIR / skill_name / "SKILL.md"
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text(skill_name, encoding="utf-8")
        compatibility = check_ai_assets.CLAUDE_SKILLS_LINK / skill_name / "SKILL.md"
        compatibility.parent.mkdir(parents=True, exist_ok=True)
        compatibility.write_text(skill_name, encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")
    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")

    check_ai_assets.ensure_symlinks()


def test_ensure_gitignore_rules_detects_ignored_tracked_agents_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    for skill_name in check_ai_assets.REQUIRED_SKILLS:
        skill = tmp_path / ".agents" / "skills" / skill_name / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(f"---\nname: {skill_name}\ndescription: test\n---\nAGENTS.md\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".claude/*\n!.claude/skills\n.reviews/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".agents", ".gitignore"], cwd=tmp_path, check=True)

    monkeypatch.setattr(check_ai_assets, "ROOT", tmp_path)
    check_ai_assets.ensure_gitignore_rules()

    # Even though SKILL.md is already tracked, adding `.agents/` to .gitignore must fail.
    (tmp_path / ".gitignore").write_text(".claude/*\n!.claude/skills\n.reviews/\n.agents/\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        check_ai_assets.ensure_gitignore_rules()
    assert exc_info.value.code == 1
