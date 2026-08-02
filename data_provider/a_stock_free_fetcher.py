# -*- coding: utf-8 -*-
"""Zero-key A-share intelligence and fallback sources.

The implementation is adapted from the a-stock-data skill, but shaped as a
project-native provider instead of a copied script.  It focuses on sources that
add information not already covered by the daily K-line fetchers:

- CLS 7x24 telegraph news
- THS hot-stock reason tags
- CNINFO announcements with dynamic orgId lookup
- Sina fund-flow fallback
- SSE/SZSE official dragon-tiger fallback
- SZSE/Eastmoney announcement fallback
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import normalize_stock_code
from .free_source_http import (
    DEFAULT_USER_AGENT,
    FreeSourceError,
    FreeSourceHttpClient,
    default_free_source_client,
)

logger = logging.getLogger(__name__)


def _env_enabled(name: str, default: str = "true") -> bool:
    value = os.getenv(name, default)
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(str(value).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _cninfo_ts_to_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        numeric = int(value)
        if numeric > 10_000_000_000:
            numeric = numeric // 1000
        return datetime.fromtimestamp(numeric).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        text = str(value)
        return text[:10]


def _cls_sign(params: Dict[str, str]) -> str:
    query = "&".join(f"{key}={params[key]}" for key in sorted(params))
    return hashlib.md5(hashlib.sha1(query.encode("utf-8")).hexdigest().encode("utf-8")).hexdigest()


class AStockFreeFetcher:
    """Fetch selected free A-share intelligence sources with stable schemas."""

    name = "AStockFreeFetcher"

    def __init__(self, client: Optional[FreeSourceHttpClient] = None):
        self.client = client or default_free_source_client
        self.enabled = _env_enabled("FREE_A_STOCK_SOURCES_ENABLED", "true")
        self.cls_enabled = _env_enabled("CLS_TELEGRAPH_ENABLED", "true")
        self.ths_hot_enabled = _env_enabled("THS_HOT_REASON_ENABLED", "true")
        self.cninfo_enabled = _env_enabled("CNINFO_ANNOUNCEMENT_ENABLED", "true")
        self.sina_fund_flow_enabled = _env_enabled("SINA_FUND_FLOW_FALLBACK_ENABLED", "true")
        self.official_dragon_tiger_enabled = _env_enabled("OFFICIAL_DRAGON_TIGER_FALLBACK_ENABLED", "true")
        self.announcement_fallback_enabled = _env_enabled("ANNOUNCEMENT_FALLBACK_ENABLED", "true")
        self._cninfo_orgid_map: Dict[str, str] = {}

    def cls_telegraph(self, page_size: int = 50) -> List[Dict[str, Any]]:
        """Return CLS 7x24 telegraph news as zero-key market events."""
        if not self.enabled or not self.cls_enabled:
            return []
        size = max(1, min(int(page_size or 50), 100))
        params = {
            "appName": "CailianpressWeb",
            "os": "web",
            "sv": "7.7.5",
            "last_time": "",
            "refresh_type": "1",
            "rn": str(size),
        }
        query = "&".join(f"{key}={params[key]}" for key in sorted(params))
        url = f"https://www.cls.cn/v1/roll/get_roll_list?{query}&sign={_cls_sign(params)}"
        response = self.client.get(
            url,
            headers={"Referer": "https://www.cls.cn/", "User-Agent": DEFAULT_USER_AGENT},
            timeout=10,
        )
        payload = response.json()
        rows: List[Dict[str, Any]] = []
        for item in payload.get("data", {}).get("roll_data", []) or []:
            timestamp = item.get("ctime")
            published_at = ""
            if timestamp:
                try:
                    published_at = datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M:%S")
                except (TypeError, ValueError, OSError):
                    published_at = ""
            title = item.get("title") or item.get("brief") or ""
            rows.append(
                {
                    "title": title,
                    "content": item.get("content") or item.get("brief") or title,
                    "time": published_at,
                    "source": "cls",
                    "url": item.get("shareurl") or item.get("url") or "https://www.cls.cn/",
                    "raw_id": item.get("id"),
                }
            )
        return rows

    def ths_hot_reason(self, date: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return THS hot-stock reason tags for the requested trading date."""
        if not self.enabled or not self.ths_hot_enabled:
            return []
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        url = (
            "http://zx.10jqka.com.cn/event/api/getharden/"
            f"date/{date}/orderby/date/orderway/desc/charset/GBK/"
        )
        response = self.client.get(
            url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": "http://zx.10jqka.com.cn/",
            },
            timeout=10,
        )
        payload = response.json()
        if int(payload.get("errocode", 0) or 0) != 0:
            raise FreeSourceError(f"ths hot reason error: {payload.get('errormsg', '')}")
        rows = payload.get("data") or []
        if limit:
            rows = rows[: max(0, int(limit))]
        normalized: List[Dict[str, Any]] = []
        for index, item in enumerate(rows, start=1):
            code = normalize_stock_code(str(item.get("code", "")))
            normalized.append(
                {
                    "code": code,
                    "name": item.get("name", ""),
                    "reason": item.get("reason", ""),
                    "change_pct": _safe_float(item.get("zhangfu")),
                    "turnover_rate": _safe_float(item.get("huanshou")),
                    "amount": _safe_float(item.get("chengjiaoe")),
                    "volume": _safe_float(item.get("chengjiaoliang")),
                    "large_order_net": _safe_float(item.get("ddejingliang")),
                    "close": _safe_float(item.get("close")),
                    "market": item.get("market", ""),
                    "rank": index,
                    "date": date,
                    "source": "ths_hot_reason",
                }
            )
        return normalized

    def cninfo_announcements(self, stock_code: str, page_size: int = 30) -> List[Dict[str, Any]]:
        """Return CNINFO full-text announcements for an A-share code."""
        if not self.enabled or not self.cninfo_enabled:
            return []
        code = normalize_stock_code(stock_code)
        if not (code.isdigit() and len(code) == 6):
            return []
        org_id = self._cninfo_orgid(code)
        payload = {
            "stock": f"{code},{org_id}",
            "tabName": "fulltext",
            "pageSize": str(max(1, min(int(page_size or 30), 100))),
            "pageNum": "1",
            "column": "",
            "category": "",
            "plate": "",
            "seDate": "",
            "searchkey": "",
            "secid": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        response = self.client.post(
            "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www.cninfo.com.cn/new/disclosure",
                "Origin": "https://www.cninfo.com.cn",
                "User-Agent": DEFAULT_USER_AGENT,
            },
            timeout=15,
        )
        data = response.json()
        rows: List[Dict[str, Any]] = []
        for item in data.get("announcements", []) or []:
            adjunct_url = item.get("adjunctUrl") or ""
            pdf_url = (
                f"https://static.cninfo.com.cn/{adjunct_url}"
                if adjunct_url and not adjunct_url.startswith("http")
                else adjunct_url
            )
            anno_id = item.get("announcementId", "")
            rows.append(
                {
                    "code": code,
                    "title": item.get("announcementTitle", ""),
                    "type": item.get("announcementTypeName", ""),
                    "date": _cninfo_ts_to_date(item.get("announcementTime")),
                    "url": f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={anno_id}",
                    "pdf_url": pdf_url,
                    "source": "cninfo",
                    "raw_id": anno_id,
                }
            )
        return rows

    def sina_fund_flow_backup(self, stock_code: str, days: int = 60) -> List[Dict[str, Any]]:
        """Return Sina daily fund-flow rows as an Eastmoney-independent fallback."""
        if not self.enabled or not self.sina_fund_flow_enabled:
            return []
        code = normalize_stock_code(stock_code)
        if not (code.isdigit() and len(code) == 6):
            return []
        size = max(1, min(int(days or 60), 240))
        prefixed = self._sina_prefixed_code(code)
        url = (
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"MoneyFlow.ssl_qsfx_zjlrqs?page=1&num={size}&sort=opendate&asc=0&daima={prefixed}"
        )
        response = self.client.get(
            url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": "https://finance.sina.com.cn/",
            },
            timeout=15,
        )
        rows = self._parse_sina_json_array(response.text)
        normalized: List[Dict[str, Any]] = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "code": code,
                    "date": item.get("opendate") or item.get("date") or "",
                    "close": _safe_float(item.get("trade")),
                    "net_amount": _safe_float(item.get("netamount")),
                    "turnover": _safe_float(item.get("turnover")),
                    "source": "sina_fund_flow",
                }
            )
        return normalized

    def official_dragon_tiger_backup(self, trade_date: str) -> Dict[str, Any]:
        """Return official SZSE/SSE dragon-tiger data as a zero-key fallback."""
        if not self.enabled or not self.official_dragon_tiger_enabled:
            return {"date": trade_date, "source": "official_exchange", "sse_raw": "", "szse": []}
        date_text = str(trade_date or "").strip()
        if not date_text:
            return {"date": date_text, "source": "official_exchange", "sse_raw": "", "szse": []}

        result: Dict[str, Any] = {
            "date": date_text,
            "source": "official_exchange",
            "sse_raw": "",
            "szse": [],
        }

        szse_url = (
            "https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON"
            f"&CATALOGID=1842_xxpl&TABKEY=tab1&txtStart={date_text}&txtEnd={date_text}&random=0.9"
        )
        try:
            response = self.client.get(
                szse_url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Referer": "https://www.szse.cn/disclosure/supervision/dealinfo/index.html",
                },
                timeout=15,
            )
            payload = response.json()
            first = payload[0] if isinstance(payload, list) and payload else {}
            result["szse"] = [
                {
                    "code": normalize_stock_code(str(row.get("zqdm", ""))),
                    "name": row.get("zqjc", ""),
                    "amount": row.get("cjje"),
                    "reason": row.get("plyy", ""),
                    "source": "szse_dragon_tiger",
                }
                for row in first.get("data", []) or []
                if isinstance(row, dict)
            ]
        except Exception as exc:
            result["szse_error"] = str(exc)
            logger.debug("[AStockFreeFetcher] SZSE dragon-tiger fallback failed: %s", exc)

        sse_url = (
            "https://query.sse.com.cn/infodisplay/showTradePublicFile.do?"
            f"jsonCallBack=cb&isPagination=false&dateTx={date_text}"
        )
        try:
            response = self.client.get(
                sse_url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Referer": "https://www.sse.com.cn/disclosure/diclosure/public/",
                },
                timeout=15,
            )
            payload = self._parse_jsonp_object(response.text)
            result["sse_raw"] = "\n".join(payload.get("fileContents", []) or [])
        except Exception as exc:
            result["sse_error"] = str(exc)
            logger.debug("[AStockFreeFetcher] SSE dragon-tiger fallback failed: %s", exc)
        return result

    def announcement_fallback(self, stock_code: str, page_size: int = 20) -> List[Dict[str, Any]]:
        """Return SZSE official / Eastmoney announcement rows as a fallback."""
        if not self.enabled or not self.announcement_fallback_enabled:
            return []
        code = normalize_stock_code(stock_code)
        if not (code.isdigit() and len(code) == 6):
            return []
        size = max(1, min(int(page_size or 20), 100))
        if code.startswith(("0", "3")):
            return self._szse_announcement_fallback(code, size)
        return self._eastmoney_announcement_fallback(code, size)

    def _cninfo_orgid(self, code: str) -> str:
        if not self._cninfo_orgid_map:
            try:
                response = self.client.get(
                    "http://www.cninfo.com.cn/new/data/szse_stock.json",
                    headers={"User-Agent": DEFAULT_USER_AGENT},
                    timeout=15,
                )
                data = response.json()
                self._cninfo_orgid_map = {
                    str(item.get("code")): str(item.get("orgId"))
                    for item in data.get("stockList", [])
                    if item.get("code") and item.get("orgId")
                }
            except Exception as exc:  # pragma: no cover - fallback is tested directly
                logger.warning("[AStockFreeFetcher] CNINFO orgId map unavailable, using fallback: %s", exc)
        org_id = self._cninfo_orgid_map.get(code)
        if org_id:
            return org_id
        if code.startswith("6"):
            return f"gssh0{code}"
        if code.startswith(("8", "4", "9")):
            return f"gsbj0{code}"
        return f"gssz0{code}"

    @staticmethod
    def _sina_prefixed_code(code: str) -> str:
        if code.startswith(("6", "9")):
            return f"sh{code}"
        if code.startswith(("8", "4")):
            return f"bj{code}"
        return f"sz{code}"

    @staticmethod
    def _parse_sina_json_array(text: str) -> List[Dict[str, Any]]:
        payload = str(text or "").strip()
        if not payload:
            return []
        start = payload.find("[")
        end = payload.rfind("]")
        if start >= 0 and end >= start:
            payload = payload[start : end + 1]
        data = json.loads(payload)
        return data if isinstance(data, list) else []

    @staticmethod
    def _parse_jsonp_object(text: str) -> Dict[str, Any]:
        payload = str(text or "").strip()
        start = payload.find("(")
        end = payload.rfind(")")
        if start >= 0 and end > start:
            payload = payload[start + 1 : end]
        data = json.loads(payload)
        return data if isinstance(data, dict) else {}

    def _szse_announcement_fallback(self, code: str, page_size: int) -> List[Dict[str, Any]]:
        body = {
            "channelCode": ["listedNotice_disc"],
            "pageSize": page_size,
            "pageNum": 1,
            "stock": [code],
        }
        response = self.client.post(
            "https://www.szse.cn/api/disc/announcement/annList",
            json=body,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Content-Type": "application/json",
                "Referer": "https://www.szse.cn/disclosure/listed/notice/index.html",
            },
            timeout=15,
        )
        data = response.json()
        rows: List[Dict[str, Any]] = []
        for item in data.get("data", []) or []:
            attach_path = item.get("attachPath") or ""
            rows.append(
                {
                    "code": code,
                    "title": item.get("title", ""),
                    "date": str(item.get("publishTime", ""))[:10],
                    "url": "",
                    "pdf_url": (
                        f"https://disc.static.szse.cn/download{attach_path}"
                        if attach_path and not attach_path.startswith("http")
                        else attach_path
                    ),
                    "source": "szse_announcement",
                    "raw_id": item.get("id") or item.get("announcementId"),
                }
            )
        return rows

    def _eastmoney_announcement_fallback(self, code: str, page_size: int) -> List[Dict[str, Any]]:
        url = (
            "https://np-anotice-stock.eastmoney.com/api/security/ann"
            f"?sr=-1&page_size={page_size}&page_index=1&ann_type=A"
            f"&client_source=web&stock_list={code}&f_node=0&s_node=0"
        )
        response = self.client.get(
            url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": "https://data.eastmoney.com/notices/",
            },
            timeout=15,
        )
        data = response.json()
        rows: List[Dict[str, Any]] = []
        for item in data.get("data", {}).get("list", []) or []:
            art_code = item.get("art_code", "")
            rows.append(
                {
                    "code": code,
                    "title": item.get("title", ""),
                    "date": str(item.get("notice_date", ""))[:10],
                    "url": "",
                    "pdf_url": f"https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf" if art_code else "",
                    "source": "eastmoney_announcement_fallback",
                    "raw_id": art_code,
                }
            )
        return rows

    def snapshot(self, stock_code: Optional[str] = None, *, date: Optional[str] = None) -> Dict[str, Any]:
        """Convenience method for diagnostics and future pipeline integration."""
        result: Dict[str, Any] = {
            "source": self.name,
            "news": self.cls_telegraph(page_size=20),
            "hot_reasons": self.ths_hot_reason(date=date, limit=50),
        }
        if stock_code:
            result["announcements"] = self.cninfo_announcements(stock_code, page_size=20)
            result["fund_flow_fallback"] = self.sina_fund_flow_backup(stock_code, days=20)
        return result


__all__ = ["AStockFreeFetcher", "FreeSourceError"]
