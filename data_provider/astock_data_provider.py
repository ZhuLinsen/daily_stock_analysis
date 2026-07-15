# -*- coding: utf-8 -*-
"""
===================================
A-Stock Data Provider (from a-stock-data)
===================================

集成 simonlin1212/a-stock-data 的关键数据函数，
提供龙虎榜、融资融券、大宗交易、
股东户数、资金流、概念板块等补充数据。

数据源优先级：东财独有数据（限流防封）

改进项（相比 a-stock-data 原版）：
- _normalize_code() 支持点号前缀（SH.600519、SZ.000001、BJ.920748）
- em_get() 使用 threading.Lock 保证线程安全节流
- dragon_tiger_board() 无记录时不返回零值 institution
"""

import logging
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ── 东财防封：全局节流 + 会话复用 ────────────────────────────────────
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    _em_adapter = HTTPAdapter(max_retries=Retry(
        total=3, connect=3, backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]))
    EM_SESSION.mount("https://", _em_adapter)
    EM_SESSION.mount("http://", _em_adapter)
except Exception as e:
    logger.debug("[AStockData] HTTPAdapter 配置失败，使用默认 adapter: %s", e)

EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]
_em_lock = threading.Lock()


def em_get(url: str, params: dict = None, headers: dict = None,
           timeout: int = 15, **kwargs) -> requests.Response:
    """东财统一请求入口：线程安全节流 + 复用 session + 默认 UA。"""
    with _em_lock:
        wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
        if wait > 0:
            time.sleep(wait + random.uniform(0.1, 0.5))
        try:
            resp = EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
            return resp
        finally:
            _em_last_call[0] = time.time()


def eastmoney_datacenter(report_name: str, columns: str = "ALL",
                         filter_str: str = "", page_size: int = 50,
                         sort_columns: str = "", sort_types: str = "-1",
                         timeout: int = 15) -> List[Dict]:
    """东财数据中心统一查询 — 龙虎榜/解禁/融资融券/大宗交易/股东户数/分红 共用。"""
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    try:
        r = em_get(DATACENTER_URL, params=params, timeout=timeout)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        logger.warning("[AStockData] datacenter 请求失败 reportName=%s: %s", report_name, e)
        return []
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


# ── 代码标准化 ───────────────────────────────────────────────────────

def _normalize_code(code: str) -> str:
    """标准化股票代码，支持多种格式。

    支持格式：
    - '600519'      -> '600519'   (already clean)
    - 'SH600519'    -> '600519'   (strip SH prefix)
    - 'SH.600519'   -> '600519'   (strip SH. prefix)
    - 'SZ000001'    -> '000001'   (strip SZ prefix)
    - 'SZ.000001'   -> '000001'   (strip SZ. prefix)
    - 'BJ920748'    -> '920748'   (strip BJ prefix)
    - 'BJ.920748'   -> '920748'   (strip BJ. prefix)
    - '600519.SH'   -> '600519'   (strip .SH suffix)
    - '000001.SZ'   -> '000001'   (strip .SZ suffix)
    - '920748.BJ'   -> '920748'   (strip .BJ suffix)
    """
    c = code.strip().upper()

    # Strip dotted prefix (SH.600519 -> 600519)
    for prefix in ("SH.", "SZ.", "SS.", "BJ."):
        if c.startswith(prefix):
            candidate = c[len(prefix):]
            if candidate.isdigit() and len(candidate) in (5, 6):
                return candidate

    # Strip non-dotted prefix (SH600519 -> 600519)
    for prefix in ("SH", "SZ", "SS", "BJ"):
        if c.startswith(prefix) and not c.startswith(prefix + "."):
            candidate = c[len(prefix):]
            if candidate.isdigit() and len(candidate) in (5, 6):
                return candidate

    # Strip suffix (600519.SH -> 600519)
    for suffix in (".SH", ".SZ", ".BJ", ".SS"):
        if c.endswith(suffix):
            candidate = c[:-len(suffix)]
            if candidate.isdigit() and len(candidate) in (5, 6):
                return candidate

    return c


# ── 数据函数 ─────────────────────────────────────────────────────────

