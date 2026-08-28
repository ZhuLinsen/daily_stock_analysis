# -*- coding: utf-8 -*-
"""Market temperature (恐惧贪婪指数) service.

将多个市场宽度/资金/情绪子指标合成为一个 0-100 的"温度"，0 表示极度恐惧，
100 表示极度贪婪。既接受外部快照输入，也能基于本地自选股日线数据兜底计算。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import select

from src.repositories.market_temperature_repo import MarketTemperatureRepository
from src.services.portfolio_service import VALID_MARKETS
from src.storage import DatabaseManager, StockDaily

logger = logging.getLogger(__name__)

# 各子指标权重（缺失维度会按权重归一化）
_DIMENSION_WEIGHTS: Dict[str, float] = {
    "breadth": 0.25,      # 涨跌家数比
    "limit": 0.20,        # 涨跌停家数比
    "high_low": 0.20,     # 52 周新高/新低比
    "northbound": 0.10,   # 北向资金净流入
    "margin": 0.10,       # 两融余额变化
    "turnover": 0.05,     # 换手率
    "index": 0.10,        # 指数涨跌
}

_DIMENSION_NAMES_ZH = {
    "breadth": "市场宽度",
    "limit": "涨跌停比",
    "high_low": "新高新低比",
    "northbound": "北向资金",
    "margin": "两融余额",
    "turnover": "换手率",
    "index": "指数涨跌",
}

# 归一化参考刻度（可文档化，非硬编码业务逻辑）
_NORTHBOUND_SCALE_CNY_YI = 100.0  # 北向净流入 100 亿 -> 满分档
_MARGIN_SCALE_PCT = 10.0          # 两融余额单日变化 10% -> 满分档
_TURNOVER_SCALE_PCT = 10.0        # 换手率 10% -> 满分档
_INDEX_SCALE_PCT = 10.0           # 指数单日 10% -> 满分档

LABEL_BANDS = (
    (80, 100, "extreme_greed", "极度贪婪"),
    (60, 80, "greed", "贪婪"),
    (40, 60, "neutral", "中性"),
    (20, 40, "fear", "恐惧"),
    (0, 20, "extreme_fear", "极度恐惧"),
)

GUIDANCE_BY_LABEL = {
    "extreme_greed": "市场情绪过热，追高风险显著上升；大师通常会在别人贪婪时保持警惕，考虑降低暴露或收紧止损。",
    "greed": "情绪偏暖但尚未极端；顺势参与时仍需严守买点纪律，避免在乖离过大时追入。",
    "neutral": "多空相对均衡，方向不明朗；适合轻仓观察，等待更明确的趋势或支撑确认。",
    "fear": "市场偏谨慎，优质标的有望出现更好的风险收益比；可分批布局但保留现金应对进一步下探。",
    "extreme_fear": "情绪极度悲观，往往是中长期布局窗口；大师会在别人恐惧时开始贪婪，但仍需控制单次风险。",
}


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def label_for_score(score: int) -> Tuple[str, str]:
    for low, high, key, name in LABEL_BANDS:
        if low <= score <= high:
            return key, name
    return "neutral", "中性"


def _ratio_score(numerator: float, denominator: float) -> Optional[float]:
    if denominator <= 0:
        return None
    return clamp(numerator / denominator * 100.0)


def _midpoint_score(delta: float, scale: float) -> float:
    return clamp(50.0 + (delta / scale) * 50.0)


def compute_temperature(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Pure computation: breadth snapshot -> temperature dict.

    All sub-metrics are optional; missing ones are excluded and weights
    renormalised over the available dimensions.
    """
    dimensions: List[Dict[str, Any]] = []
    weighted_sum = 0.0
    weight_sum = 0.0

    def _add(key: str, score: Optional[float]) -> None:
        nonlocal weighted_sum, weight_sum
        if score is None:
            return
        score = clamp(score)
        weight = _DIMENSION_WEIGHTS[key]
        dimensions.append({
            "key": key,
            "name": _DIMENSION_NAMES_ZH[key],
            "score": round(score),
            "available": True,
        })
        weighted_sum += score * weight
        weight_sum += weight

    adv = _to_float(snapshot.get("advancers"))
    dec = _to_float(snapshot.get("decliners"))
    _add("breadth", _ratio_score(adv, adv + dec) if adv is not None and dec is not None else None)

    lu = _to_float(snapshot.get("limit_up"))
    ld = _to_float(snapshot.get("limit_down"))
    _add("limit", _ratio_score(lu, lu + ld) if lu is not None and ld is not None else None)

    nh = _to_float(snapshot.get("new_high_52w"))
    nl = _to_float(snapshot.get("new_low_52w"))
    _add("high_low", _ratio_score(nh, nh + nl) if nh is not None and nl is not None else None)

    north = _to_float(snapshot.get("northbound_net"))
    _add("northbound", _midpoint_score(north, _NORTHBOUND_SCALE_CNY_YI) if north is not None else None)

    margin = _to_float(snapshot.get("margin_change_pct"))
    _add("margin", _midpoint_score(margin, _MARGIN_SCALE_PCT) if margin is not None else None)

    turnover = _to_float(snapshot.get("turnover_pct"))
    _add("turnover", _midpoint_score(turnover, _TURNOVER_SCALE_PCT) if turnover is not None else None)

    idx = _to_float(snapshot.get("index_pct_chg"))
    _add("index", _midpoint_score(idx, _INDEX_SCALE_PCT) if idx is not None else None)

    if weight_sum <= 0:
        score = 50
        label_key, label = "neutral", "中性"
        reasons = ["无有效输入维度，温度按中性 50 计。"]
    else:
        score = round(weighted_sum / weight_sum)
        label_key, label = label_for_score(score)
        reasons = _build_reasons(dimensions, score, label_key)

    return {
        "score": score,
        "label": label,
        "label_key": label_key,
        "dimensions": dimensions,
        "available_dimensions": len(dimensions),
        "reasons": reasons,
        "guidance": GUIDANCE_BY_LABEL[label_key],
    }


