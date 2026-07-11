# -*- coding: utf-8 -*-
"""Shared execution lock for market review runs."""

import logging
import errno
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from src.config import Config

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None


_market_review_lock = threading.Lock()
_market_review_running = False
_MARKET_REVIEW_LOCK_STALE_TTL_SECONDS = 24 * 60 * 60
logger = logging.getLogger(__name__)


@dataclass
class MarketReviewExecutionLock:
    handle: Any
    path: Path
    uses_flock: bool


def market_review_lock_path(config: Config) -> Path:
    database_path = getattr(config, "database_path", "./data/stock_analysis.db")
    return Path(database_path).parent / "market_review.lock"


def _write_market_review_lock_metadata(handle: Any) -> None:
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid={os.getpid()}\nstarted_at={datetime.now().isoformat()}\n")
    handle.flush()


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name == "nt":
        return _is_windows_process_alive(pid)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _is_windows_process_alive(pid: int) -> bool:
    try:
        import ctypes
    except ImportError:  # pragma: no cover - ctypes is part of stdlib
        return True

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        process_query_limited_information = 0x1000
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return ctypes.get_last_error() != 87

        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    except Exception as exc:
        logger.warning("Windows 进程存活探测失败，保守视为仍在运行: %s", exc)
        return True


def _read_lock_metadata(lock_path: Path) -> dict[str, str]:
    try:
        raw = lock_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    metadata: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            metadata[key.strip()] = value.strip()
    return metadata


def _is_lock_file_expired(lock_path: Path) -> bool:
    try:
        modified_at = datetime.fromtimestamp(lock_path.stat().st_mtime)
    except OSError:
        return False

    return datetime.now() - modified_at > timedelta(
        seconds=_MARKET_REVIEW_LOCK_STALE_TTL_SECONDS
    )


def _is_stale_lock(lock_path: Path) -> bool:
    metadata = _read_lock_metadata(lock_path)
    pid_raw = metadata.get("pid")
    if not pid_raw:
        return _is_lock_file_expired(lock_path)

    try:
        pid = int(pid_raw)
    except ValueError:
        return _is_lock_file_expired(lock_path)

    if not _is_process_alive(pid):
        return True

    started_raw = metadata.get("started_at")
    if not started_raw:
        return False

    try:
        started_at = datetime.fromisoformat(started_raw)
    except ValueError:
        return True

    return datetime.now() - started_at > timedelta(
        seconds=_MARKET_REVIEW_LOCK_STALE_TTL_SECONDS
    )


def try_acquire_market_review_lock(
    config: Config,
) -> Optional[MarketReviewExecutionLock]:
    """Acquire a process-local and same-host lock for market-review execution.

    The lock combines an in-process guard with a file lock. It prevents API,
    CLI, and scheduler market-review entrypoints in the same runtime from
    overlapping, and also dedupes same-host processes that share the data path.
    It does not provide cross-host/container dedupe for multi-instance deploys.
    """
    global _market_review_running
    lock_path = market_review_lock_path(config)

    with _market_review_lock:
        if _market_review_running:
            return None

        lock_path.parent.mkdir(parents=True, exist_ok=True)

        if fcntl is not None:
            handle = open(lock_path, "a+", encoding="utf-8")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError) as exc:
                handle.close()
                if isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in (
                    errno.EACCES,
                    errno.EAGAIN,
                ):
                    return None
                raise
            uses_flock = True
        else:  # pragma: no cover - exercised only on platforms without fcntl
            fd: Optional[int] = None
            for _ in range(2):
                try:
                    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                    break
                except FileExistsError:
                    if not _is_stale_lock(lock_path):
                        return None

                    logger.warning("检测到过期的 market_review.lock，尝试清理后重试。")
                    try:
                        lock_path.unlink()
                    except OSError as exc:
                        logger.warning("清理过期 market_review.lock 失败: %s", exc)
                        return None

            if fd is None:
                return None

            handle = os.fdopen(fd, "w+", encoding="utf-8")
            uses_flock = False

        _write_market_review_lock_metadata(handle)
        _market_review_running = True
        return MarketReviewExecutionLock(
            handle=handle,
            path=lock_path,
            uses_flock=uses_flock,
        )


def release_market_review_lock(
    lock_token: Optional[MarketReviewExecutionLock],
) -> None:
    if lock_token is None:
        return

    global _market_review_running
    with _market_review_lock:
        _market_review_running = False

    try:
        if lock_token.uses_flock and fcntl is not None:
            fcntl.flock(lock_token.handle.fileno(), fcntl.LOCK_UN)
    finally:
        lock_token.handle.close()
        if not lock_token.uses_flock:
            try:
                lock_token.path.unlink()
            except FileNotFoundError:
                pass
