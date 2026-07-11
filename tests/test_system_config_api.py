# -*- coding: utf-8 -*-
"""Integration tests for system configuration API endpoints."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException, Request

from tests.litellm_stub import ensure_litellm_stub

ensure_litellm_stub()

from api.middlewares.auth import add_auth_middleware
from api.middlewares.error_handler import add_error_handlers
from api.v1.endpoints import system_config
from api.v1.schemas.system_config import (
    DiscoverLLMChannelModelsRequest,
    GenerationBackendStatusPreviewRequest,
    ImportSystemConfigRequest,
    TestGenerationBackendRequest,
    TestLLMChannelRequest,
    TestNotificationChannelRequest,
    UpdateSystemConfigRequest,
)
import src.auth as auth
from src.config import Config
from src.core.config_manager import ConfigManager
from src.services.system_config_service import SystemConfigService


class SystemConfigApiTestCase(unittest.TestCase):
    """System config API tests in isolation without loading the full app."""

    def setUp(self) -> None:
        auth._auth_enabled = None
        auth._session_secret = None
        auth._password_hash_salt = None
        auth._password_hash_stored = None
        auth._rate_limit = {}

        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519,000001",
                    "GEMINI_API_KEY=secret-key-value",
                    "SCHEDULE_TIME=18:00",
                    "LOG_LEVEL=INFO",
                    "ADMIN_AUTH_ENABLED=true",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self._orig_dsa_desktop_mode = os.environ.get("DSA_DESKTOP_MODE")
        self._orig_database_path = os.environ.get("DATABASE_PATH")
        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["DATABASE_PATH"] = str(Path(self.temp_dir.name) / "system_config_api_test.db")
        Config.reset_instance()

        self.manager = ConfigManager(env_path=self.env_path)
        self.service = SystemConfigService(manager=self.manager)
        self._verify_session_patch = patch.object(system_config, "verify_session", return_value=True)
        self._verify_session_patch.start()

    def tearDown(self) -> None:
        Config.reset_instance()
        self._verify_session_patch.stop()
        os.environ.pop("ENV_FILE", None)
        if self._orig_dsa_desktop_mode is None:
            os.environ.pop("DSA_DESKTOP_MODE", None)
        else:
            os.environ["DSA_DESKTOP_MODE"] = self._orig_dsa_desktop_mode
        if self._orig_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self._orig_database_path
        self.temp_dir.cleanup()

    @staticmethod
    def _build_request(cookies: dict[str, str] | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            cookies=cookies if cookies is not None else {system_config.COOKIE_NAME: "valid-session-token"}
        )

    def _rewrite_env(self, *lines: str) -> None:
        self.env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        Config.reset_instance()
        self.manager = ConfigManager(env_path=self.env_path)
        self.service = SystemConfigService(manager=self.manager)

    def _build_client_app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/api/v1/system/config/export")
        async def export_config(request: Request):
            return system_config.export_system_config(request=request, service=self.service)

        add_error_handlers(app)
        add_auth_middleware(app)
        return app

    def test_get_config_keeps_regular_secret_value_unmasked(self) -> None:
        payload = system_config.get_system_config(include_schema=True, service=self.service).model_dump(by_alias=True)
        item_map = {item["key"]: item for item in payload["items"]}
        self.assertEqual(item_map["GEMINI_API_KEY"]["value"], "secret-key-value")
        self.assertFalse(item_map["GEMINI_API_KEY"]["is_masked"])

    def test_get_config_masks_llm_usage_hmac_secret(self) -> None:
        self._rewrite_env(
            "STOCK_LIST=600519,000001",
            "GEMINI_API_KEY=secret-key-value",
            "LLM_USAGE_HMAC_SECRET=telemetry-secret",
            "LLM_USAGE_HMAC_KEY_VERSION=test-v1",
            "ADMIN_AUTH_ENABLED=true",
        )

        payload = system_config.get_system_config(include_schema=True, service=self.service).model_dump(by_alias=True)
        item_map = {item["key"]: item for item in payload["items"]}

        self.assertEqual(item_map["LLM_USAGE_HMAC_SECRET"]["value"], payload["mask_token"])
        self.assertTrue(item_map["LLM_USAGE_HMAC_SECRET"]["is_masked"])
        self.assertTrue(item_map["LLM_USAGE_HMAC_SECRET"]["raw_value_exists"])
        self.assertEqual(item_map["LLM_USAGE_HMAC_KEY_VERSION"]["value"], "test-v1")
        self.assertFalse(item_map["LLM_USAGE_HMAC_KEY_VERSION"]["is_masked"])

    def test_get_config_schema_includes_help_metadata(self) -> None:
        payload = system_config.get_system_config(include_schema=True, service=self.service).model_dump(by_alias=True)
        item_map = {item["key"]: item for item in payload["items"]}
        stock_schema = item_map["STOCK_LIST"]["schema"]

        self.assertEqual(stock_schema["help_key"], "settings.base.STOCK_LIST")
        self.assertTrue(stock_schema["examples"])
        self.assertTrue(stock_schema["docs"])

    def test_get_config_schema_exposes_generation_backend_bounds_and_agent_options(self) -> None:
        payload = system_config.get_system_config(include_schema=True, service=self.service).model_dump(by_alias=True)
        item_map = {item["key"]: item for item in payload["items"]}

        self.assertEqual(
            item_map["GENERATION_BACKEND_TIMEOUT_SECONDS"]["schema"]["validation"],
            {"min": 1, "max": 3600},
        )
        self.assertEqual(
            item_map["GENERATION_BACKEND_MAX_OUTPUT_BYTES"]["schema"]["validation"],
            {"min": 1, "max": 33554432},
        )
        self.assertEqual(
            item_map["GENERATION_BACKEND_MAX_CONCURRENCY"]["schema"]["validation"],
            {"min": 1, "max": 16},
        )
        self.assertEqual(
            item_map["LOCAL_CLI_BACKEND_MAX_CONCURRENCY"]["schema"]["validation"],
            {"min": 1, "max": 4},
        )
        agent_schema = item_map["AGENT_GENERATION_BACKEND"]["schema"]
        self.assertEqual(agent_schema["validation"]["enum"], ["auto", "litellm"])
        self.assertNotIn("codex_cli", {option["value"] for option in agent_schema["options"]})
        self.assertNotIn("claude_code_cli", {option["value"] for option in agent_schema["options"]})
        self.assertNotIn("opencode_cli", {option["value"] for option in agent_schema["options"]})
        generation_schema = item_map["GENERATION_BACKEND"]["schema"]
        self.assertIn("claude_code_cli", generation_schema["validation"]["enum"])
        self.assertIn("opencode_cli", generation_schema["validation"]["enum"])

    def test_get_config_schema_includes_notification_noise_fields(self) -> None:
        payload = system_config.get_system_config(include_schema=True, service=self.service).model_dump(by_alias=True)
        item_map = {item["key"]: item for item in payload["items"]}

        self.assertEqual(item_map["NOTIFICATION_DEDUP_TTL_SECONDS"]["schema"]["data_type"], "integer")
        self.assertEqual(item_map["NOTIFICATION_COOLDOWN_SECONDS"]["schema"]["data_type"], "integer")
        self.assertEqual(item_map["NOTIFICATION_DAILY_DIGEST_ENABLED"]["schema"]["data_type"], "boolean")
        min_severity_schema = item_map["NOTIFICATION_MIN_SEVERITY"]["schema"]
        self.assertEqual(min_severity_schema["options"][0]["value"], "")
        self.assertIn("", min_severity_schema["validation"]["enum"])
        self.assertIn("warning", min_severity_schema["validation"]["enum"])

    def test_get_setup_status_returns_readiness_payload(self) -> None:
        self.env_path.write_text(
            "\n".join(
                [
                    "LITELLM_MODEL=gemini/gemini-3-flash-preview",
                    "GEMINI_API_KEY=secret-key-value",
                    "STOCK_LIST=600519",
                    "ADMIN_AUTH_ENABLED=false",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        with patch.dict(os.environ, {}, clear=True):
            payload = system_config.get_setup_status(service=self.service).model_dump()

        self.assertTrue(payload["is_complete"])
        self.assertTrue(payload["ready_for_smoke"])
        self.assertEqual(payload["required_missing_keys"], [])
        check_map = {check["key"]: check for check in payload["checks"]}
        self.assertEqual(check_map["llm_primary"]["status"], "configured")
        self.assertEqual(check_map["llm_agent"]["status"], "inherited")

    def test_get_generation_backend_status_uses_saved_config_only(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=litellm",
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY=secret-key-value",
        )

        payload = system_config.get_generation_backend_status(service=self.service).model_dump()

        self.assertEqual(payload["primary_backend_id"], "litellm")
        self.assertEqual(payload["primary"]["backend_id"], "litellm")
        self.assertTrue(payload["primary"]["available"])

    def test_preview_generation_backend_status_uses_draft_items(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=litellm",
            "LITELLM_MODEL=gemini/gemini-3-flash-preview",
            "GEMINI_API_KEY=secret-key-value",
        )

        with patch("src.llm.local_cli_backend.shutil.which", return_value=None):
            payload = system_config.preview_generation_backend_status(
                request=GenerationBackendStatusPreviewRequest(
                    items=[
                        {"key": "GENERATION_BACKEND", "value": "codex_cli"},
                        {"key": "GENERATION_FALLBACK_BACKEND", "value": ""},
                    ],
                    mask_token="******",
                ),
                service=self.service,
            ).model_dump()

        self.assertEqual(payload["primary_backend_id"], "codex_cli")
        self.assertFalse(payload["primary"]["available"])
        self.assertEqual(payload["primary"]["last_error_code"], "command_not_found")

        saved_payload = system_config.get_generation_backend_status(service=self.service).model_dump()
        self.assertEqual(saved_payload["primary_backend_id"], "litellm")

    def test_generation_backend_smoke_test_returns_structured_failure(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=codex_cli",
            "GENERATION_FALLBACK_BACKEND=",
        )

        with patch("src.llm.local_cli_backend.shutil.which", return_value=None):
            payload = system_config.test_generation_backend(
                request=TestGenerationBackendRequest(backend_id="codex_cli"),
                service=self.service,
            ).model_dump()

        self.assertFalse(payload["success"])
        self.assertEqual(payload["mode"], "json")
        self.assertEqual(payload["status"]["backend_id"], "codex_cli")
        self.assertEqual(payload["status"]["last_error_code"], "command_not_found")

    def test_preview_generation_backend_status_returns_validation_error_for_bad_draft(self) -> None:
        self._rewrite_env(
            "GENERATION_BACKEND=codex_cli",
            "GENERATION_FALLBACK_BACKEND=",
        )

        with self.assertRaises(HTTPException) as ctx:
            system_config.preview_generation_backend_status(
                request=GenerationBackendStatusPreviewRequest(
                    items=[{"key": "GENERATION_BACKEND_TIMEOUT_SECONDS", "value": "not-int"}],
                    mask_token="******",
                ),
                service=self.service,
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["error"], "validation_failed")
        self.assertEqual(ctx.exception.detail["issues"][0]["key"], "GENERATION_BACKEND_TIMEOUT_SECONDS")

    def test_put_config_updates_secret_and_plain_field(self) -> None:
        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()
        payload = system_config.update_system_config(
            request=UpdateSystemConfigRequest(
                config_version=current["config_version"],
                mask_token="******",
                reload_now=False,
                items=[
                    {"key": "GEMINI_API_KEY", "value": "new-secret-value"},
                    {"key": "STOCK_LIST", "value": "600519,300750"},
                ],
            ),
            service=self.service,
        ).model_dump()

        self.assertEqual(payload["applied_count"], 2)
        self.assertEqual(payload["skipped_masked_count"], 0)

        env_content = self.env_path.read_text(encoding="utf-8")
        self.assertIn("STOCK_LIST=600519,300750", env_content)
        self.assertIn("GEMINI_API_KEY=new-secret-value", env_content)

    def test_put_config_escapes_custom_webhook_template_placeholders(self) -> None:
        template = '{"title":$title_json,"content":$content_json}'
        current = system_config.get_system_config(
            include_schema=False,
            service=self.service,
        ).model_dump()

        payload = system_config.update_system_config(
            request=UpdateSystemConfigRequest(
                config_version=current["config_version"],
                mask_token="******",
                reload_now=False,
                items=[
                    {
                        "key": "CUSTOM_WEBHOOK_BODY_TEMPLATE",
                        "value": template,
                    },
                ],
            ),
            service=self.service,
        ).model_dump()

        self.assertEqual(payload["applied_count"], 1)
        self.assertIn(
            'CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$$title_json,"content":$$content_json}\n',
            self.env_path.read_text(encoding="utf-8"),
        )
        item_map = {
            item["key"]: item
            for item in system_config.get_system_config(
                include_schema=True,
                service=self.service,
            ).model_dump(by_alias=True)["items"]
        }
        self.assertEqual(item_map["CUSTOM_WEBHOOK_BODY_TEMPLATE"]["value"], template)

    def test_put_config_returns_conflict_when_version_is_stale(self) -> None:
        with self.assertRaises(HTTPException) as context:
            system_config.update_system_config(
                request=UpdateSystemConfigRequest(
                    config_version="stale-version",
                    items=[{"key": "STOCK_LIST", "value": "600519"}],
                ),
                service=self.service,
            )

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.detail["error"], "config_version_conflict")

    def test_put_config_preserves_comments_and_blank_lines(self) -> None:
        self.env_path.write_text(
            "\n".join(
                [
                    "# Base settings",
                    "STOCK_LIST=600519,000001",
                    "",
                    "# Secrets",
                    "GEMINI_API_KEY=secret-key-value",
                    "ADMIN_AUTH_ENABLED=false",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()
        payload = system_config.update_system_config(
            request=UpdateSystemConfigRequest(
                config_version=current["config_version"],
                mask_token="******",
                reload_now=False,
                items=[{"key": "STOCK_LIST", "value": "600519,300750"}],
            ),
            service=self.service,
        ).model_dump()

        self.assertTrue(payload["success"])
        env_content = self.env_path.read_text(encoding="utf-8")
        self.assertIn("# Base settings\n", env_content)
        self.assertIn("\n\n# Secrets\n", env_content)
        self.assertIn("STOCK_LIST=600519,300750\n", env_content)

    def test_put_config_returns_startup_only_schedule_warning(self) -> None:
        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()
        payload = system_config.update_system_config(
            request=UpdateSystemConfigRequest(
                config_version=current["config_version"],
                reload_now=True,
                items=[
                    {"key": "RUN_IMMEDIATELY", "value": "false"},
                    {"key": "SCHEDULE_RUN_IMMEDIATELY", "value": "true"},
                ],
            ),
            service=self.service,
        ).model_dump()

        self.assertTrue(payload["success"])
        run_warning = next(
            warning
            for warning in payload["warnings"]
            if "RUN_IMMEDIATELY 已写入 .env" in warning
        )
        schedule_warning = next(
            warning
            for warning in payload["warnings"]
            if "SCHEDULE_RUN_IMMEDIATELY" in warning
        )

        self.assertIn("非 schedule 模式", run_warning)
        self.assertNotIn("以 schedule 模式", run_warning)
        self.assertIn("不会因为本次保存启动、停止或重建 scheduler", schedule_warning)
        self.assertIn("以 schedule 模式重新启动后生效", schedule_warning)
        self.assertNotIn("它属于启动期单次运行配置", schedule_warning)

    def test_put_config_returns_schedule_time_runtime_rebind_warning(self) -> None:
        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()
        payload = system_config.update_system_config(
            request=UpdateSystemConfigRequest(
                config_version=current["config_version"],
                reload_now=True,
                items=[
                    {"key": "SCHEDULE_TIME", "value": "09:30"},
                ],
            ),
            service=self.service,
        ).model_dump()

        self.assertTrue(payload["success"])
        schedule_time_warning = next(
            warning
            for warning in payload["warnings"]
            if "SCHEDULE_TIME=09:30 已写入 .env" in warning
        )

        self.assertIn("已经以 schedule 模式运行", schedule_time_warning)
        self.assertIn("自动重建 daily job", schedule_time_warning)
        self.assertIn("不会启动 scheduler", schedule_time_warning)
        self.assertNotIn("重启当前进程", schedule_time_warning)

    def test_export_system_config_returns_raw_env_content(self) -> None:
        self.env_path.write_text(
            "# Web config\nSTOCK_LIST=600519,000001\nGEMINI_API_KEY=secret-key-value\nADMIN_AUTH_ENABLED=true\n",
            encoding="utf-8",
        )
        self.manager = ConfigManager(env_path=self.env_path)
        self.service = SystemConfigService(manager=self.manager)
        Config.reset_instance()

        payload = system_config.export_system_config(
            request=self._build_request(),
            service=self.service,
        ).model_dump()

        self.assertEqual(
            payload["content"],
            "# Web config\nSTOCK_LIST=600519,000001\nGEMINI_API_KEY=secret-key-value\nADMIN_AUTH_ENABLED=true\n",
        )
        self.assertEqual(payload["config_version"], self.manager.get_config_version())

    def test_import_system_config_merges_updates(self) -> None:
        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()

        payload = system_config.import_system_config(
            request_obj=self._build_request(),
            request=ImportSystemConfigRequest(
                config_version=current["config_version"],
                content="STOCK_LIST=300750\nCUSTOM_NOTE=config backup\n",
                reload_now=False,
            ),
            service=self.service,
        ).model_dump()

        self.assertTrue(payload["success"])
        env_content = self.env_path.read_text(encoding="utf-8")
        self.assertIn("STOCK_LIST=300750\n", env_content)
        self.assertIn("CUSTOM_NOTE=config backup\n", env_content)
        self.assertIn("GEMINI_API_KEY=secret-key-value\n", env_content)

    def test_import_export_system_config_preserves_generation_backend_keys(self) -> None:
        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()

        payload = system_config.import_system_config(
            request_obj=self._build_request(),
            request=ImportSystemConfigRequest(
                config_version=current["config_version"],
                content=(
                    "GENERATION_BACKEND=codex_cli\n"
                    "GENERATION_FALLBACK_BACKEND=\n"
                    "GENERATION_BACKEND_MAX_OUTPUT_BYTES=1048576\n"
                    "AGENT_GENERATION_BACKEND=auto\n"
                ),
                reload_now=False,
            ),
            service=self.service,
        ).model_dump()
        export_payload = system_config.export_system_config(
            request=self._build_request(),
            service=self.service,
        ).model_dump()

        self.assertTrue(payload["success"])
        self.assertIn("GENERATION_BACKEND=codex_cli\n", export_payload["content"])
        self.assertIn("GENERATION_FALLBACK_BACKEND=\n", export_payload["content"])
        self.assertIn("GENERATION_BACKEND_MAX_OUTPUT_BYTES=1048576\n", export_payload["content"])
        self.assertIn("AGENT_GENERATION_BACKEND=auto\n", export_payload["content"])

    def test_import_system_config_returns_conflict_when_version_is_stale(self) -> None:
        with self.assertRaises(HTTPException) as context:
            system_config.import_system_config(
                request_obj=self._build_request(),
                request=ImportSystemConfigRequest(
                    config_version="stale-version",
                    content="STOCK_LIST=300750\n",
                    reload_now=False,
                ),
                service=self.service,
            )

        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.detail["error"], "config_version_conflict")

    def test_import_system_config_returns_bad_request_for_invalid_content(self) -> None:
        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()

        with self.assertRaises(HTTPException) as context:
            system_config.import_system_config(
                request_obj=self._build_request(),
                request=ImportSystemConfigRequest(
                    config_version=current["config_version"],
                    content="# comments only\n\n",
                    reload_now=False,
                ),
                service=self.service,
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail["error"], "invalid_import_file")

    def test_import_system_config_returns_bad_request_for_empty_content(self) -> None:
        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()

        with self.assertRaises(HTTPException) as context:
            system_config.import_system_config(
                request_obj=self._build_request(),
                request=ImportSystemConfigRequest(
                    config_version=current["config_version"],
                    content="",
                    reload_now=False,
                ),
                service=self.service,
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail["error"], "invalid_import_file")

    def test_config_env_endpoints_work_outside_desktop_mode(self) -> None:
        with patch.dict(os.environ, {"DSA_DESKTOP_MODE": "false"}, clear=False):
            current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()

            export_payload = system_config.export_system_config(
                request=self._build_request(),
                service=self.service,
            ).model_dump()
            import_payload = system_config.import_system_config(
                request_obj=self._build_request(),
                request=ImportSystemConfigRequest(
                    config_version=current["config_version"],
                    content="STOCK_LIST=300750\n",
                    reload_now=False,
                ),
                service=self.service,
            ).model_dump()

            self.assertIn("STOCK_LIST=600519,000001", export_payload["content"])
            self.assertTrue(import_payload["success"])
            self.assertEqual(self.manager.read_config_map()["STOCK_LIST"], "300750")

    def test_config_env_endpoints_reject_without_backup_access(self) -> None:
        with patch.dict(
            os.environ,
            {"DSA_DESKTOP_MODE": "false"},
            clear=False,
        ):
            self.env_path.write_text(
                "\n".join(
                    [
                        "STOCK_LIST=600519,000001",
                        "GEMINI_API_KEY=secret-key-value",
                        "SCHEDULE_TIME=18:00",
                        "LOG_LEVEL=INFO",
                        "ADMIN_AUTH_ENABLED=false",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            self.manager = ConfigManager(env_path=self.env_path)
            self.service = SystemConfigService(manager=self.manager)
            Config.reset_instance()

            current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()

            with self.assertRaises(HTTPException) as export_ctx:
                system_config.export_system_config(
                    request=self._build_request(),
                    service=self.service,
                )
            self.assertEqual(export_ctx.exception.status_code, 403)
            self.assertEqual(export_ctx.exception.detail["error"], "env_backup_access_denied")

            with self.assertRaises(HTTPException) as import_ctx:
                system_config.import_system_config(
                    request_obj=self._build_request(),
                    request=ImportSystemConfigRequest(
                        config_version=current["config_version"],
                        content="STOCK_LIST=300750\n",
                        reload_now=False,
                    ),
                    service=self.service,
                )
            self.assertEqual(import_ctx.exception.status_code, 403)
            self.assertEqual(import_ctx.exception.detail["error"], "env_backup_access_denied")

    def test_config_env_endpoints_require_valid_admin_session(self) -> None:
        with (
            patch.dict(os.environ, {"DSA_DESKTOP_MODE": "false"}, clear=False),
            patch.object(system_config, "verify_session", return_value=False),
        ):
            current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()
            invalid_request = self._build_request({system_config.COOKIE_NAME: "invalid-session"})

            with self.assertRaises(HTTPException) as export_ctx:
                system_config.export_system_config(request=invalid_request, service=self.service)
            self.assertEqual(export_ctx.exception.status_code, 401)
            self.assertEqual(export_ctx.exception.detail["error"], "env_backup_access_denied")

            with self.assertRaises(HTTPException) as import_ctx:
                system_config.import_system_config(
                    request_obj=invalid_request,
                    request=ImportSystemConfigRequest(
                        config_version=current["config_version"],
                        content="STOCK_LIST=300750\n",
                        reload_now=False,
                    ),
                    service=self.service,
                )
            self.assertEqual(import_ctx.exception.status_code, 401)
            self.assertEqual(import_ctx.exception.detail["error"], "env_backup_access_denied")

    def test_config_env_endpoints_require_explicit_true_for_desktop_bypass(self) -> None:
        with patch.dict(
            os.environ,
            {"DSA_DESKTOP_MODE": "desktop"},
            clear=False,
        ):
            self.env_path.write_text(
                "\n".join(
                    [
                        "STOCK_LIST=600519,000001",
                        "GEMINI_API_KEY=secret-key-value",
                        "SCHEDULE_TIME=18:00",
                        "LOG_LEVEL=INFO",
                        "ADMIN_AUTH_ENABLED=false",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            self.manager = ConfigManager(env_path=self.env_path)
            self.service = SystemConfigService(manager=self.manager)
            Config.reset_instance()

            with self.assertRaises(HTTPException) as export_ctx:
                system_config.export_system_config(
                    request=self._build_request(),
                    service=self.service,
                )

            self.assertEqual(export_ctx.exception.status_code, 403)
            self.assertEqual(export_ctx.exception.detail["error"], "env_backup_access_denied")

    def test_config_env_endpoints_return_server_error_for_storage_permission_error(self) -> None:
        current = system_config.get_system_config(include_schema=False, service=self.service).model_dump()

        with patch.object(self.service, "export_env", side_effect=PermissionError("read denied")):
            with self.assertRaises(HTTPException) as export_ctx:
                system_config.export_system_config(
                    request=self._build_request(),
                    service=self.service,
                )

        self.assertEqual(export_ctx.exception.status_code, 500)
        self.assertEqual(export_ctx.exception.detail["error"], "internal_error")

        with patch.object(self.service, "import_env", side_effect=PermissionError("write denied")):
            with self.assertRaises(HTTPException) as import_ctx:
                system_config.import_system_config(
                    request_obj=self._build_request(),
                    request=ImportSystemConfigRequest(
                        config_version=current["config_version"],
                        content="STOCK_LIST=300750\n",
                        reload_now=False,
                    ),
                    service=self.service,
                )

        self.assertEqual(import_ctx.exception.status_code, 500)
        self.assertEqual(import_ctx.exception.detail["error"], "internal_error")

    def test_config_env_endpoints_reject_without_session_after_auth_toggle(self) -> None:
        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519,000001",
                    "GEMINI_API_KEY=secret-key-value",
                    "SCHEDULE_TIME=18:00",
                    "LOG_LEVEL=INFO",
                    "ADMIN_AUTH_ENABLED=false",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.manager = ConfigManager(env_path=self.env_path)
        self.service = SystemConfigService(manager=self.manager)
        Config.reset_instance()

        self.env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519,000001",
                    "GEMINI_API_KEY=secret-key-value",
                    "SCHEDULE_TIME=18:00",
                    "LOG_LEVEL=INFO",
                    "ADMIN_AUTH_ENABLED=true",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        auth._auth_enabled = False

        async def request_export() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._build_client_app())
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.get("/api/v1/system/config/export")

        response = asyncio.run(request_export())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "env_backup_access_denied")

    def test_test_llm_channel_endpoint_returns_service_payload(self) -> None:
        with patch.object(
            self.service,
            "test_llm_channel",
            return_value={
                "success": True,
                "message": "LLM channel test succeeded",
                "error": None,
                "error_code": None,
                "stage": "chat_completion",
                "retryable": False,
                "details": {},
                "resolved_protocol": "openai",
                "resolved_model": "openai/gpt-4o-mini",
                "latency_ms": 123,
            },
        ) as mock_test:
            payload = system_config.test_llm_channel(
                request=TestLLMChannelRequest(
                    name="primary",
                    protocol="openai",
                    base_url="https://api.example.com/v1",
                    api_key="sk-test",
                    models=["gpt-4o-mini"],
                    capability_checks=["json", "stream"],
                ),
                service=self.service,
            ).model_dump()

        self.assertTrue(payload["success"])
        self.assertEqual(payload["resolved_model"], "openai/gpt-4o-mini")
        self.assertEqual(payload["stage"], "chat_completion")
        self.assertEqual(payload["capability_results"], {})
        mock_test.assert_called_once()
        self.assertEqual(mock_test.call_args.kwargs["capability_checks"], ["json", "stream"])

    def test_test_notification_channel_endpoint_returns_service_payload(self) -> None:
        with patch.object(
            self.service,
            "test_notification_channel",
            return_value={
                "success": True,
                "message": "notification ok",
                "error_code": None,
                "stage": "notification_send",
                "retryable": False,
                "latency_ms": 42,
                "attempts": [
                    {
                        "channel": "wechat",
                        "success": True,
                        "message": "sent",
                        "target": "https://qyapi.example.com/cgi-bin/webhook/send?key=***",
                        "error_code": None,
                        "stage": "notification_send",
                        "retryable": False,
                        "latency_ms": 42,
                        "http_status": 200,
                    }
                ],
            },
        ) as mock_test:
            payload = system_config.test_notification_channel(
                request=TestNotificationChannelRequest(
                    channel="wechat",
                    items=[{"key": "WECHAT_WEBHOOK_URL", "value": "https://example.com/hook"}],
                    title="DSA 通知测试",
                    content="hello",
                    timeout_seconds=5,
                ),
                service=self.service,
            ).model_dump()

        self.assertTrue(payload["success"])
        self.assertEqual(payload["attempts"][0]["channel"], "wechat")
        self.assertEqual(payload["attempts"][0]["latency_ms"], 42)
        mock_test.assert_called_once()
        self.assertEqual(mock_test.call_args.kwargs["channel"], "wechat")
        self.assertEqual(mock_test.call_args.kwargs["timeout_seconds"], 5)

    def test_test_notification_channel_schema_accepts_p6_channels(self) -> None:
        ntfy_request = TestNotificationChannelRequest(
            channel="ntfy",
            items=[{"key": "NTFY_URL", "value": "https://ntfy.sh/dsa-topic"}],
            title="DSA 通知测试",
            content="hello",
            timeout_seconds=5,
        )
        gotify_request = TestNotificationChannelRequest(
            channel="gotify",
            items=[
                {"key": "GOTIFY_URL", "value": "https://gotify.example"},
                {"key": "GOTIFY_TOKEN", "value": "app-token"},
            ],
            title="DSA 通知测试",
            content="hello",
            timeout_seconds=5,
        )

        self.assertEqual(ntfy_request.channel, "ntfy")
        self.assertEqual(gotify_request.channel, "gotify")

    def test_validate_returns_user_facing_model_message_without_internal_env_key_name(self) -> None:
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
        issue = next(issue for issue in validation["issues"] if issue["key"] == "LITELLM_MODEL")
        self.assertEqual(issue["code"], "unknown_model")
        self.assertNotIn("LITELLM_MODEL", issue["message"])
        self.assertIn("primary model", issue["message"].lower())

    def test_discover_llm_channel_models_endpoint_returns_service_payload(self) -> None:
        with patch.object(
            self.service,
            "discover_llm_channel_models",
            return_value={
                "success": True,
                "message": "LLM channel model discovery succeeded",
                "error": None,
                "error_code": None,
                "stage": "model_discovery",
                "retryable": False,
                "details": {"model_count": 2},
                "resolved_protocol": "openai",
                "models": ["qwen-plus", "qwen-turbo"],
                "latency_ms": 88,
            },
        ) as mock_discover:
            payload = system_config.discover_llm_channel_models(
                request=DiscoverLLMChannelModelsRequest(
                    name="dashscope",
                    protocol="openai",
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    api_key="sk-test",
                ),
                service=self.service,
            ).model_dump()

        self.assertTrue(payload["success"])
        self.assertEqual(payload["models"], ["qwen-plus", "qwen-turbo"])
        self.assertEqual(payload["stage"], "model_discovery")
        mock_discover.assert_called_once()


if __name__ == "__main__":
    unittest.main()
