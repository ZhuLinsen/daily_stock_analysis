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


@pytest.mark.parametrize("filename", ["build-backend.ps1", "build-backend-macos.sh"])
def test_backend_build_collects_and_probes_fin_primitives(filename: str) -> None:
    script = _read_text(REPO_ROOT / "scripts" / filename)
    assert "import fin_primitives" in script
    assert "--collect-all" in script
    assert "fin_primitives" in script
    if filename.endswith(".ps1"):
        assert "'--collect-all', 'fin_primitives'" in script
        assert "'fin_primitives'" in script
    else:
        assert 'cmd+=("--collect-all" "fin_primitives")' in script
        assert 'DSA_PACKAGED_IMPORT_PROBE="fin_primitives"' in script


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


def test_macos_adhoc_packaging_contract_is_explicit() -> None:
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
    check_call = (
        'bash "${SCRIPT_DIR}/macos-signature-audit.sh" check "${packaged_root}"'
    )
    assert normalize_call in backend_script
    assert check_call in backend_script
    assert backend_script.index(normalize_call) < backend_script.index(check_call)
    assert backend_script.index(check_call) < backend_script.index(
        '"${packaged_entry}" --help'
    )
    assert 'bash "${SCRIPT_DIR}/macos-signature-audit.sh" check "${app_path}"' in (
        desktop_script
    )
    assert "verify_adhoc_signed_app" in desktop_script
    assert "verify_packaged_dmg" in desktop_script
    assert "verify_installed_dmg_app_launch" in desktop_script
    assert "unset GITHUB_ACTIONS" in desktop_script
    assert "DSA_SKIP_GUI_SMOKE" not in desktop_script
    assert "Signature=adhoc" in desktop_script
    assert "Authority=" in desktop_script
    assert "codesign --verify --deep --strict --verbose=4" in desktop_script
    assert "ELECTRON_RUN_AS_NODE=1" in desktop_script
    assert "Backend ready in " in desktop_script
    assert "Main UI loaded in " in desktop_script
    assert "Contents/Resources/backend/stock_analysis/stock_analysis" in desktop_script
    assert "code has no resources but signature indicates they must be present" in (
        desktop_script
    )
    for doc_name in ("FAQ.md", "FAQ_EN.md", "desktop-package.md"):
        doc_text = _read_text(REPO_ROOT / "docs" / doc_name)
        assert "Contents/Resources/backend" in doc_text
        assert '# find "/Applications/Daily Stock Analysis.app/Contents/Resources/backend"' not in doc_text
    assert "scripts/macos-signature-audit.sh" in workflow
    assert "scripts/build-desktop-macos.sh" in workflow
    assert "run: bash scripts/build-backend-macos.sh" in workflow
    assert "run: bash scripts/build-desktop-macos.sh" in workflow


def _write_fake_macos_signature_tools(fake_bin: Path, sign_log: Path) -> None:
    fake_bin.mkdir()
    file_tool = fake_bin / "file"
    file_tool.write_text(
        """#!/usr/bin/env bash
case "$(basename "${@: -1}")" in
  *.bin|*.dylib|*.so|Python|stock_analysis)
    printf 'Mach-O 64-bit executable arm64\\n'
    ;;
  *)
    printf 'ASCII text\\n'
    ;;
esac
""",
        encoding="utf-8",
        newline="\n",
    )
    codesign_tool = fake_bin / "codesign"
    codesign_tool.write_text(
        """#!/usr/bin/env bash
candidate="${@: -1}"
if [[ -d "${candidate}" ]]; then
  signed_marker="${candidate}/_CodeSignature/.signed"
else
  signed_marker="${candidate}.signed"
fi
has_adhoc_flag() {
  [[ -f "${signed_marker}" ]] || [[ "$(basename "${candidate}")" == valid* ]]
}
has_devid_flag() {
  [[ ! -f "${signed_marker}" ]] && [[ "$(basename "${candidate}")" == devid* ]]
}
has_verbose_flag() {
  for arg in "$@"; do
    case "${arg}" in
      -v|--verbose|--verbose=*|-dv*)
        return 0
        ;;
    esac
  done
  return 1
}
case "$1" in
  -d)
    if has_adhoc_flag || has_devid_flag || [[ "${candidate}" == *"broken"* ]]; then
      printf 'Executable=%s\\n' "${candidate}" >&2
      if has_verbose_flag "$@"; then
        if has_devid_flag; then
          printf 'Authority=Developer ID Application: Example Corp (TEAM123456)\\n' >&2
          printf 'TeamIdentifier=TEAM123456\\n' >&2
        else
          printf 'Signature=adhoc\\n' >&2
          printf 'TeamIdentifier=not set\\n' >&2
        fi
      fi
      exit 0
    fi
    printf 'code object is not signed at all\\n' >&2
    exit 1
    ;;
  --verify)
    if [[ "${candidate}" == *"broken"* ]] && [[ ! -f "${signed_marker}" ]]; then
      printf 'broken signature\\n' >&2
      exit 1
    fi
    if ! has_adhoc_flag && ! has_devid_flag; then
      printf 'code object is not signed at all\\n' >&2
      exit 1
    fi
    ;;
  --force)
    if [[ -d "${candidate}" ]] && [[ "${candidate}" == *.framework ]] && [[ ! -e "${candidate}/Versions/Current" ]] && [[ ! -f "${candidate}/Resources/Info.plist" ]] && [[ ! -f "${candidate}/Info.plist" ]]; then
      printf 'bundle format unrecognized, invalid, or unsuitable\\n' >&2
      exit 1
    fi
    if [[ -d "${candidate}" ]]; then
      mkdir -p "${candidate}/_CodeSignature"
    fi
    : > "${signed_marker}"
    printf '%s\\n' "${candidate}" >> """ + shlex.quote(_bash_path(sign_log)) + """
    ;;
esac
""",
        encoding="utf-8",
        newline="\n",
    )
    file_tool.chmod(0o755)
    codesign_tool.chmod(0o755)


