# -*- coding: utf-8 -*-
"""数据源接入状态服务。

提供一个 side-effect-free 的外部数据源接入状态视图：
- 行情数据源：镜像 ``DataFetcherManager._init_default_fetchers`` 的注册门槛
- 新闻搜索源：镜像 ``SearchService.__init__`` 的注册门槛

状态只从运行时配置推导，不实例化任何 Fetcher / SearchProvider，
不发起网络请求。熔断状态来自 ``DataFetcherManager`` 的进程内快照，
属于 best-effort 信息（独立进程运行分析时不可见）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

STATUS_ACTIVE = "active"
STATUS_NOT_CONFIGURED = "not_configured"

# SearXNG 公共实例自动发现模式的稳定标识（Web 端据此翻译展示文案）
DETAIL_PUBLIC_INSTANCE_AUTO_DISCOVERY = "public_instance_auto_discovery"


def _has_text(value: Any) -> bool:
    return bool(str(value).strip()) if value is not None else False


def _has_items(value: Any) -> bool:
    return bool(value) if isinstance(value, (list, tuple)) else False


def _longbridge_configured(config: Any) -> bool:
    """镜像 LongbridgeFetcher.has_configured_credentials 的判定。"""
    try:
        from data_provider.longbridge_fetcher import LongbridgeFetcher

        return bool(LongbridgeFetcher.has_configured_credentials(config))
    except Exception as exc:  # pragma: no cover - 防御性兜底
        logger.debug("Longbridge 凭据检查失败: %s", exc)
        return False


@dataclass(frozen=True)
class _SourceSpec:
    """单个外部数据源的静态定义。"""

    source_id: str
    name: str
    kind: str  # market_data | search
    config_keys: List[str] = field(default_factory=list)
    markets: List[str] = field(default_factory=list)
    # fetcher 类名，用于关联日线熔断器 key（daily_data:{market}:{fetcher_name}）
    fetcher_name: Optional[str] = None
    # 返回 True 表示已配置可用；None 表示无需配置、默认激活
    configured_check: Optional[Callable[[Any], bool]] = None
    detail: Optional[str] = None


# 行情数据源定义顺序与 A 股日线实际尝试顺序保持一致：
# TencentFetcher/AkshareFetcher/BaostockFetcher 被 DataFetcherManager
# 提升到最前（见 _DAILY_MARKET_FETCHER_PROMOTED["cn"]），其余源随后作为兜底
_MARKET_DATA_SPECS: List[_SourceSpec] = [
    _SourceSpec("tencent", "腾讯行情", "market_data",
                markets=["cn", "hk"], fetcher_name="TencentFetcher"),
    _SourceSpec("akshare", "Akshare + 新浪财经", "market_data",
                markets=["cn", "hk"], fetcher_name="AkshareFetcher"),
    _SourceSpec("baostock", "Baostock", "market_data",
                markets=["cn"], fetcher_name="BaostockFetcher"),
    _SourceSpec("efinance", "Efinance（东方财富）", "market_data",
                markets=["cn"], fetcher_name="EfinanceFetcher"),
    _SourceSpec("pytdx", "通达信 (pytdx)", "market_data",
                markets=["cn"], fetcher_name="PytdxFetcher"),
    _SourceSpec("yfinance", "Yahoo Finance + Stooq", "market_data",
                markets=["cn", "hk", "us", "jp", "kr", "tw"],
                fetcher_name="YfinanceFetcher"),
    _SourceSpec("tushare", "Tushare Pro", "market_data",
                config_keys=["TUSHARE_TOKEN"], markets=["cn", "hk"],
                fetcher_name="TushareFetcher",
                configured_check=lambda c: _has_text(getattr(c, "tushare_token", None))),
    _SourceSpec("tickflow", "TickFlow", "market_data",
                config_keys=["TICKFLOW_API_KEY"], markets=["cn"],
                fetcher_name="TickFlowFetcher",
                configured_check=lambda c: _has_text(getattr(c, "tickflow_api_key", None))),
    _SourceSpec("longbridge", "Longbridge（长桥）", "market_data",
                config_keys=[
                    "LONGBRIDGE_OAUTH_CLIENT_ID",
                    "LONGBRIDGE_APP_KEY",
                    "LONGBRIDGE_APP_SECRET",
                    "LONGBRIDGE_ACCESS_TOKEN",
                ],
                markets=["hk", "us"], fetcher_name="LongbridgeFetcher",
                configured_check=_longbridge_configured),
    _SourceSpec("finnhub", "Finnhub", "market_data",
                config_keys=["FINNHUB_API_KEY"], markets=["us"],
                fetcher_name="FinnhubFetcher",
                configured_check=lambda c: _has_text(getattr(c, "finnhub_api_key", None))),
    _SourceSpec("alphavantage", "Alpha Vantage", "market_data",
                config_keys=["ALPHAVANTAGE_API_KEY"], markets=["us"],
                fetcher_name="AlphaVantageFetcher",
                configured_check=lambda c: _has_text(getattr(c, "alphavantage_api_key", None))),
]

# 搜索源定义顺序与 SearchService 内的优先级说明保持一致
_SEARCH_SPECS: List[_SourceSpec] = [
    _SourceSpec("anspire", "Anspire Search", "search",
                config_keys=["ANSPIRE_API_KEYS"],
                configured_check=lambda c: _has_items(getattr(c, "anspire_api_keys", None))),
    _SourceSpec("bocha", "博查 Bocha", "search",
                config_keys=["BOCHA_API_KEYS"],
                configured_check=lambda c: _has_items(getattr(c, "bocha_api_keys", None))),
    _SourceSpec("tavily", "Tavily", "search",
                config_keys=["TAVILY_API_KEYS"],
                configured_check=lambda c: _has_items(getattr(c, "tavily_api_keys", None))),
    _SourceSpec("brave", "Brave Search", "search",
                config_keys=["BRAVE_API_KEYS"],
                configured_check=lambda c: _has_items(getattr(c, "brave_api_keys", None))),
    _SourceSpec("serpapi", "SerpAPI", "search",
                config_keys=["SERPAPI_API_KEYS"],
                configured_check=lambda c: _has_items(getattr(c, "serpapi_keys", None))),
    _SourceSpec("minimax", "MiniMax Search", "search",
                config_keys=["MINIMAX_API_KEYS"],
                configured_check=lambda c: _has_items(getattr(c, "minimax_api_keys", None))),
]


class DataSourceStatusService:
    """从配置推导外部数据源接入状态（只读、无副作用）。"""

    def __init__(self, config: Optional[Any] = None):
        self._config = config

    def _get_config(self) -> Any:
        if self._config is not None:
            return self._config
        from src.config import get_config

        return get_config()

    @staticmethod
    def _daily_circuit_states() -> Dict[str, str]:
        """读取进程内日线熔断器快照；失败时返回空。"""
        try:
            from data_provider.base import DataFetcherManager

            return DataFetcherManager.get_daily_source_health_status()
        except Exception as exc:  # pragma: no cover - 防御性兜底
            logger.debug("读取日线熔断状态失败: %s", exc)
            return {}

    @staticmethod
    def _circuit_for_fetcher(
        circuit_states: Dict[str, str], fetcher_name: Optional[str]
    ) -> List[Dict[str, str]]:
        """提取指定 fetcher 的非 closed 熔断状态。

        熔断器 key 格式：``daily_data:{market}:{fetcher_name}``。
        """
        if not fetcher_name:
            return []
        results: List[Dict[str, str]] = []
        for key, state in circuit_states.items():
            parts = key.split(":", 2)
            if len(parts) != 3 or parts[0] != "daily_data" or parts[2] != fetcher_name:
                continue
            if state and state != "closed":
                results.append({"market": parts[1], "state": state})
        return results

    def _build_entry(
        self,
        spec: _SourceSpec,
        config: Any,
        circuit_states: Dict[str, str],
    ) -> Dict[str, Any]:
        requires_credentials = spec.configured_check is not None
        if requires_credentials:
            active = bool(spec.configured_check(config))
        else:
            active = True
        return {
            "source_id": spec.source_id,
            "name": spec.name,
            "kind": spec.kind,
            "status": STATUS_ACTIVE if active else STATUS_NOT_CONFIGURED,
            "requires_credentials": requires_credentials,
            "markets": list(spec.markets),
            "config_keys": list(spec.config_keys),
            "detail": spec.detail,
            "circuit": self._circuit_for_fetcher(circuit_states, spec.fetcher_name),
        }

    def _build_searxng_entry(self, config: Any) -> Dict[str, Any]:
        """SearXNG：自建实例或公共实例自动发现，二者其一即视为已接入。"""
        base_urls = getattr(config, "searxng_base_urls", None)
        public_enabled = bool(getattr(config, "searxng_public_instances_enabled", False))
        has_base_urls = _has_items(base_urls)
        active = has_base_urls or public_enabled
        detail = None
        if active and not has_base_urls:
            detail = DETAIL_PUBLIC_INSTANCE_AUTO_DISCOVERY
        return {
            "source_id": "searxng",
            "name": "SearXNG",
            "kind": "search",
            "status": STATUS_ACTIVE if active else STATUS_NOT_CONFIGURED,
            "requires_credentials": False,
            "markets": [],
            "config_keys": ["SEARXNG_BASE_URLS", "SEARXNG_PUBLIC_INSTANCES_ENABLED"],
            "detail": detail,
            "circuit": [],
        }

    def get_status(self) -> Dict[str, Any]:
        """返回外部数据源接入状态载荷。"""
        config = self._get_config()
        circuit_states = self._daily_circuit_states()

        market_data = [
            self._build_entry(spec, config, circuit_states)
            for spec in _MARKET_DATA_SPECS
        ]
        search = [
            self._build_entry(spec, config, circuit_states)
            for spec in _SEARCH_SPECS
        ]
        search.append(self._build_searxng_entry(config))

        def _active_count(entries: List[Dict[str, Any]]) -> int:
            return sum(1 for entry in entries if entry["status"] == STATUS_ACTIVE)

        return {
            "market_data": market_data,
            "search": search,
            "summary": {
                "market_data_active": _active_count(market_data),
                "market_data_total": len(market_data),
                "search_active": _active_count(search),
                "search_total": len(search),
            },
        }
