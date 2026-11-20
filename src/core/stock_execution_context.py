# -*- coding: utf-8 -*-
"""Cancellation state shared by a single stock analysis execution."""

from __future__ import annotations

import threading
from typing import Callable, List, Optional


class StockCancellationToken:
    """Cooperative cancellation token with immediate cleanup callbacks."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: List[Callable[[], None]] = []

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def add_callback(self, callback: Callable[[], None]) -> None:
        with self._lock:
            if not self._event.is_set():
                self._callbacks.append(callback)
                return
        try:
            callback()
        except Exception:
            return

    def cancel(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            callbacks = list(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                continue


_STOCK_EXECUTION_CTX = threading.local()


def get_current_stock_cancellation() -> Optional[StockCancellationToken]:
    return getattr(_STOCK_EXECUTION_CTX, "token", None)


def is_current_stock_cancelled() -> bool:
    token = get_current_stock_cancellation()
    return bool(token is not None and token.is_cancelled())


def set_current_stock_cancellation(token: Optional[StockCancellationToken]) -> Optional[StockCancellationToken]:
    previous = get_current_stock_cancellation()
    _STOCK_EXECUTION_CTX.token = token
    return previous
