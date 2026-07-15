# -*- coding: utf-8 -*-
"""Daily-analysis outcome contract and report artifact validation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from stat import S_ISREG
from typing import Any, Iterable, List, Mapping, Optional, Sequence

OUTCOME_FILENAME = "daily_analysis_outcome.json"
SUCCESS_REASONS = frozenset({"reports_generated"})
SKIP_REASONS = frozenset({"non_trading_day", "reports_not_required"})
FAILURE_REASONS = frozenset({
    "analysis_failed",
    "no_reports_generated",
    "report_evidence_unavailable",
})


class DailyAnalysisOutcomeError(RuntimeError):
    """Raised when outcome evidence is invalid or cannot be persisted."""


@dataclass(frozen=True)
class ReportArtifact:
    """A report file produced by the current run."""

    absolute_path: Path
    relative_path: str
    sha256: str


@dataclass(frozen=True)
class VerifiedDailyAnalysisOutcome:
    """Validated daily-analysis outcome file contents."""

    status: str
    reason: str
    report_artifacts: List[ReportArtifact]


def normalize_project_root(project_root: Path | str) -> Path:
    return Path(project_root).resolve()


def outcome_path_for_log_dir(project_root: Path | str, log_dir: Any) -> Path:
    log_path = Path(str(log_dir or "./logs"))
    if not log_path.is_absolute():
        log_path = normalize_project_root(project_root) / log_path
    return log_path / OUTCOME_FILENAME


def _coerce_report_path(project_root: Path, report_file: Path | str) -> Path:
    path = Path(report_file)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _relative_report_path(project_root: Path, absolute_path: Path) -> str:
    try:
        relative = absolute_path.relative_to(project_root)
    except ValueError as exc:
        raise DailyAnalysisOutcomeError(f"报告文件不在项目目录内: {absolute_path}") from exc
    return relative.as_posix()


def _normalize_sha256(value: Any) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise DailyAnalysisOutcomeError("报告产物缺少有效 sha256 摘要")
    return digest


def _artifact_evidence(report_artifact: Mapping[str, Any] | ReportArtifact) -> tuple[str, str]:
    if isinstance(report_artifact, ReportArtifact):
        return report_artifact.relative_path, report_artifact.sha256
    if not isinstance(report_artifact, Mapping):
        raise DailyAnalysisOutcomeError("报告产物证据格式无效")

    raw_path = report_artifact.get("path")
    if raw_path is None:
        raw_path = report_artifact.get("relative_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise DailyAnalysisOutcomeError("报告产物证据缺少有效路径")
    return raw_path, _normalize_sha256(report_artifact.get("sha256"))


def normalize_report_artifact_payloads(
    report_artifacts: Iterable[Mapping[str, Any] | ReportArtifact],
) -> List[dict[str, str]]:
    payloads_by_path: dict[str, dict[str, str]] = {}
    for report_artifact in report_artifacts:
        path, digest = _artifact_evidence(report_artifact)
        payloads_by_path[path] = {"path": path, "sha256": digest}
    return list(payloads_by_path.values())


def validate_report_artifact(
    project_root: Path | str,
    report_artifact: Mapping[str, Any] | ReportArtifact,
) -> ReportArtifact:
    """Validate one current-run report artifact.

    The compatibility contract is intentionally minimal: producer-returned
    artifacts must be UTF-8, non-empty Markdown files directly under
    ``reports/`` and must still match the producer-captured SHA-256 digest.
    Custom Jinja2 templates may choose their own Markdown shape.
    """

    root = normalize_project_root(project_root)
    raw_path, expected_sha256 = _artifact_evidence(report_artifact)
    absolute_path = _coerce_report_path(root, raw_path)
    relative_path = _relative_report_path(root, absolute_path)
    relative = Path(relative_path)

    if relative.parent != Path("reports") or relative.suffix != ".md":
        raise DailyAnalysisOutcomeError(f"报告路径必须是 reports/*.md: {relative_path}")

    try:
        stat_result = absolute_path.stat()
    except OSError as exc:
        raise DailyAnalysisOutcomeError(f"无法读取报告文件状态: {relative_path}") from exc
    if not S_ISREG(stat_result.st_mode):
        raise DailyAnalysisOutcomeError(f"报告路径不是普通文件: {relative_path}")
    if stat_result.st_size <= 0:
        raise DailyAnalysisOutcomeError(f"报告文件为空: {relative_path}")

    try:
        content_bytes = absolute_path.read_bytes()
    except OSError as exc:
        raise DailyAnalysisOutcomeError(f"无法读取报告文件内容: {relative_path}") from exc

    actual_sha256 = hashlib.sha256(content_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise DailyAnalysisOutcomeError(f"报告文件内容摘要不匹配: {relative_path}")

    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DailyAnalysisOutcomeError(f"报告文件不是有效 UTF-8 Markdown: {relative_path}") from exc
    if not content.strip():
        raise DailyAnalysisOutcomeError(f"报告文件没有有效内容: {relative_path}")

    return ReportArtifact(
        absolute_path=absolute_path,
        relative_path=relative_path,
        sha256=expected_sha256,
    )


def validate_report_artifacts(
    project_root: Path | str,
    report_artifacts: Iterable[Mapping[str, Any] | ReportArtifact],
) -> List[ReportArtifact]:
    artifacts: List[ReportArtifact] = []
    seen: set[tuple[str, str]] = set()
    for report_artifact in normalize_report_artifact_payloads(report_artifacts):
        key = (report_artifact["path"], report_artifact["sha256"])
        if key in seen:
            continue
        seen.add(key)
        artifact = validate_report_artifact(project_root, report_artifact)
        artifacts.append(artifact)
    return artifacts


def _validate_outcome_shape(
    *,
    status: str,
    reason: str,
    report_files: Sequence[str],
    report_artifacts: Sequence[Mapping[str, str]],
) -> None:
    if status == "success":
        if reason not in SUCCESS_REASONS:
            raise DailyAnalysisOutcomeError(f"不支持的成功原因: {reason or 'missing'}")
        if not report_artifacts:
            raise DailyAnalysisOutcomeError("success 状态缺少报告产物证据")
        artifact_paths = [artifact["path"] for artifact in report_artifacts]
        if list(report_files) != artifact_paths:
            raise DailyAnalysisOutcomeError("report_files 与 report_artifacts 不一致")
        return

    if status == "skipped":
        if reason not in SKIP_REASONS:
            raise DailyAnalysisOutcomeError(f"不支持的跳过原因: {reason or 'missing'}")
        if report_files:
            raise DailyAnalysisOutcomeError("skipped 状态不能包含报告文件")
        if report_artifacts:
            raise DailyAnalysisOutcomeError("skipped 状态不能包含报告产物证据")
        return

    if status == "failed":
        if reason not in FAILURE_REASONS:
            raise DailyAnalysisOutcomeError(f"不支持的失败原因: {reason or 'missing'}")
        if report_artifacts:
            raise DailyAnalysisOutcomeError("failed 状态不能包含报告产物证据")
        return

    raise DailyAnalysisOutcomeError(f"不支持的分析状态: {status or 'missing'}")


def write_analysis_outcome(
    outcome_path: Path | str,
    *,
    status: str,
    reason: str,
    report_files: Optional[Sequence[str]] = None,
    report_artifacts: Optional[Sequence[Mapping[str, Any] | ReportArtifact]] = None,
) -> None:
    artifact_payloads = normalize_report_artifact_payloads(report_artifacts or [])
    report_file_list = (
        [artifact["path"] for artifact in artifact_payloads]
        if artifact_payloads
        else list(report_files or [])
    )
    normalized_status = str(status or "").strip().lower()
    normalized_reason = str(reason or "").strip()
    _validate_outcome_shape(
        status=normalized_status,
        reason=normalized_reason,
        report_files=report_file_list,
        report_artifacts=artifact_payloads,
    )

    payload = {
        "status": normalized_status,
        "reason": normalized_reason,
        "report_files": report_file_list,
        "report_artifacts": artifact_payloads,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    path = Path(outcome_path)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as outcome_file:
            outcome_file.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            outcome_file.flush()
            os.fsync(outcome_file.fileno())
        tmp_path.replace(path)
    except OSError as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise DailyAnalysisOutcomeError(f"写入分析结果状态文件失败: {path}") from exc


def verify_daily_analysis_outcome(
    *,
    outcome_path: Path | str,
    project_root: Path | str,
) -> VerifiedDailyAnalysisOutcome:
    path = Path(outcome_path)
    try:
        outcome = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DailyAnalysisOutcomeError(f"分析结果状态文件无法解析: {exc}") from exc

    status = str(outcome.get("status") or "").strip().lower()
    reason = str(outcome.get("reason") or "").strip()
    raw_report_files = outcome.get("report_files")
    if not isinstance(raw_report_files, list):
        raise DailyAnalysisOutcomeError("分析结果状态文件缺少 report_files 数组")
    if not all(isinstance(item, str) and item.strip() for item in raw_report_files):
        raise DailyAnalysisOutcomeError("分析结果状态文件包含无效报告路径")
    raw_report_artifacts = outcome.get("report_artifacts")
    if raw_report_artifacts is None:
        raw_report_artifacts = []
    if not isinstance(raw_report_artifacts, list):
        raise DailyAnalysisOutcomeError("分析结果状态文件 report_artifacts 格式无效")
    artifact_payloads = normalize_report_artifact_payloads(raw_report_artifacts)

    _validate_outcome_shape(
        status=status,
        reason=reason,
        report_files=raw_report_files,
        report_artifacts=artifact_payloads,
    )
    if status == "skipped":
        return VerifiedDailyAnalysisOutcome(
            status=status,
            reason=reason,
            report_artifacts=[],
        )
    if status != "success":
        raise DailyAnalysisOutcomeError(
            f"分析未成功完成: status={status or 'missing'} reason={reason or 'unknown'}"
        )

    return VerifiedDailyAnalysisOutcome(
        status=status,
        reason=reason,
        report_artifacts=validate_report_artifacts(project_root, artifact_payloads),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify daily analysis outcome")
    parser.add_argument("outcome_path", nargs="?", default="logs/daily_analysis_outcome.json")
    parser.add_argument("reports_dir", nargs="?", default="reports")
    args = parser.parse_args(argv)

    outcome_path = Path(args.outcome_path)
    if not outcome_path.is_file():
        print(f"::error::未找到分析结果状态文件: {outcome_path}")
        return 1

    reports_dir = Path(args.reports_dir)
    project_root = reports_dir.parent
    try:
        verified = verify_daily_analysis_outcome(
            outcome_path=outcome_path,
            project_root=project_root,
        )
    except DailyAnalysisOutcomeError as exc:
        print(f"::error::{exc}")
        return 1

    if not verified.report_artifacts:
        print(f"分析按配置跳过: {verified.reason or 'unknown'}")
        return 0

    print("生成的报告:")
    for artifact in verified.report_artifacts:
        print(f"- {artifact.relative_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
