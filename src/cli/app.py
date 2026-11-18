# -*- coding: utf-8 -*-
"""Thin `dsa` CLI entrypoint (Typer + Rich, lazy imports, `--json` contract)."""

from __future__ import annotations

import json
import sys
import uuid
from contextlib import redirect_stdout
from typing import List, Optional

import typer

from src.cli.env import apply_dsa_home_env, configure_cli_stderr_logging

app = typer.Typer(
    name="dsa",
    help="Daily Stock Analysis (DSA) CLI & read-only MCP adapter.",
    no_args_is_help=True,
)
mcp_app = typer.Typer(
    name="mcp",
    help="Read-only MCP server commands for external Agent clients.",
    no_args_is_help=True,
)
app.add_typer(mcp_app, name="mcp")


def _emit_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _rich_console():
    from rich.console import Console

    return Console()


@app.callback()
def _cli_root() -> None:
    """Initialize `DSA_HOME` defaults before running subcommands."""
    apply_dsa_home_env()


@app.command("doctor")
def cmd_doctor(
    json_output: bool = typer.Option(False, "--json", help="Output structured JSON diagnostics."),
) -> None:
    """Run offline redacted config/LLM/notification/storage diagnostics."""
    import main as root_main

    argv = ["--doctor"]
    if json_output:
        argv.append("--json")
    code = root_main.main(argv)
    raise typer.Exit(code=code)


@app.command("analyze")
def cmd_analyze(
    target: str = typer.Argument(..., help="Stock code, index code, or Chinese stock name."),
    notify: bool = typer.Option(False, "--notify", help="Send notification after analysis (default: off)."),
    report_type: str = typer.Option("detailed", "--report-type", help="Report type: simple/detailed/full/brief."),
    force_refresh: bool = typer.Option(False, "--force-refresh", help="Bypass analysis cache."),
    json_output: bool = typer.Option(False, "--json", help="Output canonical AnalysisReport JSON."),
) -> None:
    """Analyze a single stock or index (notifications disabled by default)."""
    configure_cli_stderr_logging(quiet=json_output)

    from src.cli.mcp_server import resolve_stock_query
    from src.services.analysis_service import AnalysisService
    from src.services.report_builder_service import (
        build_analysis_report_payload,
        load_sync_fundamental_sources,
    )

    resolved = resolve_stock_query(target)
    if not resolved.get("ok"):
        err_payload = {
            "ok": False,
            "error": resolved.get("error", "unresolved_stock"),
            "message": resolved.get("message", f"Could not resolve stock: {target}"),
        }
        if json_output:
            _emit_json(err_payload)
        else:
            typer.echo(f"ERROR: {err_payload['message']}", err=True)
        raise typer.Exit(code=2)

    stock_code = resolved["stock_code"]
    query_id = uuid.uuid4().hex
    service = AnalysisService()

    if json_output:
        with redirect_stdout(sys.stderr):
            raw_report = service.analyze_stock(
                stock_code=stock_code,
                report_type=report_type,
                force_refresh=force_refresh,
                query_id=query_id,
                send_notification=notify,
                query_source="cli",
            )
    else:
        raw_report = service.analyze_stock(
            stock_code=stock_code,
            report_type=report_type,
            force_refresh=force_refresh,
            query_id=query_id,
            send_notification=notify,
            query_source="cli",
        )

    if not raw_report:
        err_msg = service.last_error or f"Analysis returned no result for {stock_code}"
        if json_output:
            _emit_json({"ok": False, "error": "analysis_failed", "message": err_msg})
        else:
            typer.echo(f"ERROR: {err_msg}", err=True)
        raise typer.Exit(code=1)

    ctx_snap, fb_fund, fb_raw = load_sync_fundamental_sources(query_id, stock_code)
    canonical = build_analysis_report_payload(
        report_data=raw_report,
        query_id=query_id,
        stock_code=stock_code,
        stock_name=resolved.get("stock_name"),
        context_snapshot=ctx_snap,
        fallback_fundamental_payload=fb_fund,
        fallback_raw_result_payload=fb_raw,
    )

    if json_output:
        _emit_json(canonical)
        return

    meta = canonical.get("meta") or {}
    summary = canonical.get("summary") or {}
    strategy = canonical.get("strategy") or {}
    console = _rich_console()
    console.print(
        f"[bold]{meta.get('stock_name') or meta.get('stock_code')} ({meta.get('stock_code')})[/bold]"
    )
    console.print(
        f"Advice: {summary.get('operation_advice') or '-'} | "
        f"Action: {summary.get('action') or '-'} | "
        f"Score: {summary.get('sentiment_score') if summary.get('sentiment_score') is not None else '-'}"
    )
    if summary.get("analysis_summary"):
        console.print(f"Summary: {summary['analysis_summary']}")
    if strategy:
        console.print(
            f"Levels: buy={strategy.get('ideal_buy') or '-'} "
            f"stop={strategy.get('stop_loss') or '-'} "
            f"target={strategy.get('take_profit') or '-'}"
        )


