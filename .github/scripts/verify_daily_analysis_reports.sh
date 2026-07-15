#!/usr/bin/env bash
set -euo pipefail

outcome_path="${1:-logs/daily_analysis_outcome.json}"
reports_dir="${2:-reports}"

if [ ! -f "$outcome_path" ]; then
  echo "::error::未找到分析结果状态文件: $outcome_path"
  exit 1
fi

python - "$outcome_path" "$reports_dir" <<'PY'
import json
import sys
from stat import S_ISREG
from pathlib import Path

outcome_path = Path(sys.argv[1])
reports_dir = Path(sys.argv[2])
success_reasons = {"reports_generated"}
skip_reasons = {"non_trading_day", "reports_not_required"}
failure_reasons = {
    "analysis_failed",
    "no_reports_generated",
    "report_baseline_unavailable",
    "report_evidence_unavailable",
}
min_report_non_whitespace_chars = 80


def valid_report_file(report_path):
    try:
        stat_result = report_path.stat()
    except OSError as exc:
        print(f"::error::无法读取报告文件: {report_path}: {exc}")
        return False
    if not S_ISREG(stat_result.st_mode) or report_path.suffix != ".md" or stat_result.st_size <= 0:
        return False

    non_whitespace_chars = 0
    has_heading = False
    try:
        with report_path.open("r", encoding="utf-8") as report_file:
            for _ in range(50):
                line = report_file.readline()
                if line == "":
                    break
                stripped = line.strip()
                non_whitespace_chars += len("".join(stripped.split()))
                normalized = stripped.lstrip("\ufeff")
                if normalized.startswith("# ") or normalized.startswith("## ") or normalized.startswith("### "):
                    has_heading = True
                if has_heading and non_whitespace_chars >= min_report_non_whitespace_chars:
                    return True
    except UnicodeDecodeError:
        print(f"::error::报告文件不是有效 UTF-8 Markdown: {report_path}")
        return False
    return False

try:
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"::error::分析结果状态文件无法解析: {exc}")
    raise SystemExit(1)

status = str(outcome.get("status") or "").strip().lower()
reason = str(outcome.get("reason") or "").strip()
report_files = outcome.get("report_files")
if not isinstance(report_files, list):
    print("::error::分析结果状态文件缺少 report_files 数组")
    raise SystemExit(1)

actual_reports = sorted(
    path
    for path in reports_dir.glob("*.md")
    if valid_report_file(path)
)

if status == "skipped":
    if reason not in skip_reasons:
        print(f"::error::不支持的跳过原因: {reason or 'missing'}")
        raise SystemExit(1)
    if report_files:
        print("::error::跳过状态不能包含报告文件")
        raise SystemExit(1)
    print(f"分析按配置跳过: {reason or 'unknown'}")
    raise SystemExit(0)

if status != "success":
    if status == "failed" and reason not in failure_reasons:
        print(f"::error::不支持的失败原因: {reason or 'missing'}")
        raise SystemExit(1)
    print(f"::error::分析未成功完成: status={status or 'missing'} reason={reason or 'unknown'}")
    raise SystemExit(1)

if reason not in success_reasons:
    print(f"::error::不支持的成功原因: {reason or 'missing'}")
    raise SystemExit(1)

if not actual_reports:
    print("::error::未生成有效 Markdown 报告文件")
    raise SystemExit(1)

validated_reports = []
for raw_path in report_files:
    if not isinstance(raw_path, str) or not raw_path.strip():
        print("::error::分析结果状态文件包含无效报告路径")
        raise SystemExit(1)
    report_path = Path(raw_path)
    if report_path.is_absolute():
        print(f"::error::报告路径必须为相对路径: {raw_path}")
        raise SystemExit(1)
    if report_path.parent != reports_dir:
        print(f"::error::报告路径不在 reports 目录: {raw_path}")
        raise SystemExit(1)
    if report_path.suffix != ".md" or not valid_report_file(report_path):
        print(f"::error::报告文件不存在或不是有效 Markdown 文件: {raw_path}")
        raise SystemExit(1)
    validated_reports.append(report_path)

if not validated_reports:
    print("::error::分析结果状态文件未列出报告文件")
    raise SystemExit(1)

print("生成的报告:")
for report_path in actual_reports:
    print(f"- {report_path}")
PY
