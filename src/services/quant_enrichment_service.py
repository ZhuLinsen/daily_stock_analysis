"""Fail-open adapters for ABU/Kronos analysis and vn.py historical validation."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class QuantEnrichmentService:
    def __init__(self, config: Any):
        self.config = config

    @staticmethod
    def _abu_symbol(code: str) -> str:
        normalized = str(code).strip().lower().replace(".sh", "").replace(".sz", "")
        if normalized.startswith(("sh", "sz")):
            return normalized
        digits = "".join(character for character in normalized if character.isdigit())
        if len(digits) != 6:
            raise ValueError(f"仅支持6位A股/ETF代码，收到 {code!r}")
        return ("sh" if digits.startswith(("5", "6", "9")) else "sz") + digits

    def analyze(self, code: str) -> Optional[dict[str, Any]]:
        if not getattr(self.config, "quant_enrichment_enabled", False):
            return None
        try:
            symbol = self._abu_symbol(code)
        except ValueError:
            return {
                "status": "unsupported",
                "error": "当前量化增强仅支持六位A股和ETF代码；美股、港股暂不进入ABU/Kronos/vn.py链路",
            }
        abu_root = Path(getattr(self.config, "quant_abu_root", "")).expanduser()
        abu_config = Path(getattr(self.config, "quant_abu_config", "")).expanduser()
        if not abu_root.is_dir() or not abu_config.is_file():
            logger.warning("量化增强已启用，但ABU路径或配置不存在")
            return {"status": "unavailable", "error": "ABU路径或配置不存在"}
        timeout = max(1, int(getattr(self.config, "quant_enrichment_timeout_seconds", 600)))
        with tempfile.TemporaryDirectory(prefix="dsa-quant-") as tmp:
            tmp_path = Path(tmp)
            batch_path = tmp_path / "abu.json"
            command = [
                getattr(self.config, "quant_abu_python", "") or sys.executable,
                "-m", "daily_signal", "--config", str(abu_config),
                "--symbols", symbol, "--json-output", str(batch_path), "--machine-only",
            ]
            try:
                subprocess.run(command, cwd=abu_root, check=True, timeout=timeout, capture_output=True, text=True)
                batch = json.loads(batch_path.read_text(encoding="utf-8"))
                payload = batch["results"][0]
            except Exception as exc:
                logger.warning("[%s] ABU/Kronos量化增强失败: %s", code, exc)
                return {"status": "unavailable", "error": f"ABU/Kronos运行失败: {type(exc).__name__}"}

            payload["status"] = "ok"
            if getattr(self.config, "quant_vnpy_validation_enabled", True):
                self._attach_validation(payload, tmp_path, timeout)
            payload.pop("history", None)
            return payload

    def _attach_validation(self, payload: dict[str, Any], tmp_path: Path, timeout: int) -> None:
        vnpy_root = Path(getattr(self.config, "quant_vnpy_root", "")).expanduser()
        if not vnpy_root.is_dir():
            payload["validation"] = {"status": "unavailable", "message": "vn.py路径不存在"}
            return
        input_path, output_path = tmp_path / "symbol.json", tmp_path / "validation.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        command = [
            getattr(self.config, "quant_vnpy_python", "") or sys.executable,
            str(vnpy_root / "vnpy" / "alpha" / "signal_validation.py"),
            "--input", str(input_path), "--output", str(output_path), "--horizon", "5",
        ]
        try:
            subprocess.run(command, cwd=vnpy_root, check=True, timeout=timeout, capture_output=True, text=True)
            payload["validation"] = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("vn.py历史验证失败: %s", exc)
            payload["validation"] = {
                "status": "unavailable", "engine": "vnpy.alpha",
                "message": f"历史验证运行失败: {type(exc).__name__}",
            }


def attach_quant_enrichment(result: Any, config: Any) -> None:
    """Attach enhancement without changing DSA's original decision fields."""
    try:
        result.quant_enrichment = QuantEnrichmentService(config).analyze(result.code)
    except Exception as exc:
        logger.warning("[%s] 量化增强已降级，不影响主分析: %s", getattr(result, "code", "?"), exc)
        result.quant_enrichment = {"status": "unavailable", "error": type(exc).__name__}