def dragon_tiger_board(code: str, trade_date: str, look_back: int = 30) -> Dict[str, Any]:
    """
    龙虎榜数据聚合。
    trade_date: YYYY-MM-DD
    返回: {records: [...], seats: {buy: [...], sell: [...]}, institution: {...}}
    """
    code = _normalize_code(code)
    start = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)
    start_str = start.strftime("%Y-%m-%d")

    records = []
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{start_str}')(TRADE_DATE<='{trade_date}')(SECURITY_CODE=\"{code}\")",
        page_size=50,
        sort_columns="TRADE_DATE", sort_types="-1",
    )
    for row in data:
        records.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "reason": row.get("EXPLANATION", ""),
            "net_buy": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            "turnover": round(float(row.get("TURNOVERRATE") or 0), 2),
        })

    seats = {"buy": [], "sell": []}
    buy_data = []
    sell_data = []
    if records:
        latest_date = records[0]["date"]
        buy_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSBUY",
            filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
            page_size=10,
            sort_columns="BUY", sort_types="-1",
        )
        for row in buy_data[:5]:
            seats["buy"].append({
                "name": row.get("OPERATEDEPT_NAME", ""),
                "buy_amt": round((row.get("BUY") or 0) / 10000, 1),
                "sell_amt": round((row.get("SELL") or 0) / 10000, 1),
                "net": round((row.get("NET") or 0) / 10000, 1),
            })
        sell_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSSELL",
            filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
            page_size=10,
            sort_columns="SELL", sort_types="-1",
        )
        for row in sell_data[:5]:
            seats["sell"].append({
                "name": row.get("OPERATEDEPT_NAME", ""),
                "buy_amt": round((row.get("BUY") or 0) / 10000, 1),
                "sell_amt": round((row.get("SELL") or 0) / 10000, 1),
                "net": round((row.get("NET") or 0) / 10000, 1),
            })

    # 机构席位：仅在有实际数据时计算，避免无龙虎榜记录时渲染零值
    institution = None
    if buy_data or sell_data:
        inst = {"buy_amt": 0, "sell_amt": 0, "net_amt": 0}
        for detail_data, side in [(buy_data, "buy"), (sell_data, "sell")]:
            for row in detail_data:
                if str(row.get("OPERATEDEPT_CODE", "")) == "0":
                    amt = (row.get("BUY") or 0) if side == "buy" else (row.get("SELL") or 0)
                    if side == "buy":
                        inst["buy_amt"] += amt
                    else:
                        inst["sell_amt"] += amt
        inst["buy_amt"] = round(inst["buy_amt"] / 10000, 1)
        inst["sell_amt"] = round(inst["sell_amt"] / 10000, 1)
        inst["net_amt"] = round(inst["buy_amt"] - inst["sell_amt"], 1)
        institution = inst

    return {"records": records, "seats": seats, "institution": institution}


def margin_trading(code: str, page_size: int = 30) -> List[Dict]:
    """
    融资融券明细（日级）。
    返回: [{date, rzye, rzmre, rzche, rqye, rqmcl, rqchl, rzrqye}]
    """
    code = _normalize_code(code)
    data = eastmoney_datacenter(
        "RPTA_WEB_RZRQ_GGMX",
        filter_str=f'(SCODE="{code}")',
        page_size=page_size,
        sort_columns="DATE", sort_types="-1",
    )
    rows = []
    for row in data:
        rows.append({
            "date": str(row.get("DATE", ""))[:10],
            "rzye": row.get("RZYE", 0),
            "rzmre": row.get("RZMRE", 0),
            "rzche": row.get("RZCHE", 0),
            "rqye": row.get("RQYE", 0),
            "rqmcl": row.get("RQMCL", 0),
            "rqchl": row.get("RQCHL", 0),
            "rzrqye": row.get("RZRQYE", 0),
        })
    return rows


def block_trade(code: str, page_size: int = 20) -> List[Dict]:
    """
    大宗交易记录。
    返回: [{date, price, close, premium_pct, vol, amount, buyer, seller}]
    """
    code = _normalize_code(code)
    data = eastmoney_datacenter(
        "RPT_DATA_BLOCKTRADE",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size,
        sort_columns="TRADE_DATE", sort_types="-1",
    )
    rows = []
    for row in data:
        close = row.get("CLOSE_PRICE") or 0
        deal_price = row.get("DEAL_PRICE") or 0
        premium = ((deal_price / close - 1) * 100) if close else 0
        rows.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "price": deal_price,
            "close": close,
            "premium_pct": round(premium, 2),
            "vol": row.get("DEAL_VOLUME", 0),
            "amount": row.get("DEAL_AMT", 0),
            "buyer": row.get("BUYER_NAME", ""),
            "seller": row.get("SELLER_NAME", ""),
        })
    return rows


def holder_num_change(code: str, page_size: int = 10) -> List[Dict]:
    """
    股东户数变化（季度级）。
    返回: [{date, holder_num, change_num, change_ratio, avg_shares}]
    """
    code = _normalize_code(code)
    data = eastmoney_datacenter(
        "RPT_HOLDERNUMLATEST",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size,
        sort_columns="END_DATE", sort_types="-1",
    )
    rows = []
    for row in data:
        rows.append({
            "date": str(row.get("END_DATE", ""))[:10],
            "holder_num": row.get("HOLDER_NUM", 0),
            "change_num": row.get("HOLDER_NUM_CHANGE", 0),
            "change_ratio": row.get("HOLDER_NUM_RATIO", 0),
            "avg_shares": row.get("AVG_FREE_SHARES", 0),
        })
    return rows


