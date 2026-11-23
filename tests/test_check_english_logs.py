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


def test_detects_adjacent_literals_and_log_message_forms() -> None:
    source = (
        'import logging\n'
        'logger.warning("分析" "失败")\n'
        'logger.log(logging.INFO, "日志失败")\n'
        'logger.info(msg="消息失败")\n'
        'logger.log(level=logging.INFO, msg="级别失败")\n'
    )
    violations = find_cjk_logs_in_source(source, Path("message_forms.py"))
    assert [(v.line, v.method) for v in violations] == [
        (2, "warning"),
        (3, "log"),
        (4, "info"),
        (5, "log"),
    ]


def test_detects_japanese_korean_and_extension_b_cjk(tmp_path: Path) -> None:
    source = (
        'logger.warning("テスト")\n'
        'logger.info("エラーです")\n'
        'logger.error("실패")\n'
        'logger.warning("𠮷")\n'
    )
    violations = find_cjk_logs_in_source(source, Path("multi_cjk.py"))
    assert [(v.line, v.method) for v in violations] == [
        (1, "warning"),
        (2, "info"),
        (3, "error"),
        (4, "warning"),
    ]
    for idx, line in enumerate(source.splitlines()):
        sample_file = tmp_path / f"sample_{idx}.py"
        sample_file.write_text(f"{line}\n", encoding="utf-8")
        assert main([str(sample_file)]) == 1


def test_allows_membership_checks_with_chinese_column_names() -> None:
    source = (
        'def run(df, col):\n'
        '    logger.info("Has close column: %s", "收盘" in df.columns)\n'
        '    logger.info("Missing close column: %s", "收盘" not in df.columns)\n'
        '    logger.info(f"has close={\'收盘\' in df.columns}")\n'
        '    logger.info("Expected col: %s", col in ("收盘", "开盘"))\n'
    )
    assert find_cjk_logs_in_source(source, Path("membership.py")) == []


def test_allows_dynamic_runtime_vars_and_cjk_lookup_key_mappings() -> None:
    source = (
        'def run(report_loader, src):\n'
        '    localized = report_loader()\n'
        '    logger.info("Report: %s", localized)\n'
        '    logger.info("Source: %s", {"新浪": "Sina", "腾讯": "Tencent"}.get(src, src))\n'
        '    return localized\n'
    )
    assert find_cjk_logs_in_source(source, Path("dynamic_runtime.py")) == []


def test_detects_inline_and_assigned_cjk_variables_and_dict_values(tmp_path: Path) -> None:
    source = (
        'def run(code):\n'
        '    logger.info("US %s %s route", "AAPL", "首选")\n'
        '    error_summary = "所有数据源获取 AAPL 失败"\n'
        '    logger.error(f"fetch failed: {error_summary}")\n'
        '    logger.error("fetch failed: %s", error_summary)\n'
        '    if code == 403:\n'
        '        err = "余额不足"\n'
        '    else:\n'
        '        err = "HTTP 500"\n'
        '    logger.warning("Failed: %s", err)\n'
        '    dim = {"desc": "最新消息", "name": "latest"}\n'
        '    logger.info("Allowed field: %s", dim["name"])\n'
        '    logger.info("Blocked field: %s", dim["desc"])\n'
    )
    violations = find_cjk_logs_in_source(source, Path("propagated_vars.py"))
    assert [(v.line, v.method) for v in violations] == [
        (2, "info"),
        (4, "error"),
        (5, "error"),
        (10, "warning"),
        (13, "info"),
    ]
    sample_file = tmp_path / "propagated.py"
    sample_file.write_text(
        'error_summary = "所有数据源获取 AAPL 失败"\nlogger.error(f"fetch failed: {error_summary}")\n',
        encoding="utf-8",
    )
    assert main([str(sample_file)]) == 1


def test_detects_container_append_helper_attribute_and_cjk_enum_value() -> None:
    source = (
        'from enum import Enum\n'
        'class CustomStatus(Enum):\n'
        '    HOLD = "观望"\n'
        'def fetch():\n'
        '    errors = []\n'
        '    reason = "数据源未配置"\n'
        '    errors.append(f"[src] {reason}")\n'
        '    logger.error("exhausted: %s", "; ".join(errors))\n'
        'def score():\n'
        '    reasons = []\n'
        '    def add_reason(r):\n'
        '        reasons.append(r)\n'
        '    add_reason("标题命中股票代码 AAPL")\n'
        '    return dict(relevance_reasons=reasons)\n'
        'def rank(top, trend_result, status: CustomStatus):\n'
        '    logger.info("reasons=%s", "; ".join(top.relevance_reasons))\n'
        '    logger.info("trend=%s", trend_result.trend_status.value)\n'
        '    logger.info("status=%s", status.value)\n'
        '    logger.info("safe=%s, count=%d", trend_result.trend_status.name, len(top.relevance_reasons))\n'
    )
    violations = find_cjk_logs_in_source(source, Path("indirect_cjk.py"))
    assert [(v.line, v.method) for v in violations] == [
        (8, "error"),
        (16, "info"),
        (17, "info"),
        (18, "info"),
    ]


def test_trend_analyzer_enum_names_are_english_for_pipeline_logs() -> None:
    import ast
    from scripts.check_english_logs import CJK_RE, find_cjk_logs_in_source

    repo_root = Path(__file__).resolve().parent.parent
    analyzer_tree = ast.parse((repo_root / "src" / "stock_analyzer.py").read_text(encoding="utf-8"))
    enum_members: dict[str, list[str]] = {}
    for node in ast.walk(analyzer_tree):
        if isinstance(node, ast.ClassDef) and node.name in {"TrendStatus", "BuySignal"}:
            enum_members[node.name] = [
                stmt.targets[0].id
                for stmt in node.body
                if isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
            ]
    assert enum_members["TrendStatus"]
    assert enum_members["BuySignal"]
    for names in enum_members.values():
        assert all(CJK_RE.search(name) is None for name in names)

    pipeline_source = (repo_root / "src" / "core" / "pipeline.py").read_text(encoding="utf-8")
    assert "trend_result.trend_status.name" in pipeline_source
    assert "trend_result.buy_signal.name" in pipeline_source
    assert find_cjk_logs_in_source(pipeline_source, repo_root / "src" / "core" / "pipeline.py") == []


def test_cli_exit_code_on_clean_and_dirty_files(tmp_path: Path) -> None:
    clean_file = tmp_path / "clean_mod.py"
    clean_file.write_text('logger.info("Pipeline finished in %.2fs", 1.5)\n', encoding="utf-8")
    assert main([str(clean_file)]) == 0

    dirty_file = tmp_path / "dirty_mod.py"
    dirty_file.write_text('logger.info("流水线完成")\n', encoding="utf-8")
    assert main([str(dirty_file)]) == 1
