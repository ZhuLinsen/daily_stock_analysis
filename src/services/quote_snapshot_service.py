# -*- coding: utf-8 -*-
"""
===================================
个股行情快照服务（issue #771 看板后端）
===================================

口径（计划默认值 4 钉死，不得增删）：
- 直出 15：UnifiedRealtimeQuote 的展示级字段（price/pre_close/open_price/high/low/
  volume/amount/change_amount/change_pct/amplitude/volume_ratio/turnover_rate/
  change_60d/high_52w/low_52w）。
- 派生 3：VWAP（amount/volume 均价口径，缺 amount → null）、
  委比 bid_ask_ratio（A 股东财五档盘口派生，不可得 → null）、
  成交笔数 trade_count（akshare em 标准接口无此字段，探针实证，恒 null）。
- MA 4 档：ma5/ma10/ma20/ma60，历史日线收盘价严格全窗滚动
  （最近 N 条均值；有效收盘不足 N 条 → null）。
- 多市场降级：缺失一律 null 并合入 missing_fields，不做字段级硬失败。

数据入口（全部只读，不修改 data_provider/base.py）：
- 实时行情：``DataFetcherManager.get_realtime_quote()``（base.py 统一入口）
- 历史 K 线：``DataFetcherManager.get_daily_data()``
- 盘口（委比输入）：``AkshareFetcher.get_a_share_order_book()``（本服务配套新增）

缓存：端点级短 TTL 响应缓存复用 ``config.realtime_cache_ttl`` 既有机制
（该键既有语义为行情 staleness 阈值 / tickflow 内部缓存 TTL，此处以同值
作为响应缓存 TTL；不新增 env 键）。缓存键为**原始入参代码**（仅大小写归一），
不做前缀/后缀剥离——指数形态（sh000016/000016.SH）与同码股票（000016）
天然不同键，互不污染（PR #2492 blocker A）。TTL <= 0 时禁用缓存。

代码透传契约：入参代码**原样**传给 DataFetcherManager（其内部在规范化前
用 parse_analysis_target 解析指数身份），本服务仅在「A 股盘口探针」一处
做身份判定与归一。
"""

import logging
import math
import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from data_provider.akshare_fetcher import AkshareFetcher
from data_provider.base import DataFetcherManager, normalize_stock_code
from src.config import get_config
from src.services.stock_list_parser import ParseStatus, parse_analysis_target

logger = logging.getLogger(__name__)

# MA 档位 → 窗口（严格全窗，禁止 min_periods=1 部分窗口口径）
MA_WINDOWS: Dict[str, int] = {"ma5": 5, "ma10": 10, "ma20": 20, "ma60": 60}

# 直出 15 字段（UnifiedRealtimeQuote 同名属性）
DIRECT_QUOTE_FIELDS: Tuple[str, ...] = (
    "price",
    "pre_close",
    "open_price",
    "high",
    "low",
    "volume",
    "amount",
    "change_amount",
    "change_pct",
    "amplitude",
    "volume_ratio",
    "turnover_rate",
    "change_60d",
    "high_52w",
    "low_52w",
)

# 取 MA 需要的日线天数（get_daily_data 内部按日历日 ×2 估算，
# days=100 → 约 137 个交易日，保证 MA60 有足够窗口余量）
MA_HISTORY_DAYS = 100

# A 股纯 6 位代码（normalize_stock_code 已剥 SH/SZ/BJ 前缀与后缀）
_A_SHARE_CODE_RE = re.compile(r"^\d{6}$")

# 端点级短 TTL 缓存：code(upper) -> (expires_at, payload)
_SNAPSHOT_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()

_DEFAULT_CACHE_TTL = 600  # 与 config.realtime_cache_ttl 默认值一致


def clear_snapshot_cache() -> None:
    """清空端点级快照缓存（测试隔离用）。"""
    with _CACHE_LOCK:
        _SNAPSHOT_CACHE.clear()


def compute_vwap(amount: Any, volume: Any) -> Optional[float]:
    """VWAP = amount / volume（均价口径）。

    缺 amount、缺 volume、volume<=0 或任一非有限数 → null。
    """
    if amount is None or volume is None:
        return None
    try:
        amt = float(amount)
        vol = float(volume)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amt) or not math.isfinite(vol) or vol <= 0:
        return None
    return amt / vol


