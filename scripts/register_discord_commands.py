#!/usr/bin/env python3
"""Bulk-register the bot's Discord application commands."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from typing import Sequence
from urllib import error as urllib_error
from urllib import request as urllib_request


DISCORD_API_BASE = "https://discord.com/api/v10"


def _option(name: str, description: str, *, required: bool = False, kind: int = 3):
    return {
        "type": kind,
        "name": name,
        "description": description,
        "required": required,
    }


COMMAND_PAYLOADS = [
    {
        "name": "help",
        "description": "显示帮助信息",
        "options": [_option("command", "要查看的命令名")],
    },
    {"name": "status", "description": "显示系统状态"},
    {
        "name": "analyze",
        "description": "分析指定股票",
        "options": [
            _option("stock_code", "股票代码", required=True),
            _option("full", "生成完整分析", kind=5),
        ],
    },
    {"name": "market", "description": "执行大盘复盘分析"},
    {
        "name": "batch",
        "description": "批量分析自选股",
        "options": [_option("count", "最多分析的股票数量", kind=4)],
    },
    {
        "name": "ask",
        "description": "使用 Agent 技能分析股票",
        "options": [
            _option("stock_codes", "股票代码，多个代码用逗号分隔", required=True),
            _option("strategy", "可选的技能或策略名称"),
        ],
    },
    {
        "name": "chat",
        "description": "与 AI 助手自由对话",
        "options": [_option("question", "要询问的问题", required=True)],
    },
    {
        "name": "research",
        "description": "深度研究股票或市场主题",
        "options": [
            _option("topic", "股票代码或研究主题", required=True),
            _option("question", "可选的具体问题"),
        ],
    },
    {
        "name": "strategies",
        "description": "查看可用交易策略",
        "options": [_option("active", "仅显示已激活策略", kind=5)],
    },
    {
        "name": "history",
        "description": "查看 Agent 对话历史",
        "options": [_option("session", "会话 ID，或输入 clear 清空")],
    },
]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Register Daily Stock Analysis slash commands with Discord."
    )
    parser.add_argument("--application-id", required=True, help="Discord application ID")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--guild-id", help="Register commands in one Discord guild")
    scope.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="Register commands globally",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the JSON command payload without contacting Discord",
    )
    return parser


def _endpoint(application_id: str, guild_id: str | None) -> str:
    base = f"{DISCORD_API_BASE}/applications/{application_id}"
    if guild_id:
        return f"{base}/guilds/{guild_id}/commands"
    return f"{base}/commands"


def _load_bot_token() -> str:
    """Read the token without placing it in argv or echoing it."""
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if token:
        return token
    if sys.stdin.isatty():
        try:
            return getpass.getpass("Discord bot token: ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""
    return ""


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if any(
        argument == "--bot-token" or argument.startswith("--bot-token=")
        for argument in raw_argv
    ):
        print(
            "error: command-line token input is rejected; use the "
            "DISCORD_BOT_TOKEN environment variable or the secure prompt",
            file=sys.stderr,
        )
        return 2

    args = _parser().parse_args(raw_argv)

    if args.dry_run:
        print(json.dumps(COMMAND_PAYLOADS, ensure_ascii=False, indent=2))
        return 0

    bot_token = _load_bot_token()
    if not bot_token:
        print(
            "error: set DISCORD_BOT_TOKEN or run interactively to enter it securely",
            file=sys.stderr,
        )
        return 2

    endpoint = _endpoint(args.application_id, args.guild_id)
    request = urllib_request.Request(
        endpoint,
        data=json.dumps(COMMAND_PAYLOADS, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "daily-stock-analysis-discord-command-register/1.0",
        },
        method="PUT",
    )
    try:
        response = urllib_request.urlopen(request, timeout=20)
        response_body = response.read()
        response.close()
    except (urllib_error.HTTPError, urllib_error.URLError, TimeoutError) as exc:
        status = getattr(exc, "code", None)
        detail = f" (HTTP {status})" if status is not None else ""
        print(f"Discord command registration failed{detail}", file=sys.stderr)
        return 1

    try:
        registered_count = len(json.loads(response_body.decode("utf-8")))
    except (AttributeError, TypeError, UnicodeDecodeError, ValueError):
        registered_count = len(COMMAND_PAYLOADS)
    scope_name = f"guild {args.guild_id}" if args.guild_id else "global"
    print(f"Registered {registered_count} Discord commands ({scope_name}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
