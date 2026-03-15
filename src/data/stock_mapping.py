# -*- coding: utf-8 -*-
from __future__ import annotations

"""
===================================
股票代码与名称映射
===================================

Shared stock code -> name mapping, used by analyzer, data_provider, and name_to_code_resolver.
"""

# Stock code -> name mapping (common stocks)
STOCK_NAME_MAP = {
    # === A-shares ===
    "600519": "贵州茅台",
    "000001": "平安银行",
    "300750": "宁德时代",
    "002594": "比亚迪",
    "600036": "招商银行",
    "601318": "中国平安",
    "000858": "五粮液",
    "600276": "恒瑞医药",
    "601012": "隆基绿能",
    "002475": "立讯精密",
    "300059": "东方财富",
    "002415": "海康威视",
    "600900": "长江电力",
    "601166": "兴业银行",
    "600028": "中国石化",
    "600030": "中信证券",
    "600031": "三一重工",
    "600050": "中国联通",
    "600104": "上汽集团",
    "600111": "北方稀土",
    "600150": "中国船舶",
    "600309": "万华化学",
    "600406": "国电南瑞",
    "600690": "海尔智家",
    "600760": "中航沈飞",
    "600809": "山西汾酒",
    "600887": "伊利股份",
    "600930": "华电新能",
    "601088": "中国神华",
    "601127": "赛力斯",
    "601211": "国泰海通",
    "601225": "陕西煤业",
    "601288": "农业银行",
    "601328": "交通银行",
    "601398": "工商银行",
    "601601": "中国太保",
    "601628": "中国人寿",
    "601658": "邮储银行",
    "601668": "中国建筑",
    "601728": "中国电信",
    "601816": "京沪高铁",
    "601857": "中国石油",
    "601888": "中国中免",
    "601899": "紫金矿业",
    "601919": "中远海控",
    "601985": "中国核电",
    "601988": "中国银行",
    "603019": "中科曙光",
    "603259": "药明康德",
    "603501": "豪威集团",
    "603993": "洛阳钼业",
    "688008": "澜起科技",
    "688012": "中微公司",
    "688041": "海光信息",
    "688111": "金山办公",
    "688256": "寒武纪",
    "688981": "中芯国际",
    # === US stocks ===
    "AAPL": "苹果",
    "TSLA": "特斯拉",
    "MSFT": "微软",
    "GOOGL": "谷歌A",
    "GOOG": "谷歌C",
    "AMZN": "亚马逊",
    "NVDA": "英伟达",
    "META": "Meta",
    "AMD": "AMD",
    "INTC": "英特尔",
    "BABA": "阿里巴巴",
    "PDD": "拼多多",
    "JD": "京东",
    "BIDU": "百度",
    "NIO": "蔚来",
    "XPEV": "小鹏汽车",
    "LI": "理想汽车",
    "COIN": "Coinbase",
    "MSTR": "MicroStrategy",
    # === HK stocks (5-digit) ===
    "00700": "腾讯控股",
    "03690": "美团",
    "01810": "小米集团",
    "09988": "阿里巴巴",
    "09618": "京东集团",
    "09888": "百度集团",
    "01024": "快手",
    "00981": "中芯国际",
    "02015": "理想汽车",
    "09868": "小鹏汽车",
    "00005": "汇丰控股",
    "01299": "友邦保险",
    "00941": "中国移动",
    "00883": "中国海洋石油",
}


def is_meaningful_stock_name(name: str | None, stock_code: str) -> bool:
    """Return whether a stock name is useful for display or caching."""
    if not name:
        return False

    normalized_name = str(name).strip()
    if not normalized_name:
        return False

    normalized_code = (stock_code or "").strip().upper()
    if normalized_name.upper() == normalized_code:
        return False

    if normalized_name.startswith("股票"):
        return False

    placeholder_values = {
        "N/A",
        "NA",
        "NONE",
        "NULL",
        "--",
        "-",
        "UNKNOWN",
        "TICKER",
    }
    if normalized_name.upper() in placeholder_values:
        return False

    return True
