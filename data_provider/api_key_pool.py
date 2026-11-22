# -*- coding: utf-8 -*-
"""多 API Key 池：轮询使用 + 当前 Key 失效时自动切换。

数据源适配器（Finnhub / AlphaVantage 等）通常只接受单个 Key。当同一服务配置了
多个账号的 Key 时，本模块负责：

1. 解析 ``key1,key2`` / JSON 数组 / 列表形式的配置；
2. 轮询选择起始 Key，单次请求内依次尝试其余 Key；
3. 仅在鉴权失败、配额用尽或限流等 Key 级错误时切换，避免网络抖动重复消耗配额；
4. 连续失败的 Key 进入冷却（默认 5 分钟），冷却结束后自动重新参与轮询。
"""

import json
import logging
import threading
import time
from typing import Any, Callable, Iterable, List, Optional, Sequence, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 命中这些特征的失败视为 Key 级失效（鉴权 / 配额 / 限流）
_KEY_FAILURE_MARKERS = (
    "invalid api key",
    "invalid key",
    "api key is not valid",
    "apikey is invalid",
    "unauthorized",
    "forbidden",
    "authentication",
    "not authorized",
    "rate limit",
    "ratelimited",
    "quota",
    "daily limit",
    "api call frequency",
    "calls per day",
    "calls per minute",
    "insufficient",
    "run out of",
    "upgrade to premium",
    "premium plan",
    "401",
    "402",
    "403",
    "429",
)


def parse_api_keys(value: Any) -> List[str]:
    """把配置值解析为去重后的 Key 列表。

    支持 ``"k1,k2"``、``["k1", "k2"]``、``'["k1", "k2"]'`` 以及 ``None``。
    """
    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, (list, tuple)):
                return parse_api_keys(parsed)
        raw_keys: Sequence[Any] = text.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_keys = list(value)
    else:
        # 其它类型（如测试替身对象）视为未配置，避免把对象的字符串形式当成 Key
        return []

    keys: List[str] = []
    for raw_key in raw_keys:
        key = str(raw_key or "").strip().strip('"').strip("'").strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def is_key_failure(error: Optional[BaseException]) -> bool:
    """判断异常是否属于 Key 级失效（可用另一个 Key 重试）。"""
    if error is None:
        return False
    text = str(error).strip().lower()
    if not text:
        return False
    return any(marker in text for marker in _KEY_FAILURE_MARKERS)


def describe_request_error(error: BaseException) -> str:
    """生成不含请求 URL / Key 的错误摘要，避免日志泄露凭据。"""
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is not None:
        reason = str(getattr(response, "reason", "") or "").strip()
        return f"HTTP {status_code} {reason}".strip()
    message = " ".join(str(error).split())
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


class ApiKeyPool:
    """线程安全的 API Key 池。"""

    MAX_CONSECUTIVE_ERRORS = 3
    # 连续失败超过阈值的 Key 进入冷却；冷却结束自动重新参与轮询
    COOLDOWN_SECONDS = 300

    def __init__(self, keys: Iterable[str] = ()) -> None:
        self._keys = parse_api_keys(list(keys))
        self._errors = {key: 0 for key in self._keys}
        self._blocked_until = {key: 0.0 for key in self._keys}
        self._cursor = 0
        self._lock = threading.RLock()

    @property
    def keys(self) -> List[str]:
        with self._lock:
            return list(self._keys)

    @property
    def primary(self) -> Optional[str]:
        with self._lock:
            return self._keys[0] if self._keys else None

    @property
    def is_configured(self) -> bool:
        return bool(self._keys)

    def error_counts(self) -> dict:
        """返回各 Key 的连续错误计数快照（用于日志与测试）。"""
        with self._lock:
            return dict(self._errors)

    def call(self, func: Callable[[str], T]) -> T:
        """用池中的 Key 依次调用 ``func(key)``，Key 级失败时切换下一个。"""
        keys = self._ordered_keys()
        if not keys:
            raise RuntimeError("未配置可用的 API Key")

        last_error: Optional[BaseException] = None
        for key in keys:
            try:
                result = func(key)
            except Exception as exc:  # noqa: BLE001 - 需要按错误类型决定是否换 Key
                last_error = exc
                if not is_key_failure(exc):
                    raise
                self._record_error(key)
                logger.warning(
                    "[APIKeyPool] API Key %s... 不可用（%s），尝试下一个 Key",
                    key[:8],
                    describe_request_error(exc),
                )
                continue

            self._record_success(key)
            return result

        if last_error is not None:
            raise last_error
        raise RuntimeError("所有 API Key 调用失败")

    def _ordered_keys(self) -> List[str]:
        """按轮询顺序返回可用 Key；全部不可用时退回轮询首位。"""
        with self._lock:
            if not self._keys:
                return []
            start = self._cursor % len(self._keys)
            self._cursor = (start + 1) % len(self._keys)
            ordered = [
                self._keys[(start + offset) % len(self._keys)]
                for offset in range(len(self._keys))
            ]
            now = time.time()
            healthy = [key for key in ordered if self._is_available(key, now)]
            return healthy or ordered[:1]

    def _is_available(self, key: str, now: float) -> bool:
        """Key 是否可参与轮询；冷却结束后自动恢复。"""
        if self._errors.get(key, 0) < self.MAX_CONSECUTIVE_ERRORS:
            return True

        blocked_until = self._blocked_until.get(key, 0.0)
        if now >= blocked_until:
            self._errors[key] = 0
            self._blocked_until[key] = 0.0
            logger.info("[APIKeyPool] API Key %s... 冷却结束，恢复参与轮询", key[:8])
            return True

        return False

    def _record_success(self, key: str) -> None:
        with self._lock:
            if self._errors.get(key, 0) > 0:
                self._errors[key] -= 1

    def _record_error(self, key: str) -> None:
        with self._lock:
            errors = self._errors.get(key, 0) + 1
            self._errors[key] = errors
            if errors >= self.MAX_CONSECUTIVE_ERRORS:
                self._blocked_until[key] = time.time() + self.COOLDOWN_SECONDS
