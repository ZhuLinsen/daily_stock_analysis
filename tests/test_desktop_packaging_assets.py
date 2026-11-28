# -*- coding: utf-8 -*-
"""Static contracts for third-party data bundled in desktop backends."""

from __future__ import annotations

import unittest
from pathlib import Path


class DesktopPackagingAssetsTestCase(unittest.TestCase):
    """Keep Windows and macOS PyInstaller package-data rules aligned."""

    repo_root = Path(__file__).resolve().parent.parent

    def test_optional_litellm_stack_is_excluded_from_core_and_desktop_packaging(self) -> None:
        requirements_path = self.repo_root / "requirements.txt"
        optional_req_path = self.repo_root / "requirements-litellm.txt"
        requirements = requirements_path.read_text(encoding="utf-8")
        optional_requirements = optional_req_path.read_text(encoding="utf-8")
        main = (self.repo_root / "main.py").read_text(encoding="utf-8")
        macos_script = (self.repo_root / "scripts" / "build-backend-macos.sh").read_text(
            encoding="utf-8"
        )
        windows_script = (self.repo_root / "scripts" / "build-backend.ps1").read_text(
            encoding="utf-8"
        )

        # Optional LiteLLM stack lives strictly in ASCII-clean requirements-litellm.txt.
        optional_req_path.read_bytes().decode("ascii")
        core_pkg_lines = [
            line.split("#", 1)[0].strip().lower()
            for line in requirements.splitlines()
            if line.split("#", 1)[0].strip()
        ]
        for excluded in ("litellm", "orjson", "openai"):
            self.assertFalse(
                any(
                    line == excluded
                    or line.startswith(f"{excluded}>")
                    or line.startswith(f"{excluded}<")
                    or line.startswith(f"{excluded}=")
                    or line.startswith(f"{excluded}[")
                    or line.startswith(f"{excluded};")
                    for line in core_pkg_lines
                ),
                f"{excluded} must not be declared in core requirements.txt",
            )
        # tiktoken<0.12 remains pinned in requirements.txt for tavily-python runtime (#537).
        self.assertIn("tiktoken>=0.8.0,<0.12.0", requirements)

        self.assertIn("orjson>=3.10,<4", optional_requirements)
        self.assertIn("litellm>=1.80.10", optional_requirements)
        self.assertIn("tiktoken>=0.8.0,<0.12.0", optional_requirements)
        self.assertIn("openai>=1.0.0", optional_requirements)
        self.assertIn("google-auth>=2.0.0", optional_requirements)

        for script_text in (macos_script, windows_script):
            self.assertNotIn("orjson", script_text)
            self.assertNotIn("litellm", script_text)
            self.assertIn("tiktoken", script_text)
            self.assertIn("tiktoken_ext.openai_public", script_text)

        self.assertIn('DSA_PACKAGED_IMPORT_PROBE="${module}"', macos_script)
        self.assertIn("$env:DSA_PACKAGED_IMPORT_PROBE = $module", windows_script)
        self.assertIn('importlib.import_module(_packaged_import_probe)', main)

    def test_scripts_collect_and_verify_akshare_calendar_data(self) -> None:
        macos_script = (self.repo_root / "scripts" / "build-backend-macos.sh").read_text(
            encoding="utf-8"
        )
        windows_script = (self.repo_root / "scripts" / "build-backend.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("--collect-data akshare", macos_script)
        self.assertIn("'--collect-data', 'akshare'", windows_script)
        self.assertIn("_internal/akshare/file_fold/calendar.json", macos_script)
        self.assertIn("_internal\\akshare\\file_fold\\calendar.json", windows_script)


if __name__ == "__main__":
    unittest.main()
