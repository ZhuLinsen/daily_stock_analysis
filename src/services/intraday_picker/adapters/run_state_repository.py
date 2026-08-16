"""JSON run-state persistence for idempotent intraday scans."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Sequence


class JsonRunStateRepository:
    def __init__(self, root: str | Path = "data/intraday_picker/runs"):
        self.root = Path(root)

    def _path(self, run_id: str) -> Path:
        date_key = run_id[:8]
        hhmm = run_id.split("-")[-1]
        return self.root / date_key / f"{hhmm}.json"

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return {str(k): JsonRunStateRepository._jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [JsonRunStateRepository._jsonable(v) for v in value]
        return value

    def _read(self, run_id: str) -> dict[str, Any]:
        path = self._path(run_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write(self, run_id: str, payload: dict[str, Any]) -> None:
        path = self._path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")

    def is_completed(self, run_id: str) -> bool:
        """Return True once a run has produced preliminary output or final output.

        The historical method name is kept for the domain port, but the semantic
        is deliberately "already claimed" so a second scheduler tick cannot
        duplicate Top10 notifications or DSA submissions.
        """
        return self._read(run_id).get("status") in {"preliminary", "completed"}

    def save_preliminary(self, run_id: str, candidates: Sequence[Any], metadata: dict[str, Any]) -> None:
        payload = self._read(run_id)
        payload.update({
            "run_id": run_id,
            "status": "preliminary",
            "metadata": metadata,
            "top10": list(candidates),
        })
        self._write(run_id, payload)

    def save_dsa_tasks(self, run_id: str, task_refs: dict[str, str]) -> None:
        payload = self._read(run_id)
        payload["dsa_tasks"] = task_refs
        self._write(run_id, payload)

    def save_final(self, run_id: str, candidates: Sequence[Any]) -> None:
        payload = self._read(run_id)
        payload.update({"status": "completed", "top5": list(candidates)})
        self._write(run_id, payload)
