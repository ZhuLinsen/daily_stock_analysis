# -*- coding: utf-8 -*-
"""
===================================
YfinanceFetcher - 兜底数据源 (Priority 4)
===================================

数据来源：Yahoo Finance（通过 yfinance 库）
特点：国际数据源、可能有延迟或缺失
定位：当所有国内数据源都失败时的最后保障

关键策略：
1. 自动将 A 股代码转换为 yfinance 格式（.SS / .SZ）
2. 处理 Yahoo Finance 的数据格式差异
3. 失败后指数退避重试
"""

import csv
import logging
import math
from datetime import date, datetime, timedelta
from io import StringIO
from typing import Optional, List, Dict, Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import BaseFetcher, DataFetchError, STANDARD_COLUMNS, _is_hk_market, is_bse_code
from .realtime_types import UnifiedRealtimeQuote, RealtimeSource
from .us_index_mapping import get_us_index_yf_symbol, get_us_stock_yf_symbol, is_us_stock_code
from .yfinance_fundamental_adapter import _safe_float
from src.services.market_symbol_utils import get_suffix_market, is_suffix_market_symbol

# 可选导入本地股票映射补丁，若缺失则使用空字典兜底
try:
    from src.data.stock_mapping import STOCK_NAME_MAP, is_meaningful_stock_name, lookup_static_stock_name
