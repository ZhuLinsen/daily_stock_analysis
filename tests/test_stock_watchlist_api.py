# -*- coding: utf-8 -*-
"""Watchlist API regressions for stock-code variant matching."""

import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from api.v1.endpoints.stocks import add_to_watchlist, get_watchlist, remove_from_watchlist
from api.v1.schemas.history import WatchlistRequest
from src.config import Config, setup_env
from src.core.config_manager import ConfigManager
from src.services.system_config_service import SystemConfigService


class FakeSystemConfigService:
    def __init__(self, stock_list: str) -> None:
        self.stock_list = stock_list
        self.config_version = "cfg-v1"
        self.update_calls: list[str] = []

    def get_config(self, include_schema: bool = False) -> dict:
        return {
            "config_version": self.config_version,
            "items": [{"key": "STOCK_LIST", "value": self.stock_list}],
        }

    def update(self, **kwargs) -> None:
        items = kwargs["items"]
        self.stock_list = items[0]["value"]
        self.update_calls.append(self.stock_list)


def test_watchlist_add_deduplicates_raw_hk_code_against_prefixed_variant() -> None:
    service = FakeSystemConfigService("00700")

    response = add_to_watchlist(
        WatchlistRequest(stock_code="HK00700"),
        service=service,
    )

    assert response.stock_codes == ["00700"]
    assert service.stock_list == "00700"
    assert service.update_calls == []


def test_watchlist_remove_deletes_raw_hk_code_from_prefixed_variant_request() -> None:
    service = FakeSystemConfigService("00700")

    response = remove_from_watchlist(
        WatchlistRequest(stock_code="HK00700"),
        service=service,
    )

    assert response.stock_codes == []
    assert service.stock_list == ""
    assert service.update_calls == [""]


def test_watchlist_matching_is_case_insensitive_for_us_tickers() -> None:
    service = FakeSystemConfigService("aapl")

    add_response = add_to_watchlist(
        WatchlistRequest(stock_code="AAPL"),
        service=service,
    )
    remove_response = remove_from_watchlist(
        WatchlistRequest(stock_code="AAPL"),
        service=service,
    )

    assert add_response.stock_codes == ["aapl"]
    assert remove_response.stock_codes == []
    assert service.update_calls == [""]


def test_watchlist_reads_common_copy_paste_separators() -> None:
    service = FakeSystemConfigService("600519，300750  AAPL")

    response = get_watchlist(service=service)

    assert response.stock_codes == ["600519", "300750", "AAPL"]


def test_watchlist_add_normalizes_existing_mixed_separators_on_write() -> None:
    service = FakeSystemConfigService("600519，300750")

    response = add_to_watchlist(
        WatchlistRequest(stock_code="AAPL"),
        service=service,
    )

    assert response.stock_codes == ["600519", "300750", "AAPL"]
    assert service.stock_list == "600519,300750,AAPL"
    assert service.update_calls == ["600519,300750,AAPL"]


@pytest.mark.parametrize(
    "invalid_llm_config",
    [
        "LITELLM_FALLBACK_MODELS=openai/removed-model\n",
        "LLM_PRIMARY_PROTOCOL=invalid-protocol\n",
        "AGENT_LITELLM_MODEL=openai/removed-agent-model\n",
        "VISION_MODEL=openai/removed-vision-model\n",
    ],
)
def test_watchlist_writes_with_existing_llm_errors_preserve_runtime_overrides(
    tmp_path, invalid_llm_config,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "STOCK_LIST=600519\n"
        "LLM_CHANNELS=primary\n"
        "LLM_PRIMARY_PROTOCOL=openai\n"
        "LLM_PRIMARY_API_KEY=test-secret\n"
        "LLM_PRIMARY_MODELS=gpt-test\n"
        "LITELLM_MODEL=openai/gpt-test\n"
        "WEBUI_HOST=127.0.0.1\n"
        "STRATEGIES_DIR=/local/strategies\n"
        + invalid_llm_config,
        encoding="utf-8",
    )
    with patch.dict(os.environ, {
        "ENV_FILE": str(env_path),
        "WEBUI_HOST": "0.0.0.0",
        "STRATEGIES_DIR": "/container/strategies",
    }, clear=True):
        Config.reset_instance()
        try:
            setup_env()
            runtime_config = Config.get_instance()
            manager = ConfigManager(env_path=env_path)
            service = SystemConfigService(manager=manager)
            saved_before = manager.read_config_map()
            assert service.validate(items=[])["issues"]

            added = add_to_watchlist(WatchlistRequest(stock_code="AAPL"), service=service)
            assert added.stock_codes == ["600519", "AAPL"]
            assert runtime_config.stock_list == ["600519", "AAPL"]
            removed = remove_from_watchlist(WatchlistRequest(stock_code="600519"), service=service)
            assert removed.stock_codes == ["AAPL"]
            assert runtime_config.stock_list == ["AAPL"]
            cleared = remove_from_watchlist(WatchlistRequest(stock_code="AAPL"), service=service)
            assert cleared.stock_codes == []
            assert runtime_config.stock_list == []
            assert os.environ["STOCK_LIST"] == ""
            assert get_watchlist(service=service).stock_codes == []

            assert Config.get_instance() is runtime_config
            assert runtime_config.webui_host == "0.0.0.0"
            assert os.environ["WEBUI_HOST"] == "0.0.0.0"
            assert os.environ["STRATEGIES_DIR"] == "/container/strategies"
            saved_after = manager.read_config_map()
            assert saved_after.pop("STOCK_LIST") == ""
            saved_before.pop("STOCK_LIST")
            assert saved_after == saved_before
            assert service.validate(items=[])["issues"]

            before_invalid = env_path.read_bytes()
            with pytest.raises(HTTPException) as exc:
                add_to_watchlist(WatchlistRequest(stock_code="not/a/stock"), service=service)
            assert exc.value.status_code == 400
            assert env_path.read_bytes() == before_invalid
        finally:
            Config.reset_instance()


