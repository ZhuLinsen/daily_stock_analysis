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
from pathlib import Path

outcome_path = Path(sys.argv[1])
reports_dir = Path(sys.argv[2])

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
    if path.is_file()
)

if status == "skipped":
    print(f"分析按配置跳过: {reason or 'unknown'}")
    raise SystemExit(0)

if status != "success":
    print(f"::error::分析未成功完成: status={status or 'missing'} reason={reason or 'unknown'}")
    raise SystemExit(1)

if not actual_reports:
    print("::error::未生成报告文件")
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
    if report_path.suffix != ".md" or not report_path.is_file():
        print(f"::error::报告文件不存在或不是 Markdown 文件: {raw_path}")
        raise SystemExit(1)
    validated_reports.append(report_path)

if not validated_reports:
    print("::error::分析结果状态文件未列出报告文件")
    raise SystemExit(1)

print("生成的报告:")
for report_path in actual_reports:
    print(f"- {report_path}")
PY
