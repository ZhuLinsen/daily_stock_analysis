from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install-macos.sh"


def _bash_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name != "nt":
        return str(resolved)
    drive = resolved.drive.rstrip(":").lower()
    relative = resolved.relative_to(resolved.anchor).as_posix()
    return f"/mnt/{drive}/{relative}"


def _write_exec(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _write_fake_macos_installer_env(
    fake_bin: Path,
    *,
    os_name: str = "Darwin",
    machine: str = "arm64",
    proc_translated: str = "0",
    latest_tag: str = "v3.36.0",
    dmg_payload: bytes = b"fake-dmg-content",
    sha_override: str | None = None,
    app_running: bool = False,
    trace_log: Path,
) -> tuple[str, str]:
    fake_bin.mkdir(parents=True, exist_ok=True)
    actual_sha = hashlib.sha256(dmg_payload).hexdigest()
    manifest_sha = sha_override if sha_override is not None else actual_sha

    _write_exec(
        fake_bin / "uname",
        f"""#!/usr/bin/env bash
case "${{1:-}}" in
  -s) printf '%s\\n' {shlex.quote(os_name)} ;;
  -m) printf '%s\\n' {shlex.quote(machine)} ;;
  *) printf '%s\\n' {shlex.quote(os_name)} ;;
esac
""",
    )

    _write_exec(
        fake_bin / "sysctl",
        f"""#!/usr/bin/env bash
if [[ "$*" == *"sysctl.proc_translated"* ]]; then
  printf '%s\\n' {shlex.quote(proc_translated)}
  exit 0
fi
exit 1
""",
    )

    payload_file = fake_bin / "_dmg_payload.bin"
    payload_file.write_bytes(dmg_payload)
    payload_arg = _bash_path(payload_file)
    trace_arg = _bash_path(trace_log)

    _write_exec(
        fake_bin / "curl",
        f"""#!/usr/bin/env bash
out=""
url=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o)
      out="$2"
      shift 2
      ;;
    -H|--retry|--connect-timeout)
      shift 2
      ;;
    -*)
      shift
      ;;
    *)
      url="$1"
      shift
      ;;
  esac
done
printf 'curl %s\\n' "${{url}}" >> {shlex.quote(trace_arg)}
if [[ "${{url}}" == */releases/latest ]]; then
  printf '{{"tag_name": "%s"}}\\n' {shlex.quote(latest_tag)}
  exit 0
fi
if [[ "${{url}}" == */SHA256SUMS.txt ]]; then
  tag="$(printf '%s' "${{url}}" | sed -E 's|.*/download/([^/]+)/SHA256SUMS\\.txt|\\1|')"
  cat <<EOF > "${{out}}"
{manifest_sha}  daily-stock-analysis-macos-arm64-${{tag}}.dmg
{manifest_sha}  daily-stock-analysis-macos-x64-${{tag}}.dmg
EOF
  exit 0
fi
if [[ "${{url}}" == *.dmg ]]; then
  cp {shlex.quote(payload_arg)} "${{out}}"
  exit 0
fi
exit 22
""",
    )

    _write_exec(
        fake_bin / "shasum",
        f"""#!/usr/bin/env bash
target="${{@: -1}}"
printf '%s  %s\\n' {shlex.quote(actual_sha)} "${{target}}"
""",
    )

    _write_exec(
        fake_bin / "hdiutil",
        f"""#!/usr/bin/env bash
printf 'hdiutil %s\\n' "$*" >> {shlex.quote(trace_arg)}
if [[ "$1" == "attach" ]]; then
  mountpoint=""
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == "-mountpoint" ]]; then
      mountpoint="$2"
      shift 2
    else
      shift
    fi
  done
  mkdir -p "${{mountpoint}}/Daily Stock Analysis.app/Contents/MacOS"
  printf '#!/usr/bin/env bash\\necho ok\\n' > "${{mountpoint}}/Daily Stock Analysis.app/Contents/MacOS/Daily Stock Analysis"
  chmod +x "${{mountpoint}}/Daily Stock Analysis.app/Contents/MacOS/Daily Stock Analysis"
  exit 0
fi
if [[ "$1" == "detach" ]]; then
  exit 0
fi
exit 1
""",
    )

    _write_exec(
        fake_bin / "ditto",
        f"""#!/usr/bin/env bash
printf 'ditto %s -> %s\\n' "$1" "$2" >> {shlex.quote(trace_arg)}
cp -R "$1" "$2"
""",
    )

    _write_exec(
        fake_bin / "pgrep",
        f"""#!/usr/bin/env bash
exit {0 if app_running else 1}
""",
    )

    _write_exec(
        fake_bin / "xattr",
        f"""#!/usr/bin/env bash
printf 'xattr %s\\n' "$*" >> {shlex.quote(trace_arg)}
exit 0
""",
    )

    _write_exec(
        fake_bin / "open",
        f"""#!/usr/bin/env bash
printf 'open %s\\n' "$*" >> {shlex.quote(trace_arg)}
exit 0
""",
    )

    return actual_sha, manifest_sha


def _run_installer(fake_bin: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    quoted_args = " ".join(shlex.quote(arg) for arg in args)
    return subprocess.run(
        [
            "bash",
            "-c",
            f'PATH={shlex.quote(_bash_path(fake_bin))}:"$PATH"; export PATH; '
            f"bash {shlex.quote(_bash_path(INSTALL_SCRIPT))} {quoted_args}",
        ],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )


def test_macos_install_script_syntax_and_lf_line_endings() -> None:
    raw = INSTALL_SCRIPT.read_bytes()
    assert b"\r\n" not in raw, "scripts/install-macos.sh must use LF line endings"

    res = subprocess.run(
        ["bash", "-n", _bash_path(INSTALL_SCRIPT)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr


def test_macos_install_script_detects_rosetta_and_intel_arch_in_dry_run(tmp_path: Path) -> None:
    rosetta_bin = tmp_path / "rosetta_bin"
    rosetta_trace = tmp_path / "rosetta.log"
    _write_fake_macos_installer_env(
        rosetta_bin,
        machine="x86_64",
        proc_translated="1",
        latest_tag="v3.36.1",
        trace_log=rosetta_trace,
    )
    res_rosetta = _run_installer(rosetta_bin, ["--dry-run"])
    assert res_rosetta.returncode == 0, res_rosetta.stderr
    assert "Architecture: arm64" in res_rosetta.stdout
    assert "daily-stock-analysis-macos-arm64-v3.36.1.dmg" in res_rosetta.stdout
    assert "Rosetta 2" in res_rosetta.stderr

    intel_bin = tmp_path / "intel_bin"
    intel_trace = tmp_path / "intel.log"
    _write_fake_macos_installer_env(
        intel_bin,
        machine="x86_64",
        proc_translated="0",
        latest_tag="v3.36.1",
        trace_log=intel_trace,
    )
    res_intel = _run_installer(intel_bin, ["--dry-run"])
    assert res_intel.returncode == 0, res_intel.stderr
    assert "Architecture: x64" in res_intel.stdout
    assert "daily-stock-analysis-macos-x64-v3.36.1.dmg" in res_intel.stdout


def test_macos_install_script_verifies_sha256_and_installs_atomically(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    trace_log = tmp_path / "trace.log"
    install_dir = tmp_path / "Applications"
    install_dir.mkdir()
    existing_app = install_dir / "Daily Stock Analysis.app"
    existing_app.mkdir()
    (existing_app / "OLD_MARKER").write_text("old", encoding="utf-8")

    actual_sha, _ = _write_fake_macos_installer_env(
        fake_bin,
        machine="arm64",
        latest_tag="v3.36.2",
        trace_log=trace_log,
    )

    res = _run_installer(
        fake_bin,
        ["--dir", _bash_path(install_dir), "--version", "3.36.2"],
    )
    assert res.returncode == 0, res.stderr
    assert f"SHA-256 verified: {actual_sha}" in res.stdout
    installed_exec = install_dir / "Daily Stock Analysis.app" / "Contents" / "MacOS" / "Daily Stock Analysis"
    assert installed_exec.is_file()
    assert not (existing_app / "OLD_MARKER").exists()

    trace = trace_log.read_text(encoding="utf-8")
    assert "hdiutil attach" in trace
    assert "hdiutil detach" in trace
    assert "xattr -dr com.apple.quarantine" in trace
    assert "open " in trace


def test_macos_install_script_respects_no_open_flag(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    trace_log = tmp_path / "trace.log"
    install_dir = tmp_path / "Applications"
    install_dir.mkdir()

    _write_fake_macos_installer_env(fake_bin, trace_log=trace_log)
    res = _run_installer(
        fake_bin,
        ["--dir", _bash_path(install_dir), "--no-open"],
    )
    assert res.returncode == 0, res.stderr
    trace = trace_log.read_text(encoding="utf-8")
    assert "open " not in trace


def test_macos_install_script_rejects_sha256_mismatch_without_touching_existing_app(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    trace_log = tmp_path / "trace.log"
    install_dir = tmp_path / "Applications"
    install_dir.mkdir()
    existing_app = install_dir / "Daily Stock Analysis.app"
    existing_app.mkdir()
    marker = existing_app / "KEEP_ME"
    marker.write_text("intact", encoding="utf-8")

    _write_fake_macos_installer_env(
        fake_bin,
        sha_override="0" * 64,
        trace_log=trace_log,
    )

    res = _run_installer(fake_bin, ["--dir", _bash_path(install_dir)])
    assert res.returncode != 0
    assert "SHA-256 mismatch" in res.stderr
    assert marker.read_text(encoding="utf-8") == "intact"
    trace = trace_log.read_text(encoding="utf-8")
    assert "hdiutil attach" not in trace


def test_macos_install_script_refuses_when_app_running_or_invalid_args(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    trace_log = tmp_path / "trace.log"
    install_dir = tmp_path / "Applications"
    install_dir.mkdir()

    _write_fake_macos_installer_env(
        fake_bin,
        app_running=True,
        trace_log=trace_log,
    )

    res_running = _run_installer(fake_bin, ["--dir", _bash_path(install_dir)])
    assert res_running.returncode != 0
    assert "currently running" in res_running.stderr

    res_bad_ver = _run_installer(fake_bin, ["--version", "../evil", "--dry-run"])
    assert res_bad_ver.returncode != 0
    assert "Invalid release tag format" in res_bad_ver.stderr

    res_bad_arch = _run_installer(fake_bin, ["--arch", "ppc", "--dry-run"])
    assert res_bad_arch.returncode != 0
    assert "Unsupported --arch" in res_bad_arch.stderr
