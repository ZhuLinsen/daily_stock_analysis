# -*- coding: utf-8 -*-
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import register_discord_commands


EXPECTED_COMMANDS = {
    "help",
    "status",
    "analyze",
    "market",
    "batch",
    "ask",
    "chat",
    "research",
    "strategies",
    "history",
}


def test_dry_run_outputs_current_discord_command_payloads(capsys):
    exit_code = register_discord_commands.main(
        ["--application-id", "app-123", "--global", "--dry-run"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert {command["name"] for command in payload} == EXPECTED_COMMANDS
    assert "market_review" not in {command["name"] for command in payload}


def test_real_guild_registration_bulk_overwrites_discord_commands(capsys):
    response = Mock()
    response.read.return_value = b'[{"id":"1"}]'

    argv = [
        "--application-id",
        "app-123",
        "--guild-id",
        "guild-456",
    ]
    with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "secret-token"}), patch(
        "scripts.register_discord_commands.urllib_request.urlopen", return_value=response
    ) as urlopen:
        exit_code = register_discord_commands.main(
            argv
        )

    assert exit_code == 0
    request = urlopen.call_args.args[0]
    assert request.full_url.endswith(
        "/applications/app-123/guilds/guild-456/commands"
    )
    assert request.get_header("Authorization") == "Bot secret-token"
    request_payload = json.loads(request.data.decode("utf-8"))
    assert {item["name"] for item in request_payload} == EXPECTED_COMMANDS
    assert "secret-token" not in argv
    assert "--bot-token" not in argv
    output = capsys.readouterr()
    assert "secret-token" not in output.out
    assert "secret-token" not in output.err


def test_real_registration_requires_token_without_echoing_empty_secret(capsys):
    with patch.dict(os.environ, {}, clear=True), patch(
        "scripts.register_discord_commands.sys.stdin.isatty", return_value=False
    ):
        exit_code = register_discord_commands.main(
            ["--application-id", "app-123", "--global"]
        )

    output = capsys.readouterr()
    assert exit_code == 2
    assert "DISCORD_BOT_TOKEN" in output.err
    assert "token=" not in output.err.lower()


def _run_legacy_token_subprocess(token_arg: list[str]):
    script = Path(register_discord_commands.__file__).resolve()
    env = os.environ.copy()
    env.pop("DISCORD_BOT_TOKEN", None)
    return subprocess.run(
        [
            sys.executable,
            str(script),
            "--application-id",
            "app-123",
            "--global",
            *token_arg,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_legacy_split_token_argument_is_rejected_without_echoing_secret():
    result = _run_legacy_token_subprocess(
        ["--bot-token", "REVIEW_FAKE_SPLIT_SECRET"]
    )

    rendered = result.stdout + result.stderr
    assert result.returncode == 2
    assert "REVIEW_FAKE_SPLIT_SECRET" not in rendered
    assert "--bot-token" not in rendered
    assert "DISCORD_BOT_TOKEN" in result.stderr


def test_legacy_equals_token_argument_is_rejected_without_echoing_secret():
    result = _run_legacy_token_subprocess(
        ["--bot-token=REVIEW_FAKE_EQUALS_SECRET"]
    )

    rendered = result.stdout + result.stderr
    assert result.returncode == 2
    assert "REVIEW_FAKE_EQUALS_SECRET" not in rendered
    assert "--bot-token" not in rendered
    assert "DISCORD_BOT_TOKEN" in result.stderr