@app.command("market")
def cmd_market(
    notify: bool = typer.Option(False, "--notify", help="Send notification after market review."),
    region: Optional[str] = typer.Option(None, "--region", help="Override market review region."),
    json_output: bool = typer.Option(False, "--json", help="Output structured JSON result."),
) -> None:
    """Run market review analysis."""
    configure_cli_stderr_logging(quiet=json_output)
    import os
    import main as root_main

    if region:
        os.environ["MARKET_REVIEW_REGION"] = region
    argv = ["--market-review"]
    if not notify:
        argv.append("--no-notify")

    if json_output:
        with redirect_stdout(sys.stderr):
            code = root_main.main(argv)
        _emit_json({"ok": code == 0, "exit_code": code, "region": region, "notify": notify})
        raise typer.Exit(code=code)

    code = root_main.main(argv)
    raise typer.Exit(code=code)


@app.command("backtest")
def cmd_backtest(
    code: Optional[str] = typer.Option(None, "--code", help="Filter backtest to a single stock code."),
    eval_window: Optional[int] = typer.Option(None, "--eval-window", help="Evaluation window in trading days."),
    force: bool = typer.Option(False, "--force", help="Force recompute existing evaluations."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON backtest summary."),
) -> None:
    """Run backtest evaluation and print summary."""
    configure_cli_stderr_logging(quiet=json_output)
    from src.services.backtest_service import BacktestService

    svc = BacktestService()
    if json_output:
        with redirect_stdout(sys.stderr):
            run_stats = svc.run_backtest(
                code=code,
                eval_window_days=eval_window,
                force=force,
            )
            summary = svc.get_summary(scope="stock" if code else "overall", code=code)
        _emit_json({"ok": True, "run": run_stats, "summary": summary})
        return

    run_stats = svc.run_backtest(code=code, eval_window_days=eval_window, force=force)
    summary = svc.get_summary(scope="stock" if code else "overall", code=code)
    console = _rich_console()
    console.print(f"Backtest run: {run_stats}")
    console.print(f"Summary: {summary}")


@app.command("etf-rotation")
def cmd_etf_rotation(
    json_output: bool = typer.Option(False, "--json", help="Output JSON wrapper."),
) -> None:
    """Run rule-based ETF dual-momentum rotation."""
    configure_cli_stderr_logging(quiet=json_output)
    import main as root_main

    if json_output:
        with redirect_stdout(sys.stderr):
            code = root_main.main(["--etf-rotation"])
        _emit_json({"ok": code == 0, "exit_code": code})
        raise typer.Exit(code=code)

    code = root_main.main(["--etf-rotation"])
    raise typer.Exit(code=code)


@app.command("serve")
def cmd_serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host."),
    port: int = typer.Option(8000, "--port", help="Bind port."),
) -> None:
    """Start the FastAPI + WebUI server."""
    import main as root_main

    code = root_main.main(["--serve-only", "--host", host, "--port", str(port)])
    raise typer.Exit(code=code)


@app.command("schedule")
def cmd_schedule() -> None:
    """Run the local daily scheduler."""
    import main as root_main

    code = root_main.main(["--schedule"])
    raise typer.Exit(code=code)


