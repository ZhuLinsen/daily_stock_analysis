#!/usr/bin/env bash
set -euo pipefail

outcome_path="${1:-logs/daily_analysis_outcome.json}"
reports_dir="${2:-reports}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"

PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}" \
  python -m src.services.daily_analysis_outcome "$outcome_path" "$reports_dir"