def compute_moving_averages(closes: Sequence[Any]) -> Dict[str, Optional[float]]:
    """MA 严格全窗：最近 N 条有效收盘的均值；有效收盘不足 N 条 → null。

    None/NaN/Inf 等无效值不参与窗口计数（但也不截断序列语义——
    直接过滤后按有效序列取尾窗）。
    """
    values: List[float] = []
    for close in closes or []:
        try:
            value = float(close)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    result: Dict[str, Optional[float]] = {}
    for name, window in MA_WINDOWS.items():
        if len(values) >= window:
            result[name] = sum(values[-window:]) / window
        else:
            result[name] = None
    return result


def compute_bid_ask_ratio(
    buy_volumes: Sequence[Any], sell_volumes: Sequence[Any]
) -> Optional[float]:
    """委比(%) = (Σ委买量 − Σ委卖量) / (Σ委买量 + Σ委卖量) × 100。

    五档量全空/总和为 0 → null（盘口不可得，降级语义）。
    """
    def _total(values: Sequence[Any]) -> Tuple[float, bool]:
        total = 0.0
        has_value = False
        for value in values or []:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                total += number
                has_value = True
        return total, has_value

    buy_total, buy_present = _total(buy_volumes)
    sell_total, sell_present = _total(sell_volumes)
    if not (buy_present or sell_present):
        return None
    denominator = buy_total + sell_total
    if denominator <= 0:
        return None
    return (buy_total - sell_total) / denominator * 100.0


