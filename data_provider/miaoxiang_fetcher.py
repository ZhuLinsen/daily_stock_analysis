"""
妙想(MiaoXiang)金融数据源 — 东方财富妙想 Skills MX_API 封装

定位：
    补齐公开行情接口不稳定时的垂直数据块（个股资金流 / 筹码分布），
    不参与日线 K 线主链路（`_DAILY_MARKET_FETCHER_SUPPORT` 中支持市场为空集）。

数据来源：
    妙想量化 API（MX_API），自然语言查询返回结构化表格：
    POST https://mkapi2.dfcfs.com/finskillshub/api/claw/query
    Header: apikey: <MX_APIKEY>
    Body:   {"toolQuery": "<自然语言查询>"}

启用条件：
    配置 MX_APIKEY 后由 DataFetcherManager 自动实例化。
"""

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

from .base import BaseFetcher, DataFetchError, normalize_stock_code
from .realtime_types import ChipDistribution

logger = logging.getLogger(__name__)

# 妙想 API 基础地址（国内直连）
MX_API_BASE_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"

# 查询结果缓存 TTL（秒）：同一股票的资金流/筹码短期内复用，降低配额消耗
MX_CACHE_TTL_SECONDS = 300.0
# 相邻请求最小间隔（秒）：对自然语言接口保持礼貌
MX_MIN_REQUEST_INTERVAL_SECONDS = 0.3


def _is_hk_code(stock_code: str) -> bool:
    return bool(re.match(r"^(hk|HK)?\d{5}$", stock_code.strip())) or stock_code.strip().lower().startswith("hk")


def _is_us_code(stock_code: str) -> bool:
    return bool(re.match(r"^[A-Za-z]{1,6}(\.[A-Za-z]+)?$", stock_code.strip()))


def _is_etf_code(stock_code: str) -> bool:
    # 与 akshare_fetcher 语义一致：常见 ETF/指数代码段
    return bool(re.match(r"^(sh|sz|bj)?(51|56|58|15|16|13|159|510|511|512|513|515|516|517|518|588)\d{3,4}$", stock_code.strip().lower()))


