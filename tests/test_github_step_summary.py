# -*- coding: utf-8 -*-
"""Tests for scripts/write_github_step_summary.py."""

from __future__ import annotations

import os
from pathlib import Path
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
        "# 决策仪表盘\nAuthorization: Bearer sk-secret-token-123456\n",
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
    assert "sk-secret-token-123456" not in written
    assert "analysis-reports-*" in written


def test_truncates_cleanly_under_max_bytes_with_valid_utf8(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    long_line = "贵州茅台走势稳健。" * 300
    (reports_dir / "report_20261120.md").write_text(long_line, encoding="utf-8")

    rendered = build_step_summary_markdown(reports_dir, max_bytes=2000, target_date="20261120")

    assert rendered
    assert len(rendered.encode("utf-8")) <= 2200
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
