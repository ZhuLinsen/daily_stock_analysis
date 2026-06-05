# -*- coding: utf-8 -*-
"""Validation tests for backend packaging scripts."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_windows_backend_build_script_collects_alphasift_adapter() -> None:
    script = _read_text(REPO_ROOT / "scripts" / "build-backend.ps1")

    assert "Checking AlphaSift adapter availability" in script
    assert "import alphasift.dsa_adapter" in script
    assert "--collect-all" in script
    assert "alphasift.dsa_adapter" in script
    assert "hiddenImports" in script


def test_macos_backend_build_script_collects_alphasift_adapter() -> None:
    script = _read_text(REPO_ROOT / "scripts" / "build-backend-macos.sh")

    assert "Checking AlphaSift adapter availability..." in script
    assert "import alphasift.dsa_adapter" in script
    assert "--collect-all" in script
    assert "cmd+=(\"--collect-all\" \"alphasift\")" in script
    assert "zipfile" in script
    assert 'normalized.startswith("alphasift/dsa_adapter.")' in script
    assert 'normalized.startswith("alphasift/dsa_adapter/")' in script
    assert 'normalized.endswith("alphasift/__init__.py")' not in script
    assert "packaged_entry=\"${packaged_root}/stock_analysis\"" in script
    assert "--help" in script
    assert "PathFinder.find_spec(" not in script
