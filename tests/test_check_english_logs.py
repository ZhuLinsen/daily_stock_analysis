# -*- coding: utf-8 -*-
"""Tests for scripts/check_english_logs.py AST runtime log checker."""

from pathlib import Path

from scripts.check_english_logs import find_cjk_logs_in_source, main


def test_detects_cjk_in_logger_and_fstring() -> None:
    source = (
        'import logging\n'
        'logger = logging.getLogger(__name__)\n'
        'def run(stock, row):\n'
        '    logger.info("Fetching %s data", stock)\n'
        '    logger.warning("分析失败: %s", stock)\n'
        '    self_log_msg = "中文用户报告正文"\n'
        '    logger.error(f"Task {stock} 异常")\n'
        '    logging.getLogger("x").debug("调试信息")\n'
        '    return self_log_msg\n'
    )
    violations = find_cjk_logs_in_source(source, Path("sample.py"))
    assert [(v.line, v.method) for v in violations] == [
        (5, "warning"),
        (7, "error"),
        (8, "debug"),
    ]


def test_allows_english_logs_and_dataframe_chinese_column_keys() -> None:
    source = (
        'def run(row):\n'
        '    logger.info(f"Parsed quote close={row[\'收盘\']} name={row.get(\'名称\', \'N/A\')}")\n'
        '    msg = "用户报告支持中文"\n'
        '    return msg\n'
    )
    violations = find_cjk_logs_in_source(source, Path("clean.py"))
    assert violations == []


def test_cli_exit_code_on_clean_and_dirty_files(tmp_path: Path) -> None:
    clean_file = tmp_path / "clean_mod.py"
    clean_file.write_text('logger.info("Pipeline finished in %.2fs", 1.5)\n', encoding="utf-8")
    assert main([str(clean_file)]) == 0

    dirty_file = tmp_path / "dirty_mod.py"
    dirty_file.write_text('logger.info("流水线完成")\n', encoding="utf-8")
    assert main([str(dirty_file)]) == 1
