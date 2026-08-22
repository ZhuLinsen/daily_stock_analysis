# -*- coding: utf-8 -*-
"""Tests for the Miaoxiang news-search provider wiring (PR #2248)."""

from __future__ import annotations

from src.search_service import SearchService


def _service(**overrides) -> SearchService:
    kwargs = {"searxng_base_urls": ["http://searxng.local:8080"], "mx_apikey": "mx-test-key"}
    kwargs.update(overrides)
    return SearchService(**kwargs)


class TestCapabilityProbe:
    def test_mx_only_config_enables_search_capability(self, monkeypatch):
        """仅配置 MX_APIKEY 时,大盘复盘等入口不得把搜索能力判定为未启用。"""
        from src.config import Config

        config = Config(
            anspire_api_keys=[], bocha_api_keys=[], minimax_api_keys=[],
            tavily_api_keys=[], brave_api_keys=[], serpapi_keys=[],
            searxng_base_urls=[], searxng_public_instances_enabled=False,
            mx_apikey="mx-test-key",
        )
        assert config.has_search_capability_enabled() is True

    def test_no_search_config_disables_capability(self, monkeypatch):
        from src.config import Config

        config = Config(
            anspire_api_keys=[], bocha_api_keys=[], minimax_api_keys=[],
            tavily_api_keys=[], brave_api_keys=[], serpapi_keys=[],
            searxng_base_urls=[], searxng_public_instances_enabled=False,
            mx_apikey=None,
        )
        assert config.has_search_capability_enabled() is False


class TestSubprocessKwargs:
    def test_constructor_kwargs_carry_mx_apikey(self):
        """bounded 题材搜索在子进程中重建 SearchService 时必须带上 mx_apikey。"""
        service = _service()
        kwargs = service._constructor_kwargs
        assert kwargs["mx_apikey"] == "mx-test-key"

        rebuilt = SearchService(**kwargs)
        names = [p.name for p in rebuilt._providers]
        assert "Miaoxiang" in names

    def test_provider_sits_after_searxng(self):
        service = _service()
        names = [p.name for p in service._providers]
        assert names.index("SearXNG") < names.index("Miaoxiang")

    def test_no_mx_apikey_no_provider(self):
        service = _service(mx_apikey=None)
        assert all(p.name != "Miaoxiang" for p in service._providers)
