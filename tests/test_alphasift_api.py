# -*- coding: utf-8 -*-
"""Tests for the AlphaSift screening endpoints."""

from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from api.v1.endpoints import alphasift as alphasift_endpoint
from src.config import Config, DEFAULT_ALPHASIFT_INSTALL_SPEC

DEFAULT_ALPHASIFT_TEST_SPEC = DEFAULT_ALPHASIFT_INSTALL_SPEC


def _alphasift_unavailable() -> HTTPException:
    return HTTPException(
        status_code=424,
        detail={"error": "alphasift_unavailable", "message": "AlphaSift is unavailable"},
    )


def _raise_alphasift_unavailable() -> None:
    raise _alphasift_unavailable()


def _make_adapter_module(
    *,
    screen=None,
    list_strategies=None,
    get_status=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        screen=screen or MagicMock(return_value=[]),
        list_strategies=list_strategies or (lambda: [{"id": "dual_low", "name": "双低选股", "description": "", "category": "价值"}]),
        get_status=get_status or (lambda: {"supported_markets": ["cn"], "contract_version": "1", "version": "0.2.0", "strategy_count": 1}),
    )


class AlphaSiftOpportunitiesApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        Config.reset_instance()

    def tearDown(self) -> None:
        Config.reset_instance()

    def _config(self, *, enabled: bool, install_spec: str = DEFAULT_ALPHASIFT_TEST_SPEC) -> Config:
        return Config(alphasift_enabled=enabled, alphasift_install_spec=install_spec)

    def _screen(self, config: Config, **kwargs):
        return alphasift_endpoint.alphasift_screen(
            alphasift_endpoint.AlphaSiftScreenRequest(**kwargs),
            config=config,
        )

    def _strategies(self, config: Config):
        return alphasift_endpoint.alphasift_strategies(config=config)

    def test_default_install_spec_is_commit_pinned(self) -> None:
        self.assertRegex(
            DEFAULT_ALPHASIFT_TEST_SPEC,
            r"^git\+https://github\.com/ZhuLinsen/alphasift\.git@[0-9a-f]{40}$",
        )

    def test_status_defaults_to_disabled(self) -> None:
        config = self._config(enabled=False)

        with patch("api.v1.endpoints.alphasift._call_alphasift_status", side_effect=_raise_alphasift_unavailable):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertEqual(payload["enabled"], False)
        self.assertEqual(payload["available"], False)
        self.assertEqual(payload["install_spec_is_default"], True)
        self.assertNotIn("diagnostics", payload)
        self.assertNotIn("install_spec", payload)

    def test_status_marks_custom_install_source(self) -> None:
        config = self._config(enabled=False, install_spec="git+https://example.com/private/alphasift.git")

        with patch("api.v1.endpoints.alphasift._call_alphasift_status", side_effect=_raise_alphasift_unavailable):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertEqual(payload["install_spec_is_default"], False)
        self.assertNotIn("install_spec", payload)

    def test_status_includes_adapter_contract_metadata(self) -> None:
        config = self._config(enabled=True)

        with patch(
            "api.v1.endpoints.alphasift._call_alphasift_status",
            return_value={"available": True, "contract_version": "1", "version": "0.2.0", "strategy_count": 8},
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertTrue(payload["available"])
        self.assertEqual(payload["contract_version"], "1")
        self.assertEqual(payload["version"], "0.2.0")
        self.assertEqual(payload["strategy_count"], 8)

    def test_status_preserves_adapter_available_false_without_diagnostics(self) -> None:
        config = self._config(enabled=False)

        with patch(
            "api.v1.endpoints.alphasift._call_alphasift_status",
            return_value={"available": False, "contract_version": "1", "version": "0.2.0", "strategy_count": 0},
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["contract_version"], "1")
        self.assertNotIn("diagnostics", payload)

    def test_status_logs_and_reports_adapter_runtime_exception_diagnostics(self) -> None:
        config = self._config(enabled=False)
        fake_module = _make_adapter_module(get_status=MagicMock(side_effect=RuntimeError("get_status failed")))

        with (
            patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module),
            self.assertLogs("api.v1.endpoints.alphasift", level="WARNING") as captured,
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "unexpected_exception")
        self.assertEqual(payload["diagnostics"]["stage"], "get_status")
        self.assertEqual(payload["diagnostics"]["error_type"], "RuntimeError")
        self.assertIn("Unexpected AlphaSift get_status failure", "\n".join(captured.output))

    def test_status_logs_and_reports_unexpected_import_exception_diagnostics(self) -> None:
        config = self._config(enabled=False)
        missing_sub_dependency = ModuleNotFoundError("No module named 'optional_dep'", name="optional_dep")

        with (
            patch("api.v1.endpoints.alphasift._prepare_alphasift_runtime_env"),
            patch("api.v1.endpoints.alphasift.importlib.import_module", side_effect=missing_sub_dependency),
            self.assertLogs("api.v1.endpoints.alphasift", level="WARNING") as captured,
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "unexpected_exception")
        self.assertEqual(payload["diagnostics"]["stage"], "import_adapter")
        self.assertEqual(payload["diagnostics"]["error_type"], "ModuleNotFoundError")
        self.assertIn("Unexpected AlphaSift import_adapter failure", "\n".join(captured.output))

    def test_status_logs_and_reports_invalid_get_status_result_diagnostics(self) -> None:
        config = self._config(enabled=False)
        fake_module = _make_adapter_module(get_status=lambda: ["not", "a", "dict"])

        with (
            patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module),
            self.assertLogs("api.v1.endpoints.alphasift", level="WARNING") as captured,
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "unexpected_exception")
        self.assertEqual(payload["diagnostics"]["stage"], "get_status_result")
        self.assertEqual(payload["diagnostics"]["error_type"], "TypeError")
        self.assertIn("Unexpected AlphaSift get_status_result failure", "\n".join(captured.output))

    def test_status_logs_and_reports_missing_get_status_callable_diagnostics(self) -> None:
        config = self._config(enabled=False)
        fake_module = SimpleNamespace(list_strategies=lambda: [], screen=MagicMock(return_value=[]))

        with (
            patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module),
            self.assertLogs("api.v1.endpoints.alphasift", level="WARNING") as captured,
        ):
            payload = alphasift_endpoint.alphasift_status(config=config)

        self.assertFalse(payload["available"])
        self.assertEqual(payload["diagnostics"]["reason"], "unexpected_exception")
        self.assertEqual(payload["diagnostics"]["stage"], "get_status_callable")
        self.assertEqual(payload["diagnostics"]["error_type"], "HTTPException")
        self.assertIn("Unexpected AlphaSift get_status_callable failure", "\n".join(captured.output))

    def test_strategies_returns_adapter_strategies(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            list_strategies=lambda: [
                {"id": "dual_low", "name": "双低选股", "description": "value", "category": "价值"},
                {"id": "trend_quality", "title": "趋势质量", "description": "trend", "tag": "框架"},
            ],
        )

        with patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module):
            payload = self._strategies(config=config)

        self.assertEqual(payload["enabled"], True)
        self.assertEqual(payload["strategy_count"], 2)
        self.assertEqual(payload["strategies"][0]["id"], "dual_low")
        self.assertEqual(payload["strategies"][0]["name"], "双低选股")
        self.assertEqual(payload["strategies"][1]["name"], "趋势质量")

    def test_screen_rejects_when_disabled(self) -> None:
        config = self._config(enabled=False)

        with self.assertRaises(HTTPException) as caught:
            self._screen(config)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "alphasift_disabled")

    def test_screen_rejects_when_alphasift_unavailable(self) -> None:
        config = self._config(enabled=True)

        with (
            patch("api.v1.endpoints.alphasift.subprocess.run") as run_mock,
            patch("api.v1.endpoints.alphasift._import_alphasift", side_effect=_raise_alphasift_unavailable),
        ):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "alphasift_unavailable")
        run_mock.assert_not_called()

    def test_install_rejects_when_disabled_without_side_effects(self) -> None:
        config = self._config(enabled=False)

        with (
            patch("api.v1.endpoints.alphasift.subprocess.run") as run_mock,
            patch("api.v1.endpoints.alphasift._import_alphasift") as import_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                alphasift_endpoint.alphasift_install(config=config)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "alphasift_disabled")
        import_mock.assert_not_called()
        run_mock.assert_not_called()

    def test_install_dependency_requires_admin_auth_enabled(self) -> None:
        request = SimpleNamespace(cookies={})

        with patch("api.v1.endpoints.alphasift.is_auth_enabled", return_value=False):
            with self.assertRaises(HTTPException) as caught:
                alphasift_endpoint._require_admin_session_for_install(request)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "alphasift_install_auth_required")

    def test_install_dependency_requires_valid_admin_session(self) -> None:
        request = SimpleNamespace(cookies={"dsa_session": "session-token"})

        with (
            patch("api.v1.endpoints.alphasift.is_auth_enabled", return_value=True),
            patch("api.v1.endpoints.alphasift.verify_session", return_value=False),
        ):
            with self.assertRaises(HTTPException) as caught:
                alphasift_endpoint._require_admin_session_for_install(request)

        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.detail["error"], "alphasift_install_unauthorized")

    def test_install_dependency_accepts_valid_admin_session(self) -> None:
        request = SimpleNamespace(cookies={"dsa_session": "session-token"})

        with (
            patch("api.v1.endpoints.alphasift.is_auth_enabled", return_value=True),
            patch("api.v1.endpoints.alphasift.verify_session", return_value=True),
        ):
            alphasift_endpoint._require_admin_session_for_install(request)

    def test_install_invokes_pip_when_enabled_and_missing(self) -> None:
        config = self._config(enabled=True)
        completed = SimpleNamespace(returncode=0, stdout="installed", stderr="")

        with (
            patch("api.v1.endpoints.alphasift._is_alphasift_available", side_effect=[False, True]),
            patch(
                "api.v1.endpoints.alphasift._call_alphasift_status",
                return_value={"available": True, "supported_markets": ["cn"], "contract_version": "1", "version": "0.2.0", "strategy_count": 1},
            ),
            patch("api.v1.endpoints.alphasift.subprocess.run", return_value=completed) as run_mock,
            patch("api.v1.endpoints.alphasift._get_dsa_adapter", return_value=_make_adapter_module()),
        ):
            payload = alphasift_endpoint.alphasift_install(config=config)

        self.assertEqual(payload["installed"], True)
        self.assertEqual(payload["already_installed"], False)
        self.assertEqual(payload["install_spec_is_default"], True)
        self.assertNotIn("install_spec", payload)
        run_mock.assert_called_once()
        self.assertIn(DEFAULT_ALPHASIFT_TEST_SPEC, run_mock.call_args.args[0])

    def test_install_rejects_when_alphasift_adapter_reports_unavailable(self) -> None:
        config = self._config(enabled=True)
        completed = SimpleNamespace(returncode=0, stdout="installed", stderr="")

        with (
            patch(
                "api.v1.endpoints.alphasift._call_alphasift_status",
                side_effect=[
                    {"available": False},
                    {"available": False},
                ],
            ),
            patch("api.v1.endpoints.alphasift.subprocess.run", return_value=completed) as run_mock,
            patch("api.v1.endpoints.alphasift._get_dsa_adapter") as get_adapter_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                alphasift_endpoint.alphasift_install(config=config)

        self.assertEqual(caught.exception.status_code, 424)
        self.assertEqual(caught.exception.detail["error"], "alphasift_unavailable")
        run_mock.assert_called_once()
        get_adapter_mock.assert_not_called()

    def test_install_rejects_untrusted_spec(self) -> None:
        config = self._config(enabled=True, install_spec="git+https://example.com/private/alphasift.git")

        with (
            patch("api.v1.endpoints.alphasift._is_alphasift_available", return_value=False),
            patch("api.v1.endpoints.alphasift.subprocess.run") as run_mock,
        ):
            with self.assertRaises(HTTPException) as caught:
                alphasift_endpoint.alphasift_install(config=config)

        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.detail["error"], "alphasift_install_spec_not_allowed")
        run_mock.assert_not_called()

    def test_screen_calls_dsa_adapter_and_normalizes_llm_fields(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            screen=MagicMock(
                return_value={
                    "run_id": "run123",
                    "strategy": "dual_low",
                    "market": "cn",
                    "snapshot_count": 100,
                    "after_filter_count": 5,
                    "llm_ranked": True,
                    "llm_coverage": 1.0,
                    "warnings": ["fallback"],
                    "source_errors": [],
                    "candidates": [
                        {
                            "code": "600519",
                            "name": "Kweichow Moutai",
                            "score": 88.5,
                            "llm_score": 90.0,
                            "llm_thesis": "LLM likes the setup",
                            "risk_level": "medium",
                            "risk_flags": ["valuation"],
                            "price": 1688.0,
                            "industry": "Baijiu",
                            "factor_scores": {"value": 88.0},
                        }
                    ],
                }
            ),
        )

        with patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        fake_module.screen.assert_called_once_with(
            "dual_low",
            market="cn",
            max_results=5,
            use_llm=True,
        )
        self.assertEqual(payload["run_id"], "run123")
        self.assertEqual(payload["snapshot_count"], 100)
        self.assertEqual(payload["after_filter_count"], 5)
        self.assertEqual(payload["llm_ranked"], True)
        self.assertEqual(payload["llm_coverage"], 1.0)
        self.assertEqual(payload["warnings"], ["fallback"])
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["candidates"][0]["code"], "600519")
        self.assertEqual(payload["candidates"][0]["llm_score"], 90.0)
        self.assertEqual(payload["candidates"][0]["llm_thesis"], "LLM likes the setup")
        self.assertEqual(payload["candidates"][0]["risk_level"], "medium")
        self.assertEqual(payload["candidates"][0]["price"], 1688.0)
        self.assertEqual(payload["candidates"][0]["industry"], "Baijiu")

    def test_screen_normalizes_non_finite_values(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            screen=MagicMock(
                return_value={
                    "picks": [
                        {
                            "code": "600519",
                            "name": "Kweichow Moutai",
                            "score": float("nan"),
                            "ranking_reason": "AlphaSift pick",
                            "nested": {"pe": float("inf"), "pb": float("-inf"), "eps": 20.5},
                        },
                    ],
                }
            ),
        )

        with patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module):
            payload = self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertIsNone(payload["candidates"][0]["score"])
        self.assertIsNone(payload["candidates"][0]["raw"]["score"])
        self.assertIsNone(payload["candidates"][0]["raw"]["nested"]["pe"])
        self.assertIsNone(payload["candidates"][0]["raw"]["nested"]["pb"])

    def test_screen_allows_non_listed_strategy_as_custom(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            list_strategies=lambda: [{"id": "dual_low", "name": "双低选股"}],
            screen=MagicMock(return_value={"candidates": []}),
        )

        with patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module):
            payload = self._screen(config, market="cn", strategy="custom_alpha", max_results=5)

        fake_module.screen.assert_called_once_with(
            "custom_alpha",
            market="cn",
            max_results=5,
            use_llm=True,
        )
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(payload["candidate_count"], 0)

    def test_screen_rejects_unsupported_market(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            get_status=lambda: {"supported_markets": ["hk", "us"]},
            screen=MagicMock(return_value=[]),
        )

        with patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.detail["error"], "alphasift_invalid_market")

    def test_screen_maps_adapter_value_error_to_bad_request(self) -> None:
        config = self._config(enabled=True)
        fake_module = _make_adapter_module(
            screen=MagicMock(side_effect=ValueError("Only market='cn' is currently supported")),
        )

        with patch("api.v1.endpoints.alphasift._import_alphasift", return_value=fake_module):
            with self.assertRaises(HTTPException) as caught:
                self._screen(config, market="cn", strategy="dual_low", max_results=5)

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.detail["error"], "alphasift_screen_rejected")


if __name__ == "__main__":
    unittest.main()
