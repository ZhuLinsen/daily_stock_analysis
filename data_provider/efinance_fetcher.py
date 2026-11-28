# -*- coding: utf-8 -*-
"""
===================================
EfinanceFetcher - 优先数据源 (Priority 0)
===================================

数据来源：东方财富爬虫（通过 efinance 库）
特点：免费、无需 Token、数据全面、API 简洁
仓库：https://github.com/Micro-sheep/efinance

与 AkshareFetcher 类似，但 efinance 库：
1. API 更简洁易用
2. 支持批量获取数据
3. 更稳定的接口封装

防封禁策略：
1. 每次请求前随机休眠 1.5-3.0 秒
2. 随机轮换 User-Agent
3. 使用 tenacity 实现指数退避重试
4. 熔断器机制：连续失败后自动冷却
"""

import logging
import os
import random
import re
import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from threading import Event, Lock
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd
import requests  # 引入 requests 以捕获异常
from src.core.stock_execution_context import stock_child_thread_pool
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

# Timeout (seconds) for efinance library calls that go through eastmoney APIs
# with no built-in timeout.  Prevents indefinite hangs when hosts are unreachable.
try:
    _EF_CALL_TIMEOUT = int(os.environ.get("EFINANCE_CALL_TIMEOUT", "30"))
except (ValueError, TypeError):
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "EFINANCE_CALL_TIMEOUT is not a valid integer, using default 30s"
    )
    _EF_CALL_TIMEOUT = 30

from src.patches.eastmoney_patch import eastmoney_patch
from src.config import get_config
from src.services.stock_list_parser import ParseStatus, parse_analysis_target
from .base import (
    BaseFetcher,
    DataFetchError,
    RateLimitError,
    STANDARD_COLUMNS,
    is_bse_code,
    is_st_stock,
    is_kc_cy_stock,
    normalize_stock_code,
    _is_hk_market,
    _is_etf_code as _is_a_share_etf_code,
)
from .realtime_types import (
    UnifiedRealtimeQuote, RealtimeSource,
    get_realtime_circuit_breaker,
    safe_float, safe_int  # 使用统一的类型转换函数
)


# 保留旧的类型别名，用于向后兼容
@dataclass
class EfinanceRealtimeQuote:
    """
    实时行情数据（来自 efinance）- 向后兼容别名
    
    新代码建议使用 UnifiedRealtimeQuote
    """
    code: str
    name: str = ""
    price: float = 0.0           # 最新价
    change_pct: float = 0.0      # 涨跌幅(%)
    change_amount: float = 0.0   # 涨跌额
    
    # 量价指标
    volume: int = 0              # 成交量
    amount: float = 0.0          # 成交额
    turnover_rate: float = 0.0   # 换手率(%)
    amplitude: float = 0.0       # 振幅(%)
    
    # 价格区间
    high: float = 0.0            # 最高价
    low: float = 0.0             # 最低价
    open_price: float = 0.0      # 开盘价
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'code': self.code,
            'name': self.name,
            'price': self.price,
            'change_pct': self.change_pct,
            'change_amount': self.change_amount,
            'volume': self.volume,
            'amount': self.amount,
            'turnover_rate': self.turnover_rate,
            'amplitude': self.amplitude,
            'high': self.high,
            'low': self.low,
            'open': self.open_price,
        }


logger = logging.getLogger(__name__)

EASTMONEY_HISTORY_ENDPOINT = "push2his.eastmoney.com/api/qt/stock/kline/get"


# User-Agent 池，用于随机轮换
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]


_realtime_cache_lock = Lock()

# 缓存实时行情数据（避免重复请求）
# TTL 设为 10 分钟 (600秒)：批量分析场景下避免重复拉取
_realtime_cache: Dict[str, Any] = {
    'data': None,
    'timestamp': 0,
    'ttl': 600  # 10分钟缓存有效期
}

# ETF 实时行情缓存（与股票分开缓存）
_etf_realtime_cache: Dict[str, Any] = {
    'data': None,
    'timestamp': 0,
    'ttl': 600  # 10分钟缓存有效期
}

_ETF_SH_PREFIXES = ('51', '52', '56', '58')
_ETF_SZ_PREFIXES = ('15', '16', '18')


def _is_etf_code(stock_code: str) -> bool:
    """
    判断代码是否为 ETF 基金
    
    ETF 代码规则：
    - 上交所 ETF: 51xxxx, 52xxxx, 56xxxx, 58xxxx
    - 深交所 ETF: 15xxxx, 16xxxx, 18xxxx
    
    Args:
        stock_code: 股票/基金代码
        
    Returns:
        True 表示是 ETF 代码，False 表示是普通股票代码
    """
    return _is_a_share_etf_code(stock_code)


def _build_eastmoney_etf_secid(stock_code: str) -> str:
    """Build Eastmoney secid for A-share ETF historical K-line queries."""
    code = normalize_stock_code(stock_code)
    if not _is_etf_code(code):
        raise DataFetchError(f"无法识别 ETF 代码 {stock_code}")
    if code.startswith(_ETF_SH_PREFIXES):
        return f"1.{code}"
    if code.startswith(_ETF_SZ_PREFIXES):
        return f"0.{code}"
    raise DataFetchError(f"无法确定 ETF {stock_code} 的 Eastmoney 市场前缀")


def _is_us_code(stock_code: str) -> bool:
    """
    判断代码是否为美股
    
    美股代码规则：
    - 1-5个大写字母，如 'AAPL', 'TSLA'
    - 可能包含 '.'，如 'BRK.B'
    """
    code = stock_code.strip().upper()
    return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', code))


def _ef_call_with_timeout(func, *args, timeout=None, **kwargs):
    """Run an efinance library call in a thread with a timeout.

    efinance internally uses requests/urllib3 with no timeout, so when
    eastmoney hosts are unreachable the call can hang for many minutes.
    This helper caps the *calling thread's* wait time.  Note: Python threads
    cannot be forcibly killed, so the worker thread may continue running in
    the background until the OS-level TCP timeout fires or the process exits.
    This is acceptable — the calling thread returns promptly on timeout.
    """
    if timeout is None:
        timeout = _EF_CALL_TIMEOUT
    # Do NOT use 'with ThreadPoolExecutor(...)' here: the context manager calls
    # shutdown(wait=True) on __exit__, which would re-block on the hung thread.
    abandoned = Event()
    executor = stock_child_thread_pool(1, "efinance", abandon_workers_when=abandoned)
    try:
        future = executor.submit(func, *args, **kwargs)
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        abandoned.set()
        raise
    finally:
        # wait=False: calling thread returns immediately; worker cleans up later
        executor.shutdown(wait=False)