def stock_fund_flow_120d(code: str) -> List[Dict]:
    """
    个股资金流（日级，最近120个交易日）。
    返回: [{date, main_net, small_net, mid_net, large_net, super_net}]
    单位: 元
    """
    code = _normalize_code(code)
    market_code = 1 if code.startswith("6") else 0
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": f"{market_code}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "lmt": "120",
    }
    headers = {
        "User-Agent": UA,
        "Referer": "https://quote.eastmoney.com/",
        "Origin": "https://quote.eastmoney.com",
    }
    try:
        r = em_get(url, params=params, headers=headers, timeout=15)
        d = r.json()
    except Exception as e:
        logger.warning("[AStockData] push2 资金流请求失败: %s", e)
        return []
    klines = d.get("data", {}).get("klines", [])

    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 7:
            rows.append({
                "date": parts[0],
                "main_net": float(parts[1]) if parts[1] != "-" else 0,
                "small_net": float(parts[2]) if parts[2] != "-" else 0,
                "mid_net": float(parts[3]) if parts[3] != "-" else 0,
                "large_net": float(parts[4]) if parts[4] != "-" else 0,
                "super_net": float(parts[5]) if parts[5] != "-" else 0,
            })
    return rows


def eastmoney_concept_blocks(code: str) -> Dict[str, Any]:
    """
    个股所属板块/概念归属（东财 slist）。
    返回: {total, boards: [{name, code, change_pct, lead_stock}], concept_tags: [...]}
    """
    code = _normalize_code(code)
    market_code = 1 if code.startswith("6") else 0
    params = {
        "fltt": "2", "invt": "2",
        "secid": f"{market_code}.{code}",
        "spt": "3", "pi": "0", "pz": "200", "po": "1",
        "fields": "f12,f14,f3,f128",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get("https://push2.eastmoney.com/api/qt/slist/get",
                   params=params, headers=headers, timeout=15)
        d = r.json()
    except Exception as e:
        logger.warning("[AStockData] 东财板块归属请求失败: %s", e)
        return {"total": 0, "boards": [], "concept_tags": []}

    diff = (d.get("data") or {}).get("diff") or {}
    items = diff.values() if isinstance(diff, dict) else diff
    boards = []
    for it in items:
        boards.append({
            "name": it.get("f14", ""),
            "code": it.get("f12", ""),
            "change_pct": it.get("f3", ""),
            "lead_stock": it.get("f128", ""),
        })
    return {
        "total": len(boards),
        "boards": boards,
        "concept_tags": [b["name"] for b in boards],
    }


# ── 统一入口类 ───────────────────────────────────────────────────────

class AstockDataProvider:
    """
    A-Stock Data Provider 统一入口。

    提供补充数据维度：
    - 龙虎榜（机构/游资动向）
    - 融资融券（杠杆资金）
    - 大宗交易（机构大宗减持/增持）
    - 股东户数变化（筹码集中度）
    - 个股资金流120日（主力/散户资金流向）
    - 概念板块归属（题材归因）

    所有东财接口已内置线程安全限流防封（em_get）。
    """

    name = "AstockDataProvider"

    @staticmethod
    def get_dragon_tiger(code: str, trade_date: str = None, look_back: int = 30) -> Optional[Dict]:
        """获取龙虎榜数据。trade_date 默认今天。"""
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y-%m-%d")
        try:
            return dragon_tiger_board(code, trade_date, look_back)
        except Exception as e:
            logger.warning("[AStockData] 龙虎榜获取失败 %s: %s", code, e)
            return None

    @staticmethod
    def get_margin_trading(code: str, page_size: int = 30) -> Optional[List]:
        """获取融资融券数据。"""
        try:
            return margin_trading(code, page_size)
        except Exception as e:
            logger.warning("[AStockData] 融资融券获取失败 %s: %s", code, e)
            return None

    @staticmethod
    def get_block_trade(code: str, page_size: int = 20) -> Optional[List]:
        """获取大宗交易数据。"""
        try:
            return block_trade(code, page_size)
        except Exception as e:
            logger.warning("[AStockData] 大宗交易获取失败 %s: %s", code, e)
            return None

    @staticmethod
    def get_holder_change(code: str, page_size: int = 10) -> Optional[List]:
        """获取股东户数变化。"""
        try:
            return holder_num_change(code, page_size)
        except Exception as e:
            logger.warning("[AStockData] 股东户数获取失败 %s: %s", code, e)
            return None

    @staticmethod
    def get_fund_flow(code: str) -> Optional[List]:
        """获取个股资金流120日。"""
        try:
            return stock_fund_flow_120d(code)
        except Exception as e:
            logger.warning("[AStockData] 资金流获取失败 %s: %s", code, e)
            return None

    @staticmethod
    def get_concept_blocks(code: str) -> Optional[Dict]:
        """获取概念板块归属。"""
        try:
            return eastmoney_concept_blocks(code)
        except Exception as e:
            logger.warning("[AStockData] 概念板块获取失败 %s: %s", code, e)
            return None

    def get_supplementary_data(self, code: str, trade_date: str = None) -> Dict[str, Any]:
        """
        一次性获取某只股票的所有补充数据。

        返回 dict，每个 key 对应一类数据，获取失败的 key 值为 None。
        """
        return {
            "dragon_tiger": self.get_dragon_tiger(code, trade_date),
            "margin_trading": self.get_margin_trading(code),
            "block_trade": self.get_block_trade(code),
            "holder_change": self.get_holder_change(code),
            "fund_flow": self.get_fund_flow(code),
            "concept_blocks": self.get_concept_blocks(code),
        }
