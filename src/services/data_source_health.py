# -*- coding: utf-8 -*-
"""进程级数据源健康追踪。

按市场聚合每只股票日线抓取的"最终结果"（成功 / 全部数据源失败），用于在批量分析
收尾时识别"整市场数据源集体失效"，并在通知里附加一段简短告警。

判定口径：某市场在一个批次内有尝试、但成功次数为 0（且至少有一次失败）时，视为
该市场数据源"集体失效"。这能把"全市场源同时挂掉"与"个别股票代码无效/退市"区分开。

设计约束：
- 不影响主流程。所有记录与汇总均 fail-open，异常只记日志、绝不抛出。
- 仅做内存计数，进程级、线程安全；批次开始时由调用方 reset()。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger(__name__)

# 市场代码 -> 双语展示名（与 data_provider.base.get_daily_data 的 market 取值对齐）
_MARKET_LABELS: Dict[str, Dict[str, str]] = {
    "cn": {"zh": "A股", "en": "A-shares"},
    "hk": {"zh": "港股", "en": "HK"},
    "us": {"zh": "美股", "en": "US"},
    "jp": {"zh": "日股", "en": "JP"},
    "kr": {"zh": "韩股", "en": "KR"},
    "tw": {"zh": "台股", "en": "TW"},
}


@dataclass
class _MarketStat:
    attempts: int = 0
    successes: int = 0
    failures: int = 0


_lock = threading.Lock()
_stats: Dict[str, _MarketStat] = {}


def record_market_data_outcome(market: str, success: bool) -> None:
    """记录某市场一次日线抓取的最终结果。

    在 ``get_daily_data`` 成功返回或所有数据源耗尽抛错时各调用一次。fail-open。
    """
    if not market:
        return
    try:
        with _lock:
            stat = _stats.setdefault(market, _MarketStat())
            stat.attempts += 1
            if success:
                stat.successes += 1
            else:
                stat.failures += 1
    except Exception as exc:  # pragma: no cover - defensive fail-open guard
        logger.debug("记录数据源健康失败: %s", exc)


def reset() -> None:
    """清空计数。由批量分析在批次开始时调用。fail-open。"""
    try:
        with _lock:
            _stats.clear()
    except Exception as exc:  # pragma: no cover - defensive fail-open guard
        logger.debug("重置数据源健康计数失败: %s", exc)


def summarize_collective_failures() -> List[Dict[str, int]]:
    """返回"集体失效"市场列表：有尝试、零成功、且至少一次失败。

    每项形如 ``{"market": "cn", "attempts": 3, "failures": 3}``，按市场代码排序。
    """
    try:
        with _lock:
            return [
                {"market": market, "attempts": stat.attempts, "failures": stat.failures}
                for market, stat in sorted(_stats.items())
                if stat.attempts > 0 and stat.successes == 0 and stat.failures > 0
            ]
    except Exception as exc:  # pragma: no cover - defensive fail-open guard
        logger.debug("汇总数据源健康失败: %s", exc)
        return []


def format_health_warning(report_language: str = "zh") -> str:
    """把集体失效市场拼成一行告警文案；无异常时返回空串。fail-open。"""
    try:
        failures = summarize_collective_failures()
        if not failures:
            return ""
        lang = "en" if str(report_language).lower().startswith("en") else "zh"
        names = [
            _MARKET_LABELS.get(item["market"], {}).get(lang, item["market"])
            for item in failures
        ]
        if lang == "en":
            return (
                "⚠️ Data source health: all providers failed for "
                + ", ".join(names)
                + " in this run; results may be missing. Check upstream sources or configure a token-based fallback (TUSHARE_TOKEN / FINNHUB_API_KEY / ALPHAVANTAGE_API_KEY)."
            )
        return (
            "⚠️ 数据源健康：本次运行 "
            + "、".join(names)
            + " 的全部数据源均失败，相关结果可能缺失。请检查上游数据源，或配置带 token 的兜底源（TUSHARE_TOKEN / FINNHUB_API_KEY / ALPHAVANTAGE_API_KEY）。"
        )
    except Exception as exc:  # pragma: no cover - defensive fail-open guard
        logger.debug("格式化数据源健康告警失败: %s", exc)
        return ""
