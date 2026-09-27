# -*- coding: utf-8 -*-
"""深度投研关键锚点交叉验证注入辅助（KISS · opt-in · 零回归）。

受 ``DEEP_RESEARCH_CROSS_VALIDATE`` 开关控制：关闭时
:func:`build_cross_validation_block` 返回 None，data_tools 工具返回与改动前
完全一致（无 ``cross_validation`` 字段）—— 保证不影响现有功能。

职责（高内聚）：
- 构建/缓存 :class:`CrossSourceValidator`（MX 主源 + iFinD/Choice MCP/fuyao 验证源）。
- 对一组锚点逐个验证，压缩为 LLM 友好的 ``cross_validation`` 块。

data_tools 各 handler 只需一行调用，不感知验证细节（低耦合）。
"""

from __future__ import annotations

import logging
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional

from data_provider.cross_source_validator import (
    AnchorReading,
    CrossSourceValidator,
    SourceAdapter,
)

logger = logging.getLogger(__name__)

_validator_instance: Optional[CrossSourceValidator] = None
_validator_lock = Lock()


def reset_validator() -> None:
    """重置缓存（config reload / 测试用）。"""
    global _validator_instance
    with _validator_lock:
        _validator_instance = None


def _build_sources(config: Any) -> List[SourceAdapter]:
    """构建数据源列表：MX 主源 + iFinD/Choice MCP/fuyao 验证源（按需启用）。"""
    from data_provider.mx_data_adapter import MXSource

    sources: List[SourceAdapter] = [
        MXSource()
    ]  # 无 key 时 available=False，read 返回 None
    if getattr(config, "ifind_mcp_endpoint", None) and getattr(
        config, "ifind_mcp_token", None
    ):
        from data_provider.ifind_fundamental_adapter import IfindFetcher, IfindSource

        fetcher = IfindFetcher(
            endpoint=config.ifind_mcp_endpoint,
            token=config.ifind_mcp_token,
            timeout_seconds=float(getattr(config, "ifind_mcp_timeout_seconds", 8.0)),
        )
        sources.append(IfindSource(fetcher=fetcher))
    # 第三验证源：东财 Choice MCP（妙想 MCP），opt-in，默认关 → 零回归
    if getattr(config, "enable_mx_mcp", False) and getattr(
        config, "mx_mcp_api_key", None
    ):
        from data_provider.mx_mcp_adapter import MxMcpFetcher, MxMcpSource

        fetcher = MxMcpFetcher(
            endpoint=getattr(config, "mx_mcp_endpoint", None),
            api_key=getattr(config, "mx_mcp_api_key", None),
            timeout_seconds=float(getattr(config, "mx_mcp_timeout_seconds", 30.0)),
        )
        sources.append(MxMcpSource(fetcher=fetcher))
    # 第四验证源：同花顺 fuyao (aicubes REST)，opt-in，默认关 → 零回归
    if getattr(config, "enable_fuyao", False) and getattr(
        config, "fuyao_api_key", None
    ):
        from data_provider.fuyao_adapter import FuyaoFetcher, FuyaoSource

        fetcher = FuyaoFetcher(
            endpoint=getattr(config, "fuyao_endpoint", None),
            api_key=getattr(config, "fuyao_api_key", None),
            timeout_seconds=float(getattr(config, "fuyao_timeout_seconds", 30.0)),
        )
        sources.append(FuyaoSource(fetcher=fetcher))
    return sources


def _get_validator() -> Optional[CrossSourceValidator]:
    """懒加载 validator（进程级单例）。开关关 / 无源 → None。"""
    global _validator_instance
    if _validator_instance is not None:
        return _validator_instance
    from src.config import get_config

    config = get_config()
    if not getattr(config, "deep_research_cross_validate", False):
        return None
    with _validator_lock:
        if _validator_instance is None:
            sources = _build_sources(config)
            if not sources:
                return None
            _validator_instance = CrossSourceValidator(sources=sources)
    return _validator_instance


def build_cross_validation_block(
    code: str,
    fields: Iterable[str],
    period: Optional[str] = None,
    primary_readings: Optional[Dict[str, AnchorReading]] = None,
    validator: Optional[CrossSourceValidator] = None,
) -> Optional[Dict[str, Any]]:
    """构建 ``cross_validation`` 块。

    - 开关关 / 无 validator / 全锚点失败 → None（零回归，不注入字段）。
    - ``primary_readings``：注入主源读数（如行情类的 realtime_quote），该源作 primary。
    - ``validator``：测试注入；默认从 config 开关懒加载。
    - 任一锚点验证异常被隔离（fail-open），不影响其余锚点。
    """
    validator = validator if validator is not None else _get_validator()
    if validator is None:
        return None
    primary_readings = primary_readings or {}
    anchors: Dict[str, Any] = {}
    agreed = 0
    total = 0
    for field in fields:
        total += 1
        try:
            verification = validator.verify(
                code,
                field,
                period=period,
                primary_reading=primary_readings.get(field),
            )
        except Exception as exc:  # noqa: BLE001 — fail-open：单锚点失败不阻塞其余
            logger.debug("[CrossValidate] verify %s/%s failed: %s", code, field, exc)
            continue
        anchors[field] = verification.to_compact()
        if verification.confidence == "high":
            agreed += 1
    if not anchors:
        return None
    return {
        "enabled": True,
        "anchors": anchors,
        "summary": f"{agreed}/{total} 锚点双源验证通过",
    }
