# -*- coding: utf-8 -*-
"""Tests for scripts/write_github_step_summary.py."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from scripts.write_github_step_summary import build_step_summary_markdown, main


def test_noop_when_github_step_summary_unset(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20261120.md").write_text("# Sample\n", encoding="utf-8")

    with patch.dict(os.environ, {}, clear=True):
        code = main(["--reports-dir", str(reports_dir)])

    assert code == 0


@pytest.mark.parametrize(
    "authorization_line",
    [
        "Authorization: Bearer {credential}",
        "Authorization　： Bearer {credential}",
        "**Authorization**: Bearer {credential}",
        "**Authorization**　： Bearer {credential}",
        "**Authorization：** Bearer {credential}",
        "__Authorization:__ Bearer {credential}",
        "*Authorization*: Bearer {credential}",
        "_Authorization_: Bearer {credential}",
        "`Authorization`: Bearer {credential}",
        "`` Authorization ``: Bearer {credential}",
        "`` Authorization: `` Bearer {credential}",
        "**`Authorization`**: Bearer {credential}",
        "HTTP**Authorization**: Bearer {credential}",
        "* `Authorization`: Bearer {credential}",
        "Authorization: Bearer `` {credential} ``",
        "Authorization： Basic `` {credential} ``",
        "**Authorization:** Bearer `` {credential} ``",
        "Authorization: Bearer **` {credential} `**",
    ],
)
def test_writes_redacted_reports_to_step_summary(tmp_path: Path, authorization_line: str) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20261120.md").write_text(
        "# 决策仪表盘\n",
        encoding="utf-8",
    )
    credential = "short-bearer-token"
    market_report = "# 大盘复盘\n上证指数收涨 0.8%\n" + authorization_line.format(credential=credential)
    (reports_dir / "market_review_20261120.md").write_text(market_report, encoding="utf-8")
    summary_file = tmp_path / "step_summary.md"

    with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary_file)}, clear=True):
        code = main(["--reports-dir", str(reports_dir), "--date", "20261120"])

    assert code == 0
    written = summary_file.read_text(encoding="utf-8")
    assert "# 决策仪表盘" in written
    assert "# 大盘复盘" in written
    assert "上证指数收涨 0.8%" in written
    assert credential not in written
    assert "Authorization: <redacted>" in written
    assert "analysis-reports-*" in written


@pytest.mark.parametrize(
    ("authorization_markdown", "redacted_markdown"),
    [
        ("**Authorization**:  \nBearer {credential}", "Authorization: <redacted>"),
        ("**Authorization**\nBearer {credential}", "Authorization: <redacted>"),
        ("*Authorization:*\n  `Bearer {credential}`", "Authorization: <redacted>"),
        ("> **Authorization:**\\\n> Bearer {credential}", "> Authorization: <redacted>"),
        ("> **Authorization:**\n>\n> `Bearer {credential}`", "> Authorization: <redacted>"),
        ("**Authorization:**<br>\nBearer {credential}", "Authorization: <redacted>"),
        ("**Authorization:**<br />`Bearer {credential}`", "Authorization: <redacted>"),
        ("Authorization: Bearer  \n{credential}", "Authorization: <redacted>"),
        ("Authorization: Bearer\n{credential} **继续观察**", "Authorization: <redacted> **继续观察**"),
        ("> **Authorization：** Basic\n> {credential} **继续观察**", "> Authorization: <redacted> **继续观察**"),
        ("> **Authorization:** Bearer\\\n> `{credential}`\n> 继续观察。", "> Authorization: <redacted>\n> 继续观察。"),
        ("> Authorization: Bearer\n>\n> {credential}\n> 继续观察。", "> Authorization: <redacted>\n> 继续观察。"),
        ("Authorization: `` Bearer ``  \n{credential}", "Authorization: <redacted>"),
        (
            "Authorization: Bearer\n**Authorization:** Bearer {credential}",
            "Authorization: <redacted>\nAuthorization: <redacted>",
        ),
        (
            'Authorization: Bearer\n"Authorization": Bearer {credential}',
            'Authorization: <redacted>\n"Authorization": <redacted>',
        ),
        (
            "Authorization: Bearer\napi_key: {credential}",
            "Authorization: <redacted>\napi_key: <redacted>",
        ),
        ("**Authorization:**<br>\nBearer<br />` {credential} `", "Authorization: <redacted>"),
        (
            "| `Authorization` | Bearer {credential} | 保留 |",
            "| Authorization | `<redacted>` | 保留 |",
        ),
        (
            "| _Authorization_ | **Bearer** {credential} | 保留 |",
            "| Authorization | `<redacted>` | 保留 |",
        ),
        (
            "| `Proxy-Authorization:` | Bearer `` {credential} `` | 保留 |",
            "| Proxy-Authorization | `<redacted>` | 保留 |",
        ),
        (
            '| `Authorization` | "Bearer {credential}" | 保留 |',
            "| Authorization | `<redacted>` | 保留 |",
        ),
        (
            "| `Authorization` | Bearer {credential}\\|token-suffix | 保留 |",
            "| Authorization | `<redacted>` | 保留 |",
        ),
        (
            "| `Authorization` | Bearer<br>{credential} | 保留 |",
            "| Authorization | `<redacted>` | 保留 |",
        ),
        (
            "| 市场 | Authorization | 备注 |\n"
            "| :--- | --- | ---: |\n"
            "| A 股 | Bearer {credential} | 保留 |\n"
            "| 港股 \\| 港元 | `Bearer {credential}-hk` | 继续观察 |\n"
            "| 美股 | 无 | Bearer bonds also gained. |",
            "| 市场 | Authorization | 备注 |\n"
            "| :--- | --- | ---: |\n"
            "| A 股 | `<redacted>` | 保留 |\n"
            "| 港股 \\| 港元 | `<redacted>` | 继续观察 |\n"
            "| 美股 | 无 | Bearer bonds also gained. |",
        ),
        (
            "| 市场 | [**Authorization**](https://example.invalid/docs?section=http-headers)： | 备注 |\n"
            "| --- | --- | --- |\n"
            "| A 股 | Bearer {credential} | 沪指收涨 0.8% |",
            "| 市场 | [**Authorization**](https://example.invalid/docs?section=http-headers) | 备注 |\n"
            "| --- | --- | --- |\n"
            "| A 股 | `<redacted>` | 沪指收涨 0.8% |",
        ),
        (
            "| 市场 | Authorization | 备注 |\n"
            "| --- | --- | --- |\n"
            "| 港股 | Basic {credential} | 恒指反弹 |\n"
            "| 美股 | 无 | Basic materials gained. |",
            "| 市场 | Authorization | 备注 |\n"
            "| --- | --- | --- |\n"
            "| 港股 | `<redacted>` | 恒指反弹 |\n"
            "| 美股 | 无 | Basic materials gained. |",
        ),
        (
            "| [Authorization][headers] | 市场 | Proxy-Authorization | 备注 |\n"
            "| --- | --- | --- | --- |\n"
            "| {credential} | 港股 | Basic {credential}-proxy | 恒指反弹 |\n\n"
            "[headers]: https://example.invalid/docs",
            "| [Authorization][headers] | 市场 | Proxy-Authorization | 备注 |\n"
            "| --- | --- | --- | --- |\n"
            "| `<redacted>` | 港股 | `<redacted>` | 恒指反弹 |\n\n"
            "[headers]: https://example.invalid/docs",
        ),
        (
            "| 字段 | 值 | 备注 |\n"
            "| --- | --- | --- |\n"
            "| [Authorization](https://example.invalid/docs) | Basic {credential} | 恒指反弹 |\n"
            "| Authorization | {credential}-opaque | 继续观察 |",
            "| 字段 | 值 | 备注 |\n"
            "| --- | --- | --- |\n"
            "| Authorization | `<redacted>` | 恒指反弹 |\n"
            "| Authorization | `<redacted>` | 继续观察 |",
        ),
        (
            "**Proxy-Authorization:** | 市场\n"
            "--- | ---\n"
            "**Bearer**<br>{credential} | 沪指",
            "**Proxy-Authorization** | 市场\n"
            "--- | ---\n"
            "`<redacted>` | 沪指",
        ),
        (
            '> | 市场 | "Authorization" | 备注 |\n'
            "> | --- | --- | --- |\n"
            "> | A 股 | Bearer {credential} | 保留 |",
            '> | 市场 | "Authorization" | 备注 |\n'
            "> | --- | --- | --- |\n"
            "> | A 股 | `<redacted>` | 保留 |",
        ),
        (
            "| Authorization |\n| --- |\nBearer {credential}",
            "| Authorization |\n| --- |\n`<redacted>`",
        ),
        (
            "市场 | Authorization\n"
            "--- | ---\n"
            "A 股\n"
            "港股 | Bearer {credential}",
            "市场 | Authorization\n"
            "--- | ---\n"
            "A 股\n"
            "港股 | `<redacted>`",
        ),
        (
            "| Authorization | 市场 |\n| --- | --- |\n| 无 | A 股 |\n"
            "## 港股\n| 市场 | Authorization |\n| --- | --- |\n| 港股 | Bearer {credential} |",
            "| Authorization | 市场 |\n| --- | --- |\n| 无 | A 股 |\n"
            "## 港股\n| 市场 | Authorization |\n| --- | --- |\n| 港股 | `<redacted>` |",
        ),
    ],
)
def test_writes_redacted_multiline_and_table_authorization(
    tmp_path: Path,
    authorization_markdown: str,
    redacted_markdown: str,
) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    credential = "short-bearer-token"
    table_header = "| 字段 | 值 | 备注 |\n| --- | --- | --- |\n"
    if not authorization_markdown.startswith("|") or "\n" in authorization_markdown:
        table_header = ""
    market_notes = "沪指收涨。\n\nBearer bonds also gained."
    report = f"# 大盘复盘\n\n{table_header}{authorization_markdown.format(credential=credential)}\n\n{market_notes}"
    report_path = reports_dir / "market_review_20261120.md"
    report_path.write_text(report, encoding="utf-8")
    summary_file = tmp_path / "step_summary.md"

    with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary_file)}, clear=True):
        code = main(["--reports-dir", str(reports_dir), "--date", "20261120"])

    assert code == 0
    written = summary_file.read_text(encoding="utf-8")
    assert credential not in written
    assert redacted_markdown in written
    assert written.startswith(f"<!-- dsa-step-summary -->\n# 大盘复盘\n\n{table_header}")
    assert market_notes in written
    assert report_path.read_text(encoding="utf-8") == report


def test_short_stock_report_leaves_remaining_budget_for_market_review(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20261120.md").write_text("# 个股汇总", encoding="utf-8")
    (reports_dir / "market_review_20261120.md").write_text(
        "# 大盘复盘\n" + ("市场走势。" * 40) + "\n建议继续观察。" + ("市场走势。" * 100),
        encoding="utf-8",
    )

    rendered = build_step_summary_markdown(reports_dir, max_bytes=1000, target_date="20261120")

    assert len(rendered.encode("utf-8")) <= 1000
    assert "# 个股汇总" in rendered
    assert "建议继续观察。" in rendered
    assert "Summary preview truncated" in rendered


def test_tiny_body_budget_prioritizes_market_review(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20261120.md").write_text("个股概况。" * 200, encoding="utf-8")
    (reports_dir / "market_review_20261120.md").write_text("# 大盘复盘\n市场走势。", encoding="utf-8")

    rendered = build_step_summary_markdown(reports_dir, max_bytes=280, target_date="20261120")

    assert len(rendered.encode("utf-8")) <= 280
    assert "# 大盘复盘" in rendered
    assert "Summary preview truncated" in rendered


def test_truncates_cleanly_under_max_bytes_with_valid_utf8(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    long_line = "贵州茅台走势稳健。" * 300
    (reports_dir / "report_20261120.md").write_text(long_line, encoding="utf-8")

    rendered = build_step_summary_markdown(reports_dir, max_bytes=2000, target_date="20261120")

    assert rendered
    assert len(rendered.encode("utf-8")) <= 2000
    assert "Summary preview truncated" in rendered
    assert "analysis-reports-*" in rendered


def test_empty_reports_dir_does_not_create_summary(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    summary_file = tmp_path / "step_summary.md"

    with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary_file)}, clear=True):
        code = main(["--reports-dir", str(reports_dir)])

    assert code == 0
    assert not summary_file.exists()


def test_redaction_failure_skips_summary_write(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20261120.md").write_text(
        "# 先生成的个股报告\n", encoding="utf-8"
    )
    (reports_dir / "market_review_20261120.md").write_text(
        "`Authorization`: Bearer short-bearer-token\n", encoding="utf-8"
    )
    summary_file = tmp_path / "step_summary.md"
    summary_file.write_text("Existing summary\n", encoding="utf-8")

    with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary_file)}, clear=True):
        with patch(
            "src.llm.local_cli_backend.redact_diagnostic_text",
            side_effect=["# 先生成的个股报告", RuntimeError("Scrubber unavailable")],
        ) as scrubber:
            code = main(["--reports-dir", str(reports_dir), "--date", "20261120"])

    assert code == 0
    assert scrubber.call_count == 2
    assert summary_file.read_text(encoding="utf-8") == "Existing summary\n"


def test_script_entrypoint_redacts_without_pythonpath(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20261120.md").write_text(
        "# 个股汇总\n**Authorization**: Bearer  \nshort-stock-token\n", encoding="utf-8"
    )
    (reports_dir / "market_review_20261120.md").write_text(
        "# 大盘复盘\n\n| Authorization | 市场 |\n| --- | --- |\n| `Bearer short-market-token` | 沪指 |\n",
        encoding="utf-8",
    )
    summary_file = tmp_path / "step_summary.md"
    env = {"GITHUB_STEP_SUMMARY": str(summary_file), "PATH": os.environ["PATH"]}

    result = subprocess.run(
        [sys.executable, "scripts/write_github_step_summary.py", "--reports-dir", str(reports_dir), "--date", "20261120"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    written = summary_file.read_text(encoding="utf-8")
    assert "# 个股汇总" in written
    assert "# 大盘复盘" in written
    assert "short-stock-token" not in written
    assert "short-market-token" not in written
    assert "| `<redacted>` | 沪指 |" in written


def test_redaction_preserves_report_beyond_diagnostic_preview_limit(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    report = "前文\n" + ("内容。" * 300) + "\n操作建议：继续观察。"
    (reports_dir / "report_20261120.md").write_text(report, encoding="utf-8")

    rendered = build_step_summary_markdown(reports_dir, target_date="20261120")

    assert "操作建议：继续观察。" in rendered
    assert "Summary preview truncated" not in rendered


def test_small_max_bytes_is_an_exact_utf8_limit(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20261120.md").write_text("贵州茅台走势稳健。" * 300, encoding="utf-8")
    summary_file = tmp_path / "step_summary.md"

    with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary_file)}, clear=True):
        code = main(["--reports-dir", str(reports_dir), "--max-bytes", "1024", "--date", "20261120"])

    assert code == 0
    written = summary_file.read_bytes()
    assert len(written) <= 1024
    assert "Summary preview truncated" in written.decode("utf-8")


def test_date_fallback_keeps_latest_stock_and_market_reports(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20261120.md").write_text("stock", encoding="utf-8")
    (reports_dir / "market_review_20261120.md").write_text("market", encoding="utf-8")

    rendered = build_step_summary_markdown(reports_dir, target_date="20261121")

    assert "stock" in rendered
    assert "market" in rendered


def test_prefers_aggregate_over_per_stock_files_and_preserves_market_review_budget(tmp_path: Path) -> None:
    """Counterexample OR-COR-880cf3f1: single-stock reports must not crowd out market review."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20261120.md").write_text("# 汇总决策报告\n" + ("核心看多。" * 250), encoding="utf-8")
    for idx in range(15):
        (reports_dir / f"report_20261120_60000{idx}.md").write_text(
            f"# 单股冗余明细 {idx}\n" + ("单股详细。" * 150),
            encoding="utf-8",
        )
    (reports_dir / "market_review_20261120.md").write_text("# 大盘复盘\n沪指收涨 1.2%", encoding="utf-8")

    rendered = build_step_summary_markdown(reports_dir, max_bytes=4000, target_date="20261120")

    assert len(rendered.encode("utf-8")) <= 4000
    assert "# 汇总决策报告" in rendered
    assert "# 大盘复盘" in rendered
    assert "单股冗余明细" not in rendered


