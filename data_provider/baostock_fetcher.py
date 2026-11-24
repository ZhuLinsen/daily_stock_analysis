# -*- coding: utf-8 -*-
"""
===================================
BaostockFetcher - 备用数据源 2 (Priority 3)
===================================

数据来源：证券宝（Baostock）
特点：免费、无需 Token、需要登录管理
优点：稳定、无配额限制

关键策略：
1. 管理 bs.login() 和 bs.logout() 生命周期
2. 使用上下文管理器防止连接泄露
3. 失败后指数退避重试
"""

import inspect
import logging
import re
from concurrent.futures import CancelledError
from contextlib import contextmanager
from threading import RLock
from typing import Dict, Generator, Optional

import pandas as pd
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .base import (
    BaseFetcher,
    DataFetchError,
    STANDARD_COLUMNS,
    is_bse_code,
    normalize_stock_code,
    _is_hk_market,
)
from src.core.stock_execution_context import (
    get_current_stock_cancellation,
    raise_if_stock_cancelled,
)
import os

logger = logging.getLogger(__name__)

# baostock uses process-global socket/login state, so sessions must be serialized.
BAOSTOCK_SESSION_LOCK = RLock()
_BAOSTOCK_SESSION_LOCK = BAOSTOCK_SESSION_LOCK


@contextmanager
def _acquire_baostock_lock() -> Generator[None, None, None]:
    """Acquire the shared process-wide Baostock lock with cancellation checks."""
    if get_current_stock_cancellation() is None:
        with BAOSTOCK_SESSION_LOCK:
            yield
        return

    raise_if_stock_cancelled()
    while not BAOSTOCK_SESSION_LOCK.acquire(timeout=0.05):
        raise_if_stock_cancelled()
    try:
        raise_if_stock_cancelled()
        yield
    finally:
        BAOSTOCK_SESSION_LOCK.release()


_BAOSTOCK_RESULT_SKIPS_NON_FULL_PAGE: Dict[type, bool] = {}


def _baostock_next_full_page_size(rs: object) -> Optional[int]:
    """Return full page size when ResultData.next() skips short final pages (baostock >=0.9.4)."""
    rs_type = type(rs)
    skips_short_page = _BAOSTOCK_RESULT_SKIPS_NON_FULL_PAGE.get(rs_type)
    if skips_short_page is None:
        next_fn = getattr(rs_type, "next", None)
        if next_fn is None:
            skips_short_page = False
        else:
            try:
                skips_short_page = "BAOSTOCK_PER_PAGE_COUNT" in inspect.getsource(next_fn)
            except (OSError, TypeError):
                skips_short_page = False
        _BAOSTOCK_RESULT_SKIPS_NON_FULL_PAGE[rs_type] = skips_short_page

    if not skips_short_page:
        return None
    try:
        import baostock.common.contants as bs_cons

        page_size = int(getattr(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 0) or 0)
        return page_size if page_size > 0 else None
    except Exception:
        return None


def check_baostock_pagination_complete(
    rs: object,
    *,
    transient_exc_type: type[Exception] = ConnectionError,
    fatal_exc_type: type[Exception] = DataFetchError,
) -> None:
    """Verify a Baostock ResultData cursor terminated cleanly rather than mid-pagination."""
    error_code = str(getattr(rs, "error_code", "0") or "").strip()
    error_msg = str(getattr(rs, "error_msg", "") or "").strip()
    if error_code != "0":
        msg = f"Baostock pagination failed ({error_code}): {error_msg}"
        if _is_transient_network_error(error_code, error_msg):
            raise transient_exc_type(msg)
        raise fatal_exc_type(msg)

    raw_data = getattr(rs, "data", None)
    cur_row_num = getattr(rs, "cur_row_num", None)
    if (
        isinstance(raw_data, list)
        and isinstance(cur_row_num, int)
        and len(raw_data) > 0
        and cur_row_num >= len(raw_data)
    ):
        full_page_size = _baostock_next_full_page_size(rs)
        if full_page_size is None or len(raw_data) == full_page_size:
            raise transient_exc_type(
                "Baostock pagination interrupted: subsequent page returned no response"
            )


def _is_transient_network_error(error_code: object, error_msg: object) -> bool:
    """Return True when Baostock reports a transient network/socket failure."""
    code = str(error_code or "").strip()
    msg = str(error_msg or "").strip()
    msg_lower = msg.lower()
    return code == "10002007" or any(
        token in msg or token in msg_lower
        for token in (
            "网络",
            "接收",
            "超时",
            "timeout",
            "connection",
            "socket",
            "broken pipe",
            "reset by peer",
        )
    )