def test_watchlist_add_keeps_container_override_when_env_file_lacks_the_key(tmp_path):
    """Docker env_file only populates the process environment.

    refresh_stock_list() falls back to os.environ when .env has no STOCK_LIST
    line, so the fast path must not write an empty string over it.
    """
    env_path = tmp_path / ".env"
    env_path.write_text(
        "LLM_CHANNELS=primary\n"
        "LLM_PRIMARY_PROTOCOL=openai\n"
        "LLM_PRIMARY_API_KEY=test-secret\n"
        "LLM_PRIMARY_MODELS=gpt-test\n"
        "LITELLM_MODEL=openai/gpt-test\n"
        "WEBUI_HOST=127.0.0.1\n",
        encoding="utf-8",
    )
    with patch.dict(os.environ, {
        "ENV_FILE": str(env_path),
        "STOCK_LIST": "600519",
        "WEBUI_HOST": "0.0.0.0",
    }, clear=True):
        Config.reset_instance()
        try:
            setup_env()
            runtime_config = Config.get_instance()
            assert runtime_config.stock_list == ["600519"]
            service = SystemConfigService(manager=ConfigManager(env_path=env_path))

            added = add_to_watchlist(WatchlistRequest(stock_code="AAPL"), service=service)

            assert added.stock_codes == ["600519", "AAPL"]
            assert runtime_config.stock_list == ["600519", "AAPL"]
            # The saved value is authoritative now that the file carries the key.
            assert "STOCK_LIST" in ConfigManager(env_path=env_path).read_config_map()
            assert os.environ["STOCK_LIST"] == "600519,AAPL"
        finally:
            Config.reset_instance()


def test_watchlist_clear_takes_effect_despite_container_override(tmp_path):
    """Clearing must win over a container override.

    refresh_stock_list() falls back to os.environ only when the file value is
    empty, so the fast path has to mirror the emptied value or the old list
    would be resurrected.
    """
    env_path = tmp_path / ".env"
    env_path.write_text(
        "STOCK_LIST=600519\n"
        "LLM_CHANNELS=primary\n"
        "LLM_PRIMARY_PROTOCOL=openai\n"
        "LLM_PRIMARY_API_KEY=test-secret\n"
        "LLM_PRIMARY_MODELS=gpt-test\n"
        "LITELLM_MODEL=openai/gpt-test\n",
        encoding="utf-8",
    )
    with patch.dict(os.environ, {
        "ENV_FILE": str(env_path),
        "STOCK_LIST": "600519",
    }, clear=True):
        Config.reset_instance()
        try:
            setup_env()
            runtime_config = Config.get_instance()
            service = SystemConfigService(manager=ConfigManager(env_path=env_path))

            cleared = remove_from_watchlist(WatchlistRequest(stock_code="600519"), service=service)

            assert cleared.stock_codes == []
            assert runtime_config.stock_list == []
            assert get_watchlist(service=service).stock_codes == []
        finally:
            Config.reset_instance()