@pytest.mark.parametrize("target_date", ["20261120", "20261121"])
@pytest.mark.parametrize("seconds_apart", [120, 7200])
def test_cross_midnight_run_pairs_yesterday_stock_report_with_today_market_review(
    tmp_path: Path, target_date: str, seconds_apart: int
) -> None:
    """Counterexample OR-COR-8f1a9182: 23:59 stock report + 00:01 market review must both appear."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    now_ts = time.time()
    agg = reports_dir / "report_20261120.md"
    mr = reports_dir / "market_review_20261121.md"
    agg.write_text("# 汇总报告\n贵州茅台看多", encoding="utf-8")
    mr.write_text("# 大盘复盘\n深成指温和反弹", encoding="utf-8")
    (reports_dir / "report_20261121_600519.md").write_text("# 单股明细", encoding="utf-8")
    agg_mtime = now_ts - seconds_apart
    os.utime(agg, (agg_mtime, agg_mtime))
    os.utime(mr, (now_ts, now_ts))

    rendered = build_step_summary_markdown(reports_dir, target_date=target_date)

    assert "# 汇总报告" in rendered
    assert "# 大盘复盘" in rendered
    assert "# 单股明细" not in rendered


@pytest.mark.parametrize(("stock_date", "seconds_apart"), [("20261120", 7201), ("20261119", 120)])
def test_cross_midnight_run_ignores_reports_outside_pairing_window(
    tmp_path: Path, stock_date: str, seconds_apart: int
) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    now_ts = time.time()
    agg = reports_dir / f"report_{stock_date}.md"
    mr = reports_dir / "market_review_20261121.md"
    agg.write_text("# 汇总报告\n个股结论", encoding="utf-8")
    mr.write_text("# 大盘复盘\n市场结论", encoding="utf-8")
    os.utime(agg, (now_ts - seconds_apart, now_ts - seconds_apart))
    os.utime(mr, (now_ts, now_ts))

    rendered = build_step_summary_markdown(reports_dir, target_date="20261121")

    assert "# 汇总报告" not in rendered
    assert "# 大盘复盘" in rendered
