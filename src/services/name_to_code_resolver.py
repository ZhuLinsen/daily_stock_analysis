# -*- coding: utf-8 -*-
"""
===================================
名称到代码解析引擎
===================================

将股票名称解析为代码：全局 ``stockDB`` 上的精确匹配 + AkShare 扩充 +
混合匹配（子串/拼音/模糊）。
"""

from __future__ import annotations

import concurrent.futures
import difflib
import json
import logging
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from src.data.stock_mapping import STOCK_NAME_MAP
from src.services.stock_code_utils import is_code_like, normalize_code

logger = logging.getLogger(__name__)

# AkShare 结果缓存：(时间戳, name_to_code 字典)。TTL 过期后作为 stale
# 数据继续服务（stale-while-revalidate），刷新由后台线程完成。
_akshare_cache: Optional[tuple[float, Dict[str, str]]] = None
_AKSHARE_CACHE_TTL = 1800  # 30 MIN

# 失败退避：最近一次拉取失败的时间戳。不写负缓存的话，网络异常期间每次
# 解析都会重打网络请求，慢速超时直接放大为全量消息的用户延迟。
# 有 stale 缓存时退避窗口内仍服务 stale（网络故障期间保持可用），
# 仅冷启动（无任何缓存）才退化为本地库。
_akshare_failure_cache: Optional[float] = None
_AKSHARE_FAILURE_TTL = 300  # 5 MIN

# 拉取超时：akshare 对交易所的部分请求无超时（如上交所 GET、北交所
# POST），挂起（非失败）时拉取线程永不返回——挂起时异常路径永不触发、
# 失败退避永不武装。拉取经子进程包装封顶时长后，挂起子进程在超时处被
# terminate/kill、以 TimeoutError 抛出，走常规失败路径写入失败退避。
_AKSHARE_FETCH_TIMEOUT = 25.0

# 冷启动等待上限：拉取被子进程封顶在 _AKSHARE_FETCH_TIMEOUT 内，worker
# 在其后有限的清账步内必然 resolve Future。等待上界从同一常数推导而非
# 独立魔法数，结构上保证与在途拉取重叠的请求都能等到其结果——曾用独立
# 常数 8s，实测拉取耗时 6.6~8.2s 与其同分布，冷启动请求确定性漏解。
# 余量覆盖 DataFrame 解析与清账；落盘/日志在唤醒之后，不计入。TTL 过期
# 走 stale-while-revalidate 零等待，此值仅影响冷启动场景。
_AKSHARE_WAIT_COLD_START = _AKSHARE_FETCH_TIMEOUT + 5.0

# 状态锁：只保证缓存/退避/在途句柄读写的原子性。锁内唯一的 IO 例外是
# _try_load_disk_cache_locked 的首次懒加载（每进程一次、本地小文件毫秒
# 级）；网络拉取与落盘都在锁外的后台刷新线程内。与 _db_lock 互不嵌套，
# 不构成锁顺序环。
_state_lock = threading.Lock()

# 在途拉取句柄：非 None 表示已有后台线程在刷新。并发等待者等 Future 的
# 完成信号（成功/失败都会精确唤醒），而非排队抢锁再双重检查——等待与
# 拉取耗时解耦，无 25<30 这类常数间隐式契约。
_akshare_inflight: Optional[concurrent.futures.Future] = None

# 磁盘缓存：成功拉取后原子落盘，重启时懒加载为 stale 数据。股票名称表
# 变化频率极低，跨重启复用把"冷启动等待"压缩到仅剩磁盘也无数据的场景。
# 路径遵循 data/cache 约定（该目录已 gitignore）。
_AKSHARE_DISK_CACHE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "cache" / "akshare_name_map.json"
)
_akshare_disk_checked = False

# stockDB 读写锁：意图解析在 asyncio.to_thread 工作线程中并发执行，
# extend_AkShare 的原地合并与迭代 stockDB 的读路径不加锁会触发
# "dictionary changed size during iteration"。RLock 允许嵌套获取。
_db_lock = threading.RLock()


