# -*- coding: utf-8 -*-
"""Validation tests for backend packaging scripts."""

import ast
import json
import os
import runpy
import shlex
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest


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


def test_windows_backend_build_script_collects_builtin_screening_engine() -> None:
    script = _read_text(REPO_ROOT / "scripts" / "build-backend.ps1")
    main_py = _read_text(REPO_ROOT / "main.py")

    assert "Checking built-in screening engine availability" in script
    assert "import src.services.screening.pipeline" in script
    assert "--collect-all" in script
    assert "src.services.screening" in script
    assert "hiddenImports" in script
    assert "Verifying packaged runtime imports" in script
    assert "DSA_PACKAGED_IMPORT_PROBE" in script
    assert "Start-Process -FilePath $packagedEntry -Wait -PassThru" in script
    assert "$probeProcess.ExitCode" in script
    assert "& $packagedEntry" not in script
    assert "Packaged backend cannot import $module" in script
    assert "pyinstaller_runtime_compat.py" in script
    assert "--runtime-hook" in script
    assert "Verifying packaged screening strategies" in script
    assert "_internal\\src\\services\\screening\\strategies" in script
    assert "packagedScreeningStrategyCount" in script
    assert "DSA_PACKAGED_IMPORT_PROBE" in main_py
    assert "importlib.import_module(_packaged_import_probe)" in main_py


def test_macos_backend_build_script_collects_builtin_screening_engine() -> None:
    script = _read_text(REPO_ROOT / "scripts" / "build-backend-macos.sh")
    main_py = _read_text(REPO_ROOT / "main.py")

    assert "Checking built-in screening engine availability..." in script
    assert "import src.services.screening.pipeline" in script
    assert "--collect-all" in script
    assert 'cmd+=("--collect-all" "src.services.screening")' in script
    assert "packaged_entry=\"${packaged_root}/stock_analysis\"" in script
    assert "--help" in script
    assert 'DSA_PACKAGED_IMPORT_PROBE="${module}"' in script
    assert "dsa-packaged-import.log" in script
    assert '--runtime-hook "${SCRIPT_DIR}/pyinstaller_runtime_compat.py"' in script
    assert "PathFinder.find_spec(" not in script
    assert "zipfile" not in script
    assert "Verifying packaged screening strategies..." in script
    assert "_internal/src/services/screening/strategies" in script
    assert "packaged_screening_strategy_count" in script
    assert "DSA_PACKAGED_IMPORT_PROBE" in main_py
    assert "importlib.import_module(_packaged_import_probe)" in main_py


@pytest.mark.parametrize("filename", ["build-backend.ps1", "build-backend-macos.sh"])
def test_backend_build_collects_and_probes_miniracer(filename: str) -> None:
    script = _read_text(REPO_ROOT / "scripts" / filename)
    assert "--collect-all" in script
    assert "py_mini_racer" in script
    assert "MiniRacer().eval('1 + 1')" in script
    # The frozen executable must probe the runtime, not the source interpreter.
    if filename.endswith(".ps1"):
        assert "'orjson', 'py_mini_racer'" in script
        assert "-WindowStyle Hidden" in script
    else:
        assert "futu orjson py_mini_racer; do" in script


@pytest.mark.parametrize("filename", ["build-backend.ps1", "build-backend-macos.sh"])
def test_backend_build_collects_fxmacrodata_data_and_probes_tool_registry(filename: str) -> None:
    script = _read_text(REPO_ROOT / "scripts" / filename)
    if filename.endswith(".ps1"):
        assert "'--collect-data', 'fxmacrodata_public'" in script
        assert "'src.agent.factory'" in script
    else:
        assert "--collect-data fxmacrodata_public" in script
        assert 'DSA_PACKAGED_IMPORT_PROBE="src.agent.factory"' in script


def _run_packaged_probe(monkeypatch, module, probe_name="py_mini_racer") -> None:
    """Execute the actual early-exit block without importing the business stack."""
    import importlib

    tree = ast.parse(_read_text(REPO_ROOT / "main.py"))
    probe = next(
        node for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "_packaged_import_probe"
    )
    monkeypatch.setattr(importlib, "import_module", lambda name: module)
    exec(
        compile(ast.Module(body=[probe], type_ignores=[]), "main.py", "exec"),
        {"_packaged_import_probe": probe_name},
    )


