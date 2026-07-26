# -*- coding: utf-8 -*-
"""Validation tests for backend packaging scripts."""

import json
import os
import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _bash_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name != "nt":
        return str(resolved)
    drive = resolved.drive.rstrip(":").lower()
    relative = resolved.relative_to(resolved.anchor).as_posix()
    return f"/mnt/{drive}/{relative}"


def test_windows_backend_build_script_collects_alphasift_adapter() -> None:
    script = _read_text(REPO_ROOT / "scripts" / "build-backend.ps1")
    main_py = _read_text(REPO_ROOT / "main.py")

    assert "Checking AlphaSift adapter availability" in script
    assert "import alphasift.dsa_adapter" in script
    assert "--collect-all" in script
    assert "alphasift.dsa_adapter" in script
    assert "hiddenImports" in script
    assert "Verifying packaged runtime imports" in script
    assert "DSA_PACKAGED_IMPORT_PROBE" in script
    assert "Start-Process -FilePath $packagedEntry -Wait -PassThru" in script
    assert "$probeProcess.ExitCode" in script
    assert "& $packagedEntry" not in script
    assert "Packaged backend cannot import $module" in script
    assert "DSA_PACKAGED_IMPORT_PROBE" in main_py
    assert "importlib.import_module(_packaged_import_probe)" in main_py


def test_macos_backend_build_script_collects_alphasift_adapter() -> None:
    script = _read_text(REPO_ROOT / "scripts" / "build-backend-macos.sh")
    main_py = _read_text(REPO_ROOT / "main.py")

    assert "Checking AlphaSift adapter availability..." in script
    assert "import alphasift.dsa_adapter" in script
    assert "--collect-all" in script
    assert "cmd+=(\"--collect-all\" \"alphasift\")" in script
    assert "packaged_entry=\"${packaged_root}/stock_analysis\"" in script
    assert "--help" in script
    assert 'DSA_PACKAGED_IMPORT_PROBE="${module}"' in script
    assert "dsa-packaged-import.log" in script
    assert "PathFinder.find_spec(" not in script
    assert "zipfile" not in script
    assert 'normalized.startswith("alphasift/dsa_adapter.")' not in script
    assert "DSA_PACKAGED_IMPORT_PROBE" in main_py
    assert "importlib.import_module(_packaged_import_probe)" in main_py


def test_macos_unsigned_packaging_contract_is_explicit() -> None:
    package = json.loads(
        _read_text(REPO_ROOT / "apps" / "dsa-desktop" / "package.json")
    )
    after_pack_hook = _read_text(
        REPO_ROOT / "apps" / "dsa-desktop" / "scripts" / "afterPackMacos.js"
    )
    backend_script = _read_text(REPO_ROOT / "scripts" / "build-backend-macos.sh")
    desktop_script = _read_text(REPO_ROOT / "scripts" / "build-desktop-macos.sh")
    workflow = _read_text(REPO_ROOT / ".github" / "workflows" / "ci.yml")

    assert package["build"]["mac"]["identity"] is None
    assert package["build"]["mac"]["hardenedRuntime"] is False
    assert package["build"]["afterPack"] == "scripts/afterPackMacos.js"
    assert "context.electronPlatformName !== 'darwin'" in after_pack_hook
    assert "'macos-signature-audit.sh'" in after_pack_hook
    assert "execFileSync('bash', [auditScript, 'normalize', appPath]" in after_pack_hook
    normalize_call = (
        'bash "${SCRIPT_DIR}/macos-signature-audit.sh" normalize "${packaged_root}"'
    )
    assert normalize_call in backend_script
    assert backend_script.index(normalize_call) < backend_script.index(
        '"${packaged_entry}" --help'
    )
    assert 'bash "${SCRIPT_DIR}/macos-signature-audit.sh" check "${app_path}"' in (
        desktop_script
    )
    assert "verify_unsigned_dmg" in desktop_script
    assert "code has no resources but signature indicates they must be present" in (
        desktop_script
    )
    assert "- 'scripts/macos-signature-audit.sh'" in workflow
    assert "run: bash scripts/build-backend-macos.sh" in workflow
    assert "run: bash scripts/build-desktop-macos.sh" in workflow


def _write_fake_macos_signature_tools(fake_bin: Path) -> None:
    fake_bin.mkdir()
    file_tool = fake_bin / "file"
    file_tool.write_text(
        "#!/usr/bin/env bash\nprintf 'Mach-O 64-bit executable\\n'\n",
        encoding="utf-8",
        newline="\n",
    )
    codesign_tool = fake_bin / "codesign"
    codesign_tool.write_text(
        """#!/usr/bin/env bash
candidate="${@: -1}"
marker="${candidate}.removed"
case "$1" in
  -d)
    if [[ -f "${marker}" ]] || [[ "${candidate}" == *"unsigned.bin" ]]; then
      printf 'code object is not signed at all\\n' >&2
      exit 1
    fi
    printf 'Authority=adhoc\\n' >&2
    ;;
  --verify)
    if [[ "${candidate}" == *"broken.bin" ]] && [[ ! -f "${marker}" ]]; then
      printf 'broken signature\\n' >&2
      exit 1
    fi
    ;;
  --remove-signature)
    : > "${marker}"
    ;;
esac
""",
        encoding="utf-8",
        newline="\n",
    )
    file_tool.chmod(0o755)
    codesign_tool.chmod(0o755)


def test_macos_signature_audit_normalizes_invalid_signatures(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    _write_fake_macos_signature_tools(fake_bin)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    broken = artifact / "broken.bin"
    broken.write_text("broken", encoding="utf-8")
    (artifact / "unsigned.bin").write_text("unsigned", encoding="utf-8")

    result = subprocess.run(
        [
            "bash",
            "-c",
            'PATH={fake_bin}:"$PATH"; export PATH; bash {script} normalize {artifact}'.format(
                fake_bin=shlex.quote(_bash_path(fake_bin)),
                script=shlex.quote(
                    _bash_path(REPO_ROOT / "scripts" / "macos-signature-audit.sh")
                ),
                artifact=shlex.quote(_bash_path(artifact)),
            ),
        ],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (artifact / "broken.bin.removed").is_file()
    assert "removed=1" in result.stdout


def test_macos_signature_audit_rejects_invalid_signatures(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    _write_fake_macos_signature_tools(fake_bin)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    broken = artifact / "broken.bin"
    broken.write_text("broken", encoding="utf-8")

    result = subprocess.run(
        [
            "bash",
            "-c",
            'PATH={fake_bin}:"$PATH"; export PATH; bash {script} check {artifact}'.format(
                fake_bin=shlex.quote(_bash_path(fake_bin)),
                script=shlex.quote(
                    _bash_path(REPO_ROOT / "scripts" / "macos-signature-audit.sh")
                ),
                artifact=shlex.quote(_bash_path(artifact)),
            ),
        ],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert not (artifact / "broken.bin.removed").exists()
    assert "invalid signature" in result.stderr