def _contains_cjk(text: str) -> bool:
    """当文本包含中日韩(CJK)字符时返回 True。"""
    return any("\u3400" <= ch <= "\u9fff" for ch in text)


def _normalize_stock_name(name: str) -> str:
    """股票名称的统一归一：NFKC 宽度归一（全角字母/数字 → 半角）+ 去除全部
    空白。

    分词管道对用户输入做同样的 NFKC（web_intent_tokenizer._preprocess_text
    的工作副本），库内名称若保留源数据拼写（AkShare 的 "京东方Ａ" 全角Ａ、
    "五 粮 液" 内嵌空格），窗口/片段与归一后的输入永远不相等——不仅全名
    精确匹配落空，还会被更短的库内名误切出错误实体（"京东方Ａ" 落空后
    2 字窗口命中 "京东"）。输入侧与库侧必须同源同变换：本地映射初值、
    AkShare 构建与合并、磁盘缓存加载三个入库口，与全部查询口共用本函数
    （磁盘缓存里的历史未归一数据同样在此归一）。展示名随之统一为归一拼写
    （与 token 层"单一代码身份"原则一致）。
    """
    return "".join(unicodedata.normalize("NFKC", name).split())


def _is_code_like(s: str) -> bool:
    """共享的“形似代码”检查的向后兼容包装。"""
    return is_code_like(s)


def _normalize_code(raw: str) -> Optional[str]:
    """共享代码规范化的向后兼容包装。"""
    return normalize_code(raw)


def _build_reverse_map_no_duplicates(
    code_to_name: Dict[str, str],
) -> Dict[str, str]:
    """
    构建 name -> code 映射。若一个名称映射到多个代码（有歧义），则将其排除。
    """
    name_to_codes: Dict[str, Set[str]] = {}
    for code, name in code_to_name.items():
        if not name or not code:
            continue
        name = name.strip()
        if name not in name_to_codes:
            name_to_codes[name] = set()
        name_to_codes[name].add(code)
    # Only include names with exactly one code
    return {name: next(iter(codes)) for name, codes in name_to_codes.items() if len(codes) == 1}


def _build_local_name_indexes(code_to_name: Dict[str, str]) -> Tuple[Dict[str, str], Set[str]]:
    """
    Build cached local lookup structures:
    - unique name -> code
    - ambiguous names that should fail fast
    """
    name_to_codes: Dict[str, Set[str]] = {}
    for code, name in code_to_name.items():
        if not name or not code:
            continue
        normalized_name = _normalize_stock_name(name)
        if not normalized_name:
            continue
        name_to_codes.setdefault(normalized_name, set()).add(code)

    unique_names = {
        name: next(iter(codes))
        for name, codes in name_to_codes.items()
        if len(codes) == 1
    }
    ambiguous_names = {
        name
        for name, codes in name_to_codes.items()
        if len(codes) > 1
    }
    return unique_names, ambiguous_names


_LOCAL_REVERSE_MAP, _LOCAL_AMBIGUOUS_NAMES = _build_local_name_indexes(STOCK_NAME_MAP)


def _akshare_stock_info_worker():
    """子进程内执行：导入 akshare 并拉取全量 A 股代码表。

    必须保持模块级函数（spawn 经 pickle 按限定名传递）；akshare 及其
    pandas 等重依赖只进子进程，父进程不加载。
    """
    import akshare as ak

    return ak.stock_info_a_code_name()


def _fetch_akshare_df():
    """AkShare 全量拉取的唯一网络出口（测试接缝）。

    经 data_provider 的子进程超时包装（spawn）执行：挂起的网络请求在
    _AKSHARE_FETCH_TIMEOUT 内被杀死，父进程侧以 TimeoutError 抛出。
    akshare 内部的 @lru_cache 只存在于子进程，30 分钟 TTL 过期后的
    刷新在父进程侧始终拿到新数据。
    """
    from data_provider.akshare_fetcher import _akshare_call_with_timeout

    return _akshare_call_with_timeout(
        _akshare_stock_info_worker,
        timeout=_AKSHARE_FETCH_TIMEOUT,
        call_name="stock_info_a_code_name",
    )