def _build_reasons(dimensions: List[Dict[str, Any]], score: int, label_key: str) -> List[str]:
    reasons: List[str] = []
    for dim in dimensions:
        key = dim["key"]
        s = dim["score"]
        if s >= 80:
            reasons.append(f"{dim['name']}处于高位（{s}），偏贪婪。")
        elif s <= 20:
            reasons.append(f"{dim['name']}处于低位（{s}），偏恐惧。")
    if not reasons:
        reasons.append("各维度均处于中性区间，情绪未明显极端。")
    reasons.append(f"综合温度 {score}，判定为「{GUIDANCE_BY_LABEL[label_key]}」对应的情绪区间。")
    return reasons


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_snapshot_from_overview(overview: Any) -> Dict[str, Any]:
    """从 MarketAnalyzer 的 MarketOverview 提取温度计算输入（宽度/涨跌停/指数）。

    提取不到任何有效维度时返回空 dict，由调用方决定如何降级。
    """
    snapshot: Dict[str, Any] = {}
    adv = _to_float(getattr(overview, "up_count", None))
    dec = _to_float(getattr(overview, "down_count", None))
    if adv is not None and dec is not None and adv + dec > 0:
        snapshot["advancers"] = adv
        snapshot["decliners"] = dec

    limit_up = _to_float(getattr(overview, "limit_up_count", None))
    limit_down = _to_float(getattr(overview, "limit_down_count", None))
    if limit_up is not None and limit_down is not None and limit_up + limit_down > 0:
        snapshot["limit_up"] = limit_up
        snapshot["limit_down"] = limit_down

    index_pct = MarketTemperatureService._pick_mood_index_pct(
        str(getattr(overview, "market", "") or "cn").strip().lower() or "cn",
        list(getattr(overview, "indices", None) or []),
    )
    if index_pct is not None:
        snapshot["index_pct_chg"] = index_pct
    return snapshot