def _classify_eastmoney_error(exc: Exception) -> Tuple[str, str]:
    """
    Classify Eastmoney request failures into stable log categories.
    """
    message = str(exc).strip()
    lowered = message.lower()

    remote_disconnect_keywords = (
        'remotedisconnected',
        'remote end closed connection without response',
        'connection aborted',
        'connection broken',
        'protocolerror',
    )
    timeout_keywords = (
        'timeout',
        'timed out',
        'readtimeout',
        'connecttimeout',
    )
    rate_limit_keywords = (
        'banned',
        'blocked',
        '频率',
        'rate limit',
        'too many requests',
        '429',
        '限制',
        'forbidden',
        '403',
    )

    if any(keyword in lowered for keyword in remote_disconnect_keywords):
        return "remote_disconnect", message
    if isinstance(exc, (TimeoutError, requests.exceptions.Timeout)) or any(
        keyword in lowered for keyword in timeout_keywords
    ):
        return "timeout", message
    if any(keyword in lowered for keyword in rate_limit_keywords):
        return "rate_limit_or_anti_bot", message
    if isinstance(exc, requests.exceptions.RequestException):
        return "request_error", message
    return "unknown_request_error", message


class EfinanceFetcher(BaseFetcher):
    """
    Efinance 数据源实现
    
    优先级：0（最高，优先于 AkshareFetcher）
    数据来源：东方财富网（通过 efinance 库封装）
    仓库：https://github.com/Micro-sheep/efinance
    
    主要 API：
    - ef.stock.get_quote_history(): 获取历史 K 线数据
    - ef.stock.get_base_info(): 获取股票基本信息
    - ef.stock.get_realtime_quotes(): 获取实时行情
    
    关键策略：
    - 每次请求前随机休眠 1.5-3.0 秒
    - 随机 User-Agent 轮换
    - 失败后指数退避重试（最多3次）
    """
    
    name = "EfinanceFetcher"
    priority = int(os.getenv("EFINANCE_PRIORITY", "0"))  # 最高优先级，排在 AkshareFetcher 之前
    
    def __init__(self, sleep_min: float = 1.5, sleep_max: float = 3.0):
        """
        初始化 EfinanceFetcher
        
        Args:
            sleep_min: 最小休眠时间（秒）
            sleep_max: 最大休眠时间（秒）
        """
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self._last_request_time: Optional[float] = None
        # 东财补丁开启才执行打补丁操作
        if get_config().enable_eastmoney_patch:
            eastmoney_patch()

    @staticmethod
    def _build_history_failure_message(
        stock_code: str,
        beg_date: str,
        end_date: str,
        exc: Exception,
        elapsed: float,
        is_etf: bool = False,
    ) -> Tuple[str, str]:
        category, detail = _classify_eastmoney_error(exc)
        instrument_type = "ETF" if is_etf else "stock"
        message = (
            "Eastmoney 历史K线接口失败: "
            f"endpoint={EASTMONEY_HISTORY_ENDPOINT}, stock_code={stock_code}, "
            f"market_type={instrument_type}, range={beg_date}~{end_date}, "
            f"category={category}, error_type={type(exc).__name__}, elapsed={elapsed:.2f}s, detail={detail}"
        )
        return category, message

    @staticmethod
    def _build_history_failure_log_message(
        stock_code: str,
        beg_date: str,
        end_date: str,
        exc: Exception,
        elapsed: float,
        category: str,
        is_etf: bool = False,
    ) -> str:
        instrument_type = "ETF" if is_etf else "stock"
        detail = str(exc).strip() or type(exc).__name__
        return (
            "Eastmoney historical K-line request failed: "
            f"endpoint={EASTMONEY_HISTORY_ENDPOINT}, stock_code={stock_code}, "
            f"market_type={instrument_type}, range={beg_date}~{end_date}, "
            f"category={category}, error_type={type(exc).__name__}, "
            f"elapsed={elapsed:.2f}s, detail={detail}"
        )

    def _set_random_user_agent(self) -> None:
        """
        设置随机 User-Agent
        
        通过修改 requests Session 的 headers 实现
        这是关键的反爬策略之一
        """
        try:
            random_ua = random.choice(USER_AGENTS)
            logger.debug(f"Set User-Agent: {random_ua[:50]}...")
        except Exception as e:
            logger.debug(f"Failed to set User-Agent: {e}")
    
    def _enforce_rate_limit(self) -> None:
        """
        强制执行速率限制
        
        策略：
        1. 检查距离上次请求的时间间隔
        2. 如果间隔不足，补充休眠时间
        3. 然后再执行随机 jitter 休眠
        """
        if self._last_request_time is not None:
            elapsed = time.time() - self._last_request_time
            min_interval = self.sleep_min
            if elapsed < min_interval:
                additional_sleep = min_interval - elapsed
                logger.debug(f"Additional sleep {additional_sleep:.2f}s")
                time.sleep(additional_sleep)
        
        # 执行随机 jitter 休眠
        self.random_sleep(self.sleep_min, self.sleep_max)
        self._last_request_time = time.time()
    
    @retry(
        stop=stop_after_attempt(1),  # 减少到1次，避免触发限流
        wait=wait_exponential(multiplier=1, min=4, max=60),  # 保持等待时间设置
        retry=retry_if_exception_type((
            ConnectionError,
            TimeoutError,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError
        )),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        从 efinance 获取原始数据
        
        根据代码类型自动选择 API：
        - 美股：不支持，抛出异常让 DataFetcherManager 切换到其他数据源
        - 普通股票：使用 ef.stock.get_quote_history()
        - ETF 基金：使用 ef.stock.get_quote_history()（ETF 是交易所证券，使用股票 K 线接口）
        
        流程：
        1. 判断代码类型（美股/股票/ETF）
        2. 设置随机 User-Agent
        3. 执行速率限制（随机休眠）
        4. 调用对应的 efinance API
        5. 处理返回数据
        """
        # 美股不支持，抛出异常让 DataFetcherManager 切换到 AkshareFetcher/YfinanceFetcher
        if _is_us_code(stock_code):
            raise DataFetchError(f"EfinanceFetcher 不支持美股 {stock_code}，请使用 AkshareFetcher 或 YfinanceFetcher")

        # efinance 的历史 K 线接口在港股代码上可能返回非预期市场数据，
        # 明确跳过并交给 AkShare/Tushare/YFinance/Longbridge 等港股路径兜底。
        if _is_hk_market(stock_code):
            raise DataFetchError(f"EfinanceFetcher 不支持港股日线 {stock_code}，请使用 AkshareFetcher 或其他港股数据源")
        
        # 根据代码类型选择不同的获取方法
        if _is_etf_code(stock_code):
            return self._fetch_etf_data(stock_code, start_date, end_date)
        else:
            return self._fetch_stock_data(stock_code, start_date, end_date)
    
    def _fetch_stock_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取普通 A 股历史数据
        
        数据来源：ef.stock.get_quote_history()
        
        API 参数说明：
        - stock_codes: 股票代码
        - beg: 开始日期，格式 'YYYYMMDD'
        - end: 结束日期，格式 'YYYYMMDD'
        - klt: 周期，101=日线
        - fqt: 复权方式，1=前复权
        """
        import efinance as ef
        
        # 防封禁策略 1: 随机 User-Agent
        self._set_random_user_agent()
        
        # 防封禁策略 2: 强制休眠
        self._enforce_rate_limit()
        
        # 格式化日期（efinance 使用 YYYYMMDD 格式）
        beg_date = start_date.replace('-', '')
        end_date_fmt = end_date.replace('-', '')
        
        logger.info(
            f"[API Call] ef.stock.get_quote_history(stock_codes={stock_code}, "
            f"beg={beg_date}, end={end_date_fmt}, klt=101, fqt=1)"
        )
        
        api_start = time.time()
        try:
            # 调用 efinance 获取 A 股日线数据
            # klt=101 获取日线数据
            # fqt=1 获取前复权数据
            df = _ef_call_with_timeout(
                ef.stock.get_quote_history,
                stock_codes=stock_code,
                beg=beg_date,
                end=end_date_fmt,
                klt=101,  # 日线
                fqt=1,    # 前复权
                timeout=60,
            )
            
            api_elapsed = time.time() - api_start
            
            # 记录返回数据摘要
            if df is not None and not df.empty:
                logger.info(
                    "[API Response] Eastmoney historical K-line succeeded: "
                    f"endpoint={EASTMONEY_HISTORY_ENDPOINT}, stock_code={stock_code}, "
                    f"range={beg_date}~{end_date_fmt}, rows={len(df)}, elapsed={api_elapsed:.2f}s"
                )
                logger.info(f"[API Response] Columns: {list(df.columns)}")
                if '日期' in df.columns:
                    logger.info(f"[API Response] Date range: {df['日期'].iloc[0]} ~ {df['日期'].iloc[-1]}")
                logger.debug(f"[API Response] Latest 3 rows:\n{df.tail(3).to_string()}")
            else:
                logger.warning(
                    "[API Response] Eastmoney historical K-line empty: "
                    f"endpoint={EASTMONEY_HISTORY_ENDPOINT}, stock_code={stock_code}, "
                    f"range={beg_date}~{end_date_fmt}, elapsed={api_elapsed:.2f}s"
                )
            
            return df
            
        except Exception as e:
            api_elapsed = time.time() - api_start
            category, failure_message = self._build_history_failure_message(
                stock_code=stock_code,
                beg_date=beg_date,
                end_date=end_date_fmt,
                exc=e,
                elapsed=api_elapsed,
            )

            if category == "rate_limit_or_anti_bot":
                logger.warning(
                    self._build_history_failure_log_message(
                        stock_code, beg_date, end_date_fmt, e, api_elapsed, category
                    )
                )
                raise RateLimitError(f"efinance 可能被限流: {failure_message}") from e

            logger.warning(
                self._build_history_failure_log_message(
                    stock_code, beg_date, end_date_fmt, e, api_elapsed, category
                )
            )
            raise DataFetchError(f"efinance 获取数据失败: {failure_message}") from e
    
    def _fetch_etf_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取 ETF 基金历史数据

        Exchange-traded ETFs have OHLCV data just like regular stocks, so we use
        ef.stock.get_quote_history (the stock K-line API) which returns full
        open/high/low/close/volume data.

        Previously this method used ef.fund.get_quote_history which only returns
        NAV data (单位净值/累计净值) without volume or OHLC, causing:
        - Issue #541: 'got an unexpected keyword argument beg'
        - Issue #527: ETF volume/turnover always showing 0

        Args:
            stock_code: ETF code, e.g. '512400', '159883', '515120'
            start_date: Start date, format 'YYYY-MM-DD'
            end_date: End date, format 'YYYY-MM-DD'

        Returns:
            ETF historical OHLCV DataFrame
        """
        import efinance as ef

        # Anti-ban strategy 1: random User-Agent
        self._set_random_user_agent()

        # Anti-ban strategy 2: enforce rate limit
        self._enforce_rate_limit()

        # Format dates (efinance uses YYYYMMDD)
        beg_date = start_date.replace('-', '')
        end_date_fmt = end_date.replace('-', '')
        secid = _build_eastmoney_etf_secid(stock_code)

        logger.info(
            f"[API Call] ef.stock.get_quote_history(stock_codes={secid}, "
            f"beg={beg_date}, end={end_date_fmt}, klt=101, fqt=1, "
            f"quote_id_mode=True, use_id_cache=False)  [ETF stock_code={stock_code}]"
        )

        api_start = time.time()
        try:
            # ETFs are exchange-traded securities; use the stock API to get full OHLCV data
            df = _ef_call_with_timeout(
                ef.stock.get_quote_history,
                stock_codes=secid,
                beg=beg_date,
                end=end_date_fmt,
                klt=101,  # daily
                fqt=1,    # forward-adjusted
                quote_id_mode=True,
                use_id_cache=False,
                timeout=60,
            )

            api_elapsed = time.time() - api_start

            if df is not None and not df.empty:
                logger.info(
                    "[API Response] Eastmoney historical K-line succeeded [ETF]: "
                    f"endpoint={EASTMONEY_HISTORY_ENDPOINT}, stock_code={stock_code}, secid={secid}, "
                    f"range={beg_date}~{end_date_fmt}, rows={len(df)}, elapsed={api_elapsed:.2f}s"
                )
                logger.info(f"[API Response] Columns: {list(df.columns)}")
                if '日期' in df.columns:
                    logger.info(f"[API Response] Date range: {df['日期'].iloc[0]} ~ {df['日期'].iloc[-1]}")
                logger.debug(f"[API Response] Latest 3 rows:\n{df.tail(3).to_string()}")
            else:
                logger.warning(
                    "[API Response] Eastmoney historical K-line empty [ETF]: "
                    f"endpoint={EASTMONEY_HISTORY_ENDPOINT}, stock_code={stock_code}, secid={secid}, "
                    f"range={beg_date}~{end_date_fmt}, elapsed={api_elapsed:.2f}s"
                )

            return df

        except Exception as e:
            api_elapsed = time.time() - api_start
            category, failure_message = self._build_history_failure_message(
                stock_code=stock_code,
                beg_date=beg_date,
                end_date=end_date_fmt,
                exc=e,
                elapsed=api_elapsed,
                is_etf=True,
            )

            if category == "rate_limit_or_anti_bot":
                logger.warning(
                    self._build_history_failure_log_message(
                        stock_code, beg_date, end_date_fmt, e, api_elapsed, category, is_etf=True
                    )
                )
                raise RateLimitError(f"efinance 可能被限流: {failure_message}") from e

            logger.warning(
                self._build_history_failure_log_message(
                    stock_code, beg_date, end_date_fmt, e, api_elapsed, category, is_etf=True
                )
            )
            raise DataFetchError(f"efinance 获取 ETF 数据失败: {failure_message}") from e
    
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        标准化 efinance 数据
        
        efinance 返回的列名（中文）：
        股票名称, 股票代码, 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
        
        需要映射到标准列名：
        date, open, high, low, close, volume, amount, pct_chg
        """
        df = df.copy()
        
        # Column mapping (efinance Chinese column names -> standard English column names)
        column_mapping = {
            '日期': 'date',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume',
            '成交额': 'amount',
            '涨跌幅': 'pct_chg',
            '股票代码': 'code',
            '股票名称': 'name',
        }
        
        # 重命名列
        df = df.rename(columns=column_mapping)
        
        # Fallback: if OHLC columns are missing (e.g. very old data path), fill from close
        ohlc_synthesized = False
        if 'close' in df.columns:
            for col in ('open', 'high', 'low'):
                if col not in df.columns:
                    df[col] = df['close']
                    ohlc_synthesized = True

        # Fill volume and amount if missing
        if 'volume' not in df.columns:
            df['volume'] = 0
        if 'amount' not in df.columns:
            df['amount'] = 0

        
        # 如果没有 code 列，手动添加
        if 'code' not in df.columns:
            df['code'] = stock_code
        
        # 只保留需要的列
        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]
        df.attrs['price_adjustment'] = 'forward'
        if ohlc_synthesized:
            df.attrs['ohlc_synthesized'] = True
        
        return df
    
    @staticmethod
    def _find_quote_row(df: pd.DataFrame, code_col: str, stock_code: str) -> Tuple[str, pd.DataFrame]:
        """Normalize an A-share/ETF code and return matching rows from a quote DataFrame."""
        normalized = normalize_stock_code(stock_code)
        if _is_us_code(stock_code) or _is_hk_market(stock_code):
            return normalized, df.iloc[0:0]
        target_code = normalized.zfill(6) if normalized.isdigit() else normalized
        code_series = df[code_col].astype(str).str.strip().apply(
            lambda val: val.zfill(6) if val.isdigit() else val
        )
        return target_code, df[code_series == target_code]

    def get_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取实时行情数据
        
        数据来源：ef.stock.get_realtime_quotes()
        ETF 数据源：ef.stock.get_realtime_quotes(['ETF'])
        已登记指数：东财单股 secid 接口（get_index_realtime_quote）
        
        Args:
            stock_code: 股票代码
            
        Returns:
            UnifiedRealtimeQuote 对象，获取失败返回 None
        """
        # 已登记指数走东财单股 secid 接口（Story 1.5）
        target = parse_analysis_target(stock_code)
        if target.asset_type == ParseStatus.INDEX:
            return self.get_index_realtime_quote(target.canonical_id)

        # ETF 需要单独请求 ETF 实时行情接口
        if _is_etf_code(stock_code):
            return self._get_etf_realtime_quote(stock_code)

        # US and HK equities are not included in A-share full-market spot snapshots
        if _is_us_code(stock_code) or _is_hk_market(stock_code):
            return None

        import efinance as ef
        circuit_breaker = get_realtime_circuit_breaker()
        source_key = "efinance"
        
        # 检查熔断器状态
        if not circuit_breaker.is_available(source_key):
            logger.info(f"[CircuitBreaker] Source {source_key} is open, skipping")
            return None
        
        try:
            # 检查缓存
            current_time = time.time()
            with _realtime_cache_lock:
                cached_df = _realtime_cache['data']
                cached_ts = _realtime_cache['timestamp']
                cache_ttl = _realtime_cache['ttl']
            if (cached_df is not None and
                not cached_df.empty and
                current_time - cached_ts < cache_ttl):
                df = cached_df
                cache_age = int(current_time - cached_ts)
                logger.debug(
                    f"[Cache Hit] Realtime quote(efinance) - cache age {cache_age}s/{cache_ttl}s"
                )
            else:
                # 触发全量刷新
                logger.info("[Cache Miss] Triggering full refresh for realtime quotes(efinance)")
                # 防封禁策略
                self._set_random_user_agent()
                self._enforce_rate_limit()
                
                logger.info("[API Call] ef.stock.get_realtime_quotes() fetching realtime quotes...")
                import time as _time
                api_start = _time.time()
                
                # efinance 的实时行情 API (with timeout to avoid indefinite hangs)
                df = _ef_call_with_timeout(ef.stock.get_realtime_quotes)
                api_elapsed = _time.time() - api_start

                if df is None or df.empty:
                    logger.info(
                        "[Realtime] ef.stock.get_realtime_quotes returned empty, skipping %s (elapsed %.2fs)",
                        stock_code,
                        api_elapsed,
                    )
                    return None

                logger.info(
                    f"[API Response] ef.stock.get_realtime_quotes succeeded: "
                    f"returned {len(df)} stocks, elapsed {api_elapsed:.2f}s"
                )
                circuit_breaker.record_success(source_key)
                
                # 更新缓存
                with _realtime_cache_lock:
                    _realtime_cache['data'] = df
                    _realtime_cache['timestamp'] = current_time
                logger.info(f"[Cache Update] Realtime quote(efinance) cache refreshed, TTL={cache_ttl}s")
            
            # 查找指定股票
            # efinance 返回的列名可能是 '股票代码' 或 'code'
            code_col = '股票代码' if '股票代码' in df.columns else 'code'
            if code_col not in df.columns:
                logger.warning(f"[Realtime] Missing code column in efinance quotes for {stock_code}")
                return None

            target_code, row = self._find_quote_row(df, code_col, stock_code)
            if row.empty:
                logger.info(f"[API Response] Realtime quote not found for stock {stock_code}")
                return None
            
            row = row.iloc[0]
            
            # 使用 realtime_types.py 中的统一转换函数
            # 获取列名（可能是中文或英文）
            name_col = '股票名称' if '股票名称' in df.columns else 'name'
            price_col = '最新价' if '最新价' in df.columns else 'price'
            pct_col = '涨跌幅' if '涨跌幅' in df.columns else 'pct_chg'
            chg_col = '涨跌额' if '涨跌额' in df.columns else 'change'
            vol_col = '成交量' if '成交量' in df.columns else 'volume'
            amt_col = '成交额' if '成交额' in df.columns else 'amount'
            turn_col = '换手率' if '换手率' in df.columns else 'turnover_rate'
            amp_col = '振幅' if '振幅' in df.columns else 'amplitude'
            high_col = '最高' if '最高' in df.columns else 'high'
            low_col = '最低' if '最低' in df.columns else 'low'
            open_col = '开盘' if '开盘' in df.columns else 'open'
            # efinance 也返回量比、市盈率、市值等字段
            vol_ratio_col = '量比' if '量比' in df.columns else 'volume_ratio'
            pe_col = '市盈率' if '市盈率' in df.columns else 'pe_ratio'
            total_mv_col = '总市值' if '总市值' in df.columns else 'total_mv'
            circ_mv_col = '流通市值' if '流通市值' in df.columns else 'circ_mv'

            raw_name = row.get(name_col)
            stock_name = '' if pd.isna(raw_name) else str(raw_name)
            
            quote = UnifiedRealtimeQuote(
                code=target_code,
                name=stock_name,
                source=RealtimeSource.EFINANCE,
                price=safe_float(row.get(price_col)),
                change_pct=safe_float(row.get(pct_col)),
                change_amount=safe_float(row.get(chg_col)),
                volume=safe_int(row.get(vol_col)),
                amount=safe_float(row.get(amt_col)),
                turnover_rate=safe_float(row.get(turn_col)),
                amplitude=safe_float(row.get(amp_col)),
                high=safe_float(row.get(high_col)),
                low=safe_float(row.get(low_col)),
                open_price=safe_float(row.get(open_col)),
                volume_ratio=safe_float(row.get(vol_ratio_col)),  # 量比
                pe_ratio=safe_float(row.get(pe_col)),  # 市盈率
                total_mv=safe_float(row.get(total_mv_col)),  # 总市值
                circ_mv=safe_float(row.get(circ_mv_col)),  # 流通市值
            )
            
            logger.info(
                f"[Realtime-efinance] {stock_code} {quote.name}: "
                f"price={quote.price}, change={quote.change_pct}%, "
                f"volume_ratio={quote.volume_ratio}, turnover_rate={quote.turnover_rate}%"
            )
            return quote
            
        except FuturesTimeoutError:
            logger.info(f"[Timeout] ef.stock.get_realtime_quotes() exceeded {_EF_CALL_TIMEOUT}s, skipping {stock_code}")
            circuit_breaker.record_failure(source_key, "timeout")
            return None
        except Exception as e:
            logger.info(f"[API Error] Failed to fetch realtime quote(efinance) for {stock_code}: {e}")
            circuit_breaker.record_failure(source_key, str(e))
            return None

    def get_index_realtime_quote(
        self, stock_code: str
    ) -> Optional[UnifiedRealtimeQuote]:
        """Fetch a registered CN index quote via the Eastmoney single-stock secid API.

        Supports SH (``1.{code}``), SZ (``0.{code}``) and CSI (``2.{code}``)
        secid forms. This is the only realtime source for CSI indices and the
        fallback for SH/SZ indices when Tencent/Sina fail (Story 1.5).
        """
        target = parse_analysis_target(stock_code)
        if target.asset_type != ParseStatus.INDEX or target.matched_index is None:
            return None
        entry = target.matched_index
        exchange = entry.exchange.upper()
        if exchange == "SH":
            secid = f"1.{entry.bare_code}"
        elif exchange == "SZ":
            secid = f"0.{entry.bare_code}"
        elif exchange == "CSI":
            secid = f"2.{entry.bare_code}"
        else:
            return None

        circuit_breaker = get_realtime_circuit_breaker()
        source_key = "efinance_index"
        if not circuit_breaker.is_available(source_key):
            logger.info(f"[CircuitBreaker] Source {source_key} is open, skipping")
            return None

        try:
            self._set_random_user_agent()
            self._enforce_rate_limit()
            response = requests.get(
                "https://push2.eastmoney.com/api/qt/stock/get",
                params={
                    "secid": secid,
                    "fltt": "2",
                    "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f168,f169,f170,f171",
                },
                timeout=10,
            )
            if response.status_code != 200:
                circuit_breaker.record_failure(source_key, f"HTTP {response.status_code}")
                return None
            payload = response.json()
            data = payload.get("data") or {}
            price = safe_float(data.get("f43"))
            if price is None or price <= 0:
                circuit_breaker.record_failure(source_key, "empty quote payload")
                return None
            circuit_breaker.record_success(source_key)
            quote = UnifiedRealtimeQuote(
                code=target.canonical_id,
                name=str(data.get("f58") or entry.display_name or ""),
                source=RealtimeSource.EFINANCE,
                price=price,
                change_pct=safe_float(data.get("f170")),
                change_amount=safe_float(data.get("f169")),
                volume=safe_int(data.get("f47")),
                amount=safe_float(data.get("f48")),
                amplitude=safe_float(data.get("f171")),
                high=safe_float(data.get("f44")),
                low=safe_float(data.get("f45")),
                open_price=safe_float(data.get("f46")),
                pre_close=safe_float(data.get("f60")),
                volume_ratio=safe_float(data.get("f168")),
            )
            logger.info(
                "[Realtime-EastmoneyIndex] %s %s: price=%s, change=%s%%, secid=%s",
                target.canonical_id,
                quote.name,
                quote.price,
                quote.change_pct,
                secid,
            )
            return quote
        except Exception as e:
            logger.info(f"[API Error] Failed to fetch index realtime quote(Eastmoney) for {target.canonical_id}: {e}")
            circuit_breaker.record_failure(source_key, str(e))
            return None

    def _get_etf_realtime_quote(self, stock_code: str) -> Optional[UnifiedRealtimeQuote]:
        """
        获取 ETF 实时行情

        efinance 默认实时接口仅返回股票数据，ETF 需要显式传入 ['ETF']。
        """
        import efinance as ef
        circuit_breaker = get_realtime_circuit_breaker()
        source_key = "efinance_etf"

        if not circuit_breaker.is_available(source_key):
            logger.info(f"[CircuitBreaker] Source {source_key} is open, skipping")
            return None

        try:
            current_time = time.time()
            with _realtime_cache_lock:
                cached_df = _etf_realtime_cache['data']
                cached_ts = _etf_realtime_cache['timestamp']
                cache_ttl = _etf_realtime_cache['ttl']
            if (
                cached_df is not None and
                not cached_df.empty and
                current_time - cached_ts < cache_ttl
            ):
                df = cached_df
                cache_age = int(current_time - cached_ts)
                logger.debug(
                    f"[Cache Hit] ETF realtime quote(efinance) - "
                    f"cache age {cache_age}s/{cache_ttl}s"
                )
            else:
                self._set_random_user_agent()
                self._enforce_rate_limit()

                logger.info("[API Call] ef.stock.get_realtime_quotes(['ETF']) fetching ETF realtime quotes...")
                import time as _time
                api_start = _time.time()
                df = _ef_call_with_timeout(ef.stock.get_realtime_quotes, ['ETF'])
                api_elapsed = _time.time() - api_start

                if df is None or df.empty:
                    logger.info(f"[API Response] ETF realtime quotes empty, elapsed {api_elapsed:.2f}s")
                    logger.info(f"[Realtime] ETF realtime quote data is empty(efinance), skipping {stock_code}")
                    return None

                logger.info(
                    f"[API Response] ETF realtime quotes succeeded: {len(df)} rows, elapsed {api_elapsed:.2f}s"
                )
                circuit_breaker.record_success(source_key)
                with _realtime_cache_lock:
                    _etf_realtime_cache['data'] = df
                    _etf_realtime_cache['timestamp'] = current_time

            code_col = '股票代码' if '股票代码' in df.columns else 'code'
            if code_col not in df.columns:
                logger.warning(f"[Realtime] Missing code column in efinance ETF quotes for {stock_code}")
                return None

            target_code, row = self._find_quote_row(df, code_col, stock_code)
            if row.empty:
                logger.info(f"[API Response] ETF realtime quote not found for {stock_code}(efinance)")
                return None

            row = row.iloc[0]
            name_col = '股票名称' if '股票名称' in df.columns else 'name'
            price_col = '最新价' if '最新价' in df.columns else 'price'
            pct_col = '涨跌幅' if '涨跌幅' in df.columns else 'pct_chg'
            chg_col = '涨跌额' if '涨跌额' in df.columns else 'change'
            vol_col = '成交量' if '成交量' in df.columns else 'volume'
            amt_col = '成交额' if '成交额' in df.columns else 'amount'
            turn_col = '换手率' if '换手率' in df.columns else 'turnover_rate'
            amp_col = '振幅' if '振幅' in df.columns else 'amplitude'
            high_col = '最高' if '最高' in df.columns else 'high'
            low_col = '最低' if '最低' in df.columns else 'low'
            open_col = '开盘' if '开盘' in df.columns else 'open'

            raw_name = row.get(name_col)
            etf_name = '' if pd.isna(raw_name) else str(raw_name)

            quote = UnifiedRealtimeQuote(
                code=target_code,
                name=etf_name,
                source=RealtimeSource.EFINANCE,
                price=safe_float(row.get(price_col)),
                change_pct=safe_float(row.get(pct_col)),
                change_amount=safe_float(row.get(chg_col)),
                volume=safe_int(row.get(vol_col)),
                amount=safe_float(row.get(amt_col)),
                turnover_rate=safe_float(row.get(turn_col)),
                amplitude=safe_float(row.get(amp_col)),
                high=safe_float(row.get(high_col)),
                low=safe_float(row.get(low_col)),
                open_price=safe_float(row.get(open_col)),
            )

            logger.info(
                f"[ETF Realtime-efinance] {target_code} {quote.name}: "
                f"price={quote.price}, change={quote.change_pct}%, turnover_rate={quote.turnover_rate}%"
            )
            return quote
        except Exception as e:
            logger.info(f"[API Error] Failed to fetch ETF realtime quote(efinance) for {stock_code}: {e}")
            circuit_breaker.record_failure(source_key, str(e))
            return None

    def get_main_indices(self, region: str = "cn") -> Optional[List[Dict[str, Any]]]:
        """
        获取主要指数实时行情 (efinance)，仅支持 A 股
        """
        if region != "cn":
            return None
        import efinance as ef

        indices_map = {
            '000001': ('上证指数', 'sh000001'),
            '399001': ('深证成指', 'sz399001'),
            '399006': ('创业板指', 'sz399006'),
            '000688': ('科创50', 'sh000688'),
            '000016': ('上证50', 'sh000016'),
            '000300': ('沪深300', 'sh000300'),
        }

        try:
            self._set_random_user_agent()
            self._enforce_rate_limit()

            logger.info("[API Call] Calling ef.stock.get_realtime_quotes for SH/SZ index quotes...")
            import time as _time
            api_start = _time.time()
            df = _ef_call_with_timeout(ef.stock.get_realtime_quotes, ['沪深系列指数'])
            api_elapsed = _time.time() - api_start

            if df is None or df.empty:
                logger.warning(f"[API Response] Index quotes empty, elapsed {api_elapsed:.2f}s")
                return None

            logger.info(f"[API Response] Index quotes succeeded: {len(df)} rows, elapsed {api_elapsed:.2f}s")
            code_col = '股票代码' if '股票代码' in df.columns else 'code'
            if code_col not in df.columns:
                logger.warning("[efinance] Missing code column in index quotes response")
                return None
            code_series = df[code_col].astype(str).str.strip().str.zfill(6)

            results: List[Dict[str, Any]] = []
            for code, (name, full_code) in indices_map.items():
                row = df[code_series == code]
                if row.empty:
                    continue
                item = row.iloc[0]

                price_col = '最新价' if '最新价' in df.columns else 'price'
                pct_col = '涨跌幅' if '涨跌幅' in df.columns else 'pct_chg'
                chg_col = '涨跌额' if '涨跌额' in df.columns else 'change'
                open_cols = [column for column in ('今开', '开盘', 'open') if column in df.columns]
                high_col = '最高' if '最高' in df.columns else 'high'
                low_col = '最低' if '最低' in df.columns else 'low'
                vol_col = '成交量' if '成交量' in df.columns else 'volume'
                amt_col = '成交额' if '成交额' in df.columns else 'amount'
                amp_col = '振幅' if '振幅' in df.columns else 'amplitude'

                current = safe_float(item.get(price_col))
                change_amount = safe_float(item.get(chg_col))
                change_pct = safe_float(item.get(pct_col))
                if current is None or current <= 0 or change_amount is None or change_pct is None:
                    logger.warning(
                        "[efinance] Index quote %s missing valid price/change fields; aborting partial index payload",
                        full_code,
                    )
                    return None
                open_price = 0.0
                for column in open_cols:
                    candidate = safe_float(item.get(column), default=None)
                    if candidate not in (None, 0.0):
                        open_price = candidate
                        break
                if open_price == 0.0 and open_cols:
                    open_price = safe_float(item.get(open_cols[0], 0), default=0.0)

                results.append({
                    'code': full_code,
                    'name': name,
                    'current': current,
                    'change': change_amount,
                    'change_pct': change_pct,
                    'open': open_price,
                    'high': safe_float(item.get(high_col, 0), default=0.0),
                    'low': safe_float(item.get(low_col, 0), default=0.0),
                    'prev_close': current - change_amount,
                    'volume': safe_float(item.get(vol_col, 0), default=0.0),
                    'amount': safe_float(item.get(amt_col, 0), default=0.0),
                    'amplitude': safe_float(item.get(amp_col, 0), default=0.0),
                })

            if results:
                logger.info(f"[efinance] Fetched {len(results)} index quotes")
            return results if results else None
        except Exception as e:
            logger.error(f"[efinance] Failed to fetch index quotes: {e}")
            return None

    def get_market_stats(self, *, allow_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        获取市场涨跌统计 (efinance)
        """
        import efinance as ef

        try:
            self._set_random_user_agent()
            self._enforce_rate_limit()

            current_time = time.time()
            with _realtime_cache_lock:
                cached_df = _realtime_cache['data']
                cached_ts = _realtime_cache['timestamp']
                cache_ttl = _realtime_cache['ttl']
            if (
                allow_cache and cached_df is not None and not cached_df.empty and
                current_time - cached_ts < cache_ttl
            ):
                df = cached_df
                logger.info(
                    "[MarketStats] component=market_stats provider=EfinanceFetcher "
                    "api=ef.stock.get_realtime_quotes action=cache_hit cache_age=%.0fs",
                    current_time - cached_ts,
                )
            else:
                started_at = time.monotonic()
                logger.info(
                    "[MarketStats] component=market_stats provider=EfinanceFetcher "
                    "api=ef.stock.get_realtime_quotes action=request_start"
                )
                df = _ef_call_with_timeout(ef.stock.get_realtime_quotes)
                elapsed = time.monotonic() - started_at
                logger.info(
                    "[MarketStats] component=market_stats provider=EfinanceFetcher "
                    "api=ef.stock.get_realtime_quotes action=request_complete elapsed=%.2fs",
                    elapsed,
                )
                if df is None or df.empty:
                    logger.warning(
                        "[MarketStats] component=market_stats provider=EfinanceFetcher "
                        "api=ef.stock.get_realtime_quotes action=parse status=empty"
                    )
                    return None
                stats = self._calc_market_stats(df)
                if stats is None:
                    return None
                with _realtime_cache_lock:
                    _realtime_cache['data'] = df
                    _realtime_cache['timestamp'] = current_time
                return stats

            return self._calc_market_stats(df)
        except Exception as e:
            logger.error(
                "[MarketStats] component=market_stats provider=EfinanceFetcher "
                "api=ef.stock.get_realtime_quotes action=failed error=%s",
                e,
            )
            return None
        
    def _calc_market_stats(
        self,
        df: pd.DataFrame,
        ) -> Optional[Dict[str, Any]]:
        """从行情 DataFrame 计算涨跌统计。"""
        import numpy as np

        df = df.copy()
        
        # 1. 提取基础比对数据：最新价、昨收
        # 兼容不同接口返回的列名 sina/em efinance tushare xtdata
        code_col = next((c for c in ['代码', '股票代码', 'ts_code','stock_code'] if c in df.columns), None)
        name_col = next((c for c in ['名称', '股票名称','name','name'] if c in df.columns), None)
        close_col = next((c for c in ['最新价', '最新价', 'close','lastPrice'] if c in df.columns), None)
        pre_close_col = next((c for c in ['昨收', '昨日收盘', 'pre_close','lastClose'] if c in df.columns), None)
        amount_col = next((c for c in ['成交额', '成交额', 'amount','amount'] if c in df.columns), None) 
        
        if code_col is None or close_col is None or pre_close_col is None:
            return None

        codes = df[code_col]
        names = df[name_col] if name_col else [""] * len(df)
        amounts = df[amount_col] if amount_col else [None] * len(df)

        limit_up_count = 0
        limit_down_count = 0
        up_count = 0
        down_count = 0
        flat_count = 0
        counted_rows = 0

        for code, name, raw_close, raw_pre_close, raw_amount in zip(
            codes, names, df[close_col], df[pre_close_col], amounts
        ):
            current_price = safe_float(raw_close)
            pre_close = safe_float(raw_pre_close)
            amount_val = safe_float(raw_amount)

            # 停牌过滤：缺失价格、无效昨收、或成交额为 0 均跳过
            if (
                current_price is None
                or pre_close is None
                or pre_close <= 0
                or (amount_val is not None and amount_val == 0)
            ):
                continue

            code_str = "" if pd.isna(code) else str(code).strip()
            name_str = "" if pd.isna(name) else str(name).strip()

            # 获取去除前缀的纯数字代码；缺代码行不可归类板块，直接跳过以免误计
            pure_code = normalize_stock_code(code_str)
            if not pure_code:
                continue

            if current_price > 0:
                counted_rows += 1
                # A. 确定涨跌幅阈值：缺失名称的主板/普通股票无法判断是否为 ST (5%)，跳过涨跌停分类
                can_classify_limits = bool(name_str) or is_bse_code(pure_code) or is_kc_cy_stock(pure_code)
                if can_classify_limits:
                    if is_bse_code(pure_code):
                        ratio = 0.30
                    elif is_kc_cy_stock(pure_code):
                        ratio = 0.20
                    elif is_st_stock(name_str):
                        ratio = 0.05
                    else:
                        ratio = 0.10

                    # B. 严格按照 A 股规则计算涨跌停价：昨收 * (1 ± 比例) -> 四舍五入保留2位小数
                    limit_up_price = np.floor(pre_close * (1 + ratio) * 100 + 0.5) / 100.0
                    limit_down_price = np.floor(pre_close * (1 - ratio) * 100 + 0.5) / 100.0

                    limit_up_price_Tolerance = round(abs(pre_close * (1 + ratio) - limit_up_price), 10)
                    limit_down_price_Tolerance = round(abs(pre_close * (1 - ratio) - limit_down_price), 10)

                    # C. 精确比对
                    is_limit_up = abs(current_price - limit_up_price) <= limit_up_price_Tolerance
                    is_limit_down = abs(current_price - limit_down_price) <= limit_down_price_Tolerance

                    if is_limit_up:
                        limit_up_count += 1
                    if is_limit_down:
                        limit_down_count += 1

                if current_price > pre_close:
                    up_count += 1
                elif current_price < pre_close:
                    down_count += 1
                else:
                    flat_count += 1

        if counted_rows == 0:
            return None
                
        # 统计数量
        stats = {
            'up_count': up_count,
            'down_count': down_count,
            'flat_count': flat_count,
            'limit_up_count': limit_up_count,
            'limit_down_count': limit_down_count,
            'total_amount': 0.0,
        }
        
        # 成交额统计
        if amount_col and amount_col in df.columns:
            numeric_amount = pd.to_numeric(df[amount_col], errors='coerce')
            total_amount = numeric_amount.sum(min_count=1)
            stats['total_amount'] = float(total_amount) / 1e8 if pd.notna(total_amount) else 0.0
            
        return stats

    def get_sector_rankings(self, n: int = 5) -> Optional[Tuple[List[Dict], List[Dict]]]:
        """
        获取板块涨跌榜 (efinance)
        """
        import efinance as ef

        try:
            self._set_random_user_agent()
            self._enforce_rate_limit()

            logger.info("[API Call] Calling ef.stock.get_realtime_quotes for industry sector quotes...")
            df = _ef_call_with_timeout(ef.stock.get_realtime_quotes, ['行业板块'])
            if df is None or df.empty:
                logger.warning("[efinance] Sector quote data is empty")
                return None

            change_col = '涨跌幅' if '涨跌幅' in df.columns else 'pct_chg'
            name_col = '股票名称' if '股票名称' in df.columns else 'name'
            if change_col not in df.columns or name_col not in df.columns:
                return None

            df = df.copy()
            df[change_col] = pd.to_numeric(df[change_col], errors='coerce')
            df = df.dropna(subset=[change_col, name_col])
            df[name_col] = df[name_col].astype(str).str.strip()
            df = df[df[name_col] != '']
            if df.empty:
                return None

            top = df.nlargest(n, change_col)
            bottom = df.nsmallest(n, change_col)

            top_sectors = [
                {'name': row[name_col], 'change_pct': float(row[change_col])}
                for _, row in top.iterrows()
            ]
            bottom_sectors = [
                {'name': row[name_col], 'change_pct': float(row[change_col])}
                for _, row in bottom.iterrows()
            ]
            return top_sectors, bottom_sectors
        except Exception as e:
            logger.error(f"[efinance] Failed to fetch sector rankings: {e}")
            return None
    
    def get_base_info(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        获取股票基本信息
        
        数据来源：ef.stock.get_base_info()
        包含：市盈率、市净率、所处行业、总市值、流通市值、ROE、净利率等
        
        Args:
            stock_code: 股票代码
            
        Returns:
            包含基本信息的字典，获取失败返回 None
        """
        import efinance as ef
        
        try:
            # 防封禁策略
            self._set_random_user_agent()
            self._enforce_rate_limit()
            
            logger.info(f"[API Call] ef.stock.get_base_info(stock_codes={stock_code}) fetching base info...")
            import time as _time
            api_start = _time.time()
            
            info = _ef_call_with_timeout(ef.stock.get_base_info, stock_code)
            
            api_elapsed = _time.time() - api_start
            logger.info(f"[API Response] ef.stock.get_base_info succeeded, elapsed {api_elapsed:.2f}s")
            
            if info is None:
                logger.warning(f"[API Response] Base info not found for {stock_code}")
                return None
            
            # 转换为字典
            if isinstance(info, pd.Series):
                return info.to_dict()
            elif isinstance(info, pd.DataFrame):
                if not info.empty:
                    return info.iloc[0].to_dict()
            
            return None
            
        except Exception as e:
            logger.error(f"[API Error] Failed to fetch base info for {stock_code}: {e}")
            return None
    
    def get_belong_board(self, stock_code: str) -> Optional[pd.DataFrame]:
        """
        获取股票所属板块
        
        数据来源：ef.stock.get_belong_board()
        
        Args:
            stock_code: 股票代码
            
        Returns:
            所属板块 DataFrame，获取失败返回 None
        """
        import efinance as ef
        
        try:
            # 防封禁策略
            self._set_random_user_agent()
            self._enforce_rate_limit()
            
            logger.info(f"[API Call] ef.stock.get_belong_board(stock_code={stock_code}) fetching belong board...")
            import time as _time
            api_start = _time.time()
            
            df = _ef_call_with_timeout(ef.stock.get_belong_board, stock_code)
            
            api_elapsed = _time.time() - api_start
            
            if df is not None and not df.empty:
                logger.info(
                    f"[API Response] ef.stock.get_belong_board succeeded: "
                    f"returned {len(df)} boards, elapsed {api_elapsed:.2f}s"
                )
                return df
            else:
                logger.warning(f"[API Response] Board info not found for {stock_code}")
                return None
            
        except FuturesTimeoutError:
            logger.warning(f"[Timeout] ef.stock.get_belong_board({stock_code}) exceeded {_EF_CALL_TIMEOUT}s, skipping")
            return None
        except Exception as e:
            logger.error(f"[API Error] Failed to fetch belong board for {stock_code}: {e}")
            return None
    
    def get_enhanced_data(self, stock_code: str, days: int = 60) -> Dict[str, Any]:
        """
        获取增强数据（历史K线 + 实时行情 + 基本信息）
        
        Args:
            stock_code: 股票代码
            days: 历史数据天数
            
        Returns:
            包含所有数据的字典
        """
        result = {
            'code': stock_code,
            'daily_data': None,
            'realtime_quote': None,
            'base_info': None,
            'belong_board': None,
        }
        
        # 获取日线数据
        try:
            df = self.get_daily_data(stock_code, days=days)
            result['daily_data'] = df
        except Exception as e:
            logger.error(f"Failed to fetch daily data for {stock_code}: {e}")
        
        # 获取实时行情
        result['realtime_quote'] = self.get_realtime_quote(stock_code)
        
        # 获取基本信息
        result['base_info'] = self.get_base_info(stock_code)
        
        # 获取所属板块
        result['belong_board'] = self.get_belong_board(stock_code)
        
        return result


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.DEBUG)
    
    fetcher = EfinanceFetcher()
    
    # 测试普通股票
    print("=" * 50)
    print("测试普通股票数据获取 (efinance)")
    print("=" * 50)
    try:
        df = fetcher.get_daily_data('600519')  # 茅台
        print(f"[股票] 获取成功，共 {len(df)} 条数据")
        print(df.tail())
    except Exception as e:
        print(f"[股票] 获取失败: {e}")
    
    # 测试 ETF 基金
    print("\n" + "=" * 50)
    print("测试 ETF 基金数据获取 (efinance)")
    print("=" * 50)
    try:
        df = fetcher.get_daily_data('512400')  # 有色龙头ETF
        print(f"[ETF] 获取成功，共 {len(df)} 条数据")
        print(df.tail())
    except Exception as e:
        print(f"[ETF] 获取失败: {e}")
    
    # 测试实时行情
    print("\n" + "=" * 50)
    print("测试实时行情获取 (efinance)")
    print("=" * 50)
    try:
        quote = fetcher.get_realtime_quote('600519')
        if quote:
            print(f"[实时行情] {quote.name}: 价格={quote.price}, 涨跌幅={quote.change_pct}%")
        else:
            print("[实时行情] 未获取到数据")
    except Exception as e:
        print(f"[实时行情] 获取失败: {e}")
    
    # 测试基本信息
    print("\n" + "=" * 50)
    print("测试基本信息获取 (efinance)")
    print("=" * 50)
    try:
        info = fetcher.get_base_info('600519')
        if info:
            print(f"[基本信息] 市盈率={info.get('市盈率(动)', 'N/A')}, 市净率={info.get('市净率', 'N/A')}")
        else:
            print("[基本信息] 未获取到数据")
    except Exception as e:
        print(f"[基本信息] 获取失败: {e}")

    # 测试市场统计 
    print("\n" + "=" * 50)
    print("Testing get_market_stats (efinance)")
    print("=" * 50)
    try:
        stats = fetcher.get_market_stats()
        if stats:
            print(f"Market Stats successfully computed:")
            print(f"Up: {stats['up_count']} (Limit Up: {stats['limit_up_count']})")
            print(f"Down: {stats['down_count']} (Limit Down: {stats['limit_down_count']})")
            print(f"Flat: {stats['flat_count']}")
            print(f"Total Amount: {stats['total_amount']:.2f} 亿 (Yi)")
        else:
            print("Failed to compute market stats.")
    except Exception as e:
        print(f"Failed to compute market stats: {e}")