@pytest.mark.parametrize("has_close", [True, False])
def test_packaged_miniracer_probe_executes_javascript(monkeypatch, has_close) -> None:
    calls = []
    engine = SimpleNamespace(eval=lambda code: calls.append(code) or 2)
    if has_close:
        engine.close = lambda: calls.append("close")
    with pytest.raises(SystemExit) as exc:
        _run_packaged_probe(monkeypatch, SimpleNamespace(MiniRacer=lambda: engine))
    assert exc.value.code == 0
    assert calls == (["1 + 1", "close"] if has_close else ["1 + 1"])


def test_packaged_miniracer_probe_rejects_importable_wrapper_without_runtime(
    monkeypatch, capsys,
) -> None:
    def missing_runtime():
        raise RuntimeError("Native library or dependency not available")

    with pytest.raises(SystemExit) as exc:
        _run_packaged_probe(monkeypatch, SimpleNamespace(MiniRacer=missing_runtime))
    assert exc.value.code == 1
    assert "Native library or dependency not available" in capsys.readouterr().err


def test_packaged_miniracer_probe_rejects_wrong_result_and_closes(monkeypatch) -> None:
    closed = []
    engine = SimpleNamespace(eval=lambda code: None, close=lambda: closed.append(True))
    with pytest.raises(SystemExit) as exc:
        _run_packaged_probe(monkeypatch, SimpleNamespace(MiniRacer=lambda: engine))
    assert exc.value.code == 1
    assert closed == [True]


def _factory_module(names):
    registry = SimpleNamespace(list_names=lambda: list(names))
    return SimpleNamespace(get_tool_registry=lambda: registry)


def test_packaged_tool_registry_probe_accepts_registry_with_macro_tools(monkeypatch) -> None:
    module = _factory_module(["get_realtime_quote", "fxmacrodata_data_catalogue"])
    with pytest.raises(SystemExit) as exc:
        _run_packaged_probe(monkeypatch, module, probe_name="src.agent.factory")
    assert exc.value.code == 0


def test_packaged_tool_registry_probe_rejects_registry_without_macro_tools(
    monkeypatch, capsys,
) -> None:
    module = _factory_module(["get_realtime_quote"])
    with pytest.raises(SystemExit) as exc:
        _run_packaged_probe(monkeypatch, module, probe_name="src.agent.factory")
    assert exc.value.code == 1
    assert "FXMacroData tools are missing" in capsys.readouterr().err


def test_pyinstaller_runtime_hook_disables_incompatible_nltk_guard(
    monkeypatch,
) -> None:
    monkeypatch.delenv("NLTK_DISABLE_IMPORT_SECURITY", raising=False)

    runpy.run_path(
        str(REPO_ROOT / "scripts" / "pyinstaller_runtime_compat.py"),
        run_name="__pyinstaller_runtime_compat__",
    )

    assert os.environ["NLTK_DISABLE_IMPORT_SECURITY"] == "1"


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
    assert "scripts/macos-signature-audit.sh" in workflow
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


def test_macos_pyinstaller_command_preserves_real_bash_argv() -> None:
    """Execute array construction: bash -n misses full-width parentheses."""
    script = _read_text(REPO_ROOT / "scripts" / "build-backend-macos.sh")
    construction = script[script.index("hidden_imports=("):script.index('echo "Running:')]
    result = subprocess.run(
        ["bash", "-c", 'set -euo pipefail\nROOT_DIR="$PWD"\n'
         'SCRIPT_DIR="$PWD/scripts"\nPYTHON_BIN="python with spaces"\n'
         + construction + '\nprintf "%s\\0" "${cmd[@]}"\n'],
        cwd=REPO_ROOT, capture_output=True, check=True,
    )
    argv = result.stdout.decode().split("\0")[:-1]
    assert argv[:3] == ["python with spaces", "-m", "PyInstaller"]
    assert argv[-1] == "main.py"
    assert argv.count("main.py") == 1
    assert "--hidden-import=uvicorn.lifespan.on" in argv
    assert not any("（" in arg or "）" in arg for arg in argv)
    data_paths = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "--add-data"]
    assert "src/services/screening/strategies:src/services/screening/strategies" in data_paths
