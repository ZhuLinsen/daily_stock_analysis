# -*- coding: utf-8 -*-
"""新闻检索未执行或零命中时的报告披露文案。

单一事实来源：字符串拼接渲染器（src/notification.py）与模板渲染链路
（src/services/report_renderer.py + templates/*.j2）共用本模块，避免
同一份分析结果在部分渠道披露、在另一些渠道沉默。

news_result_count 的三态语义：
    None  未执行检索（未配置搜索渠道）——明确说明新闻面证据未纳入
    0     执行了检索但零命中（限流、全部失败等）——静默失败，必须提示
    > 0   正常拿到新闻——不提示
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional, Tuple

from src.report_language import SUPPORTED_REPORT_LANGUAGES

_ZH_NOT_CONFIGURED = "⚠️ 未配置搜索渠道，本次分析未纳入新闻面证据。"
_EN_NOT_CONFIGURED = (
    "⚠️ No news search channel is configured; "
    "this analysis does not incorporate news-based evidence."
)
_ZH_ZERO_RESULTS = "⚠️ 本次未获取到可用的新闻面数据，以下结论未纳入新闻维度证据。"
_EN_ZERO_RESULTS = (
    "⚠️ No news data could be retrieved for this run; "
    "the conclusions below do not incorporate news-based evidence."
)
_KO_NOT_CONFIGURED = (
    "⚠️ 뉴스 검색 채널이 설정되지 않아 이번 분석에는 "
    "뉴스 근거를 반영하지 않았습니다."
)
_KO_ZERO_RESULTS = (
    "⚠️ 이번 분석에서 사용 가능한 뉴스 데이터를 가져오지 못해 "
    "아래 결론에는 뉴스 근거를 반영하지 않았습니다."
)

_DISCLOSURES = {
    "zh": (_ZH_NOT_CONFIGURED, _ZH_ZERO_RESULTS),
    "en": (_EN_NOT_CONFIGURED, _EN_ZERO_RESULTS),
    "ko": (_KO_NOT_CONFIGURED, _KO_ZERO_RESULTS),
}

if set(_DISCLOSURES) != set(SUPPORTED_REPORT_LANGUAGES):
    raise RuntimeError(
        "Empty-news disclosures must cover every SUPPORTED_REPORT_LANGUAGES value"
    )


def persisted_news_result_state(
    raw_result: Any,
    context_snapshot: Any = None,
) -> Tuple[Optional[int], bool]:
    """从持久化载荷恢复计数及其可信度。

    新记录的 raw_result 明确保存三态值；旧记录可在 context_snapshot 中留下
    0 / >0 计数。两处都没有字段时只能判定为 legacy unknown，不能把缺字段
    当成明确的 None。
    """
    if isinstance(raw_result, Mapping):
        if raw_result.get("news_result_count_known") is False:
            return None, False
        if "news_result_count" in raw_result:
            return raw_result.get("news_result_count"), True

    if isinstance(context_snapshot, Mapping) and "news_result_count" in context_snapshot:
        return context_snapshot.get("news_result_count"), True

    return None, False


def _disclosure_for_state(
    news_result_count: Optional[int],
    *,
    known: bool,
    language: str,
) -> Optional[str]:
    try:
        not_configured, zero_results = _DISCLOSURES[language]
    except KeyError as exc:
        raise ValueError(f"Unsupported report language for empty-news disclosure: {language}") from exc

    if not known:
        return None
    if news_result_count is None:
        return not_configured
    if news_result_count == 0:
        return zero_results
    return None


def empty_news_disclosure(result: Any, language: str = "zh") -> Optional[str]:
    """未执行或零命中时返回对应提示；正常命中时返回 None。

    判定必须独立于模型是否产出了消息面文字：analyzer 的输出 schema 即使
    在没有新闻时也会要求填 market_sentiment / hot_topics，若以这些字段
    是否为空来决定，就会出现「展示模型生成的情绪判断、却隐瞒无新闻证据」
    这一最糟的组合。
    """
    if isinstance(result, Mapping):
        news_result_count, known = persisted_news_result_state(result)
    else:
        news_result_count = getattr(result, "news_result_count", None)
        known = getattr(result, "news_result_count_known", True)
    return _disclosure_for_state(
        news_result_count,
        known=known,
        language=language,
    )


def empty_news_disclosure_from_stored(
    raw_result: Any,
    context_snapshot: Any,
    language: str = "zh",
) -> Optional[str]:
    """为历史/API 入口从持久化载荷生成披露；旧记录缺字段时保持静默。"""
    news_result_count, known = persisted_news_result_state(raw_result, context_snapshot)
    return _disclosure_for_state(
        news_result_count,
        known=known,
        language=language,
    )