@app.command("ask")
def cmd_ask(
    query: str = typer.Argument(..., help="Question for the stock strategy agent."),
    stock: Optional[str] = typer.Option(None, "--stock", help="Optional stock code or name context."),
    skills: Optional[List[str]] = typer.Option(None, "--skill", help="Optional strategy skill id(s)."),
    session_id: Optional[str] = typer.Option(None, "--session-id", help="Optional conversation session id."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON response."),
) -> None:
    """Ask the strategy Agent interactively (reuses AgentChatExecutor)."""
    configure_cli_stderr_logging(quiet=json_output)
    from src.agent.factory import build_agent_chat_executor
    from src.cli.mcp_server import resolve_stock_query

    context = {}
    if stock:
        resolved = resolve_stock_query(stock)
        context["stock_code"] = resolved["stock_code"] if resolved.get("ok") else stock
        if resolved.get("stock_name"):
            context["stock_name"] = resolved["stock_name"]

    executor = build_agent_chat_executor(skills=skills or None)
    sid = session_id or f"cli-{uuid.uuid4().hex[:10]}"

    def _on_progress(event: dict) -> None:
        if not isinstance(event, dict):
            return
        if event.get("type") == "tool_call":
            typer.echo(f"[tool] {event.get('tool') or event.get('name')}", err=True)

    if json_output:
        with redirect_stdout(sys.stderr):
            result = executor.chat(
                message=query,
                session_id=sid,
                progress_callback=_on_progress,
                context=context or None,
            )
        _emit_json(
            {
                "ok": bool(getattr(result, "success", False)),
                "session_id": sid,
                "content": getattr(result, "content", ""),
                "total_tokens": getattr(result, "total_tokens", 0),
                "models_used": getattr(result, "models_used", []),
                "error": getattr(result, "error", None),
            }
        )
    else:
        result = executor.chat(
            message=query,
            session_id=sid,
            progress_callback=_on_progress,
            context=context or None,
        )
        _rich_console().print(getattr(result, "content", "") or getattr(result, "error", ""))

    if not getattr(result, "success", False):
        raise typer.Exit(code=1)


@app.command("screen")
def cmd_screen(
    strategy: str = typer.Option("momentum", "--strategy", help="Screening strategy id."),
    market: str = typer.Option("cn", "--market", help="Target market: cn/hk/us."),
    limit: int = typer.Option(10, "--limit", min=1, max=100, help="Max candidate count."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON screening candidates."),
) -> None:
    """Run multi-factor stock screening."""
    configure_cli_stderr_logging(quiet=json_output)
    from src.config import get_config
    from src.services.screening_service import ScreeningService

    svc = ScreeningService(get_config())
    if json_output:
        with redirect_stdout(sys.stderr):
            result = svc.screen(strategy=strategy, market=market, max_results=limit)
        _emit_json(result)
        return

    result = svc.screen(strategy=strategy, market=market, max_results=limit)
    candidates = result.get("candidates") or []
    console = _rich_console()
    console.print(f"[bold]Screening ({strategy} / {market})[/bold]: {len(candidates)} candidates")
    for idx, item in enumerate(candidates, 1):
        console.print(
            f"{idx}. {item.get('stock_code')} {item.get('stock_name') or ''} | "
            f"score={item.get('score', '-')}"
        )


@app.command("signals")
def cmd_signals(
    stock: Optional[str] = typer.Option(None, "--stock", help="Filter by stock code."),
    action: Optional[str] = typer.Option(None, "--action", help="Filter by action (buy/hold/sell/watch...)."),
    status: Optional[str] = typer.Option(None, "--status", help="Filter by status (active/expired/closed...)."),
    limit: int = typer.Option(20, "--limit", min=1, max=100, help="Page size."),
    json_output: bool = typer.Option(False, "--json", help="Output JSON signal list."),
) -> None:
    """Query DecisionSignal records."""
    configure_cli_stderr_logging(quiet=json_output)
    from src.services.decision_signal_service import DecisionSignalService

    svc = DecisionSignalService()
    result = svc.list_signals(
        stock_code=stock,
        action=action,
        status=status,
        page=1,
        page_size=limit,
    )
    if json_output:
        _emit_json(result)
        return

    items = result.get("items") or []
    console = _rich_console()
    console.print(f"[bold]DecisionSignals[/bold] (total={result.get('total', len(items))})")
    for row in items:
        console.print(
            f"- [{row.get('status')}] {row.get('stock_code')} {row.get('stock_name') or ''} "
            f"| action={row.get('action')} | score={row.get('sentiment_score')}"
        )


@mcp_app.command("serve")
def cmd_mcp_serve(
    include_macro: bool = typer.Option(
        False,
        "--include-macro",
        help="Also expose fxmacrodata_* read-only tools.",
    ),
) -> None:
    """Start the read-only MCP stdio server."""
    from src.cli.mcp_server import run_mcp_stdio_server

    code = run_mcp_stdio_server(include_macro=include_macro)
    raise typer.Exit(code=code)


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point compatible with `python -m src.cli` and `[project.scripts]`."""
    try:
        app(args=argv, prog_name="dsa", standalone_mode=False)
        return 0
    except typer.Exit as exc:
        return int(exc.exit_code or 0)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1


if __name__ == "__main__":
    raise SystemExit(main())
