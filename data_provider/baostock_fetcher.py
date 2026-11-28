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
import os
import re
import socket
import sys
import threading
import time
import types
from concurrent.futures import CancelledError
from contextlib import contextmanager
from threading import Event, Lock, RLock
from typing import Callable, Dict, Generator, Optional

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
    is_current_stock_cancelled,
    raise_if_stock_cancelled,
)

logger = logging.getLogger(__name__)

# baostock uses process-global socket/login state, so sessions must be serialized.
BAOSTOCK_SESSION_LOCK = RLock()
_BAOSTOCK_SESSION_LOCK = BAOSTOCK_SESSION_LOCK

_BAOSTOCK_LOCK_TIMEOUT_SECONDS = 30.0
_BAOSTOCK_LOCK_POLL_INTERVAL_SECONDS = 0.05
_BAOSTOCK_SOCKET_TIMEOUT_SECONDS = 15.0
_BAOSTOCK_LOGOUT_TIMEOUT_SECONDS = 3.0
_BAOSTOCK_SOCKET_POLL_INTERVAL_SECONDS = 0.2
_BAOSTOCK_IO_LOCAL = threading.local()


@contextmanager
def acquire_baostock_session_lock(
    *,
    lock: RLock = BAOSTOCK_SESSION_LOCK,
    timeout_seconds: Optional[float] = None,
    cancel_event: Optional[Event] = None,
    cancel_exc_factory: Optional[Callable[[], BaseException]] = None,
    timeout_exc_factory: Optional[Callable[[str], BaseException]] = None,
) -> Generator[None, None, None]:
    """Acquire the shared process-wide Baostock lock with cancellation and timeout bounds."""
    effective_timeout = (
        _BAOSTOCK_LOCK_TIMEOUT_SECONDS
        if timeout_seconds is None
        else max(0.0, float(timeout_seconds))
    )
    stock_token = get_current_stock_cancellation()
    if stock_token is not None:
        remaining_token = stock_token.remaining_seconds()
        if remaining_token is not None:
            effective_timeout = min(effective_timeout, remaining_token)
    timeout_factory = timeout_exc_factory or TimeoutError

    def _check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            if cancel_exc_factory is not None:
                raise cancel_exc_factory()
            raise TimeoutError("Baostock lock wait cancelled after timeout")
        raise_if_stock_cancelled()

    _check_cancelled()
    deadline = time.monotonic() + effective_timeout
    acquired = False
    while True:
        _check_cancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            acquired = lock.acquire(blocking=False)
            if acquired:
                break
            raise timeout_factory(
                f"Timed out waiting for Baostock session lock after {effective_timeout:g}s"
            )
        wait_slice = min(_BAOSTOCK_LOCK_POLL_INTERVAL_SECONDS, remaining)
        if lock.acquire(timeout=wait_slice):
            acquired = True
            break

    try:
        _check_cancelled()
        yield
    finally:
        if acquired:
            lock.release()


_acquire_baostock_lock = acquire_baostock_session_lock