def test_macos_signature_audit_normalizes_unsigned_and_invalid_inside_out(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    sign_log = tmp_path / "sign.log"
    _write_fake_macos_signature_tools(fake_bin, sign_log)

    app_dir = tmp_path / "Daily Stock Analysis.app"
    (app_dir / "Contents").mkdir(parents=True)
    (app_dir / "Contents" / "Info.plist").write_text("<plist/>", encoding="utf-8")

    fw_dir = app_dir / "Contents" / "Frameworks" / "Electron Framework.framework"
    (fw_dir / "Versions" / "A" / "Resources").mkdir(parents=True)
    (fw_dir / "Versions" / "A" / "Resources" / "Info.plist").write_text("<plist/>", encoding="utf-8")
    (fw_dir / "Versions" / "Current").symlink_to("A")
    (fw_dir / "Resources").symlink_to("Versions/Current/Resources")
    valid_dylib = fw_dir / "Versions" / "A" / "valid.dylib"
    valid_dylib.write_text("ok", encoding="utf-8")
    broken_dylib = fw_dir / "Versions" / "A" / "broken.dylib"
    broken_dylib.write_text("broken", encoding="utf-8")
    devid_dylib = fw_dir / "Versions" / "A" / "devid.dylib"
    devid_dylib.write_text("devid", encoding="utf-8")

    partial_py_fw = (
        app_dir / "Contents" / "Resources" / "backend" / "stock_analysis" / "_internal" / "Python.framework"
    )
    (partial_py_fw / "Versions" / "3.12").mkdir(parents=True)
    py_bin = partial_py_fw / "Versions" / "3.12" / "Python"
    py_bin.write_text("broken", encoding="utf-8")
    backend_bin = app_dir / "Contents" / "Resources" / "backend" / "stock_analysis" / "stock_analysis"
    backend_bin.write_text("unsigned", encoding="utf-8")

    script_path = _bash_path(REPO_ROOT / "scripts" / "macos-signature-audit.sh")
    app_arg = _bash_path(app_dir)
    fake_bin_arg = _bash_path(fake_bin)

    def _run_audit(mode: str, target_arg: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "bash",
                "-c",
                f'PATH={shlex.quote(fake_bin_arg)}:"$PATH"; export PATH; '
                f"bash {shlex.quote(script_path)} {shlex.quote(mode)} {shlex.quote(target_arg)}",
            ],
            cwd=REPO_ROOT,
            env=os.environ.copy(),
            check=False,
            capture_output=True,
            text=True,
        )

    normalize_res = _run_audit("normalize", app_arg)
    assert normalize_res.returncode == 0, normalize_res.stderr
    assert "resigned=6" in normalize_res.stdout

    signed_order = [line.strip() for line in sign_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(signed_order) == 6
    assert _bash_path(partial_py_fw) not in signed_order
    assert not any(entry.endswith("valid.dylib") for entry in signed_order)
    assert any(entry.endswith("devid.dylib") for entry in signed_order)
    assert signed_order[-1].endswith("Daily Stock Analysis.app")
    assert signed_order.index(_bash_path(broken_dylib)) < signed_order.index(_bash_path(fw_dir))
    assert signed_order.index(_bash_path(devid_dylib)) < signed_order.index(_bash_path(fw_dir))
    assert signed_order.index(_bash_path(py_bin)) < signed_order.index(_bash_path(app_dir))
    assert signed_order.index(_bash_path(backend_bin)) < signed_order.index(_bash_path(app_dir))

    check_res = _run_audit("check", app_arg)
    assert check_res.returncode == 0, check_res.stderr
    assert "checked=7, signed=7, resigned=0" in check_res.stdout


def test_macos_signature_audit_rejects_unsigned_and_invalid_in_check_mode(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    sign_log = tmp_path / "sign.log"
    _write_fake_macos_signature_tools(fake_bin, sign_log)
    script_path = _bash_path(REPO_ROOT / "scripts" / "macos-signature-audit.sh")
    fake_bin_arg = _bash_path(fake_bin)

    def _run_check(target_dir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "bash",
                "-c",
                f'PATH={shlex.quote(fake_bin_arg)}:"$PATH"; export PATH; '
                f"bash {shlex.quote(script_path)} check {shlex.quote(_bash_path(target_dir))}",
            ],
            cwd=REPO_ROOT,
            env=os.environ.copy(),
            check=False,
            capture_output=True,
            text=True,
        )

    broken_dir = tmp_path / "broken_artifact"
    broken_dir.mkdir()
    broken = broken_dir / "broken.bin"
    broken.write_text("broken", encoding="utf-8")

    res_broken = _run_check(broken_dir)
    assert res_broken.returncode != 0
    assert "invalid signature" in res_broken.stderr
    assert not (broken_dir / "broken.bin.signed").exists()

    unsigned_dir = tmp_path / "unsigned_artifact"
    unsigned_dir.mkdir()
    (unsigned_dir / "unsigned.bin").write_text("unsigned", encoding="utf-8")

    res_unsigned = _run_check(unsigned_dir)
    assert res_unsigned.returncode != 0
    assert "unsigned macOS artifact" in res_unsigned.stderr
    assert not sign_log.exists()

    devid_dir = tmp_path / "devid_artifact"
    devid_dir.mkdir()
    (devid_dir / "devid.dylib").write_text("devid", encoding="utf-8")

    res_devid = _run_check(devid_dir)
    assert res_devid.returncode != 0
    assert "non-adhoc signature" in res_devid.stderr
    assert not sign_log.exists()


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