class MarketTemperatureService:
    """Business logic for computing and persisting market temperature snapshots."""

    def __init__(
        self,
        repo: Optional[MarketTemperatureRepository] = None,
        db_manager: Optional[DatabaseManager] = None,
    ):
        self.repo = repo or MarketTemperatureRepository(db_manager)
        self.db = db_manager or getattr(self.repo, "db", None) or DatabaseManager.get_instance()

    def normalize_market(self, market: str) -> str:
        value = str(market or "").strip().lower()
        if value not in VALID_MARKETS:
            raise ValueError(f"market must be one of {sorted(VALID_MARKETS)}: {market}")
        return value

    def snapshot(self, market: str, snapshot: Dict[str, Any], trade_date: Optional[str] = None) -> Dict[str, Any]:
        market = self.normalize_market(market)
        result = compute_temperature(snapshot)
        resolved_date = trade_date or _today_str()
        self.repo.upsert({
            "market": market,
            "trade_date": resolved_date,
            "score": result["score"],
            "label": result["label"],
            "dimensions_json": json.dumps(result["dimensions"], ensure_ascii=False),
            "reasons_json": json.dumps(result["reasons"], ensure_ascii=False),
            "guidance": result["guidance"],
        })
        return {
            "market": market,
            "trade_date": resolved_date,
            "score": result["score"],
            "label": result["label"],
            "label_key": result["label_key"],
            "dimensions": result["dimensions"],
            "available_dimensions": result["available_dimensions"],
            "reasons": result["reasons"],
            "guidance": result["guidance"],
        }

    def latest(self, market: str) -> Optional[Dict[str, Any]]:
        market = self.normalize_market(market)
        row = self.repo.get_latest(market)
        return self._snapshot_to_dict(row) if row else None

    def history(self, market: Optional[str] = None, page: int = 1, page_size: int = 20) -> Tuple[List[Dict[str, Any]], int]:
        rows, total = self.repo.list(market=market, page=page, page_size=page_size)
        return [self._snapshot_to_dict(row) for row in rows], total

    # 具备实时全市场宽度数据源（涨跌家数/涨跌停家数）的市场，当前仅 A 股。
    PROVIDER_SUPPORTED_MARKETS = {"cn"}

    def compute_from_provider(
        self,
        market: str,
        overview_provider: Optional[Callable[[], Any]] = None,
    ) -> Dict[str, Any]:
        """Fetch realtime full-market breadth from the data provider and persist it.

        目前仅 A 股（cn）具备全市场涨跌家数/涨跌停数据源；其他市场请通过
        POST /market-temperature 提交宽度快照，或使用本地自选股兜底计算。
        """
        market = self.normalize_market(market)
        if market not in self.PROVIDER_SUPPORTED_MARKETS:
            raise ValueError(
                "realtime breadth data only supports market=cn; "
                "submit a snapshot or use the tracked-universe fallback for other markets"
            )

        if overview_provider is None:
            def _default_provider() -> Any:
                # 延迟导入，避免服务层与大盘分析器之间的循环依赖。
                from src.market_analyzer import MarketAnalyzer

                return MarketAnalyzer(region=market).get_market_overview()

            overview_provider = _default_provider

        try:
            overview = overview_provider()
        except Exception as exc:
            logger.error("market temperature provider fetch failed: %s", exc)
            raise ValueError("failed to fetch realtime market breadth from data provider") from exc

        snapshot = build_snapshot_from_overview(overview)

        if not snapshot:
            raise ValueError(
                "data provider returned no usable breadth metrics; "
                "retry later or use the tracked-universe fallback"
            )

        trade_date = str(getattr(overview, "date", "") or "").strip() or _today_str()
        result = self.snapshot(market, snapshot, trade_date=trade_date)
        result["source"] = "market_stats"
        return result

    @staticmethod
    def _pick_mood_index_pct(market: str, indices: List[Any]) -> Optional[float]:
        """优先取该市场的情绪指数涨跌幅，缺失时退回第一个有涨跌幅的指数。"""
        preferred_codes: set = set()
        try:
            from src.core.market_profile import get_profile

            preferred_codes.add(get_profile(market).mood_index_code)
        except Exception:  # profile 缺失时不做优先匹配
            preferred_codes = set()

        fallback: Optional[float] = None
        for index in indices:
            pct = _to_float(getattr(index, "change_pct", None))
            if pct is None:
                continue
            code = str(getattr(index, "code", "") or "")
            if code in preferred_codes:
                return pct
            if fallback is None:
                fallback = pct
        return fallback

    def compute_from_database(self, market: str, index_pct_chg: Optional[float] = None) -> Dict[str, Any]:
        """Breadth-only fallback computed from the local tracked universe.

        每只股票各取其最新一条日线（不同股票的数据日期可能不同步），
        避免所有股票共享 MAX(date) 时样本被压缩到少数同步更新的股票。
        计算结果会作为该市场当日快照落库。
        """
        market = self.normalize_market(market)
        latest_by_code: Dict[str, Tuple[str, Optional[float]]] = {}

        with self.db.get_session() as session:
            rows = session.execute(
                select(StockDaily.code, StockDaily.date, StockDaily.pct_chg)
            ).all()
            for code, trade_date, pct_chg in rows:
                date_str = str(trade_date)
                prev = latest_by_code.get(code)
                if prev is None or date_str > prev[0]:
                    latest_by_code[code] = (date_str, pct_chg)

        if not latest_by_code:
            raise ValueError("no daily data available to build market temperature")

        advancers = 0
        decliners = 0
        unchanged = 0
        for _, (_, pct) in latest_by_code.items():
            if pct is None:
                unchanged += 1
            elif pct > 0:
                advancers += 1
            elif pct < 0:
                decliners += 1
            else:
                unchanged += 1

        snapshot: Dict[str, Any] = {"advancers": advancers, "decliners": decliners}
        if index_pct_chg is not None:
            snapshot["index_pct_chg"] = index_pct_chg

        source_date = max(item[0] for item in latest_by_code.values())
        result = self.snapshot(market, snapshot, trade_date=source_date)
        result["source"] = "tracked_universe"
        universe_size = len(latest_by_code)
        result["reasons"] = list(result.get("reasons", [])) + [
            f"基于本地 {universe_size} 只自选股各自最新日线计算，样本远小于全市场，仅供参考。"
        ]
        return result

    def _snapshot_to_dict(self, row: Any) -> Dict[str, Any]:
        return {
            "id": row.id,
            "market": row.market,
            "trade_date": row.trade_date,
            "score": row.score,
            "label": row.label,
            "dimensions": _load_json(row.dimensions_json, []),
            "reasons": _load_json(row.reasons_json, []),
            "guidance": row.guidance,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


def _load_json(raw: Optional[str], default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def _today_str() -> str:
    from datetime import date
    return date.today().isoformat()
