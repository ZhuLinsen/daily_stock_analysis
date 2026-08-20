# -*- coding: utf-8 -*-
"""新闻检索零命中时的报告披露文案。

单一事实来源：字符串拼接渲染器（src/notification.py）与模板渲染链路
（src/services/report_renderer.py + templates/*.j2）共用本模块，避免
同一份分析结果在部分渠道披露、在另一些渠道沉默。

news_result_count 的三态语义：
    None  未执行检索（未配置搜索渠道）——用户的选择，不是失败，不提示
    0     执行了检索但零命中（限流、全部失败等）——静默失败，必须提示
    > 0   正常拿到新闻——不提示
"""

from __future__ import annotations

from typing import Any, Optional

_ZH = "⚠️ 本次未获取到可用的新闻面数据，以下结论未纳入新闻维度证据。"
_EN = (
    "⚠️ No news data could be retrieved for this run; "
    "the conclusions below do not incorporate news-based evidence."
)


def empty_news_disclosure(result: Any, language: str = "zh") -> Optional[str]:
    """零命中时返回需要写进报告的一行提示；否则返回 None。

    判定必须独立于模型是否产出了消息面文字：analyzer 的输出 schema 即使
    在没有新闻时也会要求填 market_sentiment / hot_topics，若以这些字段
    是否为空来决定，就会出现「展示模型生成的情绪判断、却隐瞒无新闻证据」
    这一最糟的组合。
    """
    if getattr(result, "news_result_count", None) != 0:
        return None
    return _EN if language == "en" else _ZH
