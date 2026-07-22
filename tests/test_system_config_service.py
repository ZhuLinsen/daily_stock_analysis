# -*- coding: utf-8 -*-
"""Unit tests for system configuration service."""

import os
import json
import logging
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch

import requests

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from src.config import ANSPIRE_LLM_MODEL_DEFAULT, DEFAULT_ALPHASIFT_INSTALL_SPEC, Config
from src.core.config_manager import ConfigManager
from src.llm.backend_registry import GENERATION_ONLY_BACKEND_IDS
from src.services.system_config_service import ConfigConflictError, ConfigImportError, ConfigValidationError, SystemConfigService


class SystemConfigServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519,000001",
                    "GEMINI_API_KEY=secret-key-value",
                    "SCHEDULE_TIME=18:00",
                    "LOG_LEVEL=INFO",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        Config.reset_instance()

        self.manager = ConfigManager(env_path=self.env_path)
        self.service = SystemConfigService(manager=self.manager)

    def tearDown(self) -> None:
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        self.temp_dir.cleanup()

    def _rewrite_env(self, *lines: str) -> None:
        self.env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        Config.reset_instance()
        self.manager = ConfigManager(env_path=self.env_path)
        self.service = SystemConfigService(manager=self.manager)

    @staticmethod
    def _mock_completion_response(content: str = "OK", tool_calls=None):
        message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    def test_get_config_keeps_regular_sensitive_values_unmasked(self) -> None:
        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertIn("GEMINI_API_KEY", items)
        self.assertEqual(items["GEMINI_API_KEY"]["value"], "secret-key-value")
        self.assertFalse(items["GEMINI_API_KEY"]["is_masked"])
        self.assertTrue(items["GEMINI_API_KEY"]["raw_value_exists"])

    def _assert_agent_backend_status_matches_runtime(
        self,
        *,
        saved_backend: str,
        runtime_backend: str,
    ) -> None:
        from src.agent.agent_backend import resolve_agent_backend_id
        from src.services.agent_backend_status_service import AgentBackendStatusService

        self._rewrite_env(
            "GEMINI_API_KEY=secret-key-value",
            f"AGENT_BACKEND={saved_backend}",
            "AGENT_ARCH=single",
        )
        codex_status = {
            "backend": "codex_app_server",
            "available": True,
            "experimental": True,
            "version": "codex-cli test",
            "error_code": None,
            "message": None,
        }
        with (
            patch.dict(os.environ, {"AGENT_BACKEND": runtime_backend}),
            patch.object(
                AgentBackendStatusService,
                "_codex_cheap_status",
                return_value=codex_status,
            ),
        ):
            Config.reset_instance()
            runtime_config = Config.get_instance()
            with patch.dict(os.environ, {"AGENT_BACKEND": saved_backend}):
                settings_status = self.service.get_agent_backend_status()
                chat_status = AgentBackendStatusService(config=runtime_config).get_status()
                selected_backend = resolve_agent_backend_id(runtime_config)
                preview_baseline = self.service.preview_agent_backend_status(items=[])
                preview_draft = self.service.preview_agent_backend_status(
                    items=[{"key": "AGENT_BACKEND", "value": saved_backend}],
                )

        self.assertEqual(settings_status["backend"], runtime_backend)
        self.assertEqual(chat_status["backend"], runtime_backend)
        self.assertEqual(selected_backend, runtime_backend)
        self.assertEqual(preview_baseline["backend"], runtime_backend)
        self.assertEqual(preview_draft["backend"], saved_backend)
        self.assertIs(Config.get_instance(), runtime_config)

    def test_agent_backend_status_prefers_runtime_litellm_over_saved_codex(self) -> None:
        self._assert_agent_backend_status_matches_runtime(
            saved_backend="codex_app_server",
            runtime_backend="litellm",
        )

    def test_agent_backend_status_prefers_runtime_codex_over_saved_litellm(self) -> None:
        self._assert_agent_backend_status_matches_runtime(
            saved_backend="litellm",
            runtime_backend="codex_app_server",
        )

    def test_agent_backend_empty_preview_uses_runtime_generation_route(self) -> None:
        from src.services.agent_backend_status_service import AgentBackendStatusService

        self._rewrite_env(
            "AGENT_BACKEND=litellm",
            "LITELLM_MODEL=",
            "OPENAI_API_KEY=",
        )
        runtime_env = {
            "ENV_FILE": str(self.env_path),
            "AGENT_BACKEND": "litellm",
            "LITELLM_MODEL": "openai/gpt-4o",
            "OPENAI_API_KEY": "runtime-key",
        }
        with patch.dict(os.environ, runtime_env, clear=True):
            Config.reset_instance()
            runtime_config = Config.get_instance()
            settings_status = self.service.get_agent_backend_status()
            chat_status = AgentBackendStatusService(config=runtime_config).get_status()
            preview_baseline = self.service.preview_agent_backend_status(items=[])
            preview_draft = self.service.preview_agent_backend_status(
                items=[
                    {"key": "LITELLM_MODEL", "value": ""},
                    {"key": "OPENAI_API_KEY", "value": ""},
                ],
            )

        self.assertEqual(settings_status, chat_status)
        self.assertEqual(preview_baseline, chat_status)
        self.assertTrue(chat_status["available"])
        self.assertFalse(preview_draft["available"])
        self.assertEqual(preview_draft["message"], "no_agent_primary")

    def test_get_config_masks_alphasift_install_spec(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "ALPHASIFT_INSTALL_SPEC=git+https://user:token@example.com/internal/alphasift.git",
        )

        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertEqual(items["ALPHASIFT_INSTALL_SPEC"]["value"], payload["mask_token"])
        self.assertTrue(items["ALPHASIFT_INSTALL_SPEC"]["is_masked"])
        self.assertTrue(items["ALPHASIFT_INSTALL_SPEC"]["schema"]["is_sensitive"])

    def test_get_config_masks_hermes_secret_fields(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "LLM_CHANNELS=hermes",
            "LLM_HERMES_API_KEY=sk-hermes-secret-value",
            "LLM_HERMES_API_KEYS=sk-old-secret-value",
            "LLM_HERMES_EXTRA_HEADERS={\"Authorization\":\"Bearer secret\"}",
        )

        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertEqual(items["LLM_HERMES_API_KEY"]["value"], payload["mask_token"])
        self.assertTrue(items["LLM_HERMES_API_KEY"]["is_masked"])
        self.assertEqual(items["LLM_HERMES_API_KEYS"]["value"], payload["mask_token"])
        self.assertTrue(items["LLM_HERMES_API_KEYS"]["is_masked"])
        self.assertEqual(items["LLM_HERMES_EXTRA_HEADERS"]["value"], payload["mask_token"])
        self.assertTrue(items["LLM_HERMES_EXTRA_HEADERS"]["is_masked"])

    def test_hermes_saved_secret_changed_port_does_not_send_request(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "LLM_CHANNELS=hermes",
            "LLM_HERMES_PROTOCOL=openai",
            "LLM_HERMES_BASE_URL=http://127.0.0.1:8642/v1",
            "LLM_HERMES_API_KEY=sk-hermes-secret-value",
        )

        with patch("src.services.system_config_service.requests.Session") as session_cls:
            result = self.service.discover_llm_channel_models(
                name="hermes",
                protocol="openai",
                base_url="http://127.0.0.1:9999/v1",
                api_key="******",
                models=["hermes-agent"],
                use_saved_secret=True,
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "saved_secret_scope_mismatch")
        session_cls.assert_not_called()

    def test_hermes_saved_secret_runtime_env_cannot_rebind_endpoint(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "LLM_CHANNELS=hermes",
            "LLM_HERMES_PROTOCOL=openai",
            "LLM_HERMES_BASE_URL=http://127.0.0.1:8642/v1",
            "LLM_HERMES_API_KEY=saved-secret-token",
        )

        with patch.dict(os.environ, {"LLM_HERMES_BASE_URL": "http://127.0.0.1:9999/v1"}, clear=False), \
             patch("src.services.system_config_service.requests.Session") as session_cls:
            result = self.service.discover_llm_channel_models(
                name="hermes",
                protocol="openai",
                base_url="http://127.0.0.1:9999/v1",
                api_key="******",
                models=["hermes-agent"],
                use_saved_secret=True,
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "saved_secret_scope_mismatch")
        self.assertNotIn("saved-secret-token", str(result))
        session_cls.assert_not_called()

    def test_hermes_model_discovery_uses_no_proxy_session(self) -> None:
        observed: Dict[str, Any] = {}

        class FakeSession:
            def __init__(self) -> None:
                self.trust_env = True

            def get(self, url: str, **kwargs: Any) -> Any:
                observed["url"] = url
                observed["trust_env"] = self.trust_env
                observed["headers"] = kwargs.get("headers") or {}
                return SimpleNamespace(
                    status_code=200,
                    ok=True,
                    json=lambda: {"data": [{"id": "hermes-agent"}]},
                )

            def close(self) -> None:
                observed["closed"] = True

        with patch("src.services.system_config_service.requests.Session", side_effect=FakeSession), \
             patch("src.services.system_config_service.requests.get") as requests_get:
            result = self.service.discover_llm_channel_models(
                name="hermes",
                protocol="openai",
                base_url="http://localhost:8642/v1",
                api_key="sk-hermes-secret-value",
                models=["hermes-agent"],
            )

        self.assertTrue(result["success"])
        self.assertEqual(observed["url"], "http://127.0.0.1:8642/v1/models")
        self.assertFalse(observed["trust_env"])
        self.assertEqual(observed["headers"]["Authorization"], "Bearer sk-hermes-secret-value")
        self.assertTrue(observed["closed"])
        requests_get.assert_not_called()

    def test_hermes_model_discovery_invalid_url_fails_before_request(self) -> None:
        with patch("src.services.system_config_service.requests.Session") as session_cls:
            result = self.service.discover_llm_channel_models(
                name="hermes",
                protocol="openai",
                base_url="http://127.0.0.1:8642/v1?next=proxy",
                api_key="saved-secret-token",
                models=["hermes-agent"],
            )

        rendered = json.dumps(result, ensure_ascii=False, default=str)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "invalid_config")
        self.assertEqual(result["details"]["reason"], "invalid_hermes_url")
        self.assertNotIn("saved-secret-token", rendered)
        session_cls.assert_not_called()

    def test_hermes_model_discovery_http_error_redacts_non_sk_secret(self) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.trust_env = True

            def get(self, *_args: Any, **_kwargs: Any) -> Any:
                return SimpleNamespace(
                    status_code=500,
                    ok=False,
                    json=lambda: {"error": {"message": "upstream saw saved-secret-token"}},
                    text="upstream saw saved-secret-token",
                )

            def close(self) -> None:
                pass

        with patch("src.services.system_config_service.requests.Session", side_effect=FakeSession):
            result = self.service.discover_llm_channel_models(
                name="hermes",
                protocol="openai",
                base_url="http://127.0.0.1:8642/v1",
                api_key="saved-secret-token",
                models=["hermes-agent"],
            )

        rendered = json.dumps(result, ensure_ascii=False, default=str)
        self.assertFalse(result["success"])
        self.assertNotIn("saved-secret-token", rendered)
        self.assertNotIn("Bearer saved-secret-token", rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_llm_result_redacts_raw_comma_secret_and_segments(self) -> None:
        raw_secret = "saved-secret-token,second-part"
        redactions = self.service._build_redaction_values(raw_secret)
        variants = [
            "Bearer saved-secret-token,second-part",
            "Bearer saved-secret-token, second-part",
            "Bearer saved-secret-token ,second-part",
            "Authorization: Bearer saved-secret-token,   second-part",
            "upstream saw saved-secret-token, second-part",
        ]

        result = self.service._build_llm_channel_result(
            success=False,
            message="; ".join(variants),
            error=" | ".join(variants),
            stage="model_discovery",
            error_code="network_error",
            retryable=False,
            details={
                "raw": raw_secret,
                "variants": variants,
                "first": "saved-secret-token",
                "second": "second-part",
            },
            capability_results={
                "json": {
                    "status": "failed",
                    "message": variants[1],
                    "details": {"echo": variants[3]},
                }
            },
            resolved_protocol="openai",
            models=[],
            latency_ms=None,
            redaction_values=redactions,
        )

        rendered = json.dumps(result, ensure_ascii=False, default=str)
        self.assertNotIn(raw_secret, rendered)
        for variant in variants:
            self.assertNotIn(variant, rendered)
        self.assertNotIn("saved-secret-token", rendered)
        self.assertNotIn("second-part", rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_llm_result_recursively_redacts_models_details_and_capabilities(self) -> None:
        raw_secret = "saved-secret-token,second-part"
        redactions = self.service._build_redaction_values(raw_secret)

        details = self.service._sanitize_llm_details(
            {
                "items": [
                    {"message": "saved-secret-token"},
                    [{"nested": "Bearer saved-secret-token, second-part"}],
                ],
                "saved-secret-token": "second-part",
            },
            redaction_values=redactions,
        )
        result = self.service._build_llm_channel_result(
            success=False,
            message="upstream saw saved-secret-token, second-part",
            error="Authorization: Bearer saved-secret-token,   second-part",
            stage="model_discovery",
            error_code="network_error",
            retryable=False,
            details=details,
            resolved_protocol="openai",
            resolved_model="saved-secret-token",
            models=["saved-secret-token", ["second-part"]],
            capability_results={
                "json": {
                    "status": "failed",
                    "details": {"items": [{"message": "saved-secret-token"}]},
                }
            },
            redaction_values=redactions,
        )

        rendered = json.dumps(result, ensure_ascii=False, default=str)
        self.assertNotIn(raw_secret, rendered)
        self.assertNotIn("saved-secret-token, second-part", rendered)
        self.assertNotIn("saved-secret-token", rendered)
        self.assertNotIn("second-part", rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_hermes_model_discovery_request_exception_redacts_response_and_logs(self) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.trust_env = True

            def get(self, *_args: Any, **_kwargs: Any) -> Any:
                raise requests.RequestException("proxy saw saved-secret-token")

            def close(self) -> None:
                pass

        with patch("src.services.system_config_service.requests.Session", side_effect=FakeSession), \
             self.assertLogs("src.services.system_config_service", level="WARNING") as logs:
            result = self.service.discover_llm_channel_models(
                name="hermes",
                protocol="openai",
                base_url="http://127.0.0.1:8642/v1",
                api_key="saved-secret-token",
                models=["hermes-agent"],
            )

        rendered = json.dumps(result, ensure_ascii=False, default=str)
        log_text = "\n".join(logs.output)
        self.assertFalse(result["success"])
        self.assertNotIn("saved-secret-token", rendered)
        self.assertNotIn("saved-secret-token", log_text)
        self.assertIn("[REDACTED]", rendered)
        self.assertIn("[REDACTED]", log_text)

    def test_hermes_request_exception_redacts_comma_secret_variants_from_logs(self) -> None:
        raw_secret = "saved-secret-token,second-part"
        variants = [
            "Bearer saved-secret-token,second-part",
            "Bearer saved-secret-token, second-part",
            "Bearer saved-secret-token ,second-part",
            "Authorization: Bearer saved-secret-token,   second-part",
            "upstream saw saved-secret-token, second-part",
        ]
        redactions = self.service._build_redaction_values(raw_secret)
        sanitized = self.service._sanitize_llm_error_text(
            " | ".join(variants),
            redaction_values=redactions,
        )
        with self.assertLogs("src.services.system_config_service", level="WARNING") as logs:
            logging.getLogger("src.services.system_config_service").warning(
                "LLM channel model discovery failed for hermes: %s",
                sanitized,
            )

        log_text = "\n".join(logs.output)
        self.assertNotIn(raw_secret, log_text)
        self.assertNotIn("saved-secret-token, second-part", log_text)
        self.assertNotIn("saved-secret-token", log_text)
        self.assertNotIn("second-part", log_text)
        for variant in variants:
            self.assertNotIn(variant, log_text)
        self.assertIn("[REDACTED]", log_text)

    def test_hermes_channel_test_invalid_url_fails_before_completion(self) -> None:
        with patch("src.services.system_config_service.open_hermes_no_proxy_client") as no_proxy_client, \
             patch("litellm.completion") as completion:
            result = self.service.test_llm_channel(
                name="hermes",
                protocol="openai",
                base_url="http://127.0.0.1:8642/v1#fragment",
                api_key="saved-secret-token",
                models=["hermes-agent"],
                capability_checks=["json"],
            )

        rendered = json.dumps(result, ensure_ascii=False, default=str)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "invalid_config")
        self.assertEqual(result["details"]["reason"], "invalid_hermes_url")
        self.assertEqual(result["capability_results"]["json"]["status"], "skipped")
        self.assertNotIn("saved-secret-token", rendered)
        no_proxy_client.assert_not_called()
        completion.assert_not_called()

    def test_hermes_runtime_only_masked_key_is_not_sent_for_channel_test(self) -> None:
        with patch("src.services.system_config_service.open_hermes_no_proxy_client") as no_proxy_client, \
             patch("litellm.completion") as completion:
            result = self.service.test_llm_channel(
                name="hermes",
                protocol="openai",
                base_url="http://127.0.0.1:8642/v1",
                api_key="******",
                models=["hermes-agent"],
                use_saved_secret=False,
                capability_checks=["json"],
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "runtime_secret_not_reusable")
        self.assertEqual(result["details"]["reason"], "runtime_secret_not_reusable")
        self.assertEqual(result["capability_results"]["json"]["status"], "skipped")
        no_proxy_client.assert_not_called()
        completion.assert_not_called()

    def test_hermes_masked_key_is_not_sent_for_model_discovery(self) -> None:
        with patch("src.services.system_config_service.requests.Session") as session_cls:
            result = self.service.discover_llm_channel_models(
                name="hermes",
                protocol="openai",
                base_url="http://127.0.0.1:8642/v1",
                api_key="******",
                models=["hermes-agent"],
                use_saved_secret=False,
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "runtime_secret_not_reusable")
        self.assertEqual(result["details"]["reason"], "runtime_secret_not_reusable")
        session_cls.assert_not_called()

    def test_hermes_saved_literal_masked_key_is_not_reused(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "LLM_CHANNELS=hermes",
            "LLM_HERMES_BASE_URL=http://127.0.0.1:8642/v1",
            "LLM_HERMES_API_KEY=******",
        )

        with patch("src.services.system_config_service.open_hermes_no_proxy_client") as no_proxy_client, \
             patch("litellm.completion") as completion:
            result = self.service.test_llm_channel(
                name="hermes",
                protocol="openai",
                base_url="http://127.0.0.1:8642/v1",
                api_key="******",
                models=["hermes-agent"],
                use_saved_secret=True,
            )

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "runtime_secret_not_reusable")
        no_proxy_client.assert_not_called()
        completion.assert_not_called()

    def test_hermes_channel_test_rejects_comma_api_key_before_outbound(self) -> None:
        raw_key = "key-a,key-b"
        with patch("src.services.system_config_service.open_hermes_no_proxy_client") as no_proxy_client, \
             patch("litellm.completion") as completion:
            result = self.service.test_llm_channel(
                name="hermes",
                protocol="openai",
                base_url="http://127.0.0.1:8642/v1",
                api_key=raw_key,
                models=["hermes-agent"],
                capability_checks=["json"],
            )

        rendered = json.dumps(result, ensure_ascii=False, default=str)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "invalid_config")
        self.assertEqual(result["details"]["reason"], "multiple_api_keys")
        self.assertNotIn(raw_key, rendered)
        self.assertNotIn("key-a", rendered)
        self.assertNotIn("key-b", rendered)
        no_proxy_client.assert_not_called()
        completion.assert_not_called()

    def test_hermes_model_discovery_rejects_comma_api_key_before_outbound(self) -> None:
        raw_key = "key-a,key-b"
        with patch("src.services.system_config_service.requests.Session") as session_cls:
            result = self.service.discover_llm_channel_models(
                name="hermes",
                protocol="openai",
                base_url="http://127.0.0.1:8642/v1",
                api_key=raw_key,
                models=["hermes-agent"],
            )

        rendered = json.dumps(result, ensure_ascii=False, default=str)
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "invalid_config")
        self.assertEqual(result["details"]["reason"], "multiple_api_keys")
        self.assertNotIn(raw_key, rendered)
        self.assertNotIn("key-a", rendered)
        self.assertNotIn("key-b", rendered)
        session_cls.assert_not_called()

    def test_hermes_unsupported_capabilities_are_skipped_without_probe(self) -> None:
        no_proxy_calls: List[Dict[str, Any]] = []
        completion_models: List[str] = []

        @contextmanager
        def fake_no_proxy_openai_client(**kwargs: Any):
            no_proxy_calls.append(kwargs)
            yield object()

        def fake_completion(**kwargs: Any) -> Any:
            completion_models.append(str(kwargs.get("model") or ""))
            self.assertFalse(kwargs.get("stream"))
            self.assertIn("client", kwargs)
            self.assertNotIn("api_key", kwargs)
            self.assertNotIn("api_base", kwargs)
            return self._mock_completion_response("OK")

        with patch("src.services.system_config_service.open_hermes_no_proxy_client", fake_no_proxy_openai_client), \
             patch("litellm.completion", side_effect=fake_completion):
            result = self.service.test_llm_channel(
                name="hermes",
                protocol="openai",
                base_url="http://127.0.0.1:8642/v1",
                api_key="sk-hermes-secret-value",
                models=["hermes-agent"],
                capability_checks=["tools", "stream", "vision"],
            )

        self.assertTrue(result["success"])
        self.assertEqual(len(no_proxy_calls), 1)
        self.assertEqual(completion_models, ["openai/hermes-agent"])
        capability_results = result["capability_results"]
        self.assertEqual(set(capability_results), {"tools", "stream", "vision"})
        for capability in ("tools", "stream", "vision"):
            self.assertEqual(capability_results[capability]["status"], "skipped")
            self.assertEqual(capability_results[capability]["error_code"], "not_probed")

    def test_hermes_failure_redacts_non_sk_secret_from_response_and_logs(self) -> None:
        @contextmanager
        def fake_no_proxy_openai_client(**_kwargs: Any):
            yield object()

        def fake_completion(**_kwargs: Any) -> Any:
            raise RuntimeError("upstream echoed saved-secret-token")

        with patch("src.services.system_config_service.open_hermes_no_proxy_client", fake_no_proxy_openai_client), \
             patch("litellm.completion", side_effect=fake_completion), \
             self.assertLogs("src.services.system_config_service", level="WARNING") as logs:
            result = self.service.test_llm_channel(
                name="hermes",
                protocol="openai",
                base_url="http://127.0.0.1:8642/v1",
                api_key="saved-secret-token",
                models=["hermes-agent"],
            )

        self.assertFalse(result["success"])
        self.assertNotIn("saved-secret-token", str(result))
        self.assertNotIn("saved-secret-token", "\n".join(logs.output))

    def test_hermes_json_capability_exception_redacts_non_sk_secret(self) -> None:
        @contextmanager
        def fake_no_proxy_openai_client(**_kwargs: Any):
            yield object()

        completion_calls = 0

        def fake_completion(**_kwargs: Any) -> Any:
            nonlocal completion_calls
            completion_calls += 1
            if completion_calls == 1:
                return self._mock_completion_response("OK")
            raise RuntimeError("json capability saw saved-secret-token")

        with patch("src.services.system_config_service.open_hermes_no_proxy_client", fake_no_proxy_openai_client), \
             patch("litellm.completion", side_effect=fake_completion):
            result = self.service.test_llm_channel(
                name="hermes",
                protocol="openai",
                base_url="http://127.0.0.1:8642/v1",
                api_key="saved-secret-token",
                models=["hermes-agent"],
                capability_checks=["json"],
            )

        rendered = json.dumps(result, ensure_ascii=False, default=str)
        self.assertTrue(result["success"])
        self.assertEqual(result["capability_results"]["json"]["status"], "failed")
        self.assertNotIn("saved-secret-token", rendered)
        self.assertIn("[REDACTED]", rendered)

    def test_get_config_masks_llm_usage_hmac_secret(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "LLM_USAGE_HMAC_SECRET=telemetry-secret",
            "LLM_USAGE_HMAC_KEY_VERSION=test-v1",
        )

        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertEqual(items["LLM_USAGE_HMAC_SECRET"]["value"], payload["mask_token"])
        self.assertTrue(items["LLM_USAGE_HMAC_SECRET"]["is_masked"])
        self.assertTrue(items["LLM_USAGE_HMAC_SECRET"]["schema"]["is_sensitive"])
        self.assertEqual(items["LLM_USAGE_HMAC_KEY_VERSION"]["value"], "test-v1")
        self.assertFalse(items["LLM_USAGE_HMAC_KEY_VERSION"]["is_masked"])

    def test_get_config_uses_switch_default_for_missing_report_model_toggle(self) -> None:
        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertEqual(items["REPORT_SHOW_LLM_MODEL"]["value"], "true")
        self.assertFalse(items["REPORT_SHOW_LLM_MODEL"]["raw_value_exists"])

        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "GEMINI_API_KEY=secret-key-value",
            "SCHEDULE_TIME=18:00",
            "LOG_LEVEL=INFO",
            "REPORT_SHOW_LLM_MODEL=false",
        )

        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertEqual(items["REPORT_SHOW_LLM_MODEL"]["value"], "false")
        self.assertTrue(items["REPORT_SHOW_LLM_MODEL"]["raw_value_exists"])

    def test_get_config_preserves_manual_agent_codex_cli_value_without_schema_option(self) -> None:
        for backend in sorted(GENERATION_ONLY_BACKEND_IDS):
            with self.subTest(backend=backend):
                self._rewrite_env(
                    "STOCK_LIST=600519,000001",
                    f"AGENT_GENERATION_BACKEND={backend}",
                )

                payload = self.service.get_config(include_schema=True)
                items = {item["key"]: item for item in payload["items"]}
                agent_item = items["AGENT_GENERATION_BACKEND"]

                self.assertEqual(agent_item["value"], backend)
                self.assertNotIn(
                    backend,
                    {option["value"] for option in agent_item["schema"]["options"]},
                )

    def test_get_config_preserves_explicit_empty_switch_value(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "GEMINI_API_KEY=secret-key-value",
            "SCHEDULE_TIME=18:00",
            "LOG_LEVEL=INFO",
            "WEBHOOK_VERIFY_SSL=",
        )

        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertEqual(items["WEBHOOK_VERIFY_SSL"]["value"], "")
        self.assertTrue(items["WEBHOOK_VERIFY_SSL"]["raw_value_exists"])

    def test_get_config_preserves_explicit_empty_report_show_llm_model_value(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "GEMINI_API_KEY=secret-key-value",
            "SCHEDULE_TIME=18:00",
            "LOG_LEVEL=INFO",
            "REPORT_SHOW_LLM_MODEL=",
        )

        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertEqual(items["REPORT_SHOW_LLM_MODEL"]["value"], "")
        self.assertTrue(items["REPORT_SHOW_LLM_MODEL"]["raw_value_exists"])

    def test_get_config_uses_runtime_env_as_display_fallback(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519",
            "LOG_LEVEL=INFO",
        )

        with patch.dict(
            os.environ,
            {
                "STOCK_LIST": "300750",
                "LITELLM_MODEL": "openai/gpt-5",
                "LLM_CHANNELS": "my_proxy",
                "LLM_MY_PROXY_BASE_URL": "https://proxy.example.com/v1",
                "LLM_MY_PROXY_MODELS": "gpt-5",
                "LLM_UNUSED_API_KEY": "sk-should-not-leak",
                "UNRELATED_API_KEY": "sk-should-not-leak",
            },
        ):
            payload = self.service.get_config(include_schema=True)
            raw_payload = self.service.get_config(include_schema=False)

        items = {item["key"]: item for item in payload["items"]}
        raw_items = {item["key"]: item for item in raw_payload["items"]}
        self.assertEqual(items["STOCK_LIST"]["value"], "600519")
        self.assertTrue(items["STOCK_LIST"]["raw_value_exists"])
        self.assertEqual(items["LITELLM_MODEL"]["value"], "openai/gpt-5")
        self.assertFalse(items["LITELLM_MODEL"]["raw_value_exists"])
        self.assertEqual(items["LLM_CHANNELS"]["value"], "my_proxy")
        self.assertFalse(items["LLM_CHANNELS"]["raw_value_exists"])
        self.assertEqual(items["LLM_MY_PROXY_BASE_URL"]["value"], "https://proxy.example.com/v1")
        self.assertFalse(items["LLM_MY_PROXY_BASE_URL"]["raw_value_exists"])
        self.assertEqual(items["LLM_MY_PROXY_MODELS"]["value"], "gpt-5")
        self.assertFalse(items["LLM_MY_PROXY_MODELS"]["raw_value_exists"])
        self.assertNotIn("LLM_UNUSED_API_KEY", items)
        self.assertNotIn("UNRELATED_API_KEY", items)
        self.assertNotIn("LLM_UNUSED_API_KEY", raw_items)
        self.assertNotIn("UNRELATED_API_KEY", raw_items)

    def test_get_config_runtime_env_fallback_does_not_persist_llm_fields_on_save(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519",
            "LOG_LEVEL=INFO",
        )

        startup_env = {
            "LITELLM_MODEL": "openai/gpt-5",
            "LLM_CHANNELS": "my_proxy",
            "LLM_MY_PROXY_PROTOCOL": "openai",
            "LLM_MY_PROXY_BASE_URL": "https://proxy.example.com/v1",
            "LLM_MY_PROXY_API_KEYS": "sk-test-value",
            "LLM_MY_PROXY_MODELS": "openai/gpt-5",
        }
        with patch.dict(os.environ, startup_env, clear=False):
            payload_before = self.service.get_config(include_schema=True)
            items_before = {item["key"]: item for item in payload_before["items"]}
            self.assertEqual(items_before["LITELLM_MODEL"]["value"], "openai/gpt-5")
            self.assertFalse(items_before["LITELLM_MODEL"]["raw_value_exists"])
            self.assertEqual(
                items_before["LLM_MY_PROXY_BASE_URL"]["value"],
                "https://proxy.example.com/v1",
            )
            self.assertFalse(items_before["LLM_MY_PROXY_BASE_URL"]["raw_value_exists"])
            self.assertEqual(items_before["LLM_MY_PROXY_MODELS"]["value"], "openai/gpt-5")
            self.assertFalse(items_before["LLM_MY_PROXY_MODELS"]["raw_value_exists"])

            current_version = self.manager.get_config_version()
            response = self.service.update(
                config_version=current_version,
                items=[{"key": "STOCK_LIST", "value": "300750"}],
                reload_now=False,
            )
            self.assertTrue(response["success"])

            current_map = self.manager.read_config_map()
            self.assertEqual(current_map["STOCK_LIST"], "300750")
            self.assertNotIn("LITELLM_MODEL", current_map)
            self.assertNotIn("LLM_MY_PROXY_BASE_URL", current_map)
            self.assertNotIn("LLM_MY_PROXY_MODELS", current_map)

            payload_after = self.service.get_config(include_schema=True)
            items_after = {item["key"]: item for item in payload_after["items"]}
            self.assertEqual(items_after["LITELLM_MODEL"]["value"], "openai/gpt-5")
            self.assertFalse(items_after["LITELLM_MODEL"]["raw_value_exists"])
            self.assertEqual(
                items_after["LLM_MY_PROXY_BASE_URL"]["value"],
                "https://proxy.example.com/v1",
            )
            self.assertFalse(items_after["LLM_MY_PROXY_BASE_URL"]["raw_value_exists"])
            self.assertEqual(items_after["LLM_MY_PROXY_MODELS"]["value"], "openai/gpt-5")
            self.assertFalse(items_after["LLM_MY_PROXY_MODELS"]["raw_value_exists"])

    def test_runtime_env_fallback_does_not_override_saved_provider_and_base_url_settings(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519",
            "LOG_LEVEL=INFO",
            "LITELLM_MODEL=openai/gpt-4o-mini",
            "OPENAI_MODEL=gpt-4.1",
        )

        with patch.dict(
            os.environ,
            {
                "OPENAI_BASE_URL": "https://runtime-openai.v1",
                "OPENAI_API_KEY": "runtime-openai-key",
            },
            clear=False,
        ):
            pre_save = self.service.get_config(include_schema=True)
            pre_save_items = {item["key"]: item for item in pre_save["items"]}

            self.assertEqual(pre_save_items["OPENAI_BASE_URL"]["value"], "https://runtime-openai.v1")
            self.assertFalse(pre_save_items["OPENAI_BASE_URL"]["raw_value_exists"])
            self.assertEqual(pre_save_items["OPENAI_API_KEY"]["value"], "runtime-openai-key")
            self.assertFalse(pre_save_items["OPENAI_API_KEY"]["raw_value_exists"])
            self.assertEqual(pre_save_items["LITELLM_MODEL"]["value"], "openai/gpt-4o-mini")
            self.assertTrue(pre_save_items["LITELLM_MODEL"]["raw_value_exists"])
            self.assertEqual(pre_save_items["OPENAI_MODEL"]["value"], "gpt-4.1")
            self.assertTrue(pre_save_items["OPENAI_MODEL"]["raw_value_exists"])

            response = self.service.update(
                config_version=self.manager.get_config_version(),
                items=[{"key": "STOCK_LIST", "value": "300750"}],
                reload_now=False,
            )
            self.assertTrue(response["success"])

            current_map = self.manager.read_config_map()
            self.assertEqual(current_map["STOCK_LIST"], "300750")
            self.assertEqual(current_map["LITELLM_MODEL"], "openai/gpt-4o-mini")
            self.assertEqual(current_map["OPENAI_MODEL"], "gpt-4.1")
            self.assertNotIn("OPENAI_BASE_URL", current_map)
            self.assertNotIn("OPENAI_API_KEY", current_map)

    def test_validate_uses_runtime_injected_llm_channels_for_support_keys(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519",
            "LOG_LEVEL=INFO",
        )

        with patch.dict(
            os.environ,
            {
                "LLM_CHANNELS": "my_proxy",
                "LLM_MY_PROXY_PROTOCOL": "openai",
                "LLM_MY_PROXY_API_KEYS": "sk-test-value",
                "LLM_MY_PROXY_BASE_URL": "https://proxy.example.com/v1",
                "LLM_MY_PROXY_MODELS": "openai/gpt-5",
            },
            clear=False,
        ):
            validation = self.service.validate(
                items=[{"key": "LLM_MY_PROXY_BASE_URL", "value": "not-a-url"}],
            )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "LLM_MY_PROXY_BASE_URL" and issue["code"] == "invalid_url"
                for issue in validation["issues"]
            )
        )

    def test_get_config_switch_type_uses_runtime_env_display_fallback(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519",
            "LOG_LEVEL=INFO",
        )

        with patch.dict(os.environ, {"REPORT_SHOW_LLM_MODEL": "false"}, clear=False):
            payload = self.service.get_config(include_schema=True)

        items = {item["key"]: item for item in payload["items"]}
        self.assertEqual(items["REPORT_SHOW_LLM_MODEL"]["value"], "false")
        self.assertFalse(items["REPORT_SHOW_LLM_MODEL"]["raw_value_exists"])

    def test_get_config_with_schema_hides_unregistered_env_keys(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "DATABASE_PATH=./custom/stock_analysis.db",
            "SQLITE_WAL_ENABLED=true",
            "USE_PROXY=true",
            "PROXY_HOST=127.0.0.1",
            "PROXY_PORT=10809",
            "LOG_DIR=./logs",
        )

        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertNotIn("DATABASE_PATH", items)
        self.assertNotIn("SQLITE_WAL_ENABLED", items)
        self.assertNotIn("USE_PROXY", items)
        self.assertNotIn("PROXY_HOST", items)
        self.assertNotIn("PROXY_PORT", items)
        self.assertIn("LOG_DIR", items)
        self.assertEqual(items["LOG_DIR"]["schema"]["help_key"], "settings.system.LOG_DIR")

    def test_get_config_with_schema_keeps_declared_llm_channel_support_keys(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "LLM_CHANNELS=deepseek,my_proxy",
            "LLM_DEEPSEEK_PROTOCOL=deepseek",
            "LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com",
            "LLM_DEEPSEEK_API_KEY=sk-test-value",
            "LLM_DEEPSEEK_MODELS=deepseek-v4-flash,deepseek-v4-pro",
            "LLM_MY_PROXY_PROTOCOL=openai",
            "LLM_MY_PROXY_API_KEYS=sk-key-1,sk-key-2",
            "LLM_MY_PROXY_MODELS=gpt-5.5",
            "LLM_UNUSED_API_KEY=sk-should-not-leak",
            "DATABASE_PATH=./custom/stock_analysis.db",
        )

        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertIn("LLM_CHANNELS", items)
        self.assertEqual(items["LLM_DEEPSEEK_API_KEY"]["value"], "sk-test-value")
        self.assertEqual(items["LLM_DEEPSEEK_MODELS"]["value"], "deepseek-v4-flash,deepseek-v4-pro")
        self.assertEqual(items["LLM_MY_PROXY_API_KEYS"]["value"], "sk-key-1,sk-key-2")
        self.assertEqual(items["LLM_MY_PROXY_MODELS"]["value"], "gpt-5.5")
        self.assertEqual(items["LLM_MY_PROXY_API_KEYS"]["schema"]["category"], "ai_model")
        self.assertNotIn("LLM_UNUSED_API_KEY", items)
        self.assertNotIn("DATABASE_PATH", items)

    def test_get_config_without_schema_keeps_unregistered_env_keys(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "DATABASE_PATH=./custom/stock_analysis.db",
            "SQLITE_WAL_ENABLED=true",
        )

        payload = self.service.get_config(include_schema=False)
        items = {item["key"]: item for item in payload["items"]}

        self.assertEqual(items["DATABASE_PATH"]["value"], "./custom/stock_analysis.db")
        self.assertEqual(items["SQLITE_WAL_ENABLED"]["value"], "true")
        self.assertNotIn("schema", items["DATABASE_PATH"])

    def test_get_setup_status_reports_required_gaps_for_empty_config(self) -> None:
        self._rewrite_env("")

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        self.assertFalse(status["is_complete"])
        self.assertFalse(status["ready_for_smoke"])
        self.assertEqual(status["next_step_key"], "llm_primary")
        self.assertIn("llm_primary", status["required_missing_keys"])
        self.assertIn("stock_list", status["required_missing_keys"])

    def test_get_setup_status_marks_minimal_config_complete(self) -> None:
        self._rewrite_env(
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY=secret-key-value",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertTrue(status["is_complete"])
        self.assertTrue(status["ready_for_smoke"])
        self.assertEqual(checks["llm_primary"]["status"], "configured")
        self.assertEqual(checks["llm_agent"]["status"], "inherited")
        self.assertEqual(checks["stock_list"]["status"], "configured")
        self.assertEqual(checks["notification"]["status"], "optional")

    def test_generation_backend_status_preview_uses_draft_backend(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=litellm",
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY=secret-key-value",
        )

        with patch("src.llm.local_cli_backend.shutil.which", return_value=None):
            payload = self.service.preview_generation_backend_status(
                items=[
                    {"key": "GENERATION_BACKEND", "value": "codex_cli"},
                    {"key": "GENERATION_FALLBACK_BACKEND", "value": ""},
                ],
                mask_token="******",
            )

        self.assertEqual(payload["primary_backend_id"], "codex_cli")
        self.assertFalse(payload["primary"]["available"])
        self.assertEqual(payload["primary"]["health_status"], "failed")
        self.assertEqual(payload["primary"]["last_error_code"], "command_not_found")

    def test_generation_backend_status_preserves_masked_saved_secret(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=litellm",
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY=saved-secret-value",
        )

        payload = self.service.preview_generation_backend_status(
            items=[{"key": "GEMINI_API_KEY", "value": "******"}],
            mask_token="******",
        )

        self.assertEqual(payload["primary_backend_id"], "litellm")
        self.assertTrue(payload["primary"]["available"])

    def test_generation_backend_status_saved_invalid_numeric_returns_failed_status(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=codex_cli",
            "GENERATION_FALLBACK_BACKEND=",
            "GENERATION_BACKEND_TIMEOUT_SECONDS=not-int",
        )

        payload = self.service.get_generation_backend_status()

        self.assertEqual(payload["primary_backend_id"], "codex_cli")
        self.assertFalse(payload["primary"]["available"])
        self.assertEqual(payload["primary"]["health_status"], "failed")
        self.assertEqual(payload["primary"]["last_error_code"], "unsafe_config")

    def test_generation_backend_preview_invalid_numeric_returns_validation_error(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=codex_cli",
            "GENERATION_FALLBACK_BACKEND=",
        )

        with self.assertRaises(ConfigValidationError) as ctx:
            self.service.preview_generation_backend_status(
                items=[{"key": "GENERATION_BACKEND_TIMEOUT_SECONDS", "value": "not-int"}],
                mask_token="******",
            )

        self.assertEqual(ctx.exception.issues[0]["key"], "GENERATION_BACKEND_TIMEOUT_SECONDS")
        self.assertEqual(ctx.exception.issues[0]["severity"], "error")

    def test_generation_backend_status_saved_litellm_invalid_channel_returns_failed_status(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=litellm",
            "LLM_CHANNELS=remote",
            "LLM_REMOTE_PROTOCOL=openai",
            "LLM_REMOTE_BASE_URL=http://169.254.169.254/v1",
            "LLM_REMOTE_API_KEY=sk-remote",
            "LLM_REMOTE_MODELS=gpt-4o-mini",
        )

        payload = self.service.get_generation_backend_status()

        self.assertEqual(payload["primary_backend_id"], "litellm")
        self.assertFalse(payload["primary"]["available"])
        self.assertEqual(payload["primary"]["health_status"], "failed")
        self.assertEqual(payload["primary"]["last_error_code"], "unsafe_config")

    def test_generation_backend_status_saved_litellm_model_without_key_returns_failed_status(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=litellm",
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
        )

        with patch.dict(os.environ, {"ENV_FILE": str(self.env_path)}, clear=True):
            payload = self.service.get_generation_backend_status()

        self.assertEqual(payload["primary_backend_id"], "litellm")
        self.assertFalse(payload["primary"]["available"])
        self.assertEqual(payload["primary"]["health_status"], "failed")
        self.assertEqual(payload["primary"]["last_error_code"], "unsafe_config")

    def test_generation_backend_preview_litellm_model_without_key_returns_validation_error(self) -> None:
        self._rewrite_env("GENERATION_BACKEND=litellm")

        with patch.dict(os.environ, {"ENV_FILE": str(self.env_path)}, clear=True):
            with self.assertRaises(ConfigValidationError) as ctx:
                self.service.preview_generation_backend_status(
                    items=[{"key": "LITELLM_MODEL", "value": "gemini/gemini-3-flash-preview"}],
                    mask_token="******",
                )

        self.assertEqual(ctx.exception.issues[0]["key"], "LITELLM_MODEL")
        self.assertEqual(ctx.exception.issues[0]["code"], "missing_runtime_source")

    def test_generation_backend_preview_uses_openai_model_draft(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=litellm",
            "OPENAI_API_KEY=secret-key-value",
            "OPENAI_MODEL=gpt-5.5",
        )

        with patch.dict(os.environ, {"ENV_FILE": str(self.env_path)}, clear=True):
            payload = self.service.preview_generation_backend_status(
                items=[{"key": "OPENAI_MODEL", "value": "gemini/gemini-3-flash-preview"}],
                mask_token="******",
            )

        self.assertEqual(payload["primary_backend_id"], "litellm")
        self.assertFalse(payload["primary"]["available"])
        self.assertEqual(payload["primary"]["last_error_code"], "unsafe_config")

    def test_generation_backend_preview_uses_gemini_model_draft(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=litellm",
            "GEMINI_API_KEY=secret-key-value",
            "GEMINI_MODEL=gemini-3.1-pro-preview",
        )

        with patch.dict(os.environ, {"ENV_FILE": str(self.env_path)}, clear=True):
            payload = self.service.preview_generation_backend_status(
                items=[{"key": "GEMINI_MODEL", "value": "openai/gpt-5.5"}],
                mask_token="******",
            )

        self.assertEqual(payload["primary_backend_id"], "litellm")
        self.assertFalse(payload["primary"]["available"])
        self.assertEqual(payload["primary"]["last_error_code"], "unsafe_config")

    def test_generation_backend_status_uses_runtime_provider_key_fallback(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=litellm",
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
        )

        with patch.dict(
            os.environ,
            {
                "ENV_FILE": str(self.env_path),
                "GEMINI_API_KEY": "runtime-secret-value",
            },
            clear=True,
        ):
            payload = self.service.get_generation_backend_status()

        self.assertEqual(payload["primary_backend_id"], "litellm")
        self.assertTrue(payload["primary"]["available"])
        self.assertIsNone(payload["primary"]["last_error_code"])

    def test_generation_backend_preview_local_cli_ignores_inactive_litellm_model_error(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=litellm",
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
        )

        with patch("src.llm.local_cli_backend.shutil.which", return_value=None):
            payload = self.service.preview_generation_backend_status(
                items=[
                    {"key": "GENERATION_BACKEND", "value": "codex_cli"},
                    {"key": "GENERATION_FALLBACK_BACKEND", "value": ""},
                ],
                mask_token="******",
            )

        self.assertEqual(payload["primary_backend_id"], "codex_cli")
        self.assertEqual(payload["primary"]["last_error_code"], "command_not_found")

    def test_generation_backend_preview_ignores_unrelated_draft_errors(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=litellm",
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY=secret-key-value",
        )

        payload = self.service.preview_generation_backend_status(
            items=[{"key": "WECHAT_WEBHOOK_URL", "value": "not-a-url"}],
            mask_token="******",
        )

        self.assertEqual(payload["primary_backend_id"], "litellm")
        self.assertTrue(payload["primary"]["available"])

    def test_generation_backend_status_fallback_error_does_not_fail_primary(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=codex_cli",
            "GENERATION_FALLBACK_BACKEND=bad_backend",
        )

        with patch("src.llm.local_cli_backend.shutil.which", return_value="/usr/bin/codex"), \
             patch("src.llm.local_cli_backend.os.access", return_value=True):
            payload = self.service.get_generation_backend_status()

        self.assertTrue(payload["primary"]["available"])
        self.assertEqual(payload["fallback"]["backend_id"], "bad_backend")
        self.assertFalse(payload["fallback"]["available"])

    def test_get_setup_status_treats_codex_cli_as_primary_runtime_without_api_keys(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=codex_cli",
            "GENERATION_FALLBACK_BACKEND=",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True), \
             patch("src.services.system_config_service.shutil.which", return_value="/usr/bin/codex"):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertFalse(status["is_complete"])
        self.assertTrue(status["ready_for_smoke"])
        self.assertEqual(checks["llm_primary"]["status"], "configured")
        self.assertEqual(checks["llm_agent"]["status"], "needs_action")
        self.assertIn("Codex CLI", checks["llm_primary"]["message"])
        self.assertNotIn("llm_primary", status["required_missing_keys"])
        self.assertIn("llm_agent", status["required_missing_keys"])

    def test_get_setup_status_allows_local_cli_primary_smoke_without_agent_model(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=claude_code_cli",
            "GENERATION_FALLBACK_BACKEND=",
            "STOCK_LIST=AAPL",
        )

        with patch.dict(os.environ, {}, clear=True), \
             patch("src.services.system_config_service.shutil.which", return_value="/usr/bin/claude"):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertFalse(status["is_complete"])
        self.assertTrue(status["ready_for_smoke"])
        self.assertEqual(checks["llm_primary"]["status"], "configured")
        self.assertEqual(checks["stock_list"]["status"], "configured")
        self.assertEqual(checks["llm_agent"]["status"], "needs_action")
        self.assertIn("local CLI 主生成方式不会被自动继承", checks["llm_agent"]["message"])
        self.assertEqual(status["required_missing_keys"], ["llm_agent"])

    def test_get_setup_status_codex_cli_missing_reports_backend_path(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=codex_cli",
            "GENERATION_FALLBACK_BACKEND=",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True), \
             patch("src.services.system_config_service.shutil.which", return_value=None):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertEqual(checks["llm_primary"]["status"], "needs_action")
        self.assertIn("后端进程当前 PATH", checks["llm_primary"]["message"])
        self.assertIn("Codex CLI 交互窗口", checks["llm_primary"]["next_step"])
        self.assertNotIn("请先安装并登录", checks["llm_primary"]["next_step"])

    def test_get_setup_status_codex_primary_agent_model_explains_litellm_split(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=codex_cli",
            "GENERATION_FALLBACK_BACKEND=",
            "AGENT_LITELLM_MODEL=openai/gpt-5.5",
            "OPENAI_API_KEY=secret-key-value",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True), \
             patch("src.services.system_config_service.shutil.which", return_value="/usr/bin/codex"):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertEqual(checks["llm_agent"]["status"], "configured")
        self.assertIn("普通分析使用 Codex CLI", checks["llm_agent"]["message"])
        self.assertIn("Agent 工具调用仍使用 LiteLLM 主模型", checks["llm_agent"]["message"])

    def test_get_setup_status_codex_primary_agent_inherited_model_explains_litellm_split(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=codex_cli",
            "GENERATION_FALLBACK_BACKEND=",
            "LITELLM_MODEL=openai/gpt-5.5",
            "OPENAI_API_KEY=secret-key-value",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True), \
             patch("src.services.system_config_service.shutil.which", return_value="/usr/bin/codex"):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertEqual(checks["llm_agent"]["status"], "configured")
        self.assertIn(
            "普通分析使用 Codex CLI；Agent 工具调用仍使用 LiteLLM 主模型: openai/gpt-5.5",
            checks["llm_agent"]["message"],
        )

    def test_get_setup_status_codex_primary_hermes_only_agent_inheritance_needs_action(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=codex_cli",
            "GENERATION_FALLBACK_BACKEND=",
            "LLM_CHANNELS=hermes",
            "LLM_HERMES_PROTOCOL=openai",
            "LLM_HERMES_BASE_URL=http://127.0.0.1:8765/v1",
            "LLM_HERMES_API_KEY=test-key",
            "LLM_HERMES_MODELS=hermes-agent",
            "LITELLM_MODEL=openai/hermes-agent",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True), \
             patch("src.services.system_config_service.shutil.which", return_value="/usr/bin/codex"):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertEqual(checks["llm_primary"]["status"], "configured")
        self.assertEqual(checks["llm_agent"]["status"], "needs_action")
        self.assertIn("Hermes", checks["llm_agent"]["message"])
        self.assertIn("llm_agent", status["required_missing_keys"])
        self.assertNotIn(
            "Agent 工具调用仍使用 LiteLLM 主模型",
            checks["llm_agent"]["message"],
        )

    def test_get_setup_status_rejects_agent_codex_cli_tool_backend(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=codex_cli",
            "AGENT_GENERATION_BACKEND=codex_cli",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True), \
             patch("src.services.system_config_service.shutil.which", return_value="/usr/bin/codex"):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertEqual(checks["llm_agent"]["status"], "needs_action")
        self.assertIn("暂不支持 codex_cli", checks["llm_agent"]["message"])

    def test_get_setup_status_rejects_agent_claude_and_opencode_tool_backends(self) -> None:
        for backend in ("claude_code_cli", "opencode_cli"):
            with self.subTest(backend=backend):
                self._rewrite_env(
                    "GENERATION_BACKEND=litellm",
                    f"AGENT_GENERATION_BACKEND={backend}",
                    "STOCK_LIST=600519",
                )

                with patch.dict(os.environ, {}, clear=True):
                    status = self.service.get_setup_status()

                checks = {check["key"]: check for check in status["checks"]}
                self.assertEqual(checks["llm_agent"]["status"], "needs_action")
                self.assertIn(f"暂不支持 {backend}", checks["llm_agent"]["message"])

    def test_get_setup_status_accepts_opencode_without_model_override(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=opencode_cli",
            "GENERATION_FALLBACK_BACKEND=",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True), \
             patch("src.services.system_config_service.shutil.which", return_value="/usr/bin/opencode"):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertEqual(checks["llm_primary"]["status"], "configured")
        self.assertIn("OpenCode CLI", checks["llm_primary"]["message"])

    def test_get_setup_status_agent_litellm_without_model_reports_missing_model(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=codex_cli",
            "AGENT_GENERATION_BACKEND=litellm",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True), \
             patch("src.services.system_config_service.shutil.which", return_value="/usr/bin/codex"):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertEqual(checks["llm_agent"]["status"], "needs_action")
        self.assertIn("未检测到可用 LiteLLM 模型配置", checks["llm_agent"]["message"])
        self.assertNotIn("需要 LiteLLM backend", checks["llm_agent"]["message"])

    def test_get_setup_status_accepts_anspire_one_key_llm(self) -> None:
        self._rewrite_env(
            "ANSPIRE_API_KEYS=sk-anspire-test-value",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertTrue(status["is_complete"])
        self.assertEqual(checks["llm_primary"]["status"], "configured")
        self.assertIn("openai/Doubao-Seed-2.0-lite", checks["llm_primary"]["message"])

    def test_get_setup_status_treats_blank_anspire_channel_enabled_as_shared_disable(self) -> None:
        self._rewrite_env(
            "LLM_CHANNELS=anspire",
            "LLM_ANSPIRE_ENABLED=",
            "ANSPIRE_LLM_ENABLED=false",
            "ANSPIRE_API_KEYS=sk-anspire-test-value",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertFalse(status["is_complete"])
        self.assertEqual(checks["llm_primary"]["status"], "needs_action")
        self.assertIn("llm_primary", status["required_missing_keys"])

    def test_get_setup_status_respects_disabled_anspire_channel_without_legacy_fallback(self) -> None:
        self._rewrite_env(
            "LLM_CHANNELS=anspire",
            "LLM_ANSPIRE_ENABLED=false",
            "ANSPIRE_API_KEYS=sk-anspire-test-value",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertFalse(status["is_complete"])
        self.assertEqual(checks["llm_primary"]["status"], "needs_action")
        self.assertIn("llm_primary", status["required_missing_keys"])

    def test_get_setup_status_accepts_direct_env_primary_without_provider_key(self) -> None:
        self._rewrite_env(
            "LITELLM_MODEL=minimax/MiniMax-M1",
            "STOCK_LIST=600519",
        )

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        checks = {check["key"]: check for check in status["checks"]}
        self.assertTrue(status["is_complete"])
        self.assertEqual(checks["llm_primary"]["status"], "configured")
        self.assertEqual(checks["llm_agent"]["status"], "inherited")

    def test_get_setup_status_matches_notification_channel_requirements(self) -> None:
        base_lines = [
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY=secret-key-value",
            "STOCK_LIST=600519",
        ]

        self._rewrite_env(*base_lines, "PUSHOVER_USER_KEY=user-key")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        pushover_partial = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(pushover_partial["status"], "optional")

        self._rewrite_env(*base_lines, "PUSHOVER_USER_KEY=user-key", "PUSHOVER_API_TOKEN=app-token")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        pushover_complete = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(pushover_complete["status"], "configured")

        self._rewrite_env(*base_lines, "SLACK_BOT_TOKEN=xoxb-test", "SLACK_CHANNEL_ID=C123")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        slack_complete = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(slack_complete["status"], "configured")

        self._rewrite_env(*base_lines, "ASTRBOT_URL=https://astrbot.example/webhook")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        astrbot_complete = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(astrbot_complete["status"], "configured")

        self._rewrite_env(*base_lines, "NTFY_URL=https://ntfy.sh/dsa-topic")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        ntfy_complete = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(ntfy_complete["status"], "configured")

        self._rewrite_env(*base_lines, "NTFY_URL=https://ntfy.sh")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        ntfy_without_topic = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(ntfy_without_topic["status"], "optional")

        self._rewrite_env(*base_lines, "GOTIFY_URL=https://gotify.example")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        gotify_partial = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(gotify_partial["status"], "optional")

        self._rewrite_env(*base_lines, "GOTIFY_URL=https://gotify.example", "GOTIFY_TOKEN=app-token")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        gotify_complete = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(gotify_complete["status"], "configured")

        self._rewrite_env(*base_lines, "GOTIFY_URL=https://gotify.example/message", "GOTIFY_TOKEN=app-token")
        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()
        gotify_with_message = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(gotify_with_message["status"], "optional")

    def test_get_setup_status_accepts_feishu_app_bot_triad(self) -> None:
        self._rewrite_env(
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY=secret-key-value",
            "STOCK_LIST=600519",
            "FEISHU_APP_ID=cli_xxx",
            "FEISHU_APP_SECRET=secret_xxx",
            "FEISHU_CHAT_ID=oc_xxx",
        )

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        notification = next(check for check in status["checks"] if check["key"] == "notification")
        self.assertEqual(notification["status"], "configured")

    def test_get_setup_status_rejects_partial_feishu_app_bot_triad(self) -> None:
        base_lines = [
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY=secret-key-value",
            "STOCK_LIST=600519",
        ]
        partial_cases = [
            ("FEISHU_APP_ID=cli_xxx", "FEISHU_APP_SECRET=secret_xxx"),
            ("FEISHU_APP_ID=cli_xxx", "FEISHU_CHAT_ID=oc_xxx"),
            ("FEISHU_APP_SECRET=secret_xxx", "FEISHU_CHAT_ID=oc_xxx"),
        ]

        for partial in partial_cases:
            with self.subTest(partial=partial):
                self._rewrite_env(*base_lines, *partial)
                with patch.dict(os.environ, {}, clear=True):
                    status = self.service.get_setup_status()
                notification = next(check for check in status["checks"] if check["key"] == "notification")
                self.assertEqual(notification["status"], "optional")

    def test_get_setup_status_uses_runtime_env_without_reloading_singletons(self) -> None:
        self._rewrite_env("")

        with patch.dict(
            os.environ,
            {
                "LITELLM_MODEL": "gemini/gemini-3-flash-preview",
                "GEMINI_API_KEY": "runtime-secret",
                "STOCK_LIST": "600519",
            },
            clear=True,
        ), patch("src.services.system_config_service.Config.reset_instance") as mock_reset, \
             patch("src.services.system_config_service.setup_env") as mock_setup_env:
            status = self.service.get_setup_status()

        self.assertTrue(status["is_complete"])
        mock_reset.assert_not_called()
        mock_setup_env.assert_not_called()

    def test_get_setup_status_storage_check_does_not_create_database_parent(self) -> None:
        missing_parent = Path(self.temp_dir.name) / "missing-data"
        db_path = missing_parent / "stock_analysis.db"
        self._rewrite_env(
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY=secret-key-value",
            "STOCK_LIST=600519",
            f"DATABASE_PATH={db_path}",
        )

        with patch.dict(os.environ, {}, clear=True):
            status = self.service.get_setup_status()

        storage_check = next(check for check in status["checks"] if check["key"] == "storage")
        self.assertEqual(storage_check["status"], "configured")
        self.assertFalse(missing_parent.exists())

    def test_export_desktop_env_returns_raw_text(self) -> None:
        self.env_path.write_text(
            "# Desktop config\nSTOCK_LIST=600519,000001\n\nGEMINI_API_KEY=secret-key-value\n",
            encoding="utf-8",
        )

        payload = self.service.export_desktop_env()

        self.assertEqual(
            payload["content"],
            "# Desktop config\nSTOCK_LIST=600519,000001\n\nGEMINI_API_KEY=secret-key-value\n",
        )
        self.assertEqual(payload["config_version"], self.manager.get_config_version())

    def test_export_desktop_env_preserves_hidden_web_settings_keys(self) -> None:
        self.env_path.write_text(
            "STOCK_LIST=600519\nDATABASE_PATH=./custom/stock_analysis.db\nUSE_PROXY=true\n",
            encoding="utf-8",
        )

        payload = self.service.export_desktop_env()

        self.assertIn("DATABASE_PATH=./custom/stock_analysis.db\n", payload["content"])
        self.assertIn("USE_PROXY=true\n", payload["content"])

    def test_import_desktop_env_merges_keys_without_deleting_unspecified_values(self) -> None:
        current_version = self.manager.get_config_version()

        payload = self.service.import_desktop_env(
            config_version=current_version,
            content="STOCK_LIST=300750\nCUSTOM_NOTE=desktop backup\n",
            reload_now=False,
        )

        self.assertTrue(payload["success"])
        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["STOCK_LIST"], "300750")
        self.assertEqual(current_map["CUSTOM_NOTE"], "desktop backup")
        self.assertEqual(current_map["GEMINI_API_KEY"], "secret-key-value")

    def test_import_desktop_env_preserves_hidden_web_settings_keys(self) -> None:
        current_version = self.manager.get_config_version()

        self.service.import_desktop_env(
            config_version=current_version,
            content="DATABASE_PATH=./custom/stock_analysis.db\nPROXY_HOST=127.0.0.1\n",
            reload_now=False,
        )

        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["DATABASE_PATH"], "./custom/stock_analysis.db")
        self.assertEqual(current_map["PROXY_HOST"], "127.0.0.1")

    def test_import_desktop_env_treats_mask_token_as_literal_value(self) -> None:
        current_version = self.manager.get_config_version()

        self.service.import_desktop_env(
            config_version=current_version,
            content="GEMINI_API_KEY=******\n",
            reload_now=False,
        )

        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["GEMINI_API_KEY"], "******")

    def test_import_desktop_env_uses_last_duplicate_assignment(self) -> None:
        current_version = self.manager.get_config_version()

        self.service.import_desktop_env(
            config_version=current_version,
            content="STOCK_LIST=000001\nSTOCK_LIST=300750\n",
            reload_now=False,
        )

        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["STOCK_LIST"], "300750")

    def test_import_desktop_env_allows_empty_assignment(self) -> None:
        current_version = self.manager.get_config_version()

        self.service.import_desktop_env(
            config_version=current_version,
            content="LOG_LEVEL=\n",
            reload_now=False,
        )

        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["LOG_LEVEL"], "")

    def test_import_desktop_env_preserves_exported_braced_webhook_template(self) -> None:
        template = '{"content":${content_json}}'

        save_payload = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "CUSTOM_WEBHOOK_BODY_TEMPLATE", "value": template}],
            reload_now=False,
        )
        self.assertTrue(save_payload["success"])
        backup_content = self.service.export_desktop_env()["content"]
        self.assertIn(
            'CUSTOM_WEBHOOK_BODY_TEMPLATE={"content":$${content_json}}\n',
            backup_content,
        )

        clear_payload = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "CUSTOM_WEBHOOK_BODY_TEMPLATE", "value": ""}],
            reload_now=False,
        )
        self.assertTrue(clear_payload["success"])

        restore_payload = self.service.import_desktop_env(
            config_version=self.manager.get_config_version(),
            content=backup_content,
            reload_now=False,
        )

        self.assertTrue(restore_payload["success"])
        self.assertEqual(
            self.manager.read_config_map()["CUSTOM_WEBHOOK_BODY_TEMPLATE"],
            template,
        )

    def test_import_desktop_env_rejects_empty_or_comment_only_content(self) -> None:
        with self.assertRaises(ConfigImportError):
            self.service.import_desktop_env(
                config_version=self.manager.get_config_version(),
                content="   \n# only comments\n\n",
                reload_now=False,
            )

    def test_import_desktop_env_raises_conflict_for_stale_version(self) -> None:
        with self.assertRaises(ConfigConflictError):
            self.service.import_desktop_env(
                config_version="stale-version",
                content="STOCK_LIST=300750\n",
                reload_now=False,
            )

    def test_update_preserves_masked_secret(self) -> None:
        old_version = self.manager.get_config_version()
        response = self.service.update(
            config_version=old_version,
            items=[
                {"key": "GEMINI_API_KEY", "value": "******"},
                {"key": "STOCK_LIST", "value": "600519,300750"},
            ],
            mask_token="******",
            reload_now=False,
        )

        self.assertTrue(response["success"])
        self.assertEqual(response["applied_count"], 1)
        self.assertEqual(response["skipped_masked_count"], 1)
        self.assertIn("STOCK_LIST", response["updated_keys"])

        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["STOCK_LIST"], "600519,300750")
        self.assertEqual(current_map["GEMINI_API_KEY"], "secret-key-value")

    def test_update_alphasift_enable_does_not_rewrite_llm_fields(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "LITELLM_MODEL=openai/gpt-4o-mini",
            "AGENT_LITELLM_MODEL=openai/gpt-4o",
            "OPENAI_BASE_URL=https://api.openai.com/v1",
            "LLM_CHANNELS=openai",
            "LLM_OPENAI_PROTOCOL=openai",
            "LLM_OPENAI_BASE_URL=https://api.openai.com/v1",
            "LLM_OPENAI_API_KEYS=legacy-openai-secret",
            "LLM_OPENAI_MODELS=openai/gpt-4o-mini,openai/gpt-4o",
            "LITELLM_FALLBACK_MODELS=openai/gpt-4o-mini,openai/gpt-4o",
            "ALPHASIFT_ENABLED=false",
            f"ALPHASIFT_INSTALL_SPEC={DEFAULT_ALPHASIFT_INSTALL_SPEC}",
            "LLM_USAGE_HMAC_SECRET=telemetry-secret",
            "LLM_USAGE_HMAC_KEY_VERSION=test-v1",
            "GEMINI_API_KEY=legacy-secret",
        )

        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[
                {"key": "ALPHASIFT_ENABLED", "value": "true"},
                {"key": "ALPHASIFT_INSTALL_SPEC", "value": "******"},
                {"key": "LLM_USAGE_HMAC_SECRET", "value": "******"},
                {"key": "GEMINI_API_KEY", "value": "******"},
            ],
            mask_token="******",
            reload_now=False,
        )

        self.assertTrue(response["success"])
        self.assertEqual(response["applied_count"], 1)
        self.assertIn("ALPHASIFT_ENABLED", response["updated_keys"])
        self.assertEqual(response["skipped_masked_count"], 3)

        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["ALPHASIFT_ENABLED"], "true")
        self.assertEqual(
            current_map["ALPHASIFT_INSTALL_SPEC"],
            DEFAULT_ALPHASIFT_INSTALL_SPEC,
        )
        self.assertEqual(current_map["LLM_USAGE_HMAC_SECRET"], "telemetry-secret")
        self.assertEqual(current_map["LLM_USAGE_HMAC_KEY_VERSION"], "test-v1")
        self.assertEqual(current_map["GEMINI_API_KEY"], "legacy-secret")
        self.assertEqual(current_map["LITELLM_MODEL"], "openai/gpt-4o-mini")
        self.assertEqual(current_map["AGENT_LITELLM_MODEL"], "openai/gpt-4o")
        self.assertEqual(current_map["OPENAI_BASE_URL"], "https://api.openai.com/v1")
        self.assertEqual(current_map["LLM_CHANNELS"], "openai")
        self.assertEqual(current_map["LLM_OPENAI_PROTOCOL"], "openai")
        self.assertEqual(current_map["LLM_OPENAI_BASE_URL"], "https://api.openai.com/v1")
        self.assertEqual(current_map["LLM_OPENAI_API_KEYS"], "legacy-openai-secret")
        self.assertEqual(current_map["LLM_OPENAI_MODELS"], "openai/gpt-4o-mini,openai/gpt-4o")
        self.assertEqual(current_map["LITELLM_FALLBACK_MODELS"], "openai/gpt-4o-mini,openai/gpt-4o")

    def test_validate_reports_invalid_time(self) -> None:
        validation = self.service.validate(items=[{"key": "SCHEDULE_TIME", "value": "25:70"}])
        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_format" for issue in validation["issues"]))

    def test_validate_accepts_empty_schedule_times_fallback(self) -> None:
        validation = self.service.validate(items=[{"key": "SCHEDULE_TIMES", "value": ""}])
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_validate_reports_invalid_searxng_url(self) -> None:
        validation = self.service.validate(items=[{"key": "SEARXNG_BASE_URLS", "value": "searx.local,https://ok.example"}])
        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_url" for issue in validation["issues"]))

    def test_validate_reports_invalid_public_searxng_toggle(self) -> None:
        validation = self.service.validate(
            items=[{"key": "SEARXNG_PUBLIC_INSTANCES_ENABLED", "value": "maybe"}]
        )
        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_type" for issue in validation["issues"]))

    def test_validate_reports_invalid_feishu_webhook_url(self) -> None:
        validation = self.service.validate(
            items=[{"key": "FEISHU_WEBHOOK_URL", "value": "feishu-hook-without-scheme"}]
        )
        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_url" for issue in validation["issues"]))

    def test_validate_reports_ntfy_url_without_topic(self) -> None:
        validation = self.service.validate(
            items=[{"key": "NTFY_URL", "value": "https://ntfy.sh"}]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "NTFY_URL" and issue["code"] == "invalid_ntfy_url"
                for issue in validation["issues"]
            )
        )

    def test_validate_reports_gotify_url_with_message_endpoint(self) -> None:
        validation = self.service.validate(
            items=[{"key": "GOTIFY_URL", "value": "https://gotify.example/message"}]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "GOTIFY_URL" and issue["code"] == "invalid_gotify_url"
                for issue in validation["issues"]
            )
        )

    def test_validate_reports_invalid_notification_route_channel(self) -> None:
        validation = self.service.validate(
            items=[{"key": "NOTIFICATION_REPORT_CHANNELS", "value": "wechat,not-a-channel,email"}]
        )
        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "NOTIFICATION_REPORT_CHANNELS"
                and issue["code"] == "invalid_allowed_value"
                for issue in validation["issues"]
            )
        )

    def test_validate_reports_invalid_notification_quiet_hours(self) -> None:
        validation = self.service.validate(
            items=[{"key": "NOTIFICATION_QUIET_HOURS", "value": "9:00-18:00"}]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "NOTIFICATION_QUIET_HOURS"
                and issue["code"] == "invalid_format"
                for issue in validation["issues"]
            )
        )

    def test_validate_reports_invalid_notification_timezone(self) -> None:
        validation = self.service.validate(
            items=[{"key": "NOTIFICATION_TIMEZONE", "value": "Mars/Olympus"}]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "NOTIFICATION_TIMEZONE"
                and issue["code"] == "invalid_timezone"
                for issue in validation["issues"]
            )
        )

    def test_validate_reports_invalid_notification_min_severity(self) -> None:
        validation = self.service.validate(
            items=[{"key": "NOTIFICATION_MIN_SEVERITY", "value": "notice"}]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "NOTIFICATION_MIN_SEVERITY"
                and issue["code"] == "invalid_enum"
                for issue in validation["issues"]
            )
        )

    def test_validate_warns_daily_digest_is_reserved(self) -> None:
        validation = self.service.validate(
            items=[{"key": "NOTIFICATION_DAILY_DIGEST_ENABLED", "value": "true"}]
        )

        self.assertTrue(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "NOTIFICATION_DAILY_DIGEST_ENABLED"
                and issue["code"] == "reserved_notification_daily_digest"
                and issue["severity"] == "warning"
                for issue in validation["issues"]
            )
        )

    def test_validate_warns_when_feishu_app_credentials_are_used_without_webhook(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "FEISHU_APP_ID", "value": "cli_xxx"},
                {"key": "FEISHU_APP_SECRET", "value": "secret_xxx"},
            ]
        )
        self.assertTrue(validation["valid"])
        issue = next(
            issue
            for issue in validation["issues"]
            if issue["code"] == "feishu_mode_mismatch"
            and issue["severity"] == "warning"
        )
        self.assertEqual(issue["key"], "FEISHU_CHAT_ID")
        self.assertIn("FEISHU_CHAT_ID", issue["message"])
        self.assertIn("static notification:", issue["expected"])
        self.assertIn("event subscription:", issue["expected"])

    def test_validate_no_warning_when_feishu_cloud_doc_credentials_without_webhook(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "FEISHU_APP_ID", "value": "cli_xxx"},
                {"key": "FEISHU_APP_SECRET", "value": "secret_xxx"},
                {"key": "FEISHU_FOLDER_TOKEN", "value": "folder_xxx"},
            ]
        )
        self.assertTrue(validation["valid"])
        self.assertFalse(
            any(
                issue["code"] == "feishu_mode_mismatch"
                and issue["severity"] == "warning"
                for issue in validation["issues"]
            )
        )

    def test_validate_warns_when_only_folder_token_cleared_with_app_credentials(self) -> None:
        """Clearing FEISHU_FOLDER_TOKEN while app credentials remain should trigger mismatch."""
        old_version = self.manager.get_config_version()
        self.service.update(
            config_version=old_version,
            items=[
                {"key": "FEISHU_APP_ID", "value": "cli_xxx"},
                {"key": "FEISHU_APP_SECRET", "value": "secret_xxx"},
            ],
        )
        validation = self.service.validate(
            items=[
                {"key": "FEISHU_FOLDER_TOKEN", "value": ""},
            ]
        )
        self.assertTrue(validation["valid"])
        self.assertTrue(
            any(
                issue["code"] == "feishu_mode_mismatch"
                and issue["severity"] == "warning"
                for issue in validation["issues"]
            )
        )

    def test_update_persists_public_searxng_toggle(self) -> None:
        old_version = self.manager.get_config_version()
        response = self.service.update(
            config_version=old_version,
            items=[{"key": "SEARXNG_PUBLIC_INSTANCES_ENABLED", "value": "false"}],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["SEARXNG_PUBLIC_INSTANCES_ENABLED"], "false")

    def test_validate_reports_invalid_llm_channel_definition(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_API_KEY", "value": ""},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "missing_api_key" for issue in validation["issues"]))

    def test_validate_preserves_model_based_protocol_inference_for_ollama_channel(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "lab"},
                {"key": "LLM_LAB_MODELS", "value": "ollama/llama3"},
                {"key": "LLM_LAB_API_KEY", "value": ""},
            ]
        )

        self.assertTrue(validation["valid"], validation["issues"])
        self.assertEqual(validation["issues"], [])

    def test_validate_reports_unknown_primary_model_for_channels(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LITELLM_MODEL", "value": "openai/gpt-4o"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "LITELLM_MODEL" and issue["code"] == "unknown_model" for issue in validation["issues"]))

    def test_validate_rejects_bare_primary_when_channel_route_is_openai_canonical(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LITELLM_MODEL", "value": "gpt-4o-mini"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "LITELLM_MODEL" and issue["code"] == "unknown_model" for issue in validation["issues"]))

    def test_validate_rejects_bare_fallback_when_channel_route_is_openai_canonical(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LITELLM_MODEL", "value": "openai/gpt-4o-mini"},
                {"key": "LITELLM_FALLBACK_MODELS", "value": "gpt-4o-mini"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "LITELLM_FALLBACK_MODELS"
                and issue["code"] == "unknown_model"
                for issue in validation["issues"]
            )
        )

    def test_validate_reports_bare_vision_when_channel_route_is_openai_canonical(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "VISION_MODEL", "value": "gpt-4o-mini"},
            ]
        )

        self.assertTrue(
            any(
                issue["key"] == "VISION_MODEL"
                and issue["code"] == "unknown_model"
                for issue in validation["issues"]
            ),
            validation["issues"],
        )

    def test_validate_accepts_deepseek_v4_primary_model_for_channel(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "deepseek"},
                {"key": "LLM_DEEPSEEK_PROTOCOL", "value": "deepseek"},
                {"key": "LLM_DEEPSEEK_BASE_URL", "value": "https://api.deepseek.com"},
                {"key": "LLM_DEEPSEEK_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_DEEPSEEK_MODELS", "value": "deepseek-v4-flash,deepseek-v4-pro"},
                {"key": "LITELLM_MODEL", "value": "deepseek/deepseek-v4-flash"},
            ]
        )

        self.assertTrue(validation["valid"], validation["issues"])
        self.assertEqual(validation["issues"], [])

    def test_validate_reports_unknown_agent_primary_model_for_channels(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "AGENT_LITELLM_MODEL", "value": "openai/gpt-4o"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "AGENT_LITELLM_MODEL" and issue["code"] == "unknown_model" for issue in validation["issues"]))

    def test_validate_accepts_unprefixed_agent_model_when_channel_declares_openai_model(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "AGENT_LITELLM_MODEL", "value": "gpt-4o-mini"},
            ]
        )

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_validate_rejects_explicit_hermes_only_agent_model(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "hermes"},
                {"key": "LLM_HERMES_API_KEY", "value": "sk-hermes-test-value"},
                {"key": "LLM_HERMES_MODELS", "value": "hermes-agent"},
                {"key": "AGENT_LITELLM_MODEL", "value": "openai/hermes-agent"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "AGENT_LITELLM_MODEL"
                and issue["code"] == "explicit_agent_model_no_safe_deployment"
                for issue in validation["issues"]
            )
        )

    def test_validate_allows_explicit_mixed_agent_model(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "hermes,remote"},
                {"key": "LLM_HERMES_API_KEY", "value": "sk-hermes-test-value"},
                {"key": "LLM_HERMES_MODELS", "value": "shared-route"},
                {"key": "LLM_REMOTE_PROTOCOL", "value": "openai"},
                {"key": "LLM_REMOTE_BASE_URL", "value": "https://api.example.com/v1"},
                {"key": "LLM_REMOTE_API_KEY", "value": "sk-remote-test-value"},
                {"key": "LLM_REMOTE_MODELS", "value": "shared-route"},
                {"key": "AGENT_LITELLM_MODEL", "value": "openai/shared-route"},
            ]
        )

        self.assertFalse(
            any(
                issue["key"] == "AGENT_LITELLM_MODEL"
                and issue["code"] == "explicit_agent_model_no_safe_deployment"
                for issue in validation["issues"]
            ),
            validation["issues"],
        )

    def test_validate_rejects_mixed_generation_primary_and_fallback(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "hermes,remote"},
                {"key": "LLM_HERMES_API_KEY", "value": "sk-hermes-test-value"},
                {"key": "LLM_HERMES_MODELS", "value": "shared-route"},
                {"key": "LLM_REMOTE_PROTOCOL", "value": "openai"},
                {"key": "LLM_REMOTE_BASE_URL", "value": "https://api.example.com/v1"},
                {"key": "LLM_REMOTE_API_KEY", "value": "sk-remote-test-value"},
                {"key": "LLM_REMOTE_MODELS", "value": "shared-route"},
                {"key": "LITELLM_MODEL", "value": "openai/shared-route"},
                {"key": "LITELLM_FALLBACK_MODELS", "value": "openai/shared-route"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "LITELLM_MODEL"
                and issue["code"] == "mixed_hermes_route_unsupported"
                for issue in validation["issues"]
            )
        )
        self.assertTrue(
            any(
                issue["key"] == "LITELLM_FALLBACK_MODELS"
                and issue["code"] == "mixed_hermes_route_unsupported"
                for issue in validation["issues"]
            )
        )

    def test_validate_rejects_bare_mixed_generation_primary_and_fallback(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "hermes,remote"},
                {"key": "LLM_HERMES_API_KEY", "value": "sk-hermes-test-value"},
                {"key": "LLM_HERMES_MODELS", "value": "shared-route"},
                {"key": "LLM_REMOTE_PROTOCOL", "value": "openai"},
                {"key": "LLM_REMOTE_BASE_URL", "value": "https://api.example.com/v1"},
                {"key": "LLM_REMOTE_API_KEY", "value": "sk-remote-test-value"},
                {"key": "LLM_REMOTE_MODELS", "value": "shared-route"},
                {"key": "LITELLM_MODEL", "value": "shared-route"},
                {"key": "LITELLM_FALLBACK_MODELS", "value": "shared-route"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "LITELLM_MODEL"
                and issue["code"] == "mixed_hermes_route_unsupported"
                for issue in validation["issues"]
            )
        )
        self.assertTrue(
            any(
                issue["key"] == "LITELLM_FALLBACK_MODELS"
                and issue["code"] == "mixed_hermes_route_unsupported"
                for issue in validation["issues"]
            )
        )

    def test_validate_rejects_bare_hermes_vision_model(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "hermes"},
                {"key": "LLM_HERMES_API_KEY", "value": "sk-hermes-test-value"},
                {"key": "LLM_HERMES_MODELS", "value": "hermes-agent"},
                {"key": "VISION_MODEL", "value": "hermes-agent"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(
            any(
                issue["key"] == "VISION_MODEL"
                and issue["code"] == "hermes_vision_unsupported"
                for issue in validation["issues"]
            )
        )

    @patch.object(
        Config,
        "_parse_litellm_yaml",
        return_value=[
            {
                "model_name": "gpt4o",
                "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": "sk-test-value"},
            }
        ],
    )
    def test_validate_accepts_unprefixed_agent_model_when_yaml_declares_alias(self, _mock_parse_yaml) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LITELLM_CONFIG", "value": "/tmp/litellm.yaml"},
                {"key": "AGENT_LITELLM_MODEL", "value": "gpt4o"},
            ]
        )

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    @patch.object(
        Config,
        "_parse_litellm_yaml",
        return_value=[{"model_name": "gemini/gemini-2.5-flash", "litellm_params": {"model": "gemini/gemini-2.5-flash"}}],
    )
    def test_validate_skips_channel_checks_when_litellm_yaml_is_active(self, _mock_parse_yaml) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LITELLM_CONFIG", "value": "/tmp/litellm.yaml"},
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_API_KEY", "value": ""},
                {"key": "LITELLM_MODEL", "value": "gemini/gemini-2.5-flash"},
            ]
        )
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_get_config_preserves_labeled_select_options_and_enum_validation(self) -> None:
        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        agent_arch_schema = items["AGENT_ARCH"]["schema"]
        self.assertEqual(agent_arch_schema["options"][0]["value"], "single")
        self.assertEqual(agent_arch_schema["options"][1]["label"], "Multi Agent (Orchestrator)")
        self.assertEqual(agent_arch_schema["validation"]["enum"], ["single", "multi"])

        report_language_schema = items["REPORT_LANGUAGE"]["schema"]
        self.assertEqual(report_language_schema["validation"]["enum"], ["zh", "en", "ko"])
        self.assertEqual(report_language_schema["options"][1]["value"], "en")
        self.assertEqual(report_language_schema["options"][2]["value"], "ko")

        self.assertEqual(items["AGENT_ORCHESTRATOR_TIMEOUT_S"]["schema"]["default_value"], "600")
        self.assertTrue(items["AGENT_DEEP_RESEARCH_BUDGET"]["schema"]["is_editable"])
        self.assertTrue(items["AGENT_EVENT_MONITOR_ENABLED"]["schema"]["is_editable"])

        context_profile_schema = items["AGENT_CONTEXT_COMPRESSION_PROFILE"]["schema"]
        self.assertEqual(
            [option["label"] for option in context_profile_schema["options"]],
            ["成本优先", "均衡推荐", "长上下文原文优先"],
        )
        self.assertEqual(
            context_profile_schema["validation"]["enum"],
            ["cost", "balanced", "long_context_raw_first"],
        )
        market_review_schema = items["MARKET_REVIEW_REGION"]["schema"]
        self.assertEqual(
            market_review_schema["validation"]["allowed_values"],
            ["cn", "hk", "us", "jp", "kr", "both"],
        )
        self.assertEqual(market_review_schema["validation"]["delimiter"], ",")
        self.assertEqual(
            items["AGENT_CONTEXT_COMPRESSION_TRIGGER_TOKENS"]["schema"]["default_value"],
            "",
        )
        self.assertEqual(
            items["AGENT_CONTEXT_PROTECTED_TURNS"]["schema"]["default_value"],
            "",
        )

    def test_validate_reports_invalid_select_option(self) -> None:
        validation = self.service.validate(items=[{"key": "AGENT_ARCH", "value": "invalid-mode"}])

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_enum" for issue in validation["issues"]))

    def test_validate_rejects_codex_backend_with_multi_agent_architecture(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "AGENT_BACKEND", "value": "codex_app_server"},
                {"key": "AGENT_ARCH", "value": "multi"},
            ]
        )

        self.assertFalse(validation["valid"])
        issue = next(
            issue
            for issue in validation["issues"]
            if issue["code"] == "unsupported_agent_arch"
        )
        self.assertEqual(issue["key"], "AGENT_ARCH")
        self.assertEqual(issue["expected"], "single")

    def test_validate_rejects_disabled_timeout_for_codex_only(self) -> None:
        codex = self.service.validate(
            items=[
                {"key": "AGENT_BACKEND", "value": "codex_app_server"},
                {"key": "AGENT_ORCHESTRATOR_TIMEOUT_S", "value": "0"},
            ]
        )
        litellm = self.service.validate(
            items=[
                {"key": "AGENT_BACKEND", "value": "litellm"},
                {"key": "AGENT_ORCHESTRATOR_TIMEOUT_S", "value": "0"},
            ]
        )

        self.assertFalse(codex["valid"])
        self.assertTrue(
            any(issue["code"] == "codex_timeout_required" for issue in codex["issues"])
        )
        self.assertTrue(litellm["valid"])

    def test_validate_reports_generation_backend_numeric_maximum(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "GENERATION_BACKEND_TIMEOUT_SECONDS", "value": "3601"},
                {"key": "GENERATION_BACKEND_MAX_OUTPUT_BYTES", "value": "33554433"},
                {"key": "GENERATION_BACKEND_MAX_CONCURRENCY", "value": "17"},
                {"key": "LOCAL_CLI_BACKEND_MAX_CONCURRENCY", "value": "5"},
            ]
        )

        self.assertFalse(validation["valid"])
        issues = {issue["key"]: issue for issue in validation["issues"]}
        self.assertEqual(issues["GENERATION_BACKEND_TIMEOUT_SECONDS"]["expected"], "<=3600")
        self.assertEqual(issues["GENERATION_BACKEND_MAX_OUTPUT_BYTES"]["expected"], "<=33554432")
        self.assertEqual(issues["GENERATION_BACKEND_MAX_CONCURRENCY"]["expected"], "<=16")
        self.assertEqual(issues["LOCAL_CLI_BACKEND_MAX_CONCURRENCY"]["expected"], "<=4")

    def test_validate_accepts_report_language_english(self) -> None:
        validation = self.service.validate(items=[{"key": "REPORT_LANGUAGE", "value": "en"}])

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_validate_accepts_report_language_korean(self) -> None:
        validation = self.service.validate(items=[{"key": "REPORT_LANGUAGE", "value": "ko"}])

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_validate_accepts_comma_separated_market_review_region(self) -> None:
        validation = self.service.validate(
            items=[{"key": "MARKET_REVIEW_REGION", "value": "cn,jp,us"}]
        )

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_validate_accepts_blank_context_compression_preset_fields(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "AGENT_CONTEXT_COMPRESSION_TRIGGER_TOKENS", "value": ""},
                {"key": "AGENT_CONTEXT_PROTECTED_TURNS", "value": ""},
            ]
        )

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_validate_reports_invalid_context_compression_profile(self) -> None:
        validation = self.service.validate(
            items=[{"key": "AGENT_CONTEXT_COMPRESSION_PROFILE", "value": "invalid"}]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_enum" for issue in validation["issues"]))

    def test_config_loads_context_compression_preset_when_numeric_values_are_blank(self) -> None:
        self.env_path.write_text(
            "\n".join(
                [
                    "AGENT_CONTEXT_COMPRESSION_PROFILE=cost",
                    "AGENT_CONTEXT_COMPRESSION_TRIGGER_TOKENS=",
                    "AGENT_CONTEXT_PROTECTED_TURNS=",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"ENV_FILE": str(self.env_path)}, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.agent_context_compression_profile, "cost")
        self.assertEqual(config.agent_context_compression_trigger_tokens, 6000)
        self.assertEqual(config.agent_context_protected_turns, 2)

        self.env_path.write_text(
            "AGENT_CONTEXT_COMPRESSION_PROFILE=long_context_raw_first\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"ENV_FILE": str(self.env_path)}, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.agent_context_compression_profile, "long_context_raw_first")
        self.assertEqual(config.agent_context_compression_trigger_tokens, 24000)
        self.assertEqual(config.agent_context_protected_turns, 6)

        self.env_path.write_text(
            "\n".join(
                [
                    "AGENT_CONTEXT_COMPRESSION_PROFILE=bad-profile",
                    "AGENT_CONTEXT_COMPRESSION_TRIGGER_TOKENS=bad-int",
                    "AGENT_CONTEXT_PROTECTED_TURNS=0",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"ENV_FILE": str(self.env_path)}, clear=True):
            config = Config._load_from_env()

        self.assertEqual(config.agent_context_compression_profile, "balanced")
        self.assertEqual(config.agent_context_compression_trigger_tokens, 12000)
        self.assertEqual(config.agent_context_protected_turns, 4)

    def test_validate_reports_invalid_json(self) -> None:
        validation = self.service.validate(items=[{"key": "AGENT_EVENT_ALERT_RULES_JSON", "value": "[invalid"}])

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_json" for issue in validation["issues"]))

    def test_validate_accepts_blank_optional_json(self) -> None:
        validation = self.service.validate(items=[{"key": "AGENT_EVENT_ALERT_RULES_JSON", "value": ""}])

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_validate_accepts_multiline_json(self) -> None:
        validation = self.service.validate(items=[{
            "key": "AGENT_EVENT_ALERT_RULES_JSON",
            "value": (
                "[\n"
                '  {"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800}\n'
                "]"
            ),
        }])

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_update_minifies_multiline_json_before_storage(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{
                "key": "AGENT_EVENT_ALERT_RULES_JSON",
                "value": (
                    "[\n"
                    '  {"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800}\n'
                    "]"
                ),
            }],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        current_map = self.manager.read_config_map()
        self.assertEqual(
            current_map["AGENT_EVENT_ALERT_RULES_JSON"],
            '[{"stock_code":"600519","alert_type":"price_cross","direction":"above","price":1800}]',
        )

    def test_validate_accepts_legacy_agent_orchestrator_mode_alias(self) -> None:
        validation = self.service.validate(items=[{"key": "AGENT_ORCHESTRATOR_MODE", "value": "strategy"}])

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_get_config_projects_legacy_strategy_aliases_onto_skill_fields(self) -> None:
        self._rewrite_env(
            "AGENT_STRATEGY_DIR=legacy-strategies",
            "AGENT_STRATEGY_AUTOWEIGHT=false",
            "AGENT_STRATEGY_ROUTING=manual",
        )

        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertEqual(items["AGENT_SKILL_DIR"]["value"], "legacy-strategies")
        self.assertEqual(items["AGENT_SKILL_AUTOWEIGHT"]["value"], "false")
        self.assertEqual(items["AGENT_SKILL_ROUTING"]["value"], "manual")
        self.assertNotIn("AGENT_STRATEGY_DIR", items)
        self.assertNotIn("AGENT_STRATEGY_AUTOWEIGHT", items)
        self.assertNotIn("AGENT_STRATEGY_ROUTING", items)

    def test_get_config_respects_empty_canonical_skill_field_over_legacy_alias(self) -> None:
        self._rewrite_env(
            "AGENT_SKILL_DIR=",
            "AGENT_STRATEGY_DIR=legacy-strategies",
        )

        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertEqual(items["AGENT_SKILL_DIR"]["value"], "")

    def test_get_config_normalizes_legacy_orchestrator_mode_for_ui(self) -> None:
        self._rewrite_env("AGENT_ORCHESTRATOR_MODE=strategy")

        payload = self.service.get_config(include_schema=True)
        items = {item["key"]: item for item in payload["items"]}

        self.assertEqual(items["AGENT_ORCHESTRATOR_MODE"]["value"], "specialist")
        self.assertEqual(
            items["AGENT_ORCHESTRATOR_MODE"]["schema"]["validation"]["enum"],
            ["quick", "standard", "full", "specialist", "strategy", "skill"],
        )

    @patch.object(
        Config,
        "_parse_litellm_yaml",
        return_value=[{"model_name": "gemini/gemini-2.5-flash", "litellm_params": {"model": "gemini/gemini-2.5-flash"}}],
    )
    def test_validate_reports_unknown_primary_model_for_litellm_yaml(self, _mock_parse_yaml) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LITELLM_CONFIG", "value": "/tmp/litellm.yaml"},
                {"key": "LITELLM_MODEL", "value": "openai/gpt-4o-mini"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "LITELLM_MODEL" and issue["code"] == "unknown_model" for issue in validation["issues"]))

    @patch.object(Config, "_parse_litellm_yaml", return_value=[])
    def test_validate_keeps_channel_checks_when_litellm_yaml_has_no_models(self, _mock_parse_yaml) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LITELLM_CONFIG", "value": "/tmp/litellm.yaml"},
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_API_KEY", "value": ""},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "missing_api_key" for issue in validation["issues"]))

    def test_validate_reports_stale_primary_model_when_all_channels_disabled(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_ENABLED", "value": "false"},
                {"key": "LITELLM_MODEL", "value": "openai/gpt-4o-mini"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation["issues"]))

    def test_validate_accepts_minimax_model_as_direct_env_provider(self) -> None:
        """minimax is NOT a managed key provider; it uses LiteLLM direct-env routing."""
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "minimax/MiniMax-M1"},
                {"key": "LLM_PRIMARY_ENABLED", "value": "false"},
                {"key": "LITELLM_MODEL", "value": "minimax/MiniMax-M1"},
            ]
        )

        self.assertFalse(any(issue.get("key") == "LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation.get("issues", [])))

    def test_validate_accepts_cohere_model_as_direct_env_provider(self) -> None:
        """cohere is NOT a managed key provider; it also uses LiteLLM direct-env routing."""
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_ENABLED", "value": "false"},
                {"key": "LITELLM_MODEL", "value": "cohere/command-r-plus"},
            ]
        )

        self.assertFalse(any(issue.get("key") == "LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation.get("issues", [])))

    def test_validate_accepts_google_model_as_direct_env_provider(self) -> None:
        """google prefix is not managed by project key buckets and is kept as direct provider routing."""
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_ENABLED", "value": "false"},
                {"key": "LITELLM_MODEL", "value": "google/gemini-2.5-flash"},
            ]
        )

        self.assertFalse(any(issue.get("key") == "LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation.get("issues", [])))

    def test_validate_accepts_xai_model_as_direct_env_provider(self) -> None:
        """xai is not a managed provider key and is also preserved as direct runtime source."""
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_ENABLED", "value": "false"},
                {"key": "LITELLM_MODEL", "value": "xai/grok-beta"},
            ]
        )

        self.assertFalse(any(issue.get("key") == "LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation.get("issues", [])))

    def test_validate_reports_stale_agent_primary_model_when_all_channels_disabled(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_ENABLED", "value": "false"},
                {"key": "AGENT_LITELLM_MODEL", "value": "openai/gpt-4o-mini"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "AGENT_LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation["issues"]))

    def test_validate_allows_primary_model_when_all_channels_disabled_but_legacy_key_exists(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "primary"},
                {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test-value"},
                {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                {"key": "LLM_PRIMARY_ENABLED", "value": "false"},
                {"key": "OPENAI_API_KEY", "value": "sk-legacy-value"},
                {"key": "LITELLM_MODEL", "value": "openai/gpt-4o-mini"},
            ]
        )

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_validate_allows_anspire_channel_with_shared_key_defaults(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "anspire"},
                {"key": "ANSPIRE_API_KEYS", "value": "sk-anspire-test-value"},
            ]
        )

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_validate_treats_blank_anspire_channel_enabled_as_shared_disable(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "anspire"},
                {"key": "LLM_ANSPIRE_ENABLED", "value": "   "},
                {"key": "ANSPIRE_LLM_ENABLED", "value": "false"},
            ]
        )

        self.assertTrue(validation["valid"], validation["issues"])
        self.assertEqual(validation["issues"], [])

    def test_validate_excludes_blank_disabled_anspire_channel_from_runtime_models(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "anspire"},
                {"key": "LLM_ANSPIRE_ENABLED", "value": "   "},
                {"key": "ANSPIRE_LLM_ENABLED", "value": "false"},
                {"key": "ANSPIRE_API_KEYS", "value": "sk-anspire-test-value"},
                {"key": "LITELLM_MODEL", "value": f"openai/{ANSPIRE_LLM_MODEL_DEFAULT}"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation["issues"]))

    def test_validate_excludes_disabled_anspire_channel_from_legacy_runtime_source(self) -> None:
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "anspire"},
                {"key": "LLM_ANSPIRE_ENABLED", "value": "false"},
                {"key": "ANSPIRE_API_KEYS", "value": "sk-anspire-test-value"},
                {"key": "LITELLM_MODEL", "value": f"openai/{ANSPIRE_LLM_MODEL_DEFAULT}"},
            ]
        )

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["key"] == "LITELLM_MODEL" and issue["code"] == "missing_runtime_source" for issue in validation["issues"]))

    @staticmethod
    def _mock_http_response(status_code: int, json_body: Optional[Dict[str, Any]] = None):
        response = Mock()
        response.status_code = status_code
        response.text = "ok" if status_code == 200 else "error"
        response.json.return_value = json_body or {"errcode": 0}
        return response

    def _notification_test_env(self):
        return patch.dict(os.environ, {"ENV_FILE": str(self.env_path)}, clear=True)

    @patch("src.notification_sender.wechat_sender.requests.post")
    def test_test_notification_channel_uses_temporary_items_without_persisting(self, mock_post) -> None:
        mock_post.return_value = self._mock_http_response(200, {"errcode": 0})

        with self._notification_test_env():
            before_instance = Config.get_instance()
            payload = self.service.test_notification_channel(
                channel="wechat",
                items=[{"key": "WECHAT_WEBHOOK_URL", "value": "https://qyapi.example.com/cgi-bin/webhook/send?key=secret"}],
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )
            self.assertIs(Config.get_instance(), before_instance)

        self.assertTrue(payload["success"])
        self.assertEqual(payload["attempts"][0]["latency_ms"] >= 0, True)
        self.assertIn("key=***", payload["attempts"][0]["target"])
        self.assertNotIn("WECHAT_WEBHOOK_URL", self.env_path.read_text(encoding="utf-8"))
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 3)

    def test_test_notification_channel_reports_missing_config(self) -> None:
        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="telegram",
                items=[{"key": "TELEGRAM_BOT_TOKEN", "value": "token"}],
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "config_missing")
        self.assertIn("TELEGRAM_CHAT_ID", payload["message"])

    def test_test_notification_channel_reports_nearest_feishu_app_bot_missing_key(self) -> None:
        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="feishu",
                items=[
                    {"key": "FEISHU_APP_ID", "value": "cli_xxx"},
                    {"key": "FEISHU_APP_SECRET", "value": "secret_xxx"},
                ],
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "config_missing")
        self.assertIn("FEISHU_CHAT_ID", payload["message"])
        self.assertNotIn("FEISHU_WEBHOOK_URL", payload["message"])

    def test_test_notification_channel_feishu_domain_draft_builds_isolated_config(self) -> None:
        captured: Dict[str, Any] = {}

        def fake_dispatch(**kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "message": "ok",
                "error_code": None,
                "stage": "notification_send",
                "retryable": False,
                "latency_ms": 0,
                "attempts": [],
            }

        with self._notification_test_env(), patch.object(
            SystemConfigService,
            "_dispatch_notification_test",
            side_effect=fake_dispatch,
        ):
            payload = self.service.test_notification_channel(
                channel="feishu",
                items=[
                    {"key": "FEISHU_APP_ID", "value": "cli_xxx"},
                    {"key": "FEISHU_APP_SECRET", "value": "secret_xxx"},
                    {"key": "FEISHU_CHAT_ID", "value": "oc_xxx"},
                    {"key": "FEISHU_DOMAIN", "value": "lark"},
                ],
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )

        self.assertTrue(payload["success"])
        self.assertEqual(captured["config"].feishu_domain, "lark")

    @patch("src.notification_sender.wechat_sender.requests.post")
    def test_test_notification_channel_skips_masked_secret_overwrite(self, mock_post) -> None:
        self._rewrite_env("WECHAT_WEBHOOK_URL=https://saved.example.com/hook?key=savedsecret")
        mock_post.return_value = self._mock_http_response(200, {"errcode": 0})

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="wechat",
                items=[{"key": "WECHAT_WEBHOOK_URL", "value": "******"}],
                mask_token="******",
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )

        self.assertTrue(payload["success"])
        self.assertEqual(mock_post.call_args[0][0], "https://saved.example.com/hook?key=savedsecret")

    @patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_test_notification_channel_returns_custom_webhook_attempts(self, mock_post) -> None:
        mock_post.side_effect = [
            self._mock_http_response(500),
            self._mock_http_response(200),
        ]

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="custom",
                items=[
                    {
                        "key": "CUSTOM_WEBHOOK_URLS",
                        "value": (
                            "https://example.com/robot/send?access_token=first,"
                            "https://example.com/verylongsecrettoken1234567890"
                        ),
                    }
                ],
                title="Test title",
                content="hello",
                timeout_seconds=4,
            )

        self.assertTrue(payload["success"])
        self.assertIn("部分成功", payload["message"])
        self.assertIn("1/2", payload["message"])
        self.assertEqual(len(payload["attempts"]), 2)
        self.assertFalse(payload["attempts"][0]["success"])
        self.assertTrue(payload["attempts"][1]["success"])
        self.assertIn("access_token=***", payload["attempts"][0]["target"])
        self.assertNotIn("verylongsecrettoken1234567890", payload["attempts"][1]["target"])
        self.assertNotIn("access_token=first", str(payload))
        self.assertEqual(mock_post.call_args_list[0].kwargs["timeout"], 4)

    @patch("src.notification_sender.custom_webhook_sender.requests.post")
    def test_test_notification_channel_custom_webhook_all_failures_are_retryable(self, mock_post) -> None:
        mock_post.side_effect = [
            self._mock_http_response(500),
            self._mock_http_response(429),
        ]

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="custom",
                items=[
                    {
                        "key": "CUSTOM_WEBHOOK_URLS",
                        "value": (
                            "https://example.com/robot/send?access_token=first,"
                            "https://example.com/robot/send?token=second"
                        ),
                    }
                ],
                title="Test title",
                content="hello",
                timeout_seconds=4,
            )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "send_failed")
        self.assertTrue(payload["retryable"])
        self.assertIn("失败", payload["message"])
        self.assertIn("0/2", payload["message"])
        self.assertEqual(len(payload["attempts"]), 2)
        self.assertTrue(all(attempt["retryable"] for attempt in payload["attempts"]))
        self.assertNotIn("access_token=first", str(payload))
        self.assertNotIn("token=second", str(payload))

    @patch("src.notification_sender.ntfy_sender.requests.post")
    def test_test_notification_channel_supports_ntfy_and_masks_topic_target(self, mock_post) -> None:
        mock_post.return_value = self._mock_http_response(200)

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="ntfy",
                items=[
                    {"key": "NTFY_URL", "value": "https://ntfy.sh/private-topic"},
                    {"key": "NTFY_TOKEN", "value": "secret-token"},
                ],
                title="Test title",
                content="hello",
                timeout_seconds=4,
            )

        self.assertTrue(payload["success"])
        self.assertEqual(mock_post.call_args.args[0], "https://ntfy.sh")
        self.assertEqual(mock_post.call_args.kwargs["json"]["topic"], "private-topic")
        self.assertEqual(mock_post.call_args.kwargs["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 4)
        self.assertIn("https://ntfy.sh/***", payload["attempts"][0]["target"])
        self.assertNotIn("private-topic", str(payload))
        self.assertNotIn("NTFY_URL", self.env_path.read_text(encoding="utf-8"))

    @patch("src.notification_sender.ntfy_sender.requests.post")
    def test_test_notification_channel_rejects_ntfy_url_without_topic(self, mock_post) -> None:
        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="ntfy",
                items=[{"key": "NTFY_URL", "value": "https://ntfy.sh"}],
                title="Test title",
                content="hello",
                timeout_seconds=4,
            )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "config_invalid")
        self.assertEqual(payload["stage"], "config_validation")
        self.assertIn("NTFY_URL", payload["message"])
        mock_post.assert_not_called()

    @patch("src.notification_sender.gotify_sender.requests.post")
    def test_test_notification_channel_supports_gotify_and_keeps_token_out_of_url(self, mock_post) -> None:
        mock_post.return_value = self._mock_http_response(200)

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="gotify",
                items=[
                    {"key": "GOTIFY_URL", "value": "https://gotify.example"},
                    {"key": "GOTIFY_TOKEN", "value": "secret-token"},
                ],
                title="Test title",
                content="hello",
                timeout_seconds=4,
            )

        self.assertTrue(payload["success"])
        self.assertEqual(mock_post.call_args.args[0], "https://gotify.example/message")
        self.assertEqual(mock_post.call_args.kwargs["headers"]["X-Gotify-Key"], "secret-token")
        self.assertEqual(mock_post.call_args.kwargs["timeout"], 4)
        self.assertEqual(payload["attempts"][0]["target"], "https://gotify.example")
        self.assertNotIn("secret-token", str(payload))
        self.assertNotIn("GOTIFY_URL", self.env_path.read_text(encoding="utf-8"))

    @patch("src.notification_sender.gotify_sender.requests.post")
    def test_test_notification_channel_rejects_gotify_message_endpoint(self, mock_post) -> None:
        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="gotify",
                items=[
                    {"key": "GOTIFY_URL", "value": "https://gotify.example/message"},
                    {"key": "GOTIFY_TOKEN", "value": "secret-token"},
                ],
                title="Test title",
                content="hello",
                timeout_seconds=4,
            )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "config_invalid")
        self.assertEqual(payload["stage"], "config_validation")
        self.assertIn("GOTIFY_URL", payload["message"])
        mock_post.assert_not_called()

    @patch(
        "src.notification_sender.WechatSender.send_to_wechat",
        side_effect=requests.exceptions.Timeout(
            "timeout for https://qyapi.example.com/cgi-bin/webhook/send?key=secret token=abc123"
        ),
    )
    def test_test_notification_channel_classifies_escaped_timeout(self, _mock_send) -> None:
        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="wechat",
                items=[
                    {
                        "key": "WECHAT_WEBHOOK_URL",
                        "value": "https://qyapi.example.com/cgi-bin/webhook/send?key=secret",
                    }
                ],
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "timeout")
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["attempts"][0]["error_code"], "timeout")
        self.assertIn("key=***", payload["attempts"][0]["target"])
        self.assertNotIn("key=secret", str(payload))
        self.assertNotIn("abc123", str(payload))

    @patch("src.notification_sender.telegram_sender.requests.post")
    def test_test_notification_channel_masks_short_sensitive_target(self, mock_post) -> None:
        mock_post.return_value = self._mock_http_response(200, {"ok": True})

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="telegram",
                items=[
                    {"key": "TELEGRAM_BOT_TOKEN", "value": "tok123"},
                    {"key": "TELEGRAM_CHAT_ID", "value": "chat-id"},
                ],
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["attempts"][0]["target"], "***")
        self.assertNotIn("tok123", str(payload))

    @patch("src.notification_sender.wechat_sender.requests.post")
    def test_test_notification_channel_strips_url_userinfo_from_target(self, mock_post) -> None:
        mock_post.return_value = self._mock_http_response(200, {"errcode": 0})

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="wechat",
                items=[
                    {
                        "key": "WECHAT_WEBHOOK_URL",
                        "value": "https://user:password@example.com/cgi-bin/webhook/send?key=secret",
                    }
                ],
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )

        self.assertTrue(payload["success"])
        target = payload["attempts"][0]["target"]
        self.assertIn("https://example.com/cgi-bin/webhook/send?key=***", target)
        self.assertNotIn("user", target)
        self.assertNotIn("password", target)

    @patch("src.notification_sender.discord_sender.requests.post")
    def test_test_notification_channel_prefers_discord_main_channel_alias(self, mock_post) -> None:
        mock_post.return_value = self._mock_http_response(200)

        with self._notification_test_env():
            payload = self.service.test_notification_channel(
                channel="discord",
                items=[
                    {"key": "DISCORD_BOT_TOKEN", "value": "bot-token"},
                    {"key": "DISCORD_MAIN_CHANNEL_ID", "value": "main-channel"},
                    {"key": "DISCORD_CHANNEL_ID", "value": "legacy-channel"},
                ],
                title="Test title",
                content="hello",
                timeout_seconds=3,
            )

        self.assertTrue(payload["success"])
        self.assertIn("/channels/main-channel/messages", mock_post.call_args[0][0])

    @patch("litellm.completion")
    def test_test_llm_channel_returns_success_payload(self, mock_completion) -> None:
        mock_completion.return_value = type(
            "MockResponse",
            (),
            {
                "choices": [type("Choice", (), {"message": type("Message", (), {"content": "OK"})()})()],
            },
        )()

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.deepseek.com/v1",
            api_key="sk-test-value",
            models=["deepseek-chat"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["resolved_protocol"], "openai")
        self.assertEqual(payload["resolved_model"], "openai/deepseek-chat")
        self.assertEqual(payload["capability_results"], {})
        self.assertEqual(mock_completion.call_count, 1)

    @patch("litellm.completion")
    def test_test_llm_channel_falls_back_to_message_content_when_content_blocks_empty(
        self,
        mock_completion,
    ) -> None:
        mock_completion.return_value = type(
            "MockResponse",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {
                            "content_blocks": [],
                            "message": type("Message", (), {"content": "OK"})(),
                        },
                    )(),
                ]
            },
        )()

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.deepseek.com/v1",
            api_key="sk-test-value",
            models=["deepseek-chat"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["resolved_model"], "openai/deepseek-chat")

    @patch("litellm.completion")
    def test_test_llm_channel_allows_ollama_prefix_without_explicit_protocol(self, mock_completion) -> None:
        mock_completion.return_value = type(
            "MockResponse",
            (),
            {
                "choices": [type("Choice", (), {"message": type("Message", (), {"content": "OK"})()})()],
            },
        )()

        payload = self.service.test_llm_channel(
            name="lab",
            protocol="",
            base_url="http://localhost:11434/v1",
            api_key="",
            models=["ollama/llama3"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["resolved_protocol"], "ollama")
        self.assertEqual(payload["resolved_model"], "ollama/llama3")

    @patch("litellm.completion")
    def test_test_llm_channel_normalizes_kimi_temperature(self, mock_completion) -> None:
        mock_completion.return_value = type(
            "MockResponse",
            (),
            {
                "choices": [type("Choice", (), {"message": type("Message", (), {"content": "OK"})()})()],
            },
        )()

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.moonshot.cn/v1",
            api_key="sk-test-value",
            models=["kimi-k2.6"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["resolved_model"], "openai/kimi-k2.6")
        self.assertEqual(mock_completion.call_args.kwargs["temperature"], 1.0)

    def test_update_switching_to_kimi_does_not_rewrite_saved_llm_temperature(self) -> None:
        self._rewrite_env(
            "LITELLM_MODEL=openai/gpt-4o-mini",
            "LLM_TEMPERATURE=0.42",
        )

        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "LITELLM_MODEL", "value": "openai/kimi-k2.6"}],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["LITELLM_MODEL"], "openai/kimi-k2.6")
        self.assertEqual(current_map["LLM_TEMPERATURE"], "0.42")

    def test_update_runtime_model_cleanup_does_not_rewrite_temperature(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "LLM_CHANNELS=deepseek",
            "LLM_DEEPSEEK_PROTOCOL=deepseek",
            "LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com",
            "LLM_DEEPSEEK_API_KEY=sk-test-value",
            "LLM_DEEPSEEK_MODELS=deepseek-chat,deepseek-v4-flash",
            "LITELLM_MODEL=deepseek/deepseek-chat",
            "AGENT_LITELLM_MODEL=deepseek/deepseek-v4-flash",
            "LLM_TEMPERATURE=0.42",
            "LITELLM_FALLBACK_MODELS=deepseek/deepseek-v4-flash,cohere/command-r-plus",
            "VISION_MODEL=deepseek/deepseek-chat",
        )

        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[
                {"key": "LLM_DEEPSEEK_MODELS", "value": "deepseek-v4-flash"},
                {"key": "LITELLM_MODEL", "value": ""},
                {"key": "AGENT_LITELLM_MODEL", "value": ""},
                {"key": "LITELLM_FALLBACK_MODELS", "value": "deepseek/deepseek-v4-flash"},
                {"key": "VISION_MODEL", "value": ""},
            ],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["LLM_TEMPERATURE"], "0.42")
        self.assertEqual(current_map["LITELLM_MODEL"], "")
        self.assertEqual(current_map["AGENT_LITELLM_MODEL"], "")
        self.assertEqual(current_map["VISION_MODEL"], "")
        self.assertEqual(
            current_map["LITELLM_FALLBACK_MODELS"],
            "deepseek/deepseek-v4-flash",
        )

    def test_update_warns_when_clearing_unsupported_hermes_keys(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "LLM_CHANNELS=hermes",
            "LLM_HERMES_PROTOCOL=openai",
            "LLM_HERMES_BASE_URL=http://127.0.0.1:8642/v1",
            "LLM_HERMES_API_KEY=sk-hermes-test-value",
            "LLM_HERMES_API_KEYS=sk-old-a,sk-old-b",
            'LLM_HERMES_EXTRA_HEADERS={"X":"Y"}',
            "LLM_HERMES_MODELS=hermes-agent",
        )

        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[
                {"key": "LLM_HERMES_API_KEYS", "value": ""},
                {"key": "LLM_HERMES_EXTRA_HEADERS", "value": ""},
            ],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        joined = " | ".join(response["warnings"])
        self.assertIn("Hermes Phase 3 不支持", joined)
        self.assertIn("LLM_HERMES_API_KEYS", joined)
        self.assertIn("LLM_HERMES_EXTRA_HEADERS", joined)
        self.assertIn("LLM_HERMES_API_KEY", joined)
        self.assertIn(".env 备份", joined)
        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["LLM_HERMES_API_KEYS"], "")
        self.assertEqual(current_map["LLM_HERMES_EXTRA_HEADERS"], "")

    @patch("litellm.completion")
    def test_test_llm_channel_does_not_persist_normalized_kimi_temperature(self, mock_completion) -> None:
        self._rewrite_env("LLM_TEMPERATURE=0.42")
        mock_completion.return_value = type(
            "MockResponse",
            (),
            {
                "choices": [type("Choice", (), {"message": type("Message", (), {"content": "OK"})()})()],
            },
        )()

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.moonshot.cn/v1",
            api_key="sk-test-value",
            models=["kimi-k2.6"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(mock_completion.call_args.kwargs["temperature"], 1.0)
        self.assertEqual(self.manager.read_config_map()["LLM_TEMPERATURE"], "0.42")

    @patch("litellm.completion")
    def test_test_llm_channel_omits_temperature_for_gpt5_family(self, mock_completion) -> None:
        mock_completion.return_value = type(
            "MockResponse",
            (),
            {
                "choices": [type("Choice", (), {"message": type("Message", (), {"content": "OK"})()})()],
            },
        )()

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt5.5-ferr"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["resolved_model"], "openai/gpt5.5-ferr")
        self.assertNotIn("temperature", mock_completion.call_args.kwargs)

    @patch("litellm.completion")
    @patch("src.services.system_config_service.Config._load_from_env")
    def test_test_llm_channel_recovers_from_unsupported_temperature(
        self,
        mock_load_config,
        mock_completion,
    ) -> None:
        from src.llm.generation_params import clear_litellm_generation_param_recovery_cache

        clear_litellm_generation_param_recovery_cache()
        mock_load_config.return_value = SimpleNamespace(llm_temperature=0.42)
        mock_completion.side_effect = [
            RuntimeError("Unsupported parameter: temperature is not supported"),
            type(
                "MockResponse",
                (),
                {
                    "choices": [type("Choice", (), {"message": type("Message", (), {"content": "OK"})()})()],
                },
            )(),
        ]

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["custom-temp-locked-settings"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(mock_completion.call_args_list[0].kwargs["temperature"], 0.42)
        self.assertNotIn("temperature", mock_completion.call_args_list[1].kwargs)

    @patch("litellm.completion")
    @patch("src.services.system_config_service.Config._load_from_env")
    def test_test_llm_channel_uses_runtime_temperature_for_non_kimi_models(
        self,
        mock_load_config,
        mock_completion,
    ) -> None:
        mock_load_config.return_value = SimpleNamespace(llm_temperature=0.42)
        mock_completion.return_value = type(
            "MockResponse",
            (),
            {
                "choices": [type("Choice", (), {"message": type("Message", (), {"content": "OK"})()})()],
            },
        )()

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt-4o-mini"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["resolved_model"], "openai/gpt-4o-mini")
        self.assertEqual(mock_completion.call_args.kwargs["temperature"], 0.42)

    @patch("litellm.completion")
    def test_test_llm_channel_classifies_common_failure_scenarios(self, mock_completion) -> None:
        cases = [
            (PermissionError("401 Unauthorized Bearer sk-secret-value"), "auth", "chat_completion", False),
            (TimeoutError("request timed out"), "timeout", "chat_completion", True),
            (Exception("404 model not found: gpt-4o-mini"), "model_not_found", "chat_completion", False),
            (Exception("The model `gpt-4o-mini` does not exist"), "model_not_found", "chat_completion", False),
            (Exception("404 Not Found: page not found"), "network_error", "chat_completion", False),
            (
                type("MockResponse", (), {"choices": [type("Choice", (), {"message": type("Message", (), {"content": ""})()})()]})(),
                "empty_response",
                "response_parse",
                False,
            ),
            (object(), "format_error", "response_parse", False),
        ]

        for response_or_exc, error_code, stage, retryable in cases:
            with self.subTest(error_code=error_code):
                mock_completion.reset_mock()
                if isinstance(response_or_exc, Exception):
                    mock_completion.side_effect = response_or_exc
                    mock_completion.return_value = None
                else:
                    mock_completion.side_effect = None
                    mock_completion.return_value = response_or_exc

                payload = self.service.test_llm_channel(
                    name="primary",
                    protocol="openai",
                    base_url="https://api.example.com/v1",
                    api_key="sk-secret-value",
                    models=["gpt-4o-mini"],
                )

                self.assertFalse(payload["success"])
                self.assertEqual(payload["error_code"], error_code)
                self.assertEqual(payload["stage"], stage)
                self.assertEqual(payload["retryable"], retryable)
                if error_code == "auth":
                    self.assertNotIn("sk-secret-value", payload["error"])
                if error_code == "format_error":
                    self.assertIn("choices", payload["error"])

    @patch("litellm.completion")
    def test_test_llm_channel_marks_requested_capabilities_skipped_when_base_fails(self, mock_completion) -> None:
        mock_completion.side_effect = PermissionError("401 Unauthorized Bearer sk-secret-value")

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-secret-value",
            models=["gpt-4o-mini"],
            capability_checks=["json", "tools"],
        )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "auth")
        self.assertEqual(payload["details"]["reason"], "api_key_rejected")
        self.assertEqual(payload["capability_results"]["json"]["status"], "skipped")
        self.assertEqual(payload["capability_results"]["tools"]["details"]["reason"], "base_test_failed")
        self.assertEqual(mock_completion.call_count, 1)

    @patch("litellm.completion")
    def test_test_llm_channel_runs_json_and_tools_capability_checks(self, mock_completion) -> None:
        tool_call = SimpleNamespace(function=SimpleNamespace(name="dsa_probe_echo"))
        mock_completion.side_effect = [
            self._mock_completion_response("OK"),
            self._mock_completion_response('{"status":"ok"}'),
            self._mock_completion_response("", tool_calls=[tool_call]),
        ]

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt-4o-mini"],
            capability_checks=["tools", "json", "tools"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(list(payload["capability_results"].keys()), ["json", "tools"])
        self.assertEqual(payload["capability_results"]["json"]["status"], "passed")
        self.assertEqual(payload["capability_results"]["tools"]["status"], "passed")
        self.assertEqual(mock_completion.call_count, 3)
        self.assertEqual(mock_completion.call_args_list[1].kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(mock_completion.call_args_list[2].kwargs["tool_choice"]["function"]["name"], "dsa_probe_echo")

    @patch("litellm.completion")
    def test_test_llm_channel_json_capability_ignores_minimax_reasoning_blocks(self, mock_completion) -> None:
        mock_completion.side_effect = [
            self._mock_completion_response("OK"),
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "content_blocks": [
                                {"type": "reasoning", "content": "Internal reasoning"},
                                {"type": "text", "text": '{"status":"ok"}'},
                            ],
                        }
                    }
                ]
            },
        ]

        payload = self.service.test_llm_channel(
            name="minimax",
            protocol="openai",
            base_url="https://api.minimax.io/v1",
            api_key="sk-test-value",
            models=["MiniMax-M3"],
            capability_checks=["json"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["capability_results"]["json"]["status"], "passed")

    @patch("litellm.completion")
    def test_test_llm_channel_json_capability_strips_minimax_think_wrapper(self, mock_completion) -> None:
        mock_completion.side_effect = [
            self._mock_completion_response("OK"),
            self._mock_completion_response('<think>Internal reasoning</think>{"status":"ok"}'),
        ]

        payload = self.service.test_llm_channel(
            name="minimax",
            protocol="openai",
            base_url="https://api.minimax.io/v1",
            api_key="sk-test-value",
            models=["MiniMax-M3"],
            capability_checks=["json"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["capability_results"]["json"]["status"], "passed")

    @patch("litellm.completion")
    def test_test_llm_channel_reports_json_capability_failures(self, mock_completion) -> None:
        mock_completion.side_effect = [
            self._mock_completion_response("OK"),
            self._mock_completion_response("not json"),
        ]

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt-4o-mini"],
            capability_checks=["json"],
        )

        self.assertTrue(payload["success"])
        result = payload["capability_results"]["json"]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "format_error")
        self.assertEqual(result["details"]["reason"], "non_json")

    @patch("litellm.completion")
    def test_test_llm_channel_runs_stream_capability_check_and_closes_stream(self, mock_completion) -> None:
        class _Stream:
            def __init__(self):
                self.closed = False

            def __iter__(self):
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="OK"))])

            def close(self):
                self.closed = True

        stream = _Stream()
        mock_completion.side_effect = [
            self._mock_completion_response("OK"),
            stream,
        ]

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt-4o-mini"],
            capability_checks=["stream"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["capability_results"]["stream"]["status"], "passed")
        self.assertTrue(stream.closed)
        self.assertTrue(mock_completion.call_args_list[1].kwargs["stream"])

    @patch("litellm.completion")
    def test_test_llm_channel_ignores_stream_close_failures(self, mock_completion) -> None:
        class _Stream:
            def __init__(self):
                self.close_attempted = False

            def __iter__(self):
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="OK"))])

            def close(self):
                self.close_attempted = True
                raise RuntimeError("transport already closed")

        stream = _Stream()
        mock_completion.side_effect = [
            self._mock_completion_response("OK"),
            stream,
        ]

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt-4o-mini"],
            capability_checks=["stream"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["capability_results"]["stream"]["status"], "passed")
        self.assertTrue(stream.close_attempted)

    @patch("litellm.completion")
    def test_test_llm_channel_runs_vision_capability_check(self, mock_completion) -> None:
        mock_completion.side_effect = [
            self._mock_completion_response("OK"),
            self._mock_completion_response("OK"),
        ]

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt-4o-mini"],
            capability_checks=["vision"],
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["capability_results"]["vision"]["status"], "passed")
        vision_content = mock_completion.call_args_list[1].kwargs["messages"][0]["content"]
        self.assertEqual(vision_content[1]["type"], "image_url")
        self.assertTrue(vision_content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    @patch("litellm.completion")
    def test_test_llm_channel_classifies_capability_unsupported(self, mock_completion) -> None:
        mock_completion.side_effect = [
            self._mock_completion_response("OK"),
            Exception("response_format is not supported"),
        ]

        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key="sk-test-value",
            models=["gpt-4o-mini"],
            capability_checks=["json"],
        )

        result = payload["capability_results"]["json"]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "capability_unsupported")
        self.assertEqual(result["details"]["reason"], "capability_unsupported")

    @patch("litellm.completion")
    def test_test_llm_channel_adds_focused_diagnostic_reasons(self, mock_completion) -> None:
        class RateLimitError(Exception):
            pass

        cases = [
            (Exception("account balance insufficient"), "quota", "insufficient_balance"),
            (RateLimitError("account balance insufficient"), "quota", "insufficient_balance"),
            (RateLimitError("insufficient_quota"), "quota", "quota_exceeded"),
            (Exception("account balance insufficient; your request was blocked"), "quota", "insufficient_balance"),
            (RateLimitError("rate limit: your request was blocked by policy"), "quota", "rate_limit"),
            (Exception("DNS lookup failed"), "network_error", "dns_error"),
            (Exception("TLS certificate verify failed"), "network_error", "tls_error"),
            (Exception("Connection refused"), "network_error", "connection_refused"),
            (Exception("connection request was blocked by firewall"), "network_error", "network_error"),
            (Exception("connection blocked by policy"), "network_error", "network_error"),
            (Exception("request blocked by firewall"), "network_error", "network_error"),
            (Exception("blocked"), "network_error", "unknown_error"),
            (Exception("model gpt-4o is not authorized for this account"), "model_not_found", "model_access_denied"),
            (Exception("litellm.APIError: APIError: OpenAIException - Model disabled."), "model_not_found", "model_access_denied"),
            (Exception("Model is disabled for this account"), "model_not_found", "model_access_denied"),
            (
                Exception("litellm.APIError: APIError: OpenAIException - Your request was blocked."),
                "request_blocked",
                "provider_blocked",
            ),
            (Exception("Forbidden: your request was blocked by content policy"), "request_blocked", "provider_blocked"),
            (Exception("blocked by policy"), "request_blocked", "provider_blocked"),
            (Exception("moderation_blocked"), "request_blocked", "provider_blocked"),
            (Exception("LLM Provider NOT provided for model foo"), "model_not_found", "provider_prefix_mismatch"),
        ]

        for exc, error_code, reason in cases:
            with self.subTest(reason=reason):
                mock_completion.reset_mock()
                mock_completion.side_effect = exc
                payload = self.service.test_llm_channel(
                    name="primary",
                    protocol="openai",
                    base_url="https://api.example.com/v1",
                    api_key="sk-test-value",
                    models=["gpt-4o-mini"],
                )

                self.assertFalse(payload["success"])
                self.assertEqual(payload["error_code"], error_code)
                self.assertEqual(payload["details"]["reason"], reason)
                if reason in {"model_access_denied", "provider_blocked"}:
                    self.assertFalse(payload["retryable"])
                    self.assertEqual(payload["details"]["model"], "openai/gpt-4o-mini")
                    self.assertEqual(payload["resolved_model"], "openai/gpt-4o-mini")

    def test_test_llm_channel_reports_comma_only_api_key_as_missing(self) -> None:
        payload = self.service.test_llm_channel(
            name="primary",
            protocol="openai",
            base_url="https://api.example.com/v1",
            api_key=", ,",
            models=["gpt-4o-mini"],
        )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["error_code"], "invalid_config")
        self.assertEqual(payload["details"]["reason"], "missing_api_key")

    @patch("src.services.system_config_service.requests.get")
    def test_discover_llm_channel_models_returns_deduped_ids(self, mock_get) -> None:
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "qwen-plus"},
                {"id": "qwen-plus"},
                {"id": "qwen-turbo"},
            ]
        }
        mock_get.return_value = mock_response

        payload = self.service.discover_llm_channel_models(
            name="dashscope",
            protocol="openai",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="sk-test-value",
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["resolved_protocol"], "openai")
        self.assertEqual(payload["models"], ["qwen-plus", "qwen-turbo"])
        mock_get.assert_called_once()
        self.assertEqual(
            mock_get.call_args.args[0],
            "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
        )
        self.assertEqual(
            mock_get.call_args.kwargs["headers"]["Authorization"],
            "Bearer sk-test-value",
        )
        self.assertFalse(mock_get.call_args.kwargs["allow_redirects"])

    @patch("src.services.system_config_service.requests.get")
    def test_discover_llm_channel_models_classifies_error_scenarios(self, mock_get) -> None:
        auth_response = Mock(ok=False, status_code=401, text="invalid api key sk-secret-value")
        auth_response.json.return_value = {"error": {"message": "invalid api key sk-secret-value"}}
        not_found_response = Mock(ok=False, status_code=404, text="not found")
        not_found_response.json.return_value = {"error": {"message": "not found"}}
        billing_response = Mock(ok=False, status_code=402, text="account balance insufficient")
        billing_response.json.return_value = {"error": {"message": "account balance insufficient"}}
        billing_rate_limit_response = Mock(ok=False, status_code=429, text="account balance insufficient")
        billing_rate_limit_response.json.return_value = {"error": {"message": "account balance insufficient"}}
        quota_exceeded_response = Mock(ok=False, status_code=429, text="insufficient_quota")
        quota_exceeded_response.json.return_value = {"error": {"message": "insufficient_quota"}}
        quota_blocked_response = Mock(ok=False, status_code=403, text="account balance insufficient; your request was blocked")
        quota_blocked_response.json.return_value = {"error": {"message": "account balance insufficient; your request was blocked"}}
        rate_limit_response = Mock(ok=False, status_code=429, text="too many requests")
        rate_limit_response.json.return_value = {"error": {"message": "too many requests"}}
        blocked_response = Mock(ok=False, status_code=403, text="Forbidden: your request was blocked by content policy")
        blocked_response.json.return_value = {"error": {"message": "Forbidden: your request was blocked by content policy"}}
        connection_blocked_response = Mock(ok=False, status_code=403, text="connection blocked by policy")
        connection_blocked_response.json.return_value = {"error": {"message": "connection blocked by policy"}}
        invalid_json_response = Mock(ok=True, status_code=200, text="<html>bad gateway</html>")
        invalid_json_response.json.side_effect = ValueError("invalid json")

        for response, error_code, stage, retryable, reason in [
            (auth_response, "auth", "model_discovery", False, "api_key_rejected"),
            (not_found_response, "network_error", "model_discovery", False, "endpoint_not_found"),
            (billing_response, "quota", "model_discovery", True, "insufficient_balance"),
            (billing_rate_limit_response, "quota", "model_discovery", True, "insufficient_balance"),
            (quota_exceeded_response, "quota", "model_discovery", True, "quota_exceeded"),
            (quota_blocked_response, "quota", "model_discovery", True, "insufficient_balance"),
            (rate_limit_response, "quota", "model_discovery", True, "rate_limit"),
            (blocked_response, "request_blocked", "model_discovery", False, "provider_blocked"),
            (connection_blocked_response, "network_error", "model_discovery", True, "network_error"),
            (invalid_json_response, "format_error", "response_parse", False, "non_json"),
        ]:
            with self.subTest(error_code=error_code):
                mock_get.return_value = response
                payload = self.service.discover_llm_channel_models(
                    name="dashscope",
                    protocol="openai",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    api_key="sk-secret-value",
                )

                self.assertFalse(payload["success"])
                self.assertEqual(payload["error_code"], error_code)
                self.assertEqual(payload["stage"], stage)
                self.assertEqual(payload["retryable"], retryable)
                self.assertEqual(payload["details"]["reason"], reason)
                if error_code == "auth":
                    self.assertNotIn("sk-secret-value", payload["error"])

    @patch("src.services.system_config_service.requests.get")
    def test_discover_llm_channel_models_rejects_redirect_responses(self, mock_get) -> None:
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 302
        mock_get.return_value = mock_response

        payload = self.service.discover_llm_channel_models(
            name="dashscope",
            protocol="openai",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="sk-test-value",
        )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["message"], "Model discovery request was redirected")
        self.assertIn("Redirect responses are not allowed", payload["error"])
        self.assertFalse(mock_get.call_args.kwargs["allow_redirects"])

    def test_discover_llm_channel_models_requires_base_url(self) -> None:
        payload = self.service.discover_llm_channel_models(
            name="primary",
            protocol="openai",
            base_url="",
            api_key="sk-test-value",
        )

        self.assertFalse(payload["success"])
        self.assertIn("base URL", payload["error"])
        self.assertEqual(payload["models"], [])

    def test_discover_llm_channel_models_rejects_unsupported_protocol(self) -> None:
        payload = self.service.discover_llm_channel_models(
            name="gemini",
            protocol="gemini",
            base_url="https://example.com/v1",
            api_key="sk-test-value",
        )

        self.assertFalse(payload["success"])
        self.assertEqual(payload["resolved_protocol"], "gemini")
        self.assertIn("does not support /models discovery yet", payload["error"])

    def test_build_llm_models_url_strips_query_and_fragment(self) -> None:
        models_url = SystemConfigService._build_llm_models_url(
            "https://example.com/v1/chat/completions?api-version=1#frag"
        )

        self.assertEqual(models_url, "https://example.com/v1/models")

    def test_build_llm_models_url_supports_deepseek_root_base_url(self) -> None:
        models_url = SystemConfigService._build_llm_models_url("https://api.deepseek.com")

        self.assertEqual(models_url, "https://api.deepseek.com/models")

    def test_validate_reports_invalid_event_rule_semantics(self) -> None:
        validation = self.service.validate(items=[{
            "key": "AGENT_EVENT_ALERT_RULES_JSON",
            "value": '[{"stock_code":"600519","alert_type":"price_cross","status":"bad","direction":"above","price":1800}]',
        }])

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_event_rule" for issue in validation["issues"]))

    def test_validate_accepts_price_change_percent_event_rule(self) -> None:
        validation = self.service.validate(items=[{
            "key": "AGENT_EVENT_ALERT_RULES_JSON",
            "value": (
                '[{"stock_code":"300750","alert_type":"price_change_percent",'
                '"direction":"down","change_pct":3.0}]'
            ),
        }])

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["issues"], [])

    def test_validate_rejects_unsupported_event_rule_type(self) -> None:
        validation = self.service.validate(items=[{
            "key": "AGENT_EVENT_ALERT_RULES_JSON",
            "value": '[{"stock_code":"600519","alert_type":"sentiment_shift"}]',
        }])

        self.assertFalse(validation["valid"])
        self.assertTrue(any(issue["code"] == "invalid_event_rule" for issue in validation["issues"]))

    @patch.object(SystemConfigService, "_reload_runtime_singletons")
    def test_update_with_reload_resets_runtime_singletons(
        self,
        mock_reload_runtime_singletons,
    ) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "STOCK_LIST", "value": "600519"}],
            reload_now=True,
        )

        self.assertTrue(response["success"])
        mock_reload_runtime_singletons.assert_called_once()

    def test_update_with_reload_applies_updated_env_file_when_process_env_is_stale(self) -> None:
        os.environ["STOCK_LIST"] = "600519,000001"

        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "STOCK_LIST", "value": "300750,TSLA"}],
            reload_now=True,
        )

        self.assertTrue(response["success"])
        self.assertEqual(Config.get_instance().stock_list, ["300750", "TSLA"])

    @patch.object(SystemConfigService, "_reload_runtime_singletons")
    def test_update_escapes_custom_webhook_template_and_runtime_reads_literals(
        self,
        _mock_reload_runtime_singletons,
    ) -> None:
        template = '{"title":$title_json,"content":$content_json}'

        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "CUSTOM_WEBHOOK_BODY_TEMPLATE", "value": template}],
            reload_now=True,
        )

        self.assertTrue(response["success"])
        self.assertIn(
            'CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$$title_json,"content":$$content_json}\n',
            self.env_path.read_text(encoding="utf-8"),
        )
        self.assertEqual(Config.get_instance().custom_webhook_body_template, template)

        items = {
            item["key"]: item
            for item in self.service.get_config(include_schema=True)["items"]
        }
        self.assertEqual(items["CUSTOM_WEBHOOK_BODY_TEMPLATE"]["value"], template)

    @patch.object(SystemConfigService, "_reload_runtime_singletons")
    def test_update_escapes_braced_custom_webhook_template_and_runtime_reads_literals(
        self,
        _mock_reload_runtime_singletons,
    ) -> None:
        template = '{"content":${content_json}}'

        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "CUSTOM_WEBHOOK_BODY_TEMPLATE", "value": template}],
            reload_now=True,
        )

        self.assertTrue(response["success"])
        self.assertIn(
            'CUSTOM_WEBHOOK_BODY_TEMPLATE={"content":$${content_json}}\n',
            self.env_path.read_text(encoding="utf-8"),
        )
        self.assertEqual(Config.get_instance().custom_webhook_body_template, template)

        items = {
            item["key"]: item
            for item in self.service.get_config(include_schema=True)["items"]
        }
        self.assertEqual(items["CUSTOM_WEBHOOK_BODY_TEMPLATE"]["value"], template)

    def test_update_raises_conflict_for_stale_version(self) -> None:
        with self.assertRaises(ConfigConflictError):
            self.service.update(
                config_version="stale-version",
                items=[{"key": "STOCK_LIST", "value": "600519"}],
                reload_now=False,
            )

    def test_update_appends_news_window_explainability_warning(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[
                {"key": "NEWS_STRATEGY_PROFILE", "value": "ultra_short"},
                {"key": "NEWS_MAX_AGE_DAYS", "value": "7"},
            ],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        joined = " | ".join(response["warnings"])
        self.assertIn("effective_days=1", joined)
        self.assertIn("min(profile_days, NEWS_MAX_AGE_DAYS)", joined)

    def test_update_appends_max_workers_warning(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "MAX_WORKERS", "value": "1"}],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        joined = " | ".join(response["warnings"])
        self.assertIn("MAX_WORKERS=1", joined)
        self.assertIn("reload_now=false", joined)

    def test_update_appends_mode_specific_startup_warnings(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[
                {"key": "RUN_IMMEDIATELY", "value": "false"},
                {"key": "SCHEDULE_ENABLED", "value": "true"},
                {"key": "SCHEDULE_RUN_IMMEDIATELY", "value": "true"},
            ],
            reload_now=True,
        )

        self.assertTrue(response["success"])
        run_warning = next(
            warning
            for warning in response["warnings"]
            if "RUN_IMMEDIATELY 已写入 .env" in warning
        )
        schedule_warning = next(
            warning
            for warning in response["warnings"]
            if "SCHEDULE_ENABLED" in warning
        )
        schedule_run_warning = next(
            warning
            for warning in response["warnings"]
            if "SCHEDULE_RUN_IMMEDIATELY" in warning
        )

        self.assertIn("非 schedule 模式", run_warning)
        self.assertNotIn("以 schedule 模式", run_warning)
        self.assertIn("runtime scheduler", schedule_warning)
        self.assertIn("CLI schedule", schedule_warning)
        self.assertIn("SCHEDULE_RUN_IMMEDIATELY", schedule_run_warning)
        self.assertIn("不会因为本次保存启动、停止或重建 scheduler", schedule_run_warning)
        self.assertIn("以 schedule 模式重新启动后生效", schedule_run_warning)
        self.assertNotIn("它属于启动期单次运行配置", schedule_run_warning)

    def test_update_appends_schedule_time_runtime_rebind_warning(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "SCHEDULE_TIME", "value": "09:30"}],
            reload_now=True,
        )

        self.assertTrue(response["success"])
        schedule_time_warning = next(
            warning
            for warning in response["warnings"]
            if "SCHEDULE_TIME=09:30 已写入 .env" in warning
        )

        self.assertIn("已经以 schedule 模式运行", schedule_time_warning)
        self.assertIn("自动重建 daily job", schedule_time_warning)
        self.assertIn("不会启动 scheduler", schedule_time_warning)
        self.assertNotIn("重启当前进程", schedule_time_warning)
        self.assertNotIn("不会因为本次保存启动、停止或重建 scheduler", schedule_time_warning)

    def test_update_schedule_time_blank_warning_reports_effective_default(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "SCHEDULE_TIME", "value": "   "}],
            reload_now=True,
        )

        self.assertTrue(response["success"])
        self.assertTrue(
            any("SCHEDULE_TIME=18:00 已写入 .env" in warning for warning in response["warnings"]),
            response["warnings"],
        )

    def test_update_appends_webui_bind_restart_warning(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[
                {"key": "WEBUI_HOST", "value": "0.0.0.0"},
                {"key": "WEBUI_PORT", "value": "18000"},
            ],
            reload_now=True,
        )

        self.assertTrue(response["success"])
        bind_warning = next(
            warning
            for warning in response["warnings"]
            if "WEBUI_HOST" in warning and "WEBUI_PORT" in warning
        )

        self.assertIn("启动期监听配置", bind_warning)
        self.assertIn("不会因为本次保存重新绑定监听地址或端口", bind_warning)
        self.assertIn("重启当前进程、Docker 容器或服务管理器后生效", bind_warning)

    def test_update_warns_when_runtime_model_references_are_cleared(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "LLM_CHANNELS=deepseek",
            "LLM_DEEPSEEK_PROTOCOL=deepseek",
            "LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com",
            "LLM_DEEPSEEK_API_KEY=sk-test-value",
            "LLM_DEEPSEEK_MODELS=deepseek-chat,deepseek-v4-flash,deepseek-v4-pro",
            "LITELLM_MODEL=deepseek/deepseek-chat",
            "AGENT_LITELLM_MODEL=deepseek/deepseek-v4-pro",
            "LITELLM_FALLBACK_MODELS=deepseek/deepseek-v4-pro,deepseek/deepseek-chat,cohere/command-r-plus",
            "VISION_MODEL=deepseek/deepseek-v4-flash",
        )

        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[
                {"key": "LLM_DEEPSEEK_MODELS", "value": "deepseek-v4-flash,deepseek-v4-pro"},
                {"key": "LITELLM_MODEL", "value": ""},
                {"key": "AGENT_LITELLM_MODEL", "value": ""},
                {"key": "LITELLM_FALLBACK_MODELS", "value": "deepseek/deepseek-v4-pro,cohere/command-r-plus"},
                {"key": "VISION_MODEL", "value": ""},
            ],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        warning = next(
            warning
            for warning in response["warnings"]
            if "已同步清理失效的运行时模型引用" in warning
        )
        self.assertIn("主模型 / Agent 主模型 / Vision 模型 / 备选模型中的失效项", warning)
        self.assertIn("桌面端导出备份", warning)

    def test_update_market_review_region_does_not_trigger_runtime_model_cleanup(self) -> None:
        litellm_config_path = Path(self.temp_dir.name) / "litellm_config.yaml"
        litellm_config_path.write_text("model_list: []\n", encoding="utf-8")

        self._rewrite_env(
            "MARKET_REVIEW_REGION=cn",
            "LITELLM_MODEL=openai/gpt-4o-mini",
            "AGENT_LITELLM_MODEL=openai/gpt-4o",
            "LITELLM_FALLBACK_MODELS=openai/gpt-4o-mini,openai/gpt-4o",
            "VISION_MODEL=openai/gpt-4o",
            f"LITELLM_CONFIG={litellm_config_path}",
            "LLM_CHANNELS=openai",
            "LLM_OPENAI_PROTOCOL=openai",
            "LLM_OPENAI_BASE_URL=https://llm-openai.example.com/v1",
            "LLM_OPENAI_API_KEYS=legacy-openai-secret",
            "LLM_OPENAI_MODELS=openai/gpt-4o-mini,openai/gpt-4o",
            "OPENAI_BASE_URL=https://openai.example.com/v1",
            "OPENAI_API_KEY=sk-openai",
            "OPENAI_MODEL=gpt-4.1",
            "ANTHROPIC_MODEL=claude-sonnet-4-6",
        )

        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "MARKET_REVIEW_REGION", "value": "both"}],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        self.assertIn("MARKET_REVIEW_REGION", response["updated_keys"])
        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["MARKET_REVIEW_REGION"], "both")
        self.assertEqual(current_map["LITELLM_MODEL"], "openai/gpt-4o-mini")
        self.assertEqual(current_map["AGENT_LITELLM_MODEL"], "openai/gpt-4o")
        self.assertEqual(current_map["LITELLM_FALLBACK_MODELS"], "openai/gpt-4o-mini,openai/gpt-4o")
        self.assertEqual(current_map["VISION_MODEL"], "openai/gpt-4o")
        self.assertEqual(current_map["LITELLM_CONFIG"], str(litellm_config_path))
        self.assertEqual(current_map["LLM_CHANNELS"], "openai")
        self.assertEqual(current_map["LLM_OPENAI_PROTOCOL"], "openai")
        self.assertEqual(current_map["LLM_OPENAI_BASE_URL"], "https://llm-openai.example.com/v1")
        self.assertEqual(current_map["LLM_OPENAI_API_KEYS"], "legacy-openai-secret")
        self.assertEqual(current_map["LLM_OPENAI_MODELS"], "openai/gpt-4o-mini,openai/gpt-4o")
        self.assertEqual(current_map["OPENAI_BASE_URL"], "https://openai.example.com/v1")
        self.assertEqual(current_map["OPENAI_API_KEY"], "sk-openai")
        self.assertEqual(current_map["OPENAI_MODEL"], "gpt-4.1")
        self.assertEqual(current_map["ANTHROPIC_MODEL"], "claude-sonnet-4-6")
        self.assertFalse(
            any("已同步清理失效的运行时模型引用" in warning for warning in response["warnings"]),
            response["warnings"],
        )

    def test_update_market_review_region_accepts_comma_separated_regions(self) -> None:
        response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[{"key": "MARKET_REVIEW_REGION", "value": "cn,jp,us"}],
            reload_now=False,
        )

        self.assertTrue(response["success"])
        self.assertIn("MARKET_REVIEW_REGION", response["updated_keys"])
        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["MARKET_REVIEW_REGION"], "cn,jp,us")

    def test_import_env_market_review_region_accepts_comma_separated_regions(self) -> None:
        response = self.service.import_env(
            config_version=self.manager.get_config_version(),
            content="MARKET_REVIEW_REGION=jp,kr\n",
            reload_now=False,
        )

        self.assertTrue(response["success"])
        current_map = self.manager.read_config_map()
        self.assertEqual(current_map["MARKET_REVIEW_REGION"], "jp,kr")

    def test_import_desktop_env_restores_runtime_models_after_cleanup(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "LLM_CHANNELS=deepseek",
            "LLM_DEEPSEEK_PROTOCOL=deepseek",
            "LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com",
            "LLM_DEEPSEEK_API_KEY=sk-test-value",
            "LLM_DEEPSEEK_MODELS=deepseek-chat,deepseek-v4-flash,deepseek-v4-pro",
            "LITELLM_MODEL=deepseek/deepseek-chat",
            "AGENT_LITELLM_MODEL=deepseek/deepseek-v4-pro",
            "LITELLM_FALLBACK_MODELS=deepseek/deepseek-v4-pro,deepseek/deepseek-chat,cohere/command-r-plus",
            "VISION_MODEL=deepseek/deepseek-v4-flash",
        )

        backup_content = self.service.export_desktop_env()["content"]
        pre_clear_map = dict(self.manager.read_config_map())

        clear_response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[
                {"key": "LLM_DEEPSEEK_MODELS", "value": "deepseek-v4-flash"},
                {"key": "LITELLM_MODEL", "value": ""},
                {"key": "AGENT_LITELLM_MODEL", "value": ""},
                {"key": "LITELLM_FALLBACK_MODELS", "value": "deepseek/deepseek-v4-flash"},
                {"key": "VISION_MODEL", "value": ""},
            ],
            reload_now=False,
        )
        self.assertTrue(clear_response["success"])

        cleared_map = self.manager.read_config_map()
        self.assertEqual(cleared_map["LITELLM_MODEL"], "")
        self.assertEqual(cleared_map["AGENT_LITELLM_MODEL"], "")
        self.assertEqual(cleared_map["VISION_MODEL"], "")
        self.assertEqual(cleared_map["LITELLM_FALLBACK_MODELS"], "deepseek/deepseek-v4-flash")

        restore_payload = self.service.import_desktop_env(
            config_version=self.manager.get_config_version(),
            content=backup_content,
            reload_now=False,
        )
        self.assertTrue(restore_payload["success"])

        restored_map = self.manager.read_config_map()
        self.assertEqual(restored_map["LITELLM_MODEL"], pre_clear_map["LITELLM_MODEL"])
        self.assertEqual(restored_map["AGENT_LITELLM_MODEL"], pre_clear_map["AGENT_LITELLM_MODEL"])
        self.assertEqual(restored_map["VISION_MODEL"], pre_clear_map["VISION_MODEL"])
        self.assertEqual(restored_map["LITELLM_FALLBACK_MODELS"], pre_clear_map["LITELLM_FALLBACK_MODELS"])

    def test_import_desktop_env_restores_provider_and_base_url_after_provider_cleanup(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "LITELLM_MODEL=openai/gpt-4o-mini",
            "OPENAI_MODEL=gpt-4.1",
            "OPENAI_BASE_URL=https://openai.example.com/v1",
            "OPENAI_API_KEY=legacy-openai-key",
        )

        backup_content = self.service.export_desktop_env()["content"]
        pre_clear_map = dict(self.manager.read_config_map())

        clear_response = self.service.update(
            config_version=self.manager.get_config_version(),
            items=[
                {"key": "LITELLM_MODEL", "value": ""},
                {"key": "OPENAI_MODEL", "value": ""},
                {"key": "OPENAI_BASE_URL", "value": ""},
                {"key": "OPENAI_API_KEY", "value": ""},
            ],
            reload_now=False,
        )
        self.assertTrue(clear_response["success"])

        cleared_map = self.manager.read_config_map()
        self.assertEqual(cleared_map["LITELLM_MODEL"], "")
        self.assertEqual(cleared_map["OPENAI_MODEL"], "")
        self.assertEqual(cleared_map["OPENAI_BASE_URL"], "")
        self.assertEqual(cleared_map["OPENAI_API_KEY"], "")

        restore_payload = self.service.import_desktop_env(
            config_version=self.manager.get_config_version(),
            content=backup_content,
            reload_now=False,
        )
        self.assertTrue(restore_payload["success"])

        restored_map = self.manager.read_config_map()
        self.assertEqual(restored_map["LITELLM_MODEL"], pre_clear_map["LITELLM_MODEL"])
        self.assertEqual(restored_map["OPENAI_MODEL"], pre_clear_map["OPENAI_MODEL"])
        self.assertEqual(restored_map["OPENAI_BASE_URL"], pre_clear_map["OPENAI_BASE_URL"])
        self.assertEqual(restored_map["OPENAI_API_KEY"], pre_clear_map["OPENAI_API_KEY"])

    def test_validate_rejects_comma_only_api_key(self) -> None:
        """Whitespace/comma-only api_key must fail validation (P2: parsed-segment check)."""
        for bad_key in (",", " , ", "  ,  ,  "):
            with self.subTest(api_key=bad_key):
                validation = self.service.validate(
                    items=[
                        {"key": "LLM_CHANNELS", "value": "primary"},
                        {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                        {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                        {"key": "LLM_PRIMARY_API_KEY", "value": bad_key},
                    ]
                )
                self.assertFalse(validation["valid"])
                self.assertTrue(
                    any(issue["code"] == "missing_api_key" for issue in validation["issues"]),
                    f"Expected missing_api_key for api_key={bad_key!r}, got: {validation['issues']}",
                )

    def test_validate_rejects_ssrf_metadata_base_url(self) -> None:
        """base_url pointing to cloud metadata service must be blocked (P1: SSRF guard)."""
        for bad_url in (
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://100.100.100.200/latest/meta-data/",
        ):
            with self.subTest(base_url=bad_url):
                validation = self.service.validate(
                    items=[
                        {"key": "LLM_CHANNELS", "value": "primary"},
                        {"key": "LLM_PRIMARY_PROTOCOL", "value": "openai"},
                        {"key": "LLM_PRIMARY_MODELS", "value": "gpt-4o-mini"},
                        {"key": "LLM_PRIMARY_API_KEY", "value": "sk-test"},
                        {"key": "LLM_PRIMARY_BASE_URL", "value": bad_url},
                    ]
                )
                self.assertFalse(validation["valid"])
                self.assertTrue(
                    any(issue["code"] == "ssrf_blocked" for issue in validation["issues"]),
                    f"Expected ssrf_blocked for base_url={bad_url!r}, got: {validation['issues']}",
                )

    def test_validate_allows_localhost_base_url(self) -> None:
        """localhost/LAN base_url must not be blocked (legitimate Ollama endpoints)."""
        validation = self.service.validate(
            items=[
                {"key": "LLM_CHANNELS", "value": "local"},
                {"key": "LLM_LOCAL_PROTOCOL", "value": "ollama"},
                {"key": "LLM_LOCAL_MODELS", "value": "llama3"},
                {"key": "LLM_LOCAL_API_KEY", "value": ""},
                {"key": "LLM_LOCAL_BASE_URL", "value": "http://localhost:11434"},
            ]
        )
        self.assertFalse(any(issue["code"] == "ssrf_blocked" for issue in validation["issues"]))


if __name__ == "__main__":
    unittest.main()
