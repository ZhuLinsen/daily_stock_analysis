# -*- coding: utf-8 -*-
"""Regression checks for desktop installer configuration."""

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_DIR = REPO_ROOT / "apps" / "dsa-desktop"


def test_windows_nsis_build_allows_custom_install_directory() -> None:
    package_json = json.loads((DESKTOP_DIR / "package.json").read_text(encoding="utf-8"))
    nsis = package_json.get("build", {}).get("nsis", {})

    assert nsis.get("oneClick") is False
    assert nsis.get("allowToChangeInstallationDirectory") is True
    assert nsis.get("allowElevation") is False
    assert nsis.get("include") == "installer.nsh"


def test_installer_blocks_system_protected_directories() -> None:
    installer_script = (DESKTOP_DIR / "installer.nsh").read_text(encoding="utf-8")

    assert "Function .onVerifyInstDir" in installer_script
    assert "$PROGRAMFILES" in installer_script
    assert "$PROGRAMFILES64" in installer_script
    assert "$PROGRAMFILES32" in installer_script
    assert "$WINDIR" in installer_script
    assert "Abort" in installer_script


def test_old_uninstaller_retry_quotes_install_location_parameter() -> None:
    installer_script = (DESKTOP_DIR / "installer.nsh").read_text(encoding="utf-8")

    assert '"_?=$R8"' in installer_script
    assert "Retrying old uninstaller with quoted _? installation directory." in installer_script


def test_windows_auto_updater_reuses_current_install_directory() -> None:
    main_js = (DESKTOP_DIR / "main.js").read_text(encoding="utf-8")

    assert "function quoteNsisDirectoryArgument" in main_js
    assert "const installDirectory = path.dirname(app.getPath('exe'));" in main_js
    assert "updater.installDirectory = quoteNsisDirectoryArgument(installDirectory);" in main_js
