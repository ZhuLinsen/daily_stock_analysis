# -*- coding: utf-8 -*-
"""
===================================
A 股指数代码工具
===================================

大盘复盘均线计算需要按指数拉取日线历史，而不同数据源返回的指数代码格式
不一致（akshare/新浪: ``sh000001``，tushare: ``000001`` / ``000001.SH``，
yfinance: ``000001.SS``）。本模块提供一个显式白名单映射与归一化函数，
避免把指数代码误当成个股代码（如 ``000001`` 同时是上证指数与平安银行）。

只服务指数场景；个股代码请走各 fetcher 的股票代码转换逻辑。
"""

from typing import Optional

# 纯数字代码 -> (交易所前缀, 指数名称)
# 与 get_main_indices 各数据源的指数集合保持一致。
CN_INDEX_CODES = {
    '000001': ('sh', '上证指数'),
    '399001': ('sz', '深证成指'),
    '399006': ('sz', '创业板指'),
    '000688': ('sh', '科创50'),
    '000016': ('sh', '上证50'),
    '000300': ('sh', '沪深300'),
}


def normalize_cn_index_code(code: str) -> Optional[str]:
    """
    将任意来源的 A 股指数代码归一化为纯数字代码。

    支持输入：``sh000001`` / ``SH000001`` / ``000001`` / ``000001.SH`` /
    ``000001.SS``。不在白名单内的代码返回 None（宁缺毋滥，调用方按
    数据缺失处理，不得回退到个股行情接口）。
    """
    normalized = (code or '').strip().lower()
    if not normalized:
        return None
    if '.' in normalized:
        normalized = normalized.split('.', 1)[0]
    if normalized[:2] in ('sh', 'sz') and normalized[2:].isdigit():
        normalized = normalized[2:]
    if normalized in CN_INDEX_CODES:
        return normalized
    return None


def cn_index_sina_symbol(digits: str) -> Optional[str]:
    """纯数字指数代码 -> 新浪风格符号（如 ``sh000001``）。"""
    entry = CN_INDEX_CODES.get(digits)
    if not entry:
        return None
    return f"{entry[0]}{digits}"
