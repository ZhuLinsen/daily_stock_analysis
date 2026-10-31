# -*- coding: utf-8 -*-
"""
===================================
TdxLocalFetcher - 通达信本地 vipdoc 日线数据源
===================================

数据来源：通达信客户端本地日线文件（``vipdoc/<market>/lday/<market><code>.day``）。
特点：零网络请求、无封禁风险；本地数据缺失或不支持时返回空结果，由
``DataFetcherManager`` 自动回退既有网络数据源链。

关键策略：
1. 仅当配置了 ``TDX_LOCAL_PATH`` 且目录存在时才注册（D4 双保险之注册门槛，
   见 ``DataFetcherManager._init_default_fetchers``）。
2. 请求期目录失效（被移动/删除）时 ``is_available_for_request`` 返回 False，
   管理器跳过本源（D4 双保险之可用性探针，样板 pytdx_fetcher.py:168）。
3. 缺文件/BSE/港股/窗口无交集/窗口头部缺口一律返回空 DataFrame（D6）：空结果不进
   日线熔断器（抛异常 3 次会触发 300s 熔断），管理器记 empty 后继续下一个网络源。
   头部缺口（请求窗口起点早于本地最早 bar，如中途才安装 TDX）同样返回空回退，
   不以部分数据"成功"终止回退链。
4. 过期回退（D5）：本地最新 bar 落后请求窗口 end_date 超过
   ``TDX_LOCAL_MAX_STALE_DAYS``（默认 10 个日历日，覆盖国庆长假）→ 返回空结果
   回退网络源。基准是 end_date 而非今天：回测等历史窗口且本地已覆盖时不判过期。
   合法阈值 0（零容忍滞后）被保留，不会被默认值替换。
5. 代码→vipdoc 路径映射对齐 ``PytdxFetcher._get_market_code``（D8）：显式
   前缀/后缀两种风格 + 裸 6 位码按 60/68→sh、其余→sz。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from .base import (
    STANDARD_COLUMNS,
    BaseFetcher,
    _is_hk_market,
    is_bse_code,
    normalize_stock_code,
)
from .tdx_day_parser import build_vipdoc_day_path, parse_day_file, resolve_vipdoc_root

logger = logging.getLogger(__name__)

# 本地数据可接受的最大滞后日历日（D5，Wave 3 启用过期回退时使用）
_DEFAULT_MAX_STALE_DAYS = 10


class TdxLocalFetcher(BaseFetcher):
    """
    通达信本地 vipdoc 日线数据源（BaseFetcher 子类即本仓库的插件机制）。

    优先级：默认 0（与 Efinance 同级）；注册时插在默认链最前，
    ``sort(key=priority)`` 稳定排序使本地严格先于网络源（D7）。
    可用 ``TDX_LOCAL_PRIORITY`` 调整。

    输出契约：``['code'] + STANDARD_COLUMNS``（pct_chg 由 close 计算、首行 0；
    ma5/ma20 等技术指标由基类 ``_calculate_indicators`` 生成）。
    ``.day`` 为原始未复权价。
    """

    name = "TdxLocalFetcher"

    # D6：本地文件缺失/数据过期返回空结果而非抛异常——空结果由管理器按
    # "empty" 记账并继续下一网络源，不会触发 3 次失败 300s 的日线熔断。
    allow_empty_daily_data = True

    def __init__(self) -> None:
        # D3（critic 修正）：配置在构造期读为实例属性。禁止导入期类属性
        # （pytdx_fetcher.py:118 反例）——导入期读取会让测试的
        # monkeypatch.setenv 不生效。
        from src.config import get_config

        config = get_config()
        raw_path = str(getattr(config, "tdx_local_path", None) or "").strip()
        self._tdx_root: Optional[Path] = Path(raw_path) if raw_path else None
        self.priority = int(getattr(config, "tdx_local_priority", 0) or 0)
        # 合法阈值 0（config.py/config_registry.py 均允许，语义=零容忍滞后）不得被
        # `or` 静默替换为默认 10——仅未配置（None）时才取默认值。
        raw_stale_days = getattr(config, "tdx_local_max_stale_days", None)
        self._max_stale_days = (
            int(raw_stale_days) if raw_stale_days is not None else _DEFAULT_MAX_STALE_DAYS
        )

    def _resolve_vipdoc_root(self) -> Optional[Path]:
        """每次请求实时解析 vipdoc 根（目录可能在构造后被移动/删除，D4-b）。"""
        if self._tdx_root is None:
            return None
        return resolve_vipdoc_root(self._tdx_root)

    def is_available_for_request(self, capability: str = "") -> bool:
        root = self._resolve_vipdoc_root()
        return root is not None and root.is_dir()

    def _empty_frame(self) -> pd.DataFrame:
        """空原始结果（D6 回退通道）。"""
        return pd.DataFrame()

    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        # 港股防御：manager 市场表已把本源挡在 cn 之外（_DAILY_MARKET_FETCHER_SUPPORT），
        # 直连调用时这里再加一道（D8）。
        if _is_hk_market(stock_code):
            logger.debug("TdxLocalFetcher 不支持港股 %s，返回空结果回退网络源", stock_code)
            return self._empty_frame()

        normalized = normalize_stock_code(stock_code)

        # 北交所码无 sh/sz lday 覆盖（D8）
        if is_bse_code(normalized):
            logger.debug("TdxLocalFetcher 不支持北交所 %s，返回空结果回退网络源", stock_code)
            return self._empty_frame()

        root = self._resolve_vipdoc_root()
        if root is None:
            logger.debug("TdxLocalFetcher 未配置有效的 TDX_LOCAL_PATH vipdoc 目录，返回空结果")
            return self._empty_frame()

        frame = parse_day_file(build_vipdoc_day_path(root, normalized))
        if frame is None or frame.empty:
            return self._empty_frame()

        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)

        # D5 过期回退（Wave 3）：以请求窗口的 end_date（而非今天）为基准——回测等
        # 历史窗口的 end_date 在过去且本地已覆盖时差值 <= 0，天然不判过期。仅当
        # 本地最新 bar 落后 end_date 超过 TDX_LOCAL_MAX_STALE_DAYS 个日历日（默认
        # 10，覆盖国庆长假；春节等超长假期可调大）才视为过期 → 返回空 DataFrame，
        # 由管理器按 empty 记账并回退网络源（D6，不进日线熔断器）。
        # 边界：恰好等于阈值（stale_days == N）不判过期，仍用本地数据。
        latest_ts = frame["date"].max()
        stale_days = (end_ts - latest_ts).days
        if stale_days > self._max_stale_days:
            logger.warning(
                "TdxLocalFetcher 本地数据过期，回退网络源: %s, 本地最新 bar=%s, "
                "end_date=%s, 滞后 %d 天 > TDX_LOCAL_MAX_STALE_DAYS=%d",
                stock_code,
                latest_ts.strftime("%Y-%m-%d"),
                end_date,
                stale_days,
                self._max_stale_days,
            )
            return self._empty_frame()

        window = frame[(frame["date"] >= start_ts) & (frame["date"] <= end_ts)]
        if window.empty:
            logger.debug(
                "TdxLocalFetcher 本地数据与请求窗口无交集: %s, 窗口=%s ~ %s",
                stock_code,
                start_date,
                end_date,
            )
            return self._empty_frame()

        # D5-b（OR-COR-b1d9f608）：真实头部缺口以"文件最早 bar > 请求起点"为准，
        # 而非"窗口首条 bar > 起点"——window 已滤掉起点之前的记录，且 base.py 的
        # 默认起点按日历日推导（end_date 减 days*2 个日历日），起点周期性落在
        # 周末/节假日：文件跨越起点时窗口首条天然晚于起点，那只是起点休市，
        # 完整本地数据仍应服务。文件最早 bar 在起点之后才是真覆盖不足（用户中途
        # 才安装 TDX）→ 返回空结果回退网络源。部分数据不得以"成功"身份终止回退，
        # 否则管理器视作成功后网络源没有机会补齐，下游对不足历史直接报错且写库
        # 后重试无法自愈。头部完整性（此处）与尾部新鲜度（上方 max_stale_days）
        # 同等对待；本地覆盖窗口时仍由本地服务（本地优先不变）。
        file_first_ts = frame["date"].min()
        if file_first_ts > start_ts:
            logger.warning(
                "TdxLocalFetcher 本地数据晚于请求窗口起点（头部缺口），回退网络源: %s, "
                "窗口起点=%s, 本地最早 bar=%s",
                stock_code,
                start_date,
                file_first_ts.strftime("%Y-%m-%d"),
            )
            return self._empty_frame()

        return window

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """
        标准化本地日线数据（样板 pytdx_fetcher.py:376-409）。

        ``.day`` 解析输出为 ``date/open/high/low/close/volume/amount``，无涨跌幅
        列——由 close 计算 pct_chg（首行 fillna(0)）；ma5/ma20 等技术指标交给
        基类 ``_calculate_indicators``，不在此重复计算。
        """
        df = df.copy()

        if "pct_chg" not in df.columns and "close" in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100
            df["pct_chg"] = df["pct_chg"].fillna(0).round(2)

        df["code"] = stock_code

        keep_cols = ["code"] + STANDARD_COLUMNS
        existing_cols = [col for col in keep_cols if col in df.columns]
        return df[existing_cols]