def _parse_number(text: Any) -> Optional[float]:
    """从 '13.91' / '13.91元' / '-1.5' 等文本中提取数值。"""
    if text is None:
        return None
    s = str(text).strip().replace(",", "")
    m = re.search(r"(-?\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def _parse_money_yuan(text: Any) -> Optional[float]:
    """把 '-93.64万元' / '1.2亿' / '-493.5万' 解析为元的浮点数。"""
    if text is None:
        return None
    s = str(text).strip().replace(",", "")
    val = _parse_number(s)
    if val is None:
        return None
    if "亿" in s:
        val *= 1e8
    elif "万" in s:
        val *= 1e4
    return val


def _parse_ratio(text: Any) -> Optional[float]:
    """把 '83.24%' 解析为 0.8324；'0.83' 视为已是小数。"""
    val = _parse_number(text)
    if val is None:
        return None
    if "%" in str(text or ""):
        val = val / 100.0
    if val > 1.0:
        # 兜底：个别查询可能返回 83.24 但不带 % 号
        val = val / 100.0
    return val


class MiaoxiangFetcher(BaseFetcher):
    """妙想金融数据源（资金流 / 筹码分布补充源）"""

    name = "MiaoxiangFetcher"

    def __init__(
        self,
        api_key: str = "",
        priority: int = 6,
        timeout: int = 30,
        base_url: str = MX_API_BASE_URL,
        cache_ttl: float = MX_CACHE_TTL_SECONDS,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.priority = int(priority)
        self.timeout = int(timeout)
        self.base_url = base_url.rstrip("/")
        self._cache_ttl = float(cache_ttl)
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._cache_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._last_request_ts = 0.0

    # ------------------------------------------------------------------
    # MX_API 客户端
    # ------------------------------------------------------------------

    def _query_tables(self, cache_key: str, tool_query: str) -> List[Dict[str, Any]]:
        """执行一次自然语言查询，返回 dataTableDTOList（带 TTL 缓存）。"""
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and (time.time() - cached[0]) < self._cache_ttl:
                return cached[1]

        with self._request_lock:
            wait = MX_MIN_REQUEST_INTERVAL_SECONDS - (time.time() - self._last_request_ts)
            if wait > 0:
                time.sleep(wait)
            try:
                response = requests.post(
                    self.base_url,
                    headers={"apikey": self.api_key, "Content-Type": "application/json"},
                    json={"toolQuery": tool_query},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
            except requests.RequestException as exc:
                raise DataFetchError(f"妙想 API 请求失败: {exc}") from exc
            finally:
                self._last_request_ts = time.time()

        if payload.get("status") != 0:
            message = str(payload.get("message", ""))[:120]
            raise DataFetchError(f"妙想 API 返回错误: status={payload.get('status')} {message}")

        tables = (
            payload.get("data", {})
            .get("data", {})
            .get("searchDataResultDTO", {})
            .get("dataTableDTOList", [])
        )
        tables = [t for t in tables if isinstance(t, dict)] if isinstance(tables, list) else []
        if not tables:
            raise DataFetchError("妙想 API 未返回数据表格")

        with self._cache_lock:
            self._cache[cache_key] = (time.time(), tables)
        return tables

    @staticmethod
    def _table_rows(table_dto: Dict[str, Any]) -> List[Dict[str, str]]:
        """把 MX 表格（headName 为行轴 + 指标列数组）转为 [{label: value}] 行列表。"""
        table = table_dto.get("table") or {}
        name_map = table_dto.get("nameMap") or {}
        if isinstance(name_map, list):
            name_map = {str(i): v for i, v in enumerate(name_map)}
        heads = table.get("headName") or []
        rows: List[Dict[str, str]] = []
        for key, values in table.items():
            if key == "headName" or not isinstance(values, list):
                continue
            label = str(name_map.get(key, name_map.get(str(key), key)))
            for idx, value in enumerate(values):
                while len(rows) <= idx:
                    rows.append({})
                rows[idx][label] = "" if value is None else str(value)
        # 保留每行对应日期（headName），便于资金流按日聚合
        for idx, head in enumerate(heads):
            if idx < len(rows):
                rows[idx]["_date"] = str(head)
        return rows

    def _table_labels(self, table_dto: Dict[str, Any]) -> List[str]:
        """返回表格包含的全部指标名（经 nameMap 映射）。"""
        table = table_dto.get("table") or {}
        name_map = table_dto.get("nameMap") or {}
        labels: List[str] = []
        for key in table:
            if key == "headName":
                continue
            labels.append(str(name_map.get(key, name_map.get(str(key), key))))
        return labels

    def _find_table_by_label(self, tables: List[Dict[str, Any]], keyword: str) -> Optional[Dict[str, Any]]:
        """返回包含指定指标名的表格；命中多张时优先行数最多的（时间序列优先于当前快照）。"""
        best: Optional[Dict[str, Any]] = None
        best_rows = -1
        for table_dto in tables:
            if not any(keyword in label for label in self._table_labels(table_dto)):
                continue
            rows = len((table_dto.get("table") or {}).get("headName") or [])
            if rows > best_rows:
                best = table_dto
                best_rows = rows
        return best

    def _find_table_by_label_score(
        self,
        tables: List[Dict[str, Any]],
        required_keyword: str,
        wanted_keywords: List[str],
    ) -> Optional[Dict[str, Any]]:
        """自然语言返回的表格组合不稳定：按"目标字段命中数"评分选表，行数少者优先（快照优于序列）。"""
        best: Optional[Dict[str, Any]] = None
        best_key = (-1, 10**9)
        for table_dto in tables:
            labels = self._table_labels(table_dto)
            if not any(required_keyword in label for label in labels):
                continue
            score = sum(1 for kw in wanted_keywords if any(kw in label for label in labels))
            rows = len((table_dto.get("table") or {}).get("headName") or [])
            if (score, -rows) > best_key:
                best = table_dto
                best_key = (score, -rows)
        return best

    # ------------------------------------------------------------------
    # 筹码分布
    # ------------------------------------------------------------------

    def get_chip_distribution(self, stock_code: str) -> Optional[ChipDistribution]:
        """
        通过妙想 API 获取筹码分布核心指标：
        获利比例 / 平均成本 / 90%集中度 / 70%集中度。

        Returns:
            ChipDistribution（source=miaoxiang），失败抛 DataFetchError。
        """
        stock_code = normalize_stock_code(stock_code)
        if _is_us_code(stock_code) or _is_hk_code(stock_code) or _is_etf_code(stock_code):
            logger.debug(f"[API跳过] {stock_code} 非A股个股，无筹码分布数据")
            return None

        tables = self._query_tables(
            f"chip:{stock_code}",
            f"{stock_code} 获利比例 平均成本 90%筹码集中度 70%筹码集中度",
        )
        target = self._find_table_by_label_score(
            tables,
            required_keyword="平均成本",
            wanted_keywords=["获利比例", "90%筹码集中度", "70%筹码集中度"],
        )
        if target is None:
            target = self._find_table_by_label(tables, "筹码")
        if target is None:
            raise DataFetchError("妙想 API 筹码分布返回缺少可用表格")

        rows = self._table_rows(target)
        if not rows:
            raise DataFetchError("妙想 API 筹码分布表格为空")
        row = rows[0]

        avg_cost = _parse_number(row.get("平均成本"))
        profit_ratio = _parse_ratio(row.get("获利比例"))
        concentration_90 = _parse_ratio(row.get("90%筹码集中度"))
        concentration_70 = _parse_ratio(row.get("70%筹码集中度"))

        if avg_cost is None or avg_cost <= 0:
            raise DataFetchError(f"妙想 API 筹码分布平均成本无效: {row}")

        chip = ChipDistribution(
            code=stock_code,
            date=str(row.get("_date", "")).split(" ")[0],
            source="miaoxiang",
        )
        chip.avg_cost = float(avg_cost)
        if profit_ratio is not None:
            chip.profit_ratio = float(profit_ratio)
        if concentration_90 is not None:
            chip.concentration_90 = float(concentration_90)
        if concentration_70 is not None:
            chip.concentration_70 = float(concentration_70)
        return chip

    # ------------------------------------------------------------------
    # 个股资金流
    # ------------------------------------------------------------------

    def get_capital_flow(self, stock_code: str, top_n: int = 5) -> Dict[str, Any]:
        """
        通过妙想 API 获取个股主力资金流：
        今日主力净流入 + 近5日/近10日主力净流入合计。

        Returns:
            与 AkshareFundamentalAdapter.get_capital_flow 同构的 payload。
        """
        result: Dict[str, Any] = {
            "status": "not_supported",
            "stock_flow": {},
            "sector_rankings": {"top": [], "bottom": []},
            "source_chain": [],
            "errors": [],
        }
        stock_code = normalize_stock_code(stock_code)
        if _is_us_code(stock_code) or _is_hk_code(stock_code) or _is_etf_code(stock_code):
            return result

        try:
            tables = self._query_tables(
                f"flow:{stock_code}",
                f"{stock_code} 近10日每日主力净流入资金",
            )
        except DataFetchError as exc:
            result["errors"].append(f"miaoxiang: {exc}")
            return result
        target = self._find_table_by_label(tables, "主力净流入")
        if target is None:
            result["errors"].append("miaoxiang: no capital flow table")
            return result

        rows = self._table_rows(target)
        series: List[Tuple[str, float]] = []
        for row in rows:
            label = next((k for k in row if k != "_date"), None)
            if label is None:
                continue
            value = _parse_money_yuan(row.get(label))
            if value is not None:
                series.append((str(row.get("_date", "")), value))

        if not series:
            result["errors"].append("miaoxiang: empty capital flow series")
            return result

        # headName 通常按日期倒序（最新在前），这里显式按日期排序保证聚合正确
        series.sort(key=lambda item: item[0], reverse=True)
        latest = series[0][1]
        inflow_5d = sum(v for _, v in series[:5]) if len(series) >= 2 else None
        inflow_10d = sum(v for _, v in series[:10]) if len(series) >= 6 else None

        result["stock_flow"] = {
            "main_net_inflow": latest,
            "inflow_5d": inflow_5d,
            "inflow_10d": inflow_10d,
        }
        result["status"] = "partial"
        result["source_chain"].append("miaoxiang:capital_flow")
        return result

    # ------------------------------------------------------------------
    # 日线主链路：显式不支持（快速失败，避免占用降级链时间）
    # ------------------------------------------------------------------

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise DataFetchError("MiaoxiangFetcher 不提供日线行情数据（专用补充数据源）")

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        raise DataFetchError("MiaoxiangFetcher 不提供日线行情数据（专用补充数据源）")
