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


def test_ensure_gitignore_rules_detects_ignored_tracked_agents_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    skill = tmp_path / ".agents" / "skills" / "analyze-pr" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: analyze-pr\ndescription: test\n---\nAGENTS.md\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".claude/*\n!.claude/skills\n.reviews/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".agents/skills/analyze-pr/SKILL.md", ".gitignore"], cwd=tmp_path, check=True)

    monkeypatch.setattr(check_ai_assets, "ROOT", tmp_path)
    check_ai_assets.ensure_gitignore_rules()

    # Even though SKILL.md is already tracked, adding `.agents/` to .gitignore must fail.
    (tmp_path / ".gitignore").write_text(".claude/*\n!.claude/skills\n.reviews/\n.agents/\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        check_ai_assets.ensure_gitignore_rules()
    assert exc_info.value.code == 1
