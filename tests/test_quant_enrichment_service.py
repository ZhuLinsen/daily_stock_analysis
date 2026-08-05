from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.services.quant_enrichment_service import QuantEnrichmentService, attach_quant_enrichment


def _config(tmp_path: Path, *, enabled: bool = True) -> SimpleNamespace:
    abu_root = tmp_path / "abu"
    vnpy_root = tmp_path / "vnpy"
    abu_root.mkdir()
    vnpy_root.mkdir()
    config_path = abu_root / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    return SimpleNamespace(
        quant_enrichment_enabled=enabled, quant_abu_root=str(abu_root),
        quant_abu_config=str(config_path), quant_vnpy_root=str(vnpy_root),
        quant_abu_python="", quant_vnpy_python="",
        quant_vnpy_validation_enabled=True, quant_enrichment_timeout_seconds=10,
    )


def test_disabled_enrichment_does_not_run(tmp_path):
    assert QuantEnrichmentService(_config(tmp_path, enabled=False)).analyze("588170") is None


def test_symbol_mapping_supports_mainland_etfs(tmp_path):
    service = QuantEnrichmentService(_config(tmp_path))
    assert service._abu_symbol("588170") == "sh588170"
    assert service._abu_symbol("159915") == "sz159915"


def test_non_mainland_symbol_returns_explicit_unsupported_status(tmp_path):
    result = QuantEnrichmentService(_config(tmp_path)).analyze("MU")
    assert result["status"] == "unsupported"
    assert "美股、港股" in result["error"]


def test_runner_result_is_attached_and_history_is_not_persisted(tmp_path):
    config = _config(tmp_path)

    def fake_run(command, **kwargs):
        if "daily_signal" in command:
            output = Path(command[command.index("--json-output") + 1])
            output.write_text(json.dumps({"results": [{
                "symbol": "sh588170", "status": "ok", "as_of": "2026-08-01",
                "history": [{"date": "2026-07-31", "close": 1.2}],
                "technical": {"events": []}, "kronos": None,
            }]}), encoding="utf-8")
        elif "signal_validation.py" in command[1]:
            output = Path(command[command.index("--output") + 1])
            output.write_text(json.dumps({"status": "insufficient_events"}), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    result = SimpleNamespace(code="588170")
    with patch("src.services.quant_enrichment_service.subprocess.run", side_effect=fake_run):
        attach_quant_enrichment(result, config)
    assert result.quant_enrichment["validation"]["status"] == "insufficient_events"
    assert "history" not in result.quant_enrichment


def test_runner_failure_is_fail_open(tmp_path):
    result = SimpleNamespace(code="588170")
    with patch("src.services.quant_enrichment_service.subprocess.run", side_effect=TimeoutError):
        attach_quant_enrichment(result, _config(tmp_path))
    assert result.quant_enrichment["status"] == "unavailable"