def _is_us_code(stock_code: str) -> bool:
    """
    判断代码是否为美股
    
    美股代码规则：
    - 1-5个大写字母，如 'AAPL', 'TSLA'
    - 可能包含 '.'，如 'BRK.B'
    """
    code = stock_code.strip().upper()
    return bool(re.match(r'^[A-Z]{1,5}(\.[A-Z])?$', code))


class BaostockFetcher(BaseFetcher):
    """
    Baostock 数据源实现
    
    优先级：3
    数据来源：证券宝 Baostock API
    
    关键策略：
    - 使用上下文管理器管理连接生命周期
    - 每次请求都重新登录/登出，防止连接泄露
    - 失败后指数退避重试
    
    Baostock 特点：
    - 免费、无需注册
    - 需要显式登录/登出
    - 数据更新略有延迟（T+1）
    """
    
    name = "BaostockFetcher"
    priority = int(os.getenv("BAOSTOCK_PRIORITY", "3"))
    
    def __init__(self):
        """初始化 BaostockFetcher"""
        self._bs_module = None
        self._stock_name_cache: Dict[str, str] = {}
        self._cache_lock = RLock()
    
    def _get_baostock(self):
        """
        延迟加载 baostock 模块
        
        只在首次使用时导入，避免未安装时报错
        """
        if self._bs_module is None:
            import baostock as bs
            self._bs_module = bs
        return self._bs_module
    
    @contextmanager
    def _baostock_session(self) -> Generator:
        """
        Baostock 连接上下文管理器
        
        确保：
        1. 进入上下文时自动登录（通过模块级锁串行化全局会话）
        2. 退出上下文时自动登出（仅在登录成功时登出）
        3. 异常时也能正确登出并释放锁
        
        使用示例：
            with self._baostock_session():
                # 在这里执行数据查询
        """
        bs = self._get_baostock()
        with _acquire_baostock_lock():
            logged_in = False
            try:
                raise_if_stock_cancelled()
                # 登录 Baostock
                login_result = bs.login()
                
                if login_result.error_code != '0':
                    msg = f"Baostock 登录失败: {login_result.error_msg}"
                    if _is_transient_network_error(login_result.error_code, login_result.error_msg):
                        raise ConnectionError(msg)
                    raise DataFetchError(msg)
                
                logged_in = True
                raise_if_stock_cancelled()
                logger.debug("Baostock login succeeded")
                
                yield bs
                
            finally:
                # 确保登出，防止连接泄露；未登录成功时不调用 logout
                if logged_in:
                    try:
                        logout_result = bs.logout()
                        if logout_result.error_code == '0':
                            logger.debug("Baostock logout succeeded")
                        else:
                            logger.warning(f"Baostock logout abnormal: {logout_result.error_msg}")
                    except Exception as e:
                        logger.warning(f"Error during Baostock logout: {e}")
    
    def _convert_stock_code(self, stock_code: str) -> str:
        """
        转换股票代码为 Baostock 格式
        
        Baostock 要求的格式：
        - 沪市：sh.600519
        - 深市：sz.000001
        
        Args:
            stock_code: 原始代码，如 '600519', '000001'
            
        Returns:
            Baostock 格式代码，如 'sh.600519', 'sz.000001'
        """
        raw_code = stock_code.strip()
        upper = raw_code.upper()

        # HK stocks are not supported by Baostock
        if _is_hk_market(raw_code):
            raise DataFetchError(f"BaostockFetcher 不支持港股 {raw_code}，请使用 AkshareFetcher")

        # 保留既有小写 baostock 格式输入的内部容错，但用户配置仍推荐 6 位裸代码。
        if raw_code.startswith(('sh.', 'sz.')):
            return raw_code.lower()

        exchange_hint = None
        if upper.startswith(('SH', 'SS')) or upper.endswith(('.SH', '.SS')):
            exchange_hint = 'sh'
        elif upper.startswith('SZ') or upper.endswith('.SZ'):
            exchange_hint = 'sz'

        code = normalize_stock_code(raw_code)

        if exchange_hint in ('sh', 'sz') and code.isdigit() and len(code) == 6:
            return f"{exchange_hint}.{code}"
        
        # ETF: Shanghai ETF (51xx, 52xx, 56xx, 58xx) -> sh; Shenzhen ETF (15xx, 16xx, 18xx) -> sz
        if len(code) == 6:
            if code.startswith(('51', '52', '56', '58')):
                return f"sh.{code}"
            if code.startswith(('15', '16', '18')):
                return f"sz.{code}"

        # 根据代码前缀判断市场（60/68 沪市含科创板 688/689；00/30 深市）
        if code.startswith(('60', '68')):
            return f"sh.{code}"
        elif code.startswith(('000', '001', '002', '003', '300', '301')):
            return f"sz.{code}"
        else:
            logger.warning(f"Cannot determine market for stock {code}, defaulting to SZ")
            return f"sz.{code}"
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        从 Baostock 获取原始数据
        
        使用 query_history_k_data_plus() 获取日线数据
        
        流程：
        1. 检查是否为美股（不支持）
        2. 使用上下文管理器管理连接
        3. 转换股票代码格式
        4. 调用 API 查询数据
        5. 将结果转换为 DataFrame
        """
        # 美股不支持，抛出异常让 DataFetcherManager 切换到其他数据源
        if _is_us_code(stock_code):
            raise DataFetchError(f"BaostockFetcher 不支持美股 {stock_code}，请使用 AkshareFetcher 或 YfinanceFetcher")

        # 港股不支持，抛出异常让 DataFetcherManager 切换到其他数据源
        if _is_hk_market(stock_code):
            raise DataFetchError(f"BaostockFetcher 不支持港股 {stock_code}，请使用 AkshareFetcher")

        # 北交所不支持，抛出异常让 DataFetcherManager 切换到其他数据源
        if is_bse_code(stock_code):
            raise DataFetchError(
                f"BaostockFetcher 不支持北交所 {stock_code}，将自动切换其他数据源"
            )
        
        # 转换代码格式
        bs_code = self._convert_stock_code(stock_code)
        
        logger.debug(f"Calling Baostock query_history_k_data_plus({bs_code}, {start_date}, {end_date})")
        
        with self._baostock_session() as bs:
            try:
                # 查询日线数据
                # adjustflag: 1-后复权，2-前复权，3-不复权
                rs = bs.query_history_k_data_plus(
                    code=bs_code,
                    fields="date,open,high,low,close,volume,amount,pctChg",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",  # 日线
                    adjustflag="2"  # 前复权
                )
                
                if rs.error_code != '0':
                    msg = f"Baostock 查询失败: {rs.error_msg}"
                    if _is_transient_network_error(rs.error_code, rs.error_msg):
                        raise ConnectionError(msg)
                    raise DataFetchError(msg)
                
                # 转换为 DataFrame
                data_list = []
                while True:
                    raise_if_stock_cancelled()
                    if not rs.next():
                        break
                    data_list.append(rs.get_row_data())

                check_baostock_pagination_complete(
                    rs,
                    transient_exc_type=ConnectionError,
                    fatal_exc_type=DataFetchError,
                )

                if not data_list:
                    raise DataFetchError(f"Baostock 未查询到 {stock_code} 的数据")
                
                df = pd.DataFrame(data_list, columns=rs.fields)
                
                return df
                
            except (DataFetchError, ConnectionError, TimeoutError, CancelledError):
                raise
            except Exception as e:
                raise DataFetchError(f"Baostock 获取数据失败: {e}") from e
    
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        标准化 Baostock 数据
        
        Baostock 返回的列名：
        date, open, high, low, close, volume, amount, pctChg
        
        需要映射到标准列名：
        date, open, high, low, close, volume, amount, pct_chg
        """
        df = df.copy()
        
        # 列名映射（只需要处理 pctChg）
        column_mapping = {
            'pctChg': 'pct_chg',
        }
        
        df = df.rename(columns=column_mapping)

        if 'date' in df.columns:
            df = df[df['date'].notna()].copy()
            date_str = df['date'].astype(str).str.strip()
            valid_dates = date_str != ''
            df = df[valid_dates].copy()
            df['date'] = date_str[valid_dates]
            df = df.sort_values('date', ascending=True).reset_index(drop=True)
        
        # 数值类型转换（Baostock 返回的都是字符串）
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 添加股票代码列
        df['code'] = stock_code
        
        # 只保留需要的列
        keep_cols = ['code'] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        df = df[existing_cols]
        
        return df

    def get_stock_name(self, stock_code: str) -> Optional[str]:
        """
        获取股票名称
        
        使用 Baostock 的 query_stock_basic 接口获取股票基本信息
        
        Args:
            stock_code: 股票代码
            
        Returns:
            股票名称，失败返回 None
        """
        if _is_us_code(stock_code) or _is_hk_market(stock_code) or is_bse_code(stock_code):
            return None

        try:
            bs_code = self._convert_stock_code(stock_code)
        except DataFetchError:
            return None

        # 检查缓存（使用带交易所前缀的 bs_code 键，避免 000001 上证指数与深市平安银行混淆）
        with self._cache_lock:
            if bs_code in self._stock_name_cache:
                return self._stock_name_cache[bs_code]
        
        try:
            with self._baostock_session() as bs:
                # 查询股票基本信息
                rs = bs.query_stock_basic(code=bs_code)
                
                if rs.error_code == '0':
                    data_list = []
                    while True:
                        raise_if_stock_cancelled()
                        if not rs.next():
                            break
                        data_list.append(rs.get_row_data())

                    check_baostock_pagination_complete(
                        rs,
                        transient_exc_type=ConnectionError,
                        fatal_exc_type=DataFetchError,
                    )

                    if data_list:
                        # Baostock 返回的字段：code, code_name, ipoDate, outDate, type, status
                        fields = rs.fields
                        name_idx = fields.index('code_name') if 'code_name' in fields else None
                        if name_idx is not None and len(data_list[0]) > name_idx:
                            name = str(data_list[0][name_idx] or '').strip()
                            if name:
                                with self._cache_lock:
                                    self._stock_name_cache[bs_code] = name
                                logger.debug(f"Baostock fetched stock name: {bs_code} -> {name}")
                                return name
                
        except CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Baostock failed to fetch stock name for {stock_code}: {e}")
        
        return None
    
    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """
        获取股票列表
        
        使用 Baostock 的 query_stock_basic 接口获取全部股票列表
        
        Returns:
            包含 code, name 列的 DataFrame，失败返回 None
        """
        try:
            with self._baostock_session() as bs:
                # 查询所有股票基本信息
                rs = bs.query_stock_basic()
                
                if rs.error_code == '0':
                    data_list = []
                    while True:
                        raise_if_stock_cancelled()
                        if not rs.next():
                            break
                        data_list.append(rs.get_row_data())

                    check_baostock_pagination_complete(
                        rs,
                        transient_exc_type=ConnectionError,
                        fatal_exc_type=DataFetchError,
                    )

                    if data_list:
                        df = pd.DataFrame(data_list, columns=rs.fields)
                        if 'code' not in df.columns or 'code_name' not in df.columns:
                            return None
                        
                        # Preserve exchange-qualified codes (e.g. sh.000001 vs sz.000001) for cache keys
                        raw_bs_codes = df['code'].fillna('').astype(str).str.strip().str.lower()
                        df['code'] = raw_bs_codes.apply(
                            lambda x: x.split('.', 1)[1].strip() if '.' in x else x
                        )
                        df = df.rename(columns={'code_name': 'name'})
                        df['name'] = df['name'].fillna('').astype(str).str.strip()
                        valid_mask = (df['code'] != '') & (df['name'] != '')
                        df = df[valid_mask].reset_index(drop=True)
                        valid_bs_codes = raw_bs_codes[valid_mask].tolist()
                        if df.empty:
                            return None
                        
                        # 更新缓存（使用带交易所前缀的 Baostock 代码）
                        with self._cache_lock:
                            for raw_bs_code, name_val in zip(valid_bs_codes, df['name']):
                                if raw_bs_code:
                                    self._stock_name_cache[raw_bs_code] = name_val
                        
                        logger.info(f"Baostock fetched stock list successfully: {len(df)} records")
                        return df[['code', 'name']]
                
        except CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Baostock failed to fetch stock list: {e}")
        
        return None


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.DEBUG)
    
    fetcher = BaostockFetcher()
    
    try:
        # 测试历史数据
        df = fetcher.get_daily_data('600519')  # 茅台
        print(f"获取成功，共 {len(df)} 条数据")
        print(df.tail())
        
        # 测试股票名称
        name = fetcher.get_stock_name('600519')
        print(f"股票名称: {name}")
        
    except Exception as e:
        print(f"获取失败: {e}")
