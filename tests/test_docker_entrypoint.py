import os
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_docker_entrypoint_has_valid_shell_syntax() -> None:
    subprocess.run(
        ["sh", "-n", str(REPO_ROOT / "docker" / "entrypoint.sh")],
        check=True,
    )


def test_dockerfile_uses_entrypoint_to_drop_privileges() -> None:
    dockerfile = (REPO_ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")

    assert "gosu" in dockerfile
    assert 'ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]' in dockerfile
    assert "USER dsa" not in dockerfile


def test_docker_entrypoint_repairs_ownership_and_user_permissions() -> None:
    entrypoint = (REPO_ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")

    assert "directory_needs_repair" in entrypoint
    assert "has_unwritable_mount_path" in entrypoint
    assert "can_write_dir_as_app_user" in entrypoint
    assert "DATABASE_FILE" in entrypoint
    assert re.search(r"\bchown\s+-R\b", entrypoint)
    assert re.search(r"\bchmod\s+-R\s+u\+rwX\b", entrypoint)
    assert re.search(r"gosu\s+\"\$APP_USER:\$APP_GROUP\"\s+test\s+-w", entrypoint)


def test_documented_compose_exec_commands_run_as_dsa() -> None:
    safe_exec_prefix = "docker-compose -f ./docker/docker-compose.yml exec -u dsa"
    unsafe_exec_prefix = "docker-compose -f ./docker/docker-compose.yml exec"

    for doc_path in ("docs/DEPLOY.md", "docs/DEPLOY_EN.md"):
        doc = (REPO_ROOT / doc_path).read_text(encoding="utf-8")

        assert f"{safe_exec_prefix} stock-analyzer bash" in doc
        assert f"{safe_exec_prefix} stock-analyzer python main.py --no-notify" in doc
        assert f"{unsafe_exec_prefix} stock-analyzer bash" not in doc
        assert (
            f"{unsafe_exec_prefix} stock-analyzer python main.py --no-notify"
            not in doc
        )


def _write_fake_command(fakebin: Path, name: str, body: str) -> None:
    command = fakebin / name
    command.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    command.chmod(0o755)


def _prepare_fake_entrypoint_tools(tmp_path: Path, find_body: str) -> tuple[Path, Path]:
    fakebin = tmp_path / "bin"
    log_dir = tmp_path / "logs"
    fakebin.mkdir()
    log_dir.mkdir()

    _write_fake_command(
        fakebin,
        "id",
        'if [ "${1:-}" = "-u" ]; then printf "0\\n"; else printf "0\\n"; fi\n',
    )
    _write_fake_command(fakebin, "mkdir", "exit 0\n")
    _write_fake_command(fakebin, "find", find_body)
    _write_fake_command(
        fakebin,
        "chown",
        'printf "%s\\n" "$*" >> "$FAKE_LOG_DIR/chown.log"\n'
        'exit "${CHOWN_EXIT:-0}"\n',
    )
    _write_fake_command(
        fakebin,
        "chmod",
        'printf "%s\\n" "$*" >> "$FAKE_LOG_DIR/chmod.log"\n'
        'exit "${CHMOD_EXIT:-0}"\n',
    )
    _write_fake_command(
        fakebin,
        "gosu",
        'shift\n'
        'case "$1" in\n'
        '    sh|test) exit "${GOSU_WRITE_EXIT:-0}" ;;\n'
        'esac\n'
        'exec "$@"\n',
    )

    return fakebin, log_dir


def _run_entrypoint_with_fake_tools(
    fakebin: Path,
    log_dir: Path,
    *,
    gosu_write_exit: int,
    chown_exit: int,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{fakebin}:{env['PATH']}"
    env["FAKE_LOG_DIR"] = str(log_dir)
    env["GOSU_WRITE_EXIT"] = str(gosu_write_exit)
    env["CHOWN_EXIT"] = str(chown_exit)

    return subprocess.run(
        ["sh", str(REPO_ROOT / "docker" / "entrypoint.sh"), "true"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def test_docker_entrypoint_repairs_nested_mount_ownership(tmp_path: Path) -> None:
    fakebin, log_dir = _prepare_fake_entrypoint_tools(
        tmp_path,
        'for arg in "$@"; do\n'
        '    if [ "$arg" = "-maxdepth" ]; then exit 0; fi\n'
        "done\n"
        'printf "%s/nested-root-owned\\n" "$1"\n',
    )

    _run_entrypoint_with_fake_tools(
        fakebin,
        log_dir,
        gosu_write_exit=0,
        chown_exit=0,
    )

    chown_log = (log_dir / "chown.log").read_text(encoding="utf-8")
    chmod_log = (log_dir / "chmod.log").read_text(encoding="utf-8")
    assert "/app/data" in chown_log
    assert "/app/logs" in chown_log
    assert "/app/reports" in chown_log
    assert "/app/data" in chmod_log


def test_docker_entrypoint_skips_owner_chmod_when_chown_fails(tmp_path: Path) -> None:
    fakebin, log_dir = _prepare_fake_entrypoint_tools(
        tmp_path,
        'printf "%s/root-owned\\n" "$1"\n',
    )

    result = _run_entrypoint_with_fake_tools(
        fakebin,
        log_dir,
        gosu_write_exit=1,
        chown_exit=1,
    )

    assert (log_dir / "chown.log").exists()
    assert not (log_dir / "chmod.log").exists()
    assert "skipping owner-only chmod" in result.stderr
    assert "still not writable by dsa" in result.stderr
