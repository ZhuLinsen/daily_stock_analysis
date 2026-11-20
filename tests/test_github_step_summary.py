# -*- coding: utf-8 -*-
"""Tests for scripts/write_github_step_summary.py."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

from scripts.write_github_step_summary import build_step_summary_markdown, main


def test_noop_when_github_step_summary_unset(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20261120.md").write_text("# Sample\n", encoding="utf-8")

    with patch.dict(os.environ, {}, clear=True):
        code = main(["--reports-dir", str(reports_dir)])

    assert code == 0


def test_writes_redacted_reports_to_step_summary(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20261120.md").write_text(
        "# 决策仪表盘\n"
        "Authorization: Bearer short-bearer-token\n"
        "**Authorization**: Bearer short-bearer-token\n",
        encoding="utf-8",
    )
    (reports_dir / "market_review_20261120.md").write_text(
        "# 大盘复盘\n上证指数收涨 0.8%\n",
        encoding="utf-8",
    )
    summary_file = tmp_path / "step_summary.md"

    with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary_file)}, clear=True):
        code = main(["--reports-dir", str(reports_dir), "--date", "20261120"])

    assert code == 0
    written = summary_file.read_text(encoding="utf-8")
    assert "# 决策仪表盘" in written
    assert "# 大盘复盘" in written
    assert "short-bearer-token" not in written
    assert "analysis-reports-*" in written


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
        "Authorization: Bearer sk-secret-token-123456\n", encoding="utf-8"
    )
    summary_file = tmp_path / "step_summary.md"

    with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary_file)}, clear=True):
        with patch("scripts.write_github_step_summary._redact_text", return_value=None):
            code = main(["--reports-dir", str(reports_dir), "--date", "20261120"])

    assert code == 0
    assert not summary_file.exists()


def test_script_entrypoint_redacts_without_pythonpath(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "report_20261120.md").write_text(
        "Authorization: Bearer sk-secret-token-123456\n", encoding="utf-8"
    )
    summary_file = tmp_path / "step_summary.md"
    env = {"GITHUB_STEP_SUMMARY": str(summary_file), "PATH": os.environ["PATH"]}

    result = subprocess.run(
        [sys.executable, "scripts/write_github_step_summary.py", "--reports-dir", str(reports_dir)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "sk-secret-token-123456" not in summary_file.read_text(encoding="utf-8")


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

    rendered = build_step_summary_markdown(reports_dir, max_bytes=1024, target_date="20261120")

    assert len(rendered.encode("utf-8")) <= 1024
    assert "Summary preview truncated" in rendered


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


def test_cross_midnight_run_pairs_yesterday_stock_report_with_today_market_review(tmp_path: Path) -> None:
    """Counterexample OR-COR-8f1a9182: 23:59 stock report + 00:01 market review must both appear."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    now_ts = time.time()
    agg = reports_dir / "report_20261120.md"
    mr = reports_dir / "market_review_20261121.md"
    agg.write_text("# 汇总报告\n贵州茅台看多", encoding="utf-8")
    mr.write_text("# 大盘复盘\n深成指温和反弹", encoding="utf-8")
    os.utime(agg, (now_ts - 120, now_ts - 120))
    os.utime(mr, (now_ts, now_ts))

    rendered = build_step_summary_markdown(reports_dir, target_date="20261121")

    assert "# 汇总报告" in rendered
    assert "# 大盘复盘" in rendered


def test_cross_midnight_run_pairs_reports_after_two_hours(tmp_path: Path) -> None:
    """The pair is still from one workflow run when the phases are delayed."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    now_ts = time.time()
    agg = reports_dir / "report_20261120.md"
    mr = reports_dir / "market_review_20261121.md"
    agg.write_text("# 汇总报告\n个股结论", encoding="utf-8")
    mr.write_text("# 大盘复盘\n市场结论", encoding="utf-8")
    os.utime(agg, (now_ts - 7500, now_ts - 7500))
    os.utime(mr, (now_ts, now_ts))

    rendered = build_step_summary_markdown(reports_dir, target_date="20261121")

    assert "# 汇总报告" in rendered
    assert "# 大盘复盘" in rendered