class QuoteSnapshotService:
    """装配 22 字段行情快照 + 数据质量元数据的只读服务。"""

    def __init__(
        self,
        manager: Optional[DataFetcherManager] = None,
        cache_ttl: Optional[int] = None,
    ) -> None:
        """
        Args:
            manager: DataFetcherManager（可注入；默认懒构造统一入口）
            cache_ttl: 显式覆盖缓存 TTL；None → 读 config.realtime_cache_ttl
        """
        self._manager = manager
        self._cache_ttl = cache_ttl

    # --------------------------------------------------
    # 公共入口
    # --------------------------------------------------
    def get_snapshot(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """返回快照 dict；行情源不可得（None）时返回 None（端点映射 404）。"""
        code = (stock_code or "").strip()
        ttl = self._effective_cache_ttl()
        cache_key = code.upper()
        if ttl > 0:
            with _CACHE_LOCK:
                entry = _SNAPSHOT_CACHE.get(cache_key)
                if entry is not None and entry[0] > time.time():
                    return dict(entry[1])

        snapshot = self._build_snapshot(code)
        if snapshot is None:
            return None
        if ttl > 0:
            with _CACHE_LOCK:
                _SNAPSHOT_CACHE[cache_key] = (time.time() + ttl, dict(snapshot))
        return dict(snapshot)

    def _effective_cache_ttl(self) -> int:
        if self._cache_ttl is not None:
            return int(self._cache_ttl)
        try:
            return int(getattr(get_config(), "realtime_cache_ttl", _DEFAULT_CACHE_TTL))
        except Exception:  # noqa: BLE001 - 配置不可用时退回默认 TTL
            return _DEFAULT_CACHE_TTL

    # --------------------------------------------------
    # 快照装配
    # --------------------------------------------------
    def _build_snapshot(self, code: str) -> Optional[Dict[str, Any]]:
        quote = self._get_manager().get_realtime_quote(code)
        if quote is None:
            return None

        missing: set = set(getattr(quote, "missing_fields", None) or [])

        snapshot: Dict[str, Any] = {
            "stock_code": getattr(quote, "code", None) or code,
            "stock_name": getattr(quote, "name", None) or None,
            # 数据质量元数据（随响应透出）
            "source": getattr(getattr(quote, "source", None), "value", None),
            "fetched_at": getattr(quote, "fetched_at", None),
            "provider_timestamp": getattr(quote, "provider_timestamp", None),
            "is_stale": getattr(quote, "is_stale", None),
            "stale_seconds": getattr(quote, "stale_seconds", None),
            "market": getattr(quote, "market", None),
            "currency": getattr(quote, "currency", None),
            "data_quality": getattr(quote, "data_quality", None),
            "fallback_from": getattr(quote, "fallback_from", None),
        }

        # 直出 15（缺失记入 missing_fields）
        for field in DIRECT_QUOTE_FIELDS:
            value = getattr(quote, field, None)
            snapshot[field] = value
            if value is None:
                missing.add(field)

        # 派生：VWAP（均价口径）
        vwap = compute_vwap(snapshot["amount"], snapshot["volume"])
        snapshot["vwap"] = vwap
        if vwap is None:
            missing.add("vwap")

        # 派生：委比（仅 A 股股票身份探五档盘口；指数形态/其余市场直接 null）
        # 盘口探针使用规范化后的裸 6 位代码，但行情/历史/缓存键保留原始入参
        # （PR #2492 blocker A：sh000016/000016.SH 是指数身份，绝不能剥成裸码
        # 去探同码股票的盘口）
        bid_ask_ratio: Optional[float] = None
        order_book_code = self._a_share_order_book_code(code)
        if order_book_code is not None:
            order_book = self._fetch_order_book(order_book_code)
            if order_book is not None:
                bid_ask_ratio = compute_bid_ask_ratio(
                    order_book.get("buy_volumes"), order_book.get("sell_volumes")
                )
        snapshot["bid_ask_ratio"] = bid_ask_ratio
        if bid_ask_ratio is None:
            missing.add("bid_ask_ratio")

        # 派生：成交笔数——探针实证 akshare em 标准接口（stock_zh_a_spot_em /
        # stock_bid_ask_em）均无笔数字段（L2 专属）→ 恒 null + missing_fields
        snapshot["trade_count"] = None
        missing.add("trade_count")

        # MA 4 档（历史日线严格全窗）
        moving_averages = compute_moving_averages(self._load_closes(code))
        snapshot.update(moving_averages)
        for name, value in moving_averages.items():
            if value is None:
                missing.add(name)

        snapshot["missing_fields"] = sorted(missing)
        return snapshot

    # --------------------------------------------------
    # 数据入口（全部只读）
    # --------------------------------------------------
    def _get_manager(self) -> DataFetcherManager:
        if self._manager is None:
            self._manager = DataFetcherManager()
        return self._manager

    def _load_closes(self, code: str) -> List[Any]:
        """历史日线收盘序列；取数失败返回 []（MA 全档降级 null，不硬失败）。"""
        try:
            frame, _source_name = self._get_manager().get_daily_data(
                code, days=MA_HISTORY_DAYS
            )
        except Exception as exc:  # noqa: BLE001 - 历史源全挂时 MA 降级
            logger.warning("[行情快照] %s 日线取数失败，MA 全档降级: %s", code, exc)
            return []
        if frame is None:
            return []
        column = frame.get("close") if hasattr(frame, "get") else None
        if column is None:
            return []
        return list(column.tolist())

    def _a_share_order_book_code(self, code: str) -> Optional[str]:
        """返回可探盘口的裸 6 位 A 股代码；非 A 股股票身份返回 None。

        身份判定走 parse_analysis_target（与 DataFetcherManager 同一契约）：
        - 裸 000016（股票）→ 可探；sh000016 / 000016.SH（指数）→ 不探；
        - 600519.SH 等后缀形态归一为裸 600519 后可探（委比不因后缀形态丢失）。
        """
        try:
            target = parse_analysis_target(code)
        except Exception:  # noqa: BLE001 - 身份解析失败按不可探处理
            return None
        if getattr(target, "asset_type", None) != ParseStatus.STOCK:
            return None
        normalized = normalize_stock_code(code)
        if _A_SHARE_CODE_RE.match(normalized):
            return normalized
        return None

    def _fetch_order_book(self, code: str) -> Optional[Dict[str, List[Optional[float]]]]:
        """A 股五档盘口（委比派生输入）；不可得返回 None（降级 null 语义）。"""
        try:
            fetcher = AkshareFetcher()
            return fetcher.get_a_share_order_book(code)
        except Exception as exc:  # noqa: BLE001 - 盘口源挂时委比降级
            logger.warning("[行情快照] %s 盘口取数不可用，委比降级 null: %s", code, exc)
            return None