def _build_name_map_from_df(df) -> Dict[str, str]:
    """把 AkShare 的 code/name DataFrame 转为去歧义的 name->code 映射。"""
    code_to_name = {}
    for _, row in df.iterrows():
        code = row.get("code")
        name = row.get("name")
        if code is None or name is None:
            continue
        code_str = str(code).strip()
        # Strip .SH/.SZ suffix
        if "." in code_str:
            base, suffix = code_str.rsplit(".", 1)
            if suffix.upper() in ("SH", "SZ", "SS") and base.isdigit():
                code_str = base
        code_to_name[code_str] = _normalize_stock_name(str(name))
    return _build_reverse_map_no_duplicates(code_to_name)


def _try_load_disk_cache_locked() -> None:
    """懒加载磁盘缓存到内存（每进程至多尝试一次）。调用方必须持有 _state_lock。"""
    global _akshare_cache, _akshare_disk_checked
    if _akshare_disk_checked:
        return
    _akshare_disk_checked = True
    try:
        payload = json.loads(_AKSHARE_DISK_CACHE_PATH.read_text(encoding="utf-8"))
        ts = payload.get("ts")
        raw_map = payload.get("map")
        if isinstance(ts, (int, float)) and isinstance(raw_map, dict):
            # 历史落盘可能含未归一名称（全角拼写/内嵌空格）：加载即归一
            name_map = {
                _normalize_stock_name(str(k)): str(v)
                for k, v in raw_map.items()
                if k and v
            }
            if name_map:
                _akshare_cache = (float(ts), name_map)
                logger.info(
                    "[NameResolver] AkShare 磁盘缓存已加载: "
                    f"{len(name_map)} 条, age={time.time() - float(ts):.0f}s"
                )
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug(f"[NameResolver] AkShare 磁盘缓存不可用，忽略: {e}")


