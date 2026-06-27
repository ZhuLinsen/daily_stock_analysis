# -*- coding: utf-8 -*-
"""Agent tools for the EastMoney Miaoxiang skill package.

The downloaded Miaoxiang skills are script-oriented. This module wraps those
scripts in bounded, JSON-friendly tools so the DSA Agent can call them without
embedding secrets or large raw files into prompts.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent.tools.registry import ToolDefinition, ToolParameter


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = PROJECT_ROOT / "skills" / "mx-skills"
MAX_STDOUT_CHARS = 6000
DISCLAIMER = "仅供学习和复盘，不构成投资建议。"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _output_dir() -> Path:
    configured = os.getenv("MX_OUTPUT_DIR") or os.getenv("MX_SKILL_OUTPUT_DIR")
    if configured:
        path = Path(configured)
    else:
        db_path = Path(os.getenv("DATABASE_PATH", str(PROJECT_ROOT / "data" / "stock_analysis.db")))
        path = db_path.parent / "mx_skill_outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _bounded_timeout(value: Any, default: int = 30) -> int:
    try:
        return max(5, min(int(value), 60))
    except (TypeError, ValueError):
        return default


def _recent_files(output_dir: Path, *, limit: int = 8) -> List[str]:
    try:
        files = [path for path in output_dir.iterdir() if path.is_file()]
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return [str(path) for path in files[:limit]]
    except Exception:
        return []


def _run_mx_script(script: Path, args: List[str], *, timeout_seconds: int, output_arg_style: str = "positional") -> Dict[str, Any]:
    if not os.getenv("MX_APIKEY", "").strip():
        return {
            "source": "eastmoney.miaoxiang",
            "stale": True,
            "error": "MX_APIKEY 环境变量未配置",
            "updated_at": _now_iso(),
            "data": {"files": [], "stdout": "", "disclaimer": DISCLAIMER},
        }
    if not script.exists():
        return {
            "source": "eastmoney.miaoxiang",
            "stale": True,
            "error": f"妙想脚本不存在: {script}",
            "updated_at": _now_iso(),
            "data": {"files": [], "stdout": "", "disclaimer": DISCLAIMER},
        }

    output_dir = _output_dir()
    command = [sys.executable, str(script), *args]
    if output_arg_style == "positional":
        command.append(str(output_dir))
    else:
        command.extend(["--output-dir", str(output_dir)])
    try:
        completed = subprocess.run(
            command,
            cwd=str(script.parent),
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        error = None
        if completed.returncode != 0:
            error = stderr or stdout or f"mx_script_exit_{completed.returncode}"
        return {
            "source": f"eastmoney.miaoxiang.{script.stem}",
            "stale": bool(error),
            "error": error,
            "updated_at": _now_iso(),
            "data": {
                "stdout": stdout[:MAX_STDOUT_CHARS],
                "stderr": stderr[:1200] if error else "",
                "return_code": completed.returncode,
                "files": _recent_files(output_dir),
                "output_dir": str(output_dir),
                "disclaimer": DISCLAIMER,
            },
        }
    except subprocess.TimeoutExpired:
        return {
            "source": f"eastmoney.miaoxiang.{script.stem}",
            "stale": True,
            "error": f"timeout_after_{timeout_seconds}s",
            "updated_at": _now_iso(),
            "data": {"files": _recent_files(output_dir), "output_dir": str(output_dir), "stdout": "", "disclaimer": DISCLAIMER},
        }
    except Exception as exc:
        return {
            "source": f"eastmoney.miaoxiang.{script.stem}",
            "stale": True,
            "error": str(exc) or type(exc).__name__,
            "updated_at": _now_iso(),
            "data": {"files": _recent_files(output_dir), "output_dir": str(output_dir), "stdout": "", "disclaimer": DISCLAIMER},
        }


def _mx_script(*parts: str) -> Path:
    return SKILL_ROOT.joinpath(*parts)


def _handle_mx_data_query(query: str, timeout_seconds: int = 30) -> Dict[str, Any]:
    return _run_mx_script(
        _mx_script("mx-data", "mx-data", "mx_data.py"),
        [query],
        timeout_seconds=_bounded_timeout(timeout_seconds),
    )


def _handle_mx_search_query(query: str, timeout_seconds: int = 30) -> Dict[str, Any]:
    return _run_mx_script(
        _mx_script("mx-search", "mx-search", "mx_search.py"),
        [query],
        timeout_seconds=_bounded_timeout(timeout_seconds),
    )


def _handle_mx_xuangu_query(query: str, timeout_seconds: int = 30) -> Dict[str, Any]:
    return _run_mx_script(
        _mx_script("mx-xuangu", "mx-xuangu", "mx_xuangu.py"),
        [query],
        timeout_seconds=_bounded_timeout(timeout_seconds),
        output_arg_style="option",
    )


def _handle_mx_zixuan_query(command: str = "query", stock: Optional[str] = None, timeout_seconds: int = 30) -> Dict[str, Any]:
    args = [command]
    if stock:
        args.append(stock)
    return _run_mx_script(
        _mx_script("mx-zixuan", "mx-zixuan", "mx_zixuan.py"),
        args,
        timeout_seconds=_bounded_timeout(timeout_seconds),
        output_arg_style="option",
    )


mx_data_query_tool = ToolDefinition(
    name="mx_data_query",
    description="Use EastMoney Miaoxiang financial data skill for a natural-language data query. Returns source/stale/error/data with output file paths.",
    parameters=[
        ToolParameter(name="query", type="string", description="Natural-language financial data query, e.g. 贵州茅台最新价 涨跌幅"),
        ToolParameter(name="timeout_seconds", type="integer", description="Timeout in seconds, clamped to 5-60", required=False, default=30),
    ],
    handler=_handle_mx_data_query,
    category="data",
)

mx_search_query_tool = ToolDefinition(
    name="mx_search_query",
    description="Use EastMoney Miaoxiang search skill for news, announcements and research context. Returns bounded preview and output files.",
    parameters=[
        ToolParameter(name="query", type="string", description="Natural-language search query, e.g. 贵州茅台 最新公告 风险"),
        ToolParameter(name="timeout_seconds", type="integer", description="Timeout in seconds, clamped to 5-60", required=False, default=30),
    ],
    handler=_handle_mx_search_query,
    category="search",
)

mx_xuangu_query_tool = ToolDefinition(
    name="mx_xuangu_query",
    description="Use EastMoney Miaoxiang smart stock screening skill. It is for research only and does not trade.",
    parameters=[
        ToolParameter(name="query", type="string", description="Natural-language screening condition, e.g. 今日放量上涨且市值大于100亿的A股"),
        ToolParameter(name="timeout_seconds", type="integer", description="Timeout in seconds, clamped to 5-60", required=False, default=30),
    ],
    handler=_handle_mx_xuangu_query,
    category="market",
)

mx_zixuan_query_tool = ToolDefinition(
    name="mx_zixuan_query",
    description="Use EastMoney Miaoxiang watchlist skill to query or manage EastMoney self-selected stocks. No broker or trading operations are involved.",
    parameters=[
        ToolParameter(name="command", type="string", description="query/add/delete or a natural-language watchlist instruction", required=False, default="query"),
        ToolParameter(name="stock", type="string", description="Optional stock name or code for add/delete", required=False, default=None),
        ToolParameter(name="timeout_seconds", type="integer", description="Timeout in seconds, clamped to 5-60", required=False, default=30),
    ],
    handler=_handle_mx_zixuan_query,
    category="market",
)


ALL_MX_TOOLS: List[ToolDefinition] = [
    mx_data_query_tool,
    mx_search_query_tool,
    mx_xuangu_query_tool,
    mx_zixuan_query_tool,
]
