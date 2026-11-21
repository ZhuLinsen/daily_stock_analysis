# -*- coding: utf-8 -*-
"""Cancellation state shared by a single stock analysis execution."""

from __future__ import annotations

import threading
import time
from concurrent.futures import CancelledError, Executor, Future, ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from queue import Empty, SimpleQueue
from typing import Callable, List, Optional, TypeVar


_T = TypeVar("_T")
_WORKER_ABANDONMENT: ContextVar[tuple[threading.Event, ...]] = ContextVar(
    "stock_worker_abandonment", default=()
)


def track_stock_worker_abandonment(event: threading.Event) -> None:
    """Cancel work in this context when its caller stops waiting for it."""
    _WORKER_ABANDONMENT.set((*_WORKER_ABANDONMENT.get(), event))


class StockCancellationToken:
    """Cooperative cancellation token with immediate cleanup callbacks."""

    def __init__(self, deadline: Optional[float] = None) -> None:
        self._event = threading.Event()
        self._deadline = deadline
        self._lock = threading.Lock()
        self._callbacks: List[Callable[[], None]] = []
        self._workers_lock = threading.Lock()
        self._workers: List[tuple[threading.Thread, tuple[threading.Event, ...]]] = []

    def is_cancelled(self) -> bool:
        return self._event.is_set() or (
            self._deadline is not None and time.monotonic() >= self._deadline
        )

    def is_worker_cancelled(self) -> bool:
        """Check stock cancellation and cancellation of this worker's task."""
        return self.is_cancelled() or any(event.is_set() for event in _WORKER_ABANDONMENT.get())

    def remaining_seconds(self) -> Optional[float]:
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - time.monotonic())

    def start_with_cleanup(self, start: Callable[[], _T], cleanup: Callable[[_T], None]) -> _T:
        """Make starting a local process and registering its cleanup atomic."""
        with self._lock:
            if self.is_worker_cancelled():
                raise CancelledError()
            resource = start()
            self._callbacks.append(lambda: cleanup(resource))
            return resource

    def request_cancel(self) -> None:
        self._event.set()

    def cancel(self) -> None:
        self.request_cancel()
        with self._lock:
            for callback in self._callbacks:
                try:
                    callback()
                except Exception:
                    continue
            self._callbacks.clear()

    def start_worker(self, worker: threading.Thread, *, abandon_when: Optional[threading.Event] = None) -> None:
        abandonment = _WORKER_ABANDONMENT.get()
        if abandon_when is not None:
            abandonment = (*abandonment, abandon_when)
        with self._workers_lock:
            worker.start()
            self._workers.append((worker, abandonment))

    def join_workers(self, *, include_abandoned: bool = True) -> None:
        index = 0
        while True:
            with self._workers_lock:
                if index == len(self._workers):
                    return
                worker, abandonment = self._workers[index]
            if include_abandoned or not any(event.is_set() for event in abandonment):
                worker.join()
            index += 1


class _StockChildThreadPool(Executor):
    """Run nested work on daemon threads tracked by the enclosing stock slot."""

    def __init__(
        self,
        token: StockCancellationToken,
        max_workers: int,
        thread_name_prefix: str,
        abandon_workers_when: Optional[threading.Event],
    ) -> None:
        self._token = token
        self._max_workers = max_workers
        self._name = thread_name_prefix
        self._abandon_workers_when = abandon_workers_when
        self._lock = threading.Lock()
        self._tasks = SimpleQueue()
        self._workers: List[threading.Thread] = []
        self._closed = False

    def submit(self, fn, /, *args, **kwargs):
        with self._lock:
            if self._closed:
                raise RuntimeError("stock child thread pool has been shut down")
            future = Future()
            if self._token.is_worker_cancelled():
                future.set_exception(CancelledError("Stock analysis cancelled"))
                return future
            if len(self._workers) < self._max_workers:
                worker = threading.Thread(target=self._run, name=self._name, daemon=True)
                self._token.start_worker(worker, abandon_when=self._abandon_workers_when)
                self._workers.append(worker)
            context = copy_context()
            if self._abandon_workers_when is not None:
                context.run(track_stock_worker_abandonment, self._abandon_workers_when)
            self._tasks.put((future, context, fn, args, kwargs))
            return future

    def _run(self) -> None:
        while (task := self._tasks.get()) is not None:
            future, context, fn, args, kwargs = task
            if future.set_running_or_notify_cancel():
                try:
                    if context.run(self._token.is_worker_cancelled):
                        raise CancelledError("Stock analysis cancelled")
                    result = context.run(fn, *args, **kwargs)
                except BaseException as exc:
                    future.set_exception(exc)
                else:
                    future.set_result(result)

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                if cancel_futures:
                    while True:
                        try:
                            future, *_ = self._tasks.get_nowait()
                        except Empty:
                            break
                        future.cancel()
                        future.set_running_or_notify_cancel()
                for _ in self._workers:
                    self._tasks.put(None)
        if wait:
            for worker in self._workers:
                worker.join()


def stock_child_thread_pool(
    max_workers: int,
    thread_name_prefix: str,
    *,
    abandon_workers_when: Optional[threading.Event] = None,
) -> Executor:
    token = get_current_stock_cancellation()
    if token is not None:
        return _StockChildThreadPool(token, max_workers, thread_name_prefix, abandon_workers_when)
    return ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=thread_name_prefix)


_STOCK_EXECUTION_CTX: ContextVar[Optional[StockCancellationToken]] = ContextVar(
    "stock_cancellation", default=None
)


def get_current_stock_cancellation() -> Optional[StockCancellationToken]:
    return _STOCK_EXECUTION_CTX.get()


def is_current_stock_cancelled() -> bool:
    token = get_current_stock_cancellation()
    return token is not None and token.is_worker_cancelled()


def raise_if_stock_cancelled() -> None:
    if is_current_stock_cancelled():
        raise CancelledError("Stock analysis cancelled")


def set_current_stock_cancellation(token: Optional[StockCancellationToken]) -> Optional[StockCancellationToken]:
    previous = get_current_stock_cancellation()
    _STOCK_EXECUTION_CTX.set(token)
    return previous