except (ImportError, ModuleNotFoundError):
    STOCK_NAME_MAP = {}

    def is_meaningful_stock_name(name: str | None, stock_code: str) -> bool:
        """简单的名称有效性校验兜底"""
        if not name:
            return False
        n = str(name).strip()
        return bool(n and n.upper() != str(stock_code).strip().upper())

    def lookup_static_stock_name(
        stock_code: str,
        stock_name_map: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """Minimal fallback static lookup when src.data.stock_mapping is absent."""
        mapping = STOCK_NAME_MAP if stock_name_map is None else stock_name_map
        name = mapping.get(stock_code)
        return str(name).strip() if is_meaningful_stock_name(name, stock_code) else None

import os

logger = logging.getLogger(__name__)


class YfinanceFetcher(BaseFetcher):
    """
    Yahoo Finance 数据源实现

    优先级：4（最低，作为兜底）
    数据来源：Yahoo Finance

    关键策略：
    - 自动转换股票代码格式
    - 处理时区和数据格式差异
    - 失败后指数退避重试

    注意事项：
    - A 股数据可能有延迟
    - 某些股票可能无数据
    - 数据精度可能与国内源略有差异
    """

    name = "YfinanceFetcher"
    priority = int(os.getenv("YFINANCE_PRIORITY", "4"))

    def __init__(self):
        """初始化 YfinanceFetcher"""
        pass

    @staticmethod
    def _is_jp_kr_suffix_stock(stock_code: str) -> bool:
        """Return True for supported JP/KR suffix-only Yahoo symbols."""
        return is_suffix_market_symbol(stock_code, "jp") or is_suffix_market_symbol(stock_code, "kr")

    @staticmethod
    def _is_tw_suffix_stock(stock_code: str) -> bool:
        """Return True for supported Taiwan suffix-only Yahoo symbols (TWSE `.TW` / TPEx `.TWO`).

        Taiwan base codes are 4-6 digits (common stocks 4, ETFs/others up to 6,
        e.g. 00878 / 006208), wider than the JP `.T` range.
        """
        return is_suffix_market_symbol(stock_code, "tw")

    def _convert_stock_code(self, stock_code: str) -> str:
        """
        转换股票代码为 Yahoo Finance 格式

        Yahoo Finance 代码格式：
        - A股沪市：600519.SS (Shanghai Stock Exchange)
        - A股深市：000001.SZ (Shenzhen Stock Exchange)
        - 港股：0700.HK (Hong Kong Stock Exchange)
        - 美股：AAPL, TSLA, GOOGL (无需后缀)

        Args:
            stock_code: 原始代码，如 '600519', 'hk00700', 'AAPL'

        Returns:
            Yahoo Finance 格式代码

        Examples:
            >>> fetcher._convert_stock_code('600519')
            '600519.SS'
            >>> fetcher._convert_stock_code('hk00700')
            '0700.HK'
            >>> fetcher._convert_stock_code('AAPL')
            'AAPL'
        """
        code = stock_code.strip().upper()

        # 美股指数：映射到 Yahoo Finance 符号（如 SPX -> ^GSPC）
        yf_symbol, _ = get_us_index_yf_symbol(code)
        if yf_symbol:
            logger.debug(f"Identified as US index: {code} -> {yf_symbol}")
            return yf_symbol

        # 美股类别股在 Yahoo 使用连字符，例如 BRK.B -> BRK-B。
        yf_symbol = get_us_stock_yf_symbol(code)
        if yf_symbol:
            return yf_symbol

        # 日股/韩股/台股 MVP：显式 Yahoo Finance suffix-only 代码，原样传给 Yahoo。
        if is_suffix_market_symbol(code):
            logger.debug(f"Identified as offshore Yahoo suffix symbol: {code}")
            return code

        # 港股：hk前缀 -> .HK后缀
        if code.startswith('HK'):
            hk_code = code[2:].lstrip('0') or '0'  # 去除前导0，但保留至少一个0
            hk_code = hk_code.zfill(4)  # 补齐到4位
            logger.debug(f"Converted HK stock code: {stock_code} -> {hk_code}.HK")
            return f"{hk_code}.HK"

        # 港股裸码：4-5 位纯数字（如 00700、02513、0001）按港股处理。
        # A 股代码全部是 6 位，4-5 位裸数字不可能是 A 股或 BSE（BSE 是
        # 4/8/920xxx 6 位），因此可以先于 .SZ 兜底分流到 .HK，避免 yfinance
        # 把 02513 这类新港股误判为深市后缀导致 Yahoo 404。详见 issue #2091。
        if code.isdigit() and 4 <= len(code) <= 5:
            hk_code = code.lstrip('0') or '0'
            hk_code = hk_code.zfill(4)
            logger.debug(f"Identified bare HK stock code: {stock_code} -> {hk_code}.HK")
            return f"{hk_code}.HK"

        # 已经包含后缀的情况
        if '.SS' in code or '.SZ' in code or '.HK' in code or '.BJ' in code:
            return code

        # 去除可能的 .SH 后缀
        code = code.replace('.SH', '')

        # ETF: Shanghai ETF (51xx, 52xx, 56xx, 58xx) -> .SS; Shenzhen ETF (15xx, 16xx, 18xx) -> .SZ
        if len(code) == 6:
            if code.startswith(('51', '52', '56', '58')):
                return f"{code}.SS"
            if code.startswith(('15', '16', '18')):
                return f"{code}.SZ"

        # BSE (Beijing Stock Exchange): 8xxxxx, 4xxxxx, 920xxx
        if is_bse_code(code):
            base = code.split('.')[0] if '.' in code else code
            return f"{base}.BJ"

        # A股：根据代码前缀判断市场
        if code.startswith(('600', '601', '603', '688')):
            return f"{code}.SS"
        elif code.startswith(('000', '002', '300')):
            return f"{code}.SZ"
        else:
            logger.warning(f"Cannot determine market for stock {code}, defaulting to SZ")
            return f"{code}.SZ"

    @staticmethod
    def _exclusive_end_date(end_date: str) -> str:
        """Convert inclusive YYYY-MM-DD *end_date* to yfinance's exclusive *end*."""
        try:
            end_dt = datetime.strptime(end_date[:10], "%Y-%m-%d")
            return (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return end_date

    @staticmethod
    def _clamp_to_end_date(df: pd.DataFrame, end_date: str) -> pd.DataFrame:
        """Drop bars strictly after *end_date* after fetching with exclusive end+1."""
        if df is None or df.empty:
            return df
        try:
            end_ts = pd.Timestamp(end_date[:10]).normalize()
        except (TypeError, ValueError):
            return df
        if isinstance(df.index, pd.DatetimeIndex):
            idx_dates = df.index
            if idx_dates.tz is not None:
                idx_dates = idx_dates.tz_localize(None)
            mask = idx_dates.normalize() <= end_ts
            return df.loc[mask].copy()
        for col in ("Date", "Datetime", "date", "datetime"):
            if col in df.columns:
                parsed = pd.to_datetime(df[col], errors="coerce")
                if getattr(parsed.dt, "tz", None) is not None:
                    parsed = parsed.dt.tz_localize(None)
                mask = parsed.isna() | (parsed.dt.normalize() <= end_ts)
                return df.loc[mask].copy()
        return df

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        从 Yahoo Finance 获取原始数据

        使用 yfinance.download() 获取历史数据

        流程：
        1. 转换股票代码格式
        2. 将闭区间 end_date 转为 yfinance 开区间 end (+1 天) 后调用 API
        3. 过滤超出 end_date 的数据并处理返回结构
        """
        import yfinance as yf

        # 转换代码格式
        yf_code = self._convert_stock_code(stock_code)
        yf_end_date = self._exclusive_end_date(end_date)

        logger.debug(f"Calling yfinance.download({yf_code}, {start_date}, {yf_end_date}) [requested end={end_date}]")

        try:
            # 使用 yfinance 下载数据（yfinance 的 end 为左闭右开，不 +1 会丢失 end_date 当日 K 线）
            df = yf.download(
                tickers=yf_code,
                start=start_date,
                end=yf_end_date,
                progress=False,  # 禁止进度条
                auto_adjust=True,  # 自动调整价格（复权）
                multi_level_index=True
            )

            # 筛选出 yf_code 的列, 避免多只股票数据混淆
            if isinstance(df.columns, pd.MultiIndex) and len(df.columns) > 1:
                ticker_level = df.columns.get_level_values(1)
                mask = ticker_level == yf_code
                if mask.any():
                    df = df.loc[:, mask].copy()

            df = self._clamp_to_end_date(df, end_date)

            if df.empty:
                raise DataFetchError(f"Yahoo Finance 未查询到 {stock_code} 的数据")

            return df

        except Exception as e:
            if isinstance(e, DataFetchError):
                raise
            raise DataFetchError(f"Yahoo Finance 获取数据失败: {e}") from e

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        标准化 Yahoo Finance 数据

        yfinance 返回的列名：
        Open, High, Low, Close, Volume（索引是日期）

        注意：新版 yfinance 返回 MultiIndex 列名，如 ('Close', 'AMD')
        需要先扁平化列名再进行处理

        需要映射到标准列名：
        date, open, high, low, close, volume, amount, pct_chg
        """
        df = df.copy()

        # 处理 MultiIndex 列名（新版 yfinance 返回格式）
        # 例如: ('Close', 'AMD') -> 'Close'
        if isinstance(df.columns, pd.MultiIndex):
            logger.debug("Detected MultiIndex columns, flattening")
            # 取第一级列名（Price level: Close, High, Low, etc.）
            df.columns = df.columns.get_level_values(0)

        # 重置索引，将日期从索引变为列
        df = df.reset_index()

        # 列名映射（yfinance 使用首字母大写）
        column_mapping = {
            'Date': 'date',
            'Datetime': 'date',
            'datetime': 'date',
            'Open': 'open',
            'High': 'high',
            'Low': 'low',
            'Close': 'close',
            'Volume': 'volume',
        }

        df = df.rename(columns=column_mapping)
        if 'date' not in df.columns:
            index_col = df.columns[0] if len(df.columns) else None
            if index_col is not None:
                candidate = df[index_col]
                if pd.api.types.is_datetime64_any_dtype(candidate):
                    df = df.rename(columns={index_col: 'date'})
                elif not pd.api.types.is_numeric_dtype(candidate):
                    parsed_dates = pd.to_datetime(candidate, errors='coerce')
                    if parsed_dates.notna().any():
                        df = df.rename(columns={index_col: 'date'})
                        df['date'] = parsed_dates

        # 计算涨跌幅（因为 yfinance 不直接提供）
        if 'close' in df.columns:
            df['pct_chg'] = df['close'].pct_change() * 100
            df['pct_chg'] = df['pct_chg'].fillna(0).round(2)

        # 计算成交额（yfinance 不提供，使用估算值）
        # 成交额 ≈ 成交量 * 平均价格
        if 'volume' in df.columns and 'close' in df.columns:
            df['amount'] = df['volume'] * df['close']
        else:
            df['amount'] = 0

        # 添加股票代码列
        df['code'] = stock_code

        # 只保留需要的列
        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]

        return df

    def _fetch_yf_ticker_data(self, yf, yf_code: str, name: str, return_code: str) -> Optional[Dict[str, Any]]:
        """
        通过 yfinance 拉取单个指数/股票的行情数据。

        Args:
            yf: yfinance 模块引用
            yf_code: yfinance 使用的代码（如 '000001.SS'、'^GSPC'）
            name: 指数显示名称
            return_code: 写入结果 dict 的 code 字段（如 'sh000001'、'SPX'）

        Returns:
            行情字典，失败时返回 None
        """
        ticker = yf.Ticker(yf_code)
        # 取近两日数据以计算涨跌幅
        hist = ticker.history(period='2d')
        if hist.empty:
            return None
        today_row = hist.iloc[-1]
        prev_row = hist.iloc[-2] if len(hist) > 1 else today_row
        price = float(today_row['Close'])
        prev_close = float(prev_row['Close'])
        change = price - prev_close
        change_pct = (change / prev_close) * 100 if prev_close else 0
        high = float(today_row['High'])
        low = float(today_row['Low'])
        # 振幅 = (最高 - 最低) / 昨收 * 100
        amplitude = ((high - low) / prev_close * 100) if prev_close else 0
        return {
            'code': return_code,
            'name': name,
            'current': price,
            'change': change,
            'change_pct': change_pct,
            'open': float(today_row['Open']),
            'high': high,
            'low': low,
            'prev_close': prev_close,
            'volume': float(today_row['Volume']),
            'amount': 0.0,  # Yahoo Finance 不提供准确成交额
            'amplitude': amplitude,
        }

    def get_main_indices(self, region: str = "cn") -> Optional[List[Dict[str, Any]]]:
        """
        获取主要指数行情 (Yahoo Finance)，支持 A 股、美股、港股、日股、韩股与台股。
        region=us 时委托给 _get_us_main_indices。
        region=hk 时委托给 _get_hk_main_indices。
        region=jp/kr/tw 时分别委托给对应市场指数方法。
        """
        import yfinance as yf

        if region == "au":
            results = []
            for code, symbol, name in [("AXJO", "^AXJO", "S&P/ASX 200"), ("AORD", "^AORD", "All Ordinaries")]:
                try:
                    item = self._fetch_yf_ticker_data(yf, symbol, name, code)
                    if item:
                        item["market"] = "au"
                        results.append(item)
                except Exception as exc:
                    logger.warning("ASX index %s unavailable: %s", symbol, exc)
            return results or None
        if region == "us":
            return self._get_us_main_indices(yf)
        if region == "hk":
            return self._get_hk_main_indices(yf)
        if region == "jp":
            return self._get_jp_main_indices(yf)
        if region == "kr":
            return self._get_kr_main_indices(yf)
        if region == "tw":
            return self._get_tw_main_indices(yf)

        # A 股指数：akshare 代码 -> (yfinance 代码, 显示名称)
        yf_mapping = {
            'sh000001': ('000001.SS', '上证指数'),
            'sz399001': ('399001.SZ', '深证成指'),
            'sz399006': ('399006.SZ', '创业板指'),
            'sh000688': ('000688.SS', '科创50'),
            'sh000016': ('000016.SS', '上证50'),
            'sh000300': ('000300.SS', '沪深300'),
        }

        results = []
        try:
            for ak_code, (yf_code, name) in yf_mapping.items():
                try:
                    item = self._fetch_yf_ticker_data(yf, yf_code, name, ak_code)
                    if item:
                        results.append(item)
                        logger.debug(f"[Yfinance] Fetched index {name} succeeded")
                except Exception as e:
                    logger.warning(f"[Yfinance] Failed to fetch index {name}: {e}")

            if results:
                logger.info(f"[Yfinance] Fetched {len(results)} A-share index quotes")
                return results

        except Exception as e:
            logger.error(f"[Yfinance] Failed to fetch A-share index quotes: {e}")

        return None

    def _get_us_main_indices(self, yf) -> Optional[List[Dict[str, Any]]]:
        """获取美股主要指数行情（SPX、IXIC、DJI、VIX），复用 _fetch_yf_ticker_data"""
        # 大盘复盘所需核心美股指数
        us_indices = ['SPX', 'IXIC', 'DJI', 'VIX']
        results = []
        try:
            for code in us_indices:
                yf_symbol, name = get_us_index_yf_symbol(code)
                if not yf_symbol:
                    continue
                try:
                    item = self._fetch_yf_ticker_data(yf, yf_symbol, name, code)
                    if item:
                        results.append(item)
                        logger.debug(f"[Yfinance] Fetched US index {name} succeeded")
                except Exception as e:
                    logger.warning(f"[Yfinance] Failed to fetch US index {name}: {e}")

            if results:
                logger.info(f"[Yfinance] Fetched {len(results)} US index quotes")
                return results

        except Exception as e:
            logger.error(f"[Yfinance] Failed to fetch US index quotes: {e}")

        return None

    def _get_hk_main_indices(self, yf) -> Optional[List[Dict[str, Any]]]:
        """获取港股主要指数行情（HSI、HSTECH、HSCEI），复用 _fetch_yf_ticker_data"""
        # Yahoo Finance 港股指数符号映射：
        # - HSI -> ^HSI
        # - HSTECH -> HSTECH.HK（不是 ^HSTECH）
        # - HSCEI -> ^HSCE（不是 ^HSCEI）
        # 该映射由离线单测 tests/test_yfinance_hk_indices.py 固化，避免在线依赖导致非确定性失败。
        hk_indices = {
            'HSI': ('^HSI', '恒生指数'),
            'HSTECH': ('HSTECH.HK', '恒生科技指数'),
            'HSCEI': ('^HSCE', '国企指数'),
        }
        results = []
        try:
            for code, (yf_symbol, name) in hk_indices.items():
                try:
                    item = self._fetch_yf_ticker_data(yf, yf_symbol, name, code)
                    if item:
                        results.append(item)
                        logger.debug(f"[Yfinance] Fetched HK index {name} succeeded")
                except Exception as e:
                    logger.warning(f"[Yfinance] Failed to fetch HK index {name}: {e}")

            if results:
                logger.info(f"[Yfinance] Fetched {len(results)} HK index quotes")
                return results

        except Exception as e:
            logger.error(f"[Yfinance] Failed to fetch HK index quotes: {e}")

        return None

    def _get_jp_main_indices(self, yf) -> Optional[List[Dict[str, Any]]]:
        """获取日本主要指数行情（日经225、TOPIX），复用 _fetch_yf_ticker_data。"""
        jp_indices = {
            'N225': ('^N225', '日经225'),
            'TOPX': ('^TOPX', '东证指数'),
        }
        results = []
        try:
            for code, (yf_symbol, name) in jp_indices.items():
                try:
                    item = self._fetch_yf_ticker_data(yf, yf_symbol, name, code)
                    if item:
                        results.append(item)
                        logger.debug(f"[Yfinance] Fetched JP index {name} succeeded")
                except Exception as e:
                    logger.warning(f"[Yfinance] Failed to fetch JP index {name}: {e}")
            if results:
                logger.info(f"[Yfinance] Fetched {len(results)} JP index quotes")
                return results
        except Exception as e:
            logger.error(f"[Yfinance] Failed to fetch JP index quotes: {e}")
        return None

    def _get_kr_main_indices(self, yf) -> Optional[List[Dict[str, Any]]]:
        """获取韩国主要指数行情（KOSPI、KOSDAQ），复用 _fetch_yf_ticker_data。"""
        kr_indices = {
            'KS11': ('^KS11', 'KOSPI'),
            'KQ11': ('^KQ11', 'KOSDAQ'),
        }
        results = []
        try:
            for code, (yf_symbol, name) in kr_indices.items():
                try:
                    item = self._fetch_yf_ticker_data(yf, yf_symbol, name, code)
                    if item:
                        results.append(item)
                        logger.debug(f"[Yfinance] Fetched KR index {name} succeeded")
                except Exception as e:
                    logger.warning(f"[Yfinance] Failed to fetch KR index {name}: {e}")
            if results:
                logger.info(f"[Yfinance] Fetched {len(results)} KR index quotes")
                return results
        except Exception as e:
            logger.error(f"[Yfinance] Failed to fetch KR index quotes: {e}")
        return None

    def _get_tw_main_indices(self, yf) -> Optional[List[Dict[str, Any]]]:
        """获取台湾主要指数行情（加权指数 ^TWII、柜买指数 ^TWOII），复用 _fetch_yf_ticker_data。"""
        tw_indices = {
            'TWII': ('^TWII', '台湾加权指数'),
            'TWOII': ('^TWOII', '台湾柜买指数'),
        }
        results = []
        try:
            for code, (yf_symbol, name) in tw_indices.items():
                try:
                    item = self._fetch_yf_ticker_data(yf, yf_symbol, name, code)
                    if item:
                        results.append(item)
                        logger.debug(f"[Yfinance] Fetched TW index {name} succeeded")
                except Exception as e:
                    logger.warning(f"[Yfinance] Failed to fetch TW index {name}: {e}")
            if results:
                logger.info(f"[Yfinance] Fetched {len(results)} TW index quotes")
                return results
        except Exception as e:
            logger.error(f"[Yfinance] Failed to fetch TW index quotes: {e}")
        return None

    def _is_us_stock(self, stock_code: str) -> bool:
        """
        判断代码是否为美股股票（排除美股指数）。

        委托给 us_index_mapping 模块的 is_us_stock_code()。
        """
        return is_us_stock_code(stock_code)

    def _get_us_stock_quote_from_stooq(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        使用 Stooq 为美股实时行情提供免密钥兜底。

        Stooq 提供的是最新交易日行情，精度不如分时实时接口，但在 Yahoo / yfinance
        被限流时，至少能为 Web UI 提供可用价格；若可获取到昨收价，则同时提供涨跌幅等衍生指标。
        """
        symbol = stock_code.strip().upper()
        stooq_symbol = f"{symbol.lower()}.us"
        url = f"https://stooq.com/q/l/?s={stooq_symbol}"
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; DSA/1.0; +https://github.com/ZhuLinsen/daily_stock_analysis)",
                "Accept": "text/plain,text/csv,*/*",
            },
        )

        try:
            with urlopen(request, timeout=15) as response:
                payload = response.read().decode("utf-8", "ignore").strip()
        except (HTTPError, URLError, TimeoutError) as exc:
            logger.warning(f"[Stooq] Failed to fetch US stock {symbol} realtime quote: {exc}")
            return None

        if not payload or payload.upper().startswith("NO DATA"):
            logger.warning(f"[Stooq] No quote data available for {symbol}")
            return None

        def _parse_quote_date(quote_date_text: str) -> Optional[date]:
            # The quote CSV can use either YYYYMMDD or YYYY-MM-DD.
            if len(quote_date_text) == 8 and quote_date_text.isdigit():
                quote_date_text = f"{quote_date_text[:4]}-{quote_date_text[4:6]}-{quote_date_text[6:]}"
            try:
                return date.fromisoformat(quote_date_text)
            except ValueError:
                return None

        def _fetch_prev_close(quote_date: date) -> Optional[float]:
            history_url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"
            history_request = Request(
                history_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; DSA/1.0; +https://github.com/ZhuLinsen/daily_stock_analysis)",
                    "Accept": "text/plain,text/csv,*/*",
                },
            )
            try:
                with urlopen(history_request, timeout=15) as response:
                    history_payload = response.read().decode("utf-8", "ignore").strip()
            except (HTTPError, URLError, TimeoutError) as exc:
                logger.debug(f"[Stooq] Failed to fetch US stock {symbol} daily history: {exc}")
                return None

            if not history_payload or history_payload.upper().startswith("NO DATA"):
                return None

            try:
                reader = csv.reader(StringIO(history_payload))
                header = next(reader, None)
                if not header:
                    return None

                header_tokens = [cell.strip().lower() for cell in header]
                has_header = "close" in header_tokens and "date" in header_tokens
                if not has_header:
                    return None

                date_index = header_tokens.index("date")
                close_index = header_tokens.index("close")

                previous_date = None
                previous_close_text = None
                for row in reader:
                    if len(row) <= date_index:
                        continue
                    try:
                        session_date = date.fromisoformat(row[date_index].strip())
                    except ValueError:
                        continue
                    if session_date < quote_date and (previous_date is None or session_date > previous_date):
                        previous_date = session_date
                        previous_close_text = row[close_index] if len(row) > close_index else None

                close = _safe_float(previous_close_text)
                return close if close is not None and math.isfinite(close) and close > 0 else None
            except Exception:
                return None

        try:
            reader = csv.reader(StringIO(payload))
            first_row = next(reader, None)
            if first_row is None:
                raise ValueError(f"unexpected Stooq payload: {payload}")

            normalized_first_row = [cell.strip() for cell in first_row]
            header_tokens = [cell.lower() for cell in normalized_first_row]
            has_header = 'open' in header_tokens and 'close' in header_tokens
            row = next(reader, None) if has_header else first_row
            if row is None:
                raise ValueError(f"unexpected Stooq payload: {payload}")

            normalized_row = [cell.strip() for cell in row]
            while normalized_row and normalized_row[-1] == '':
                normalized_row.pop()

            if len(normalized_row) >= 8:
                open_index, high_index, low_index, price_index, volume_index = 3, 4, 5, 6, 7
            elif len(normalized_row) >= 7:
                open_index, high_index, low_index, price_index, volume_index = 2, 3, 4, 5, 6
            else:
                raise ValueError(f"unexpected Stooq payload: {payload}")

            open_price = float(normalized_row[open_index])
            high = float(normalized_row[high_index])
            low = float(normalized_row[low_index])
            price = float(normalized_row[price_index])
            volume = int(float(normalized_row[volume_index]))

            quote_date_text = (
                dict(zip(header_tokens, normalized_row)).get("date", "") if has_header else normalized_row[1]
            )
            quote_date = _parse_quote_date(quote_date_text)
            if quote_date is None and not has_header and len(normalized_row) == 7:
                # Seven-column quotes may start with Date,Time instead of Symbol,Date.
                quote_date = _parse_quote_date(normalized_row[0])
            prev_close = _fetch_prev_close(quote_date) if quote_date is not None else None
            change_amount = None
            change_pct = None
            amplitude = None
            if prev_close is not None:
                change_amount = price - prev_close
                change_pct = (change_amount / prev_close) * 100
                amplitude = ((high - low) / prev_close) * 100

            quote = UnifiedRealtimeQuote(
                code=symbol,
                name=lookup_static_stock_name(symbol, STOCK_NAME_MAP) or '',
                source=RealtimeSource.STOOQ,
                price=price,
                change_pct=round(change_pct, 2) if change_pct is not None else None,
                change_amount=round(change_amount, 4) if change_amount is not None else None,
                volume=volume,
                amount=None,
                volume_ratio=None,
                turnover_rate=None,
                amplitude=round(amplitude, 2) if amplitude is not None else None,
                open_price=open_price,
                high=high,
                low=low,
                pre_close=prev_close,
                pe_ratio=None,
                pb_ratio=None,
                total_mv=None,
                circ_mv=None,
            )
            logger.info(f"[Stooq] Fetched US stock {symbol} fallback quote: price={price}")
            return quote
        except Exception as exc:
            logger.warning(f"[Stooq] Failed to parse US stock {symbol} quote: {exc}")
            return None

    def _get_us_index_realtime_quote(
        self,
        user_code: str,
        yf_symbol: str,
        index_name: str,
    ) -> Optional[UnifiedRealtimeQuote]:
        """
        Get realtime quote for US index (e.g. SPX -> ^GSPC).

        Args:
            user_code: User input code (e.g. SPX)
            yf_symbol: Yahoo Finance symbol (e.g. ^GSPC)
            index_name: Chinese name for the index

        Returns:
            UnifiedRealtimeQuote or None
        """
        import yfinance as yf

        try:
            logger.debug(f"[Yfinance] Fetching US index {user_code} ({yf_symbol}) realtime quote")
            ticker = yf.Ticker(yf_symbol)

            try:
                info = ticker.fast_info
                if info is None:
                    raise ValueError("fast_info is None")
                price = getattr(info, 'lastPrice', None) or getattr(info, 'last_price', None)
                prev_close = getattr(info, 'previousClose', None) or getattr(info, 'previous_close', None)
                open_price = getattr(info, 'open', None)
                high = getattr(info, 'dayHigh', None) or getattr(info, 'day_high', None)
                low = getattr(info, 'dayLow', None) or getattr(info, 'day_low', None)
                volume = getattr(info, 'lastVolume', None) or getattr(info, 'last_volume', None)
            except Exception:
                logger.debug("[Yfinance] fast_info failed, trying history method")
                hist = ticker.history(period='2d', auto_adjust=False)
                if hist.empty:
                    logger.warning(f"[Yfinance] Unable to fetch data for {yf_symbol}")
                    return None
                today = hist.iloc[-1]
                prev = hist.iloc[-2] if len(hist) > 1 else today
                price = float(today['Close'])
                prev_close = float(prev['Close'])
                open_price = float(today['Open'])
                high = float(today['High'])
                low = float(today['Low'])
                volume = int(today['Volume'])

            change_amount = None
            change_pct = None
            if price is not None and prev_close is not None and prev_close > 0:
                change_amount = price - prev_close
                change_pct = (change_amount / prev_close) * 100

            amplitude = None
            if high is not None and low is not None and prev_close is not None and prev_close > 0:
                amplitude = ((high - low) / prev_close) * 100

            try:
                ticker_info = ticker.info or {}
            except Exception:
                ticker_info = {}
            missing_fields = [
                field
                for field, value in {
                    "price": price,
                    "prev_close": prev_close,
                    "volume": volume,
                    "amount": None,
                    "pe_ratio": None,
                    "pb_ratio": None,
                }.items()
                if value is None
            ]

            quote = UnifiedRealtimeQuote(
                code=user_code,
                name=index_name or user_code,
                source=RealtimeSource.FALLBACK,
                market="us",
                currency=str(ticker_info.get("currency") or "").upper() or None,
                data_quality="partial" if missing_fields else "ok",
                missing_fields=missing_fields or None,
                price=price,
                change_pct=round(change_pct, 2) if change_pct is not None else None,
                change_amount=round(change_amount, 4) if change_amount is not None else None,
                volume=volume,
                amount=None,
                volume_ratio=None,
                turnover_rate=None,
                amplitude=round(amplitude, 2) if amplitude is not None else None,
                open_price=open_price,
                high=high,
                low=low,
                pre_close=prev_close,
                pe_ratio=None,
                pb_ratio=None,
                total_mv=None,
                circ_mv=None,
            )
            logger.info(f"[Yfinance] Fetched US index {user_code} realtime quote: price={price}")
            return quote
        except Exception as e:
            logger.warning(f"[Yfinance] Failed to fetch US index {user_code} realtime quote: {e}")
            return None

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取美股、港股、日韩台股票或美股指数实时行情数据

        支持美股股票（AAPL、TSLA）和美股指数（SPX、DJI 等）。
        数据来源：yfinance Ticker.info

        Args:
            stock_code: 美股代码或指数代码，如 'AMD', 'AAPL', 'SPX', 'DJI'

        Returns:
            UnifiedRealtimeQuote 对象，获取失败返回 None
        """
        import yfinance as yf

        # 美股指数：使用映射（SPX -> ^GSPC）
        yf_symbol, index_name = get_us_index_yf_symbol(stock_code)
        if yf_symbol:
            return self._get_us_index_realtime_quote(
                user_code=stock_code.strip().upper(),
                yf_symbol=yf_symbol,
                index_name=index_name,
            )

        # 仅处理美股、港股或 JP/KR/TW suffix-only 股票
        if not (
            self._is_us_stock(stock_code)
            or _is_hk_market(stock_code)
            or self._is_jp_kr_suffix_stock(stock_code)
            or self._is_tw_suffix_stock(stock_code)
            or is_suffix_market_symbol(stock_code, "au")
        ):
            logger.debug(f"[Yfinance] {stock_code} is not a supported US, HK, or JP/KR/TW symbol, skipping")
            return None

        try:
            symbol = self._convert_stock_code(stock_code)
            is_us_symbol = self._is_us_stock(stock_code)
            quote_code = stock_code.strip().upper() if is_us_symbol else symbol
            suffix_market = get_suffix_market(symbol)
            logger.debug(f"[Yfinance] Fetching {symbol} realtime quote")

            ticker = yf.Ticker(symbol)
            provider_timestamp = None
            quote_date = None
            used_fast_info = False

            # 尝试获取 fast_info（更快，但字段较少）
            try:
                info = ticker.fast_info
                if info is None:
                    raise ValueError("fast_info is None")

                price = getattr(info, 'lastPrice', None) or getattr(info, 'last_price', None)
                prev_close = getattr(info, 'previousClose', None) or getattr(info, 'previous_close', None)
                open_price = getattr(info, 'open', None)
                high = getattr(info, 'dayHigh', None) or getattr(info, 'day_high', None)
                low = getattr(info, 'dayLow', None) or getattr(info, 'day_low', None)
                volume = getattr(info, 'lastVolume', None) or getattr(info, 'last_volume', None)
                market_cap = getattr(info, 'marketCap', None) or getattr(info, 'market_cap', None)
                used_fast_info = True

            except Exception:
                # 回退到 history 方法获取最新数据
                logger.debug("[Yfinance] fast_info failed, trying history method")
                hist = ticker.history(period='2d', auto_adjust=False)
                if hist.empty:
                    if is_us_symbol:
                        logger.warning(f"[Yfinance] Unable to fetch data for {symbol}, trying Stooq fallback")
                        return self._get_us_stock_quote_from_stooq(quote_code)
                    logger.warning(f"[Yfinance] Unable to fetch data for {symbol}")
                    return None

                today = hist.iloc[-1]
                prev = hist.iloc[-2] if len(hist) > 1 else today
                quote_date = pd.Timestamp(hist.index[-1]).date().isoformat()

                price = float(today['Close'])
                prev_close = float(prev['Close'])
                open_price = float(today['Open'])
                high = float(today['High'])
                low = float(today['Low'])
                volume = int(today['Volume'])
                market_cap = None

            # 获取股票名称与 provider 元数据
            try:
                ticker_info = ticker.info or {}
            except Exception:
                ticker_info = {}

            if used_fast_info:
                # fast_info does not expose the quote session.  In current
                # yfinance versions its price/OHLCV properties are backed by
                # history, so use one history response for both values and the
                # provider timestamp.  regularMarketTime from ticker.info is
                # not safe: it may belong to a different quote payload.
                try:
                    quote_history = ticker.history(period='2d', auto_adjust=False)
                    if isinstance(quote_history, pd.DataFrame) and len(quote_history) >= 2:
                        today = quote_history.iloc[-1]
                        prev = quote_history.iloc[-2]
                        required_fields = ('Open', 'High', 'Low', 'Close', 'Volume')
                        values = [today.get(field) for field in required_fields]
                        previous_close = prev.get('Close')
                        if not any(pd.isna(value) for value in values) and not pd.isna(previous_close):
                            # Keep the selected quote values and their date in
                            # the same provider response.  This avoids pairing
                            # an old fast_info daily bar with a newer info time.
                            price = float(today['Close'])
                            prev_close = float(previous_close)
                            open_price = float(today['Open'])
                            high = float(today['High'])
                            low = float(today['Low'])
                            volume = int(today['Volume'])
                            quote_date = pd.Timestamp(quote_history.index[-1]).date().isoformat()
                except Exception:
                    logger.debug("[Yfinance] Failed to read quote date for %s", symbol, exc_info=True)

            # 计算最终行情字段对应的派生指标。fast_info 之后可能被 history
            # 覆盖，不能复用覆盖前的结果。
            change_amount = None
            change_pct = None
            if price is not None and prev_close is not None and prev_close > 0:
                change_amount = price - prev_close
                change_pct = (change_amount / prev_close) * 100

            amplitude = None
            if high is not None and low is not None and prev_close is not None and prev_close > 0:
                amplitude = ((high - low) / prev_close) * 100

            try:
                candidates = [
                    ticker_info.get('shortName', ''),
                    ticker_info.get('longName', ''),
                ]
                name = next(
                    (
                        str(candidate).strip()
                        for candidate in candidates
                        if is_meaningful_stock_name(candidate, symbol)
                        and is_meaningful_stock_name(candidate, stock_code)
                    ),
                    '',
                )
                if not name:
                    name = (
                        lookup_static_stock_name(quote_code, STOCK_NAME_MAP)
                        or lookup_static_stock_name(stock_code, STOCK_NAME_MAP)
                        or ''
                    )
            except Exception:
                name = (
                    lookup_static_stock_name(quote_code, STOCK_NAME_MAP)
                    or lookup_static_stock_name(stock_code, STOCK_NAME_MAP)
                    or ''
                )

            # 复用上方已获取的 ticker_info，无额外请求
            pe_ratio = _safe_float(ticker_info.get('trailingPE'))
            pb_ratio = _safe_float(ticker_info.get('priceToBook'))

            missing_fields = [
                field
                for field, value in {
                    "price": price,
                    "prev_close": prev_close,
                    "volume": volume,
                    "amount": None,
                    "pe_ratio": pe_ratio,
                    "pb_ratio": pb_ratio,
                }.items()
                if value is None
            ]
            quote = UnifiedRealtimeQuote(
                code=quote_code,
                name=name,
                source=RealtimeSource.FALLBACK,
                market=suffix_market or ("hk" if _is_hk_market(stock_code) else "us" if is_us_symbol else None),
                currency=str(ticker_info.get("currency") or "").upper() or None,
                quote_type=str(ticker_info.get("quoteType") or "").upper() or None,
                data_quality="partial" if missing_fields else "ok",
                missing_fields=missing_fields or None,
                price=price,
                change_pct=round(change_pct, 2) if change_pct is not None else None,
                change_amount=round(change_amount, 4) if change_amount is not None else None,
                volume=volume,
                amount=None,  # yfinance 不直接提供成交额
                volume_ratio=None,
                turnover_rate=None,
                amplitude=round(amplitude, 2) if amplitude is not None else None,
                open_price=open_price,
                high=high,
                low=low,
                pre_close=prev_close,
                pe_ratio=pe_ratio,
                pb_ratio=pb_ratio,
                total_mv=market_cap,
                circ_mv=None,
                provider_timestamp=provider_timestamp,
                quote_date=quote_date,
            )

            logger.info(f"[Yfinance] Fetched {symbol} realtime quote: price={price}")
            return quote

        except Exception as e:
            if self._is_us_stock(stock_code):
                logger.warning(
                    f"[Yfinance] Failed to fetch US stock {stock_code} realtime quote: {e}, trying Stooq fallback"
                )
                return self._get_us_stock_quote_from_stooq(stock_code)
            logger.warning(f"[Yfinance] Failed to fetch {stock_code} realtime quote: {e}")
            return None

    def get_stock_name(self, stock_code: str, *, allow_network: bool = True) -> Optional[str]:
        """Resolve display name for supported US, HK, and JP/KR/TW symbols via Yahoo Finance."""
        cache_key = (stock_code or "").strip().upper()
        if not cache_key:
            return None

        if not hasattr(self, "_stock_name_cache") or self._stock_name_cache is None:
            self._stock_name_cache = {}
        if cache_key in self._stock_name_cache:
            return self._stock_name_cache[cache_key]

        yf_symbol, index_name = get_us_index_yf_symbol(cache_key)
        if yf_symbol:
            if is_meaningful_stock_name(index_name, cache_key):
                resolved = str(index_name).strip()
                self._stock_name_cache[cache_key] = resolved
                return resolved
            return None

        lookup_code = cache_key
        # Exclude single-letter '.A' here so class-A shares like 'BRK.A' map to 'BRK-A' rather than 'BRK'.
        for suffix in (".NASDAQ", ".NYSE", ".AMEX", ".ARCA", ".US", ".N", ".O"):
            if cache_key.endswith(suffix):
                candidate_base = cache_key[: -len(suffix)]
                if self._is_us_stock(candidate_base):
                    lookup_code = candidate_base
                break

        if not (
            self._is_us_stock(lookup_code)
            or _is_hk_market(lookup_code)
            or self._is_jp_kr_suffix_stock(lookup_code)
            or self._is_tw_suffix_stock(lookup_code)
        ):
            return None

        from data_provider.base import is_stock_name_prefetch_active
        from src.core.stock_execution_context import is_current_stock_cancelled

        if not allow_network or is_stock_name_prefetch_active() or is_current_stock_cancelled():
            return None

        try:
            import yfinance as yf

            symbol = self._convert_stock_code(lookup_code)
            ticker_info = yf.Ticker(symbol).info or {}
            if not isinstance(ticker_info, dict):
                return None

            for field in ("shortName", "longName"):
                candidate = ticker_info.get(field)
                if (
                    is_meaningful_stock_name(candidate, cache_key)
                    and is_meaningful_stock_name(candidate, symbol)
                ):
                    resolved = str(candidate).strip()
                    self._stock_name_cache[cache_key] = resolved
                    return resolved
        except Exception as e:
            logger.debug(f"[Yfinance] Failed to fetch stock name for {stock_code}: {e}")

        return None


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.DEBUG)

    fetcher = YfinanceFetcher()

    try:
        df = fetcher.get_daily_data('600519')  # 茅台
        print(f"获取成功，共 {len(df)} 条数据")
        print(df.tail())
    except Exception as e:
        print(f"获取失败: {e}")