def _persist_akshare_map(name_map: Dict[str, str]) -> None:
    """原子落盘（每进程唯一 tmp 名 + os.replace）。失败非致命，仅记日志。

    tmp 名掺入 PID：web 与 CLI 可能是两个进程，共用同一 tmp 名会在
    os.replace 前互相覆盖对方尚未写完的文件。
    """
    try:
        path = _AKSHARE_DISK_CACHE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps({"ts": time.time(), "map": name_map}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception as e:
        logger.debug(f"[NameResolver] AkShare 磁盘缓存写入失败（非致命）: {e}")


def _spawn_refresh_locked() -> concurrent.futures.Future:
    """启动后台刷新线程并登记在途句柄。调用方必须持有 _state_lock。

    网络拉取、DataFrame 解析、落盘全部发生在这个 daemon 线程内——请求
    路径只读取状态或等待 Future，永不执行网络 IO。
    """
    global _akshare_inflight
    fut: concurrent.futures.Future = concurrent.futures.Future()
    # 先登记再启动：worker 理论上可能在 start() 返回前就完成，其清账
    # 分支 `is fut` 必须能看到已登记的句柄
    _akshare_inflight = fut

    def _worker():
        global _akshare_cache, _akshare_failure_cache, _akshare_inflight
        result: Optional[Dict[str, str]] = None
        try:
            try:
                df = _fetch_akshare_df()
                if df is not None and not df.empty:
                    # 空数据视同失败退避：短时间内重试只会得到同样的空结果
                    result = _build_name_map_from_df(df)
            except Exception as e:
                logger.warning(f"[NameResolver] AkShare fallback failed: {e}")
        finally:
            # 先清账并唤醒全部等待者，再做日志/落盘等 best-effort 副作用：
            # 慢日志 handler 或慢磁盘不得拖住等待者拿结果（曾把落盘排在
            # set_result 之前，慢盘时缓存已就绪、等待者却超时漏解）。
            # finally 兜底：BaseException 逃逸时句柄/退避/Future 也必然
            # 清账，不留死句柄（否则之后每个冷启动请求都白等满超时）。
            with _state_lock:
                now = time.time()
                if result:
                    _akshare_cache = (now, result)
                    _akshare_failure_cache = None
                else:
                    _akshare_failure_cache = now
                    result = None
                if _akshare_inflight is fut:
                    _akshare_inflight = None
            # 成功/失败都精确唤醒全部等待者；失败以 result=None 表达
            fut.set_result(result)
            if result:
                logger.info(
                    f"[NameResolver] AkShare cache loaded: {len(result)} name->code mappings"
                )
                _persist_akshare_map(result)

    try:
        threading.Thread(
            target=_worker, name="akshare-name-refresh", daemon=True
        ).start()
    except RuntimeError as e:
        # 线程启动失败（如进程线程数耗尽）：归还句柄并唤醒等待者
        _akshare_inflight = None
        fut.set_result(None)
        logger.warning(f"[NameResolver] AkShare 刷新线程启动失败: {e}")
    return fut


def _get_akshare_name_to_code() -> Optional[Dict[str, str]]:
    """获取 AkShare name->code：新鲜缓存直读；过期走 stale-while-revalidate
    （立即返回旧值 + 后台刷新）；冷启动限时等待在途 Future；失败退避。

    请求路径最坏只阻塞冷启动等待（_AKSHARE_WAIT_COLD_START）；TTL 过期
    的请求零等待；网络 IO 全部在后台刷新线程。
    """
    with _state_lock:
        if _akshare_cache is None:
            _try_load_disk_cache_locked()
        now = time.time()
        if _akshare_cache is not None and (now - _akshare_cache[0]) < _AKSHARE_CACHE_TTL:
            return _akshare_cache[1]
        stale_map = _akshare_cache[1] if _akshare_cache is not None else None
        in_backoff = (
            _akshare_failure_cache is not None
            and (now - _akshare_failure_cache) < _AKSHARE_FAILURE_TTL
        )
        fut = _akshare_inflight
        if fut is None and not in_backoff:
            fut = _spawn_refresh_locked()
    if stale_map is not None:
        # stale-while-revalidate：TTL 的语义就是容忍陈旧，过期瞬间等待
        # 毫无收益；返回旧值，下轮调用命中后台刷新出的新缓存。
        return stale_map
    if fut is None:
        # 冷启动且处于失败退避窗口：本地库照常服务
        return None
    try:
        result = fut.result(timeout=_AKSHARE_WAIT_COLD_START)
    except concurrent.futures.TimeoutError:
        # 正常情况下不可能到达：拉取被封顶、worker 在 finally 中必然
        # resolve。到达即 worker 违约（如子进程 kill 本身挂死）。
        logger.warning(
            "[NameResolver] 在途 AkShare 拉取超过死线未 resolve"
            f"（{_AKSHARE_WAIT_COLD_START:g}s），本轮退化为本地库解析"
        )
        return None
    except Exception as e:
        # worker 以 result=None 表达失败，这里只可能是 Future 内部异常
        logger.warning(f"[NameResolver] 等待在途 AkShare 拉取异常: {e}")
        return None
    return result


def warmup_akshare_cache() -> None:
    """进程启动预热：后台线程触发一次解析链填充（幂等、非阻塞）。

    命中磁盘缓存则零网络加载；否则发起后台单飞拉取。冷启动等待发生在
    本 daemon 线程内，不阻塞调用方。重复调用共享同一在途句柄，不会
    触发多次网络拉取。
    """

    def _warm():
        try:
            _get_akshare_name_to_code()
        except Exception as e:  # noqa: BLE001 - 预热必须 best-effort
            logger.warning(f"[NameResolver] AkShare 预热失败: {e}")

    threading.Thread(target=_warm, name="akshare-warmup", daemon=True).start()


# =========================================================================
# Stock — immutable code/name/market value object
# =========================================================================


@dataclass(frozen=True)
class Stock:
    """股票条目：code / name / market（"a" | "hk" | "us"）。"""

    code: str
    name: str = ""
    market: str = ""


# =========================================================================
# stockDB — 全局 code->name 数据库，由 AkShare A 股数据扩充
# =========================================================================


stockDB: Dict[str, str] = {
    # 初值即归一（与输入侧 NFKC 同变换）：源数据的全角拼写/内嵌空白
    # 不带入库内视图
    code: _normalize_stock_name(name) for code, name in STOCK_NAME_MAP.items()
}

# 已存在代码被 AkShare 更新为当前官方名称时，旧名称作为别名保留，
# 避免证券改名后旧名称彻底不可解析。
stockAliases: Dict[str, Set[str]] = {}

_MARKET_ORDER: Dict[str, int] = {"a": 0, "hk": 1, "us": 2}

# 已合并的 AkShare 缓存对象（幂等短路：同一份缓存不重复合并）
_akshare_merged: Optional[Dict[str, str]] = None


def extend_AkShare() -> bool:
    """用 AkShare 全量 A 股数据扩充 stockDB（幂等，30 分钟缓存）。

    Returns:
        True — stockDB 实际并入了新条目或更新了已存在代码的名称；
        False — 无需扩展（同一份缓存已合并 / 拉取失败 / 返回空数据 /
        无任何变化）。
    """
    global _akshare_merged
    akshare_map = _get_akshare_name_to_code()
    if not akshare_map:
        return False
    # 合并段整体持锁：与读路径的 stockDB 迭代串行，且"已合并对象"判定原子。
    # 网络抓取（上方）保持在锁外。
    with _db_lock:
        if _akshare_merged is akshare_map:
            return False
        changed = False
        # akshare_map 是 name->code 反向映射，stockDB 是 code->name；名称
        # 统一归一（NFKC 宽度 + 去内嵌空白）后比较/写入，避免与归一后的
        # 输入/本地拼写形成假性改名（制造无谓别名）——磁盘缓存里的历史
        # 未归一数据同样在此归一
        for name, code in akshare_map.items():
            compact = _normalize_stock_name(name)
            if not compact:
                continue
            if code not in stockDB:
                stockDB[code] = compact
                changed = True
            elif stockDB[code] != compact:
                # 证券改名：保留旧名称作为别名，再更新为 AkShare 当前官方名称。
                stockAliases.setdefault(code, set()).add(stockDB[code])
                stockDB[code] = compact
                changed = True
        _akshare_merged = akshare_map
        if changed:
            # stockDB 值更新或别名变化时 len(stockDB) 可能不变，
            # 必须显式失效名称/拼音缓存，否则改名后的新名称不可见。
            _names_cache[:] = [None, None, None]
            _pinyin_cache[:] = [None, None]
        return changed


# =========================================================================
# 名称/拼音缓存 —— 以 (database 对象, len) 为键：对数据库的任何插入或
# 删除都会自动使其失效，无需手动重置。
# =========================================================================


_names_cache: List = [None, None, None]  # [database, len(database), names]
_pinyin_cache: List = [None, None]  # [names, pinyins]


def _database_names(database: Dict[str, str]) -> List[str]:
    """*database* 中去重、保持顺序的名称列表（带缓存）。

    除了 canonical（规范）名称，还会包含 stockDB 的旧名称别名；这样旧名称也能参与
    精确、子串、拼音和模糊匹配。
    """
    with _db_lock:
        if _names_cache[0] is database and _names_cache[1] == len(database):
            return _names_cache[2]
        names = list(dict.fromkeys(database.values()))
        if database is stockDB:
            for aliases in stockAliases.values():
                for alias in aliases:
                    if alias not in names:
                        names.append(alias)
        _names_cache[:] = [database, len(database), names]
        return names


def _database_pinyins(
    database: Dict[str, str], names: Optional[List[str]] = None
) -> List[str]:
    """与 *names* 对齐的全拼小写拼音列表（带缓存）。

    传入外层快照时按快照构建，保证与调用方本地 names 同源同序，
    避免并发合并期间两次取列表导致 zip 错位配对。
    """
    if names is None:
        names = _database_names(database)
    with _db_lock:
        if _pinyin_cache[0] is not names:
            try:
                from pypinyin import lazy_pinyin

                pinyins = ["".join(lazy_pinyin(name)).lower() for name in names]
            except Exception:
                pinyins = [""] * len(names)
            _pinyin_cache[:] = [names, pinyins]
        return _pinyin_cache[1]


# =========================================================================
# 名称匹配辅助函数
# =========================================================================


def _exact_names(fragment: str, database: Dict[str, str]) -> List[str]:
    """返回 database 名称中与 *fragment* 不区分大小写精确匹配的结果。"""
    fragment_lower = fragment.lower()
    return [name for name in _database_names(database) if name.lower() == fragment_lower]


def _is_single_char_typo(input_name: str, candidate_name: str) -> bool:
    """当两个名称仅有一个字符位不同时返回 True。"""
    if not input_name or not candidate_name:
        return False
    if len(input_name) != len(candidate_name):
        return False
    # Keep typo fallback conservative: only for names with enough signal.
    if len(input_name) < 3:
        return False
    diff = sum(1 for a, b in zip(input_name, candidate_name) if a != b)
    return diff == 1


# 拼音子串匹配的最短长度：拼音字母是逐音节的高频粒子，过短片段（o/k/ai/ma）
# 会命中大量无关名称的拼音子串，把普通英文输入误解析成股票。
_MIN_PINYIN_FRAGMENT_LEN = 5


def _fix_name(fragment: str, database: Dict[str, str]) -> List[str]:
    """通过混合匹配将名称片段解析为完整股票名称。

    策略链（按顺序）：
    1. 精确匹配（不区分大小写）
    2. 子串匹配（不区分大小写；片段含 >= 2 个 CJK 字符，如 茅台 -> 贵州茅台）
    3. 拼音子串匹配（如 "maotai" ⊂ "guizhoumaotai"）
    4. difflib 模糊匹配（cutoff 0.8，另加 0.7 的保守单字符错别字回退，
       如 贵州茅苔 -> 贵州茅台）
    """
    if not fragment:
        return []
    fragment_lower = fragment.lower()
    names = _database_names(database)

    # 1. Exact match
    exact = [name for name in names if name.lower() == fragment_lower]
    if exact:
        return exact

    # 2. Substring match
    if sum(1 for ch in fragment if "\u3400" <= ch <= "\u9fff") >= 2:
        matches = [name for name in names if fragment_lower in name.lower()]
        if matches:
            return matches

    # 3. Pinyin substring match — 仅对纯 ASCII 片段生效
    # （设计场景是英文拼音输入："maotai" ⊂ "guizhoumaotai"）。CJK 片段
    # 转拼音后粒度失控：实义字 + 助词（"阿里的" → "alide"）恰好 5 字母
    # 过最短长度闸门，与不相干全名（"alide" ⊂ "zhongdalide" 中大力德）
    # 发生子串碰撞；且 CJK 的合法场景已被其余三层覆盖（精确/子串/difflib）
    if _contains_cjk(fragment):
        fragment_pinyin = ""
    else:
        try:
            from pypinyin import lazy_pinyin

            fragment_pinyin = "".join(lazy_pinyin(fragment)).lower()
        except Exception:
            fragment_pinyin = ""
    if len(fragment_pinyin) >= _MIN_PINYIN_FRAGMENT_LEN:
        matches = [
            name
            for name, pinyin in zip(names, _database_pinyins(database, names))
            if fragment_pinyin in pinyin
        ]
        if matches:
            return matches

    # 4. Fuzzy match
    if len(fragment) > 2:
        matches = difflib.get_close_matches(fragment, names, n=5, cutoff=0.8)
        if matches:
            return matches
        typo_matches = difflib.get_close_matches(fragment, names, n=5, cutoff=0.7)
        matches = [m for m in typo_matches if _is_single_char_typo(fragment, m)]
        if matches:
            return matches

    return []


def _infer_code_market(code: str) -> Optional[str]:
    """根据代码格式推断市场：6 位数字→"a"，5 位数字→"hk"，字母→"us"。"""
    c = code.strip()
    if c.isdigit():
        return {5: "hk", 6: "a"}.get(len(c))
    return "us" if re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", c) else None


def _find_codes_for_name(name: str, database: Dict[str, str]) -> List[Tuple[str, str]]:
    """查找 *database* 中映射到 *name* 的所有 (code, market) 组合。"""
    results: List[Tuple[str, str]] = []
    # 持锁迭代：与 extend_AkShare 的并发写串行
    with _db_lock:
        for code, mapped_name in database.items():
            if mapped_name == name or (
                database is stockDB and name in stockAliases.get(code, set())
            ):
                market = _infer_code_market(code)
                if market:
                    results.append((code, market))
    return results


# =========================================================================
# 公开 API
# =========================================================================


def resolver_name_to_code_list(name: str) -> List[Stock]:
    """将股票名称解析为匹配的 ``Stock`` 条目（最多 5 个）。暂不解析股票代码。

    1. 对 CJK 输入，用 AkShare A 股数据扩充 ``stockDB``（幂等，带失败退避）；
       非 CJK 输入完全跳过网络拉取。
    2. 在 ``stockDB`` 上做精确匹配。
    3. 在扩充后的数据库上做混合匹配（精确/子串/拼音/模糊）。

    结果按 A 股 → 港股 → 美股 排序。

    示例：
        "阿里巴巴" → [Stock("09988", "阿里巴巴", "hk"), Stock("BABA", "阿里巴巴", "us")]
        "茅台"     → [Stock("600519", "贵州茅台", "a")]
        "你好世界"  → []
    """
    if not name or not isinstance(name, str):
        return []
    # 查询输入与入库同源归一：源形态（全角拼写/内嵌空格，如自 AkShare 数据
    # 复制的 "京东方Ａ"/"五 粮 液"）与常规拼写同样可解析
    s = _normalize_stock_name(name)
    # 单字符不可能是股票名（最短 2 字），短路避免全名表扫描
    if len(s) < 2:
        return []

    # A 股名称全是 CJK —— 非 CJK 输入无法从网络扩充获益，但仍可参与本地
    # 混合（拼音）匹配。
    # 即使是本地精确命中也要先执行 AkShare 扩充：本地已有的同名港股/美股
    # 不能阻止 AkShare 中同名 A 股被并入，否则跨市场候选会不完整。
    if _contains_cjk(s):
        extend_AkShare()

    full_names = _exact_names(s, stockDB)
    if not full_names:
        full_names = _fix_name(s, stockDB)
    if not full_names:
        return []

    stocks: List[Stock] = []
    seen: Set[str] = set()
    for full_name in full_names:
        for code, market in _find_codes_for_name(full_name, stockDB):
            if code not in seen:
                seen.add(code)
                stocks.append(Stock(code=code, name=stockDB.get(code, full_name), market=market))

    stocks.sort(key=lambda r: _MARKET_ORDER.get(r.market, 99))
    return stocks[:5]


def US_stock_code_match(segment: str) -> List[Stock]:
    """匹配美股代码：1~5 个英文字母的 ticker，仅本地库存在该代码时才返回。

    避免把普通英文单词（hello/open/...）误判为股票代码。
    """
    if not isinstance(segment, str) or not segment.isascii() or not segment.isalpha():
        return []
    if not 1 <= len(segment) <= 5:
        return []
    upper = segment.upper()
    name = stockDB.get(upper, "")
    return [Stock(code=upper, name=name, market="us")] if name else []


def lookup_stock_by_code(code: str) -> Optional[Stock]:
    """按规范化代码查库，返回完整 (code/name/market) 三元组；查不到返回 None。

    格式合法不等于存在：stockDB 未命中即 None，绝不虚构（LLM 幻觉/过期
    代码不得直接注入 stocks）。本地库港股键为裸 5 位（"00700"），HK 前缀
    形态（"HK00700"）自动补查去前缀裸键。
    """
    c = (code or "").strip().upper()
    if not c:
        return None
    with _db_lock:
        name = stockDB.get(c)
        if not name and c.startswith("HK"):
            name = stockDB.get(c[2:])
        if not name:
            return None
    if c.startswith("HK"):
        market = "hk"
    else:
        market = _infer_code_market(c) or ""
    return Stock(code=c, name=name, market=market)


def is_market_db_complete(market: str) -> bool:
    """该市场名称库是否已扩展为全量（库未命中即可断定代码不存在）。

    A 股：AkShare 全量列表已并入 stockDB（extend_AkShare 成功过，
    ``_akshare_merged`` 非空）。港股/美股：本地精选库，永不视为全量，
    未命中只能存疑交下游判断。
    """
    return market == "a" and _akshare_merged is not None


def is_known_stock_name(name: str) -> bool:
    """判断 *name* 是否为 stockDB 中已知的股票全名（含改名别名）。

    只做本地名称表成员判定，绝不触发 AkShare 网络扩展。代码键
    （如 "600519"）不算名称命中：分词管道（web_intent_tokenizer）用本
    函数保护"已识别名称 token"，代码形文本必须继续进入代码提取步骤
    重新标注，而不是被当作名称跳过。
    """
    if not isinstance(name, str):
        return False
    s = _normalize_stock_name(name)
    if not s:
        return False
    return s in _database_names(stockDB)


def resolve_name_to_code(name: str) -> Optional[str]:
    """
    Resolve stock name to code.

    Strategy (in order):
    1. If input looks like a code (5-6 digits or 1-5 letters), return it normalized.
    2. Local STOCK_NAME_MAP reverse (exclude ambiguous names).
    3. Pinyin match against local names.
    4. AkShare online fallback (A-shares).
    5. Fuzzy match (difflib).
    6. Return None.

    Args:
        name: Stock name or code string.

    Returns:
        Resolved stock code, or None if ambiguous/failed.
    """
    if not name or not isinstance(name, str):
        return None
    s = _normalize_stock_name(name)
    if not s:
        return None

    # 1. Input looks like code
    if _is_code_like(s):
        return _normalize_code(s)

    # 2. Local reverse map (no duplicates)
    local_reverse = _LOCAL_REVERSE_MAP
    if s in local_reverse:
        return local_reverse[s]
    if s in _LOCAL_AMBIGUOUS_NAMES:
        logger.debug(f"[NameResolver] 命中本地歧义名称，快速返回 None: {s}")
        return None

    # 3. Pinyin match (exact)
    try:
        from pypinyin import lazy_pinyin

        input_pinyin = "".join(lazy_pinyin(s)).lower()
        for local_name, code in local_reverse.items():
            local_pinyin = "".join(lazy_pinyin(local_name)).lower()
            if input_pinyin == local_pinyin:
                return code
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"[NameResolver] Pinyin match failed: {e}")

    # Skip AkShare/fuzzy fallback for non-CJK free text such as random Latin noise.
    # These paths are expensive and only meaningfully help Chinese stock names.
    if not _contains_cjk(s):
        logger.debug(f"[NameResolver] Skip CJK-only fallbacks for non-CJK input: {s}")
        return None

    # 4. AkShare fallback
    akshare_map = _get_akshare_name_to_code()
    if akshare_map and s in akshare_map:
        logger.debug(f"[NameResolver] 命中 AkShare 映射: {s} -> {akshare_map[s]}")
        return akshare_map[s]

    # 5. Fuzzy match (local + akshare, local takes precedence)
    all_name_to_code = dict(local_reverse)
    if akshare_map:
        all_name_to_code.update(akshare_map)
    # Skip fuzzy matching for very short inputs (<=2 chars) to avoid false positives,
    # e.g. '中国' matching arbitrary company names in a pool of 5000+ stocks.
    # Use a higher cutoff (0.8) to reduce mis-hits on longer inputs as well.
    if len(s) > 2:
        names = list(all_name_to_code.keys())
        matches = difflib.get_close_matches(s, names, n=1, cutoff=0.8)
        if matches:
            logger.debug(f"[NameResolver] 命中模糊匹配: input={s}, matched={matches[0]}")
            return all_name_to_code[matches[0]]

        # Conservative fallback for one-character typo in medium/long names.
        # This keeps the strict default threshold while fixing obvious misspellings
        # such as "贵州茅苔" -> "贵州茅台".
        typo_matches = difflib.get_close_matches(s, names, n=1, cutoff=0.7)
        if typo_matches and _is_single_char_typo(s, typo_matches[0]):
            logger.debug(f"[NameResolver] 命中单字误写兜底: input={s}, matched={typo_matches[0]}")
            return all_name_to_code[typo_matches[0]]

    logger.debug(f"[NameResolver] 解析失败: {s}")
    return None