def _force_close_socket(sock: object) -> None:
    """Best-effort shutdown and close to unblock any in-flight recv/connect."""
    shutdown = getattr(sock, "shutdown", None)
    if callable(shutdown):
        try:
            shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
    close = getattr(sock, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _resolve_baostock_io_modules() -> tuple[Optional[object], Optional[object]]:
    """Return ``(baostock.util.socketutil, baostock.common.context)`` if available."""
    bs_sock = sys.modules.get("baostock.util.socketutil")
    bs_context = sys.modules.get("baostock.common.context")
    if bs_sock is None:
        try:
            import baostock.util.socketutil as bs_sock
        except Exception:
            bs_sock = None
    if bs_context is None:
        try:
            import baostock.common.context as bs_context
        except Exception:
            bs_context = None
    return bs_sock, bs_context


class _BaostockSessionIOGuard:
    """Session-scoped state guarding Baostock socket I/O against EOF spins and hangs."""

    def __init__(
        self,
        *,
        rpc_timeout_seconds: float,
        deadline: Optional[float] = None,
        cancel_event: Optional[Event] = None,
    ) -> None:
        self.rpc_timeout_seconds = max(0.05, float(rpc_timeout_seconds))
        self.deadline = deadline
        self.cancel_event = cancel_event
        self._lock = Lock()
        self._active_socket: Optional[object] = None
        self._io_error: Optional[BaseException] = None
        self._aborted = False
        self._logout_mode = False

    @property
    def io_error(self) -> Optional[BaseException]:
        with self._lock:
            return self._io_error

    @property
    def is_aborted(self) -> bool:
        with self._lock:
            return self._aborted

    def enter_logout(self) -> None:
        with self._lock:
            self._logout_mode = True

    def set_active_socket(self, sock: object) -> None:
        with self._lock:
            self._active_socket = sock
            should_close = self._aborted
        if should_close:
            _force_close_socket(sock)

    def clear_active_socket(self, sock: object) -> None:
        with self._lock:
            if self._active_socket is sock:
                self._active_socket = None

    def record_io_error(self, exc: BaseException) -> None:
        with self._lock:
            if self._io_error is None:
                self._io_error = exc
            self._aborted = True

    def force_abort(self, exc: Optional[BaseException] = None) -> None:
        with self._lock:
            self._aborted = True
            if exc is not None and self._io_error is None:
                self._io_error = exc
            sock = self._active_socket
        if sock is not None:
            _force_close_socket(sock)

    def is_cancelled(self) -> bool:
        if self.cancel_event is not None and self.cancel_event.is_set():
            return True
        return is_current_stock_cancelled()

    def compute_rpc_deadline(self) -> float:
        now = time.monotonic()
        with self._lock:
            in_logout = self._logout_mode
        per_rpc = (
            min(self.rpc_timeout_seconds, _BAOSTOCK_LOGOUT_TIMEOUT_SECONDS)
            if in_logout
            else self.rpc_timeout_seconds
        )
        rpc_deadline = now + per_rpc
        if not in_logout and self.deadline is not None:
            rpc_deadline = min(rpc_deadline, self.deadline)
        stock_token = get_current_stock_cancellation()
        if not in_logout and stock_token is not None:
            remaining_token = stock_token.remaining_seconds()
            if remaining_token is not None:
                rpc_deadline = min(rpc_deadline, now + remaining_token)
        return rpc_deadline


class _GuardedBaostockSocket:
    """Socket proxy that breaks Baostock's empty-recv EOF spin loop and enforces timeouts."""

    def __init__(
        self,
        sock: object,
        guard: _BaostockSessionIOGuard,
        rpc_deadline: float,
    ) -> None:
        self._sock = sock
        self._guard = guard
        self._rpc_deadline = rpc_deadline
        self._supports_timeout = callable(getattr(sock, "settimeout", None))
        self._orig_timeout: Optional[float] = None
        self._has_orig_timeout = False
        if self._supports_timeout and callable(getattr(sock, "gettimeout", None)):
            try:
                self._orig_timeout = sock.gettimeout()
                self._has_orig_timeout = True
            except Exception:
                self._has_orig_timeout = False

    def _check_abort(self) -> float:
        if self._guard.is_aborted:
            err = self._guard.io_error or ConnectionResetError(
                "Baostock socket session aborted"
            )
            raise err
        if self._guard.is_cancelled():
            err = TimeoutError("Baostock socket operation cancelled")
            self._guard.force_abort(err)
            raise err
        remaining = self._rpc_deadline - time.monotonic()
        if remaining <= 0:
            err = TimeoutError("Baostock socket operation timed out")
            self._guard.force_abort(err)
            raise err
        return remaining

    def send(self, data: bytes, *args, **kwargs):
        remaining = self._check_abort()
        if self._supports_timeout:
            try:
                self._sock.settimeout(max(remaining, 0.01))
            except Exception:
                pass
        try:
            return self._sock.send(data, *args, **kwargs)
        except Exception as exc:
            self._guard.record_io_error(exc)
            _force_close_socket(self._sock)
            raise

    def sendall(self, data: bytes, *args, **kwargs):
        remaining = self._check_abort()
        if self._supports_timeout:
            try:
                self._sock.settimeout(max(remaining, 0.01))
            except Exception:
                pass
        try:
            return self._sock.sendall(data, *args, **kwargs)
        except Exception as exc:
            self._guard.record_io_error(exc)
            _force_close_socket(self._sock)
            raise

    def recv(self, bufsize: int, *args, **kwargs) -> bytes:
        while True:
            remaining = self._check_abort()
            used_poll_timeout = False
            if self._supports_timeout:
                step = min(_BAOSTOCK_SOCKET_POLL_INTERVAL_SECONDS, max(remaining, 0.01))
                try:
                    self._sock.settimeout(step)
                    used_poll_timeout = True
                except Exception:
                    used_poll_timeout = False
            try:
                chunk = self._sock.recv(bufsize, *args, **kwargs)
            except socket.timeout as exc:
                if used_poll_timeout:
                    continue
                self._guard.record_io_error(exc)
                _force_close_socket(self._sock)
                raise
            except Exception as exc:
                self._guard.record_io_error(exc)
                _force_close_socket(self._sock)
                raise
            if chunk == b"":
                err = ConnectionResetError(
                    "Baostock peer closed connection unexpectedly (EOF)"
                )
                self._guard.record_io_error(err)
                _force_close_socket(self._sock)
                raise err
            return chunk

    def restore_timeout(self) -> None:
        if self._has_orig_timeout and not self._guard.is_aborted:
            try:
                self._sock.settimeout(self._orig_timeout)
            except Exception:
                pass

    def close(self) -> None:
        _force_close_socket(self._sock)

    def __getattr__(self, name: str):
        return getattr(self._sock, name)


def get_current_baostock_io_error() -> Optional[BaseException]:
    """Return the active thread's recorded Baostock socket I/O error, if any."""
    guard = getattr(_BAOSTOCK_IO_LOCAL, "guard", None)
    return guard.io_error if guard is not None else None


@contextmanager
def baostock_socket_io_guard(
    *,
    rpc_timeout_seconds: Optional[float] = None,
    deadline: Optional[float] = None,
    cancel_event: Optional[Event] = None,
    register_cancel_callback: Optional[Callable[[Callable[[], None]], Callable[[], None]]] = None,
) -> Generator[_BaostockSessionIOGuard, None, None]:
    """Guard Baostock's process-global socket I/O while holding ``BAOSTOCK_SESSION_LOCK``."""
    guard = _BaostockSessionIOGuard(
        rpc_timeout_seconds=(
            _BAOSTOCK_SOCKET_TIMEOUT_SECONDS
            if rpc_timeout_seconds is None
            else float(rpc_timeout_seconds)
        ),
        deadline=deadline,
        cancel_event=cancel_event,
    )
    unregister_cancel = (
        register_cancel_callback(
            lambda: guard.force_abort(
                TimeoutError("Baostock socket operation cancelled after timeout")
            )
        )
        if register_cancel_callback is not None
        else lambda: None
    )

    previous_guard = getattr(_BAOSTOCK_IO_LOCAL, "guard", None)
    _BAOSTOCK_IO_LOCAL.guard = guard

    bs_sock, bs_context = _resolve_baostock_io_modules()
    if bs_sock is None or bs_context is None:
        try:
            yield guard
        finally:
            _BAOSTOCK_IO_LOCAL.guard = previous_guard
            unregister_cancel()
        return

    orig_send_msg = getattr(bs_sock, "send_msg", None)
    socket_util_cls = getattr(bs_sock, "SocketUtil", None)
    orig_connect = getattr(socket_util_cls, "connect", None) if socket_util_cls is not None else None
    patch_connect = (
        socket_util_cls is not None
        and orig_connect is not None
        and getattr(orig_connect, "__module__", "") == "baostock.util.socketutil"
    )

    def _guarded_connect(self_util) -> None:
        if guard.is_aborted or guard.is_cancelled():
            guard.force_abort(TimeoutError("Baostock socket connect cancelled"))
            setattr(bs_context, "default_socket", None)
            return
        remaining = guard.compute_rpc_deadline() - time.monotonic()
        if remaining <= 0:
            guard.force_abort(TimeoutError("Baostock socket connect timed out"))
            setattr(bs_context, "default_socket", None)
            return
        bs_cons = sys.modules.get("baostock.common.contants")
        if bs_cons is None:
            import baostock.common.contants as bs_cons
        sock_mod = getattr(bs_sock, "socket", socket)
        sock_obj = sock_mod.socket(socket.AF_INET, socket.SOCK_STREAM)
        guard.set_active_socket(sock_obj)
        try:
            sock_obj.settimeout(max(remaining, 0.01))
            sock_obj.connect((bs_cons.BAOSTOCK_SERVER_IP, bs_cons.BAOSTOCK_SERVER_PORT))
        except Exception as exc:
            guard.record_io_error(exc)
            _force_close_socket(sock_obj)
            guard.clear_active_socket(sock_obj)
            setattr(bs_context, "default_socket", None)
            return
        if guard.is_aborted or guard.is_cancelled():
            _force_close_socket(sock_obj)
            guard.clear_active_socket(sock_obj)
            setattr(bs_context, "default_socket", None)
            return
        setattr(bs_context, "default_socket", sock_obj)

    def _guarded_send_msg(msg):
        raw_sock = getattr(bs_context, "default_socket", None)
        if raw_sock is None or isinstance(raw_sock, _GuardedBaostockSocket):
            return orig_send_msg(msg)
        if guard.is_aborted or guard.is_cancelled():
            _force_close_socket(raw_sock)
            return None
        rpc_deadline = guard.compute_rpc_deadline()
        wrapped = _GuardedBaostockSocket(raw_sock, guard, rpc_deadline)
        guard.set_active_socket(raw_sock)
        setattr(bs_context, "default_socket", wrapped)
        try:
            return orig_send_msg(msg)
        finally:
            if getattr(bs_context, "default_socket", None) is wrapped:
                setattr(bs_context, "default_socket", raw_sock)
            wrapped.restore_timeout()
            guard.clear_active_socket(raw_sock)
            if guard.is_aborted:
                _force_close_socket(raw_sock)

    if callable(orig_send_msg):
        setattr(bs_sock, "send_msg", _guarded_send_msg)
    if patch_connect:
        setattr(socket_util_cls, "connect", _guarded_connect)

    try:
        yield guard
    finally:
        if callable(orig_send_msg) and getattr(bs_sock, "send_msg", None) is _guarded_send_msg:
            setattr(bs_sock, "send_msg", orig_send_msg)
        if patch_connect and getattr(socket_util_cls, "connect", None) is _guarded_connect:
            setattr(socket_util_cls, "connect", orig_connect)
        _BAOSTOCK_IO_LOCAL.guard = previous_guard
        unregister_cancel()
        if guard.is_aborted:
            leftover_sock = getattr(bs_context, "default_socket", None)
            if leftover_sock is not None:
                _force_close_socket(leftover_sock)


_BAOSTOCK_RESULT_SKIPS_NON_FULL_PAGE: Dict[type, bool] = {}


def _extract_code_object(fn: object) -> Optional[types.CodeType]:
    """Return the underlying Python code object without requiring ``.py`` source files."""
    if fn is None:
        return None
    try:
        unwrapped = inspect.unwrap(fn)
    except Exception:
        unwrapped = fn
    func = getattr(unwrapped, "__func__", unwrapped)
    code = getattr(func, "__code__", None)
    return code if isinstance(code, types.CodeType) else None


def _code_references_name(code: types.CodeType, target: str) -> bool:
    """Return True when compiled bytecode (or nested code objects) references *target*."""
    if (
        target in code.co_names
        or target in code.co_freevars
        or target in code.co_varnames
    ):
        return True
    return any(
        _code_references_name(const, target)
        for const in code.co_consts
        if isinstance(const, types.CodeType)
    )


def _method_references_per_page_count(fn: object) -> bool:
    """Inspect compiled bytecode so PyInstaller frozen builds work without .py sources."""
    code = _extract_code_object(fn)
    if code is None:
        return False
    return _code_references_name(code, "BAOSTOCK_PER_PAGE_COUNT")


def _baostock_next_full_page_size(rs: object) -> Optional[int]:
    """Return full page size when ResultData.next() skips short final pages (baostock >=0.9.4)."""
    rs_type = type(rs)
    skips_short_page = _BAOSTOCK_RESULT_SKIPS_NON_FULL_PAGE.get(rs_type)
    if skips_short_page is None:
        class_next_fn = getattr(rs_type, "next", None)
        if class_next_fn is not None:
            skips_short_page = _method_references_per_page_count(class_next_fn)
            _BAOSTOCK_RESULT_SKIPS_NON_FULL_PAGE[rs_type] = skips_short_page
        else:
            instance_next_fn = getattr(rs, "next", None)
            skips_short_page = _method_references_per_page_count(instance_next_fn)

    if not skips_short_page:
        return None
    bs_cons = sys.modules.get("baostock.common.contants")
    if bs_cons is None:
        try:
            import baostock.common.contants as bs_cons
        except Exception:
            return None
    try:
        page_size = int(getattr(bs_cons, "BAOSTOCK_PER_PAGE_COUNT", 0) or 0)
        return page_size if page_size > 0 else None
    except Exception:
        return None


def check_baostock_pagination_complete(
    rs: object,
    *,
    transient_exc_type: type[Exception] = ConnectionError,
    fatal_exc_type: type[Exception] = DataFetchError,
    io_error: Optional[BaseException] = None,
) -> None:
    """Verify a Baostock ResultData cursor terminated cleanly rather than mid-pagination."""
    error_code = str(getattr(rs, "error_code", "0") or "").strip()
    error_msg = str(getattr(rs, "error_msg", "") or "").strip()
    if error_code != "0":
        msg = f"Baostock pagination failed ({error_code}): {error_msg}"
        if _is_transient_network_error(error_code, error_msg):
            raise transient_exc_type(msg)
        raise fatal_exc_type(msg)

    active_io_error = io_error if io_error is not None else get_current_baostock_io_error()
    if active_io_error is not None:
        raise transient_exc_type(
            f"Baostock pagination interrupted by socket I/O error: {active_io_error}"
        ) from active_io_error

    raw_data = getattr(rs, "data", None)
    cur_row_num = getattr(rs, "cur_row_num", None)
    if (
        isinstance(raw_data, list)
        and isinstance(cur_row_num, int)
        and len(raw_data) > 0
        and cur_row_num >= len(raw_data)
    ):
        full_page_size = _baostock_next_full_page_size(rs)
        if full_page_size is None or len(raw_data) >= full_page_size:
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
        with acquire_baostock_session_lock():
            with baostock_socket_io_guard() as io_guard:
                logged_in = False
                try:
                    raise_if_stock_cancelled()
                    # 登录 Baostock
                    login_result = bs.login()

                    if login_result.error_code != '0':
                        raise_if_stock_cancelled()
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
                        io_guard.enter_logout()
                        try:
                            logout_result = bs.logout()
                            if getattr(logout_result, "error_code", None) == '0':
                                logger.debug("Baostock logout succeeded")
                            else:
                                logger.warning(
                                    f"Baostock logout abnormal: {getattr(logout_result, 'error_msg', '')}"
                                )
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
                raise_if_stock_cancelled()

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

                raise_if_stock_cancelled()
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
                raise_if_stock_cancelled()

                if rs.error_code == '0':
                    data_list = []
                    while True:
                        raise_if_stock_cancelled()
                        if not rs.next():
                            break
                        data_list.append(rs.get_row_data())

                    raise_if_stock_cancelled()
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
                raise_if_stock_cancelled()

                if rs.error_code == '0':
                    data_list = []
                    while True:
                        raise_if_stock_cancelled()
                        if not rs.next():
                            break
                        data_list.append(rs.get_row_data())

                    raise_if_stock_cancelled()
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
