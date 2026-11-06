# -*- coding: utf-8 -*-
"""新闻检索未执行或零命中时的报告披露文案。

单一事实来源：字符串拼接渲染器（src/notification.py）与模板渲染链路
（src/services/report_renderer.py + templates/*.j2）共用本模块，避免
同一份分析结果在部分渠道披露、在另一些渠道沉默。

披露断言的是「本次结论有没有用到新闻面证据」，因此第一依据是分析实际收到的消息面
证据（news_context）是否非空，而不是搜索命中了几条。news_context 可能来自实时检索、
社交情绪或本地已落库的资讯池，后两者同样进入模型输入却不产生搜索命中；只看计数会把
这类分析误报成「未纳入新闻面证据」（review OR-COR-2e4b9d61）。

news_result_count 因此退居第二位，只用来解释「确实没有证据」时的原因：
    None  未执行检索（未配置搜索渠道）
    0     执行了检索但零命中（限流、全部失败等）
    > 0   实时检索有命中（此时证据必然存在）
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


def news_evidence_present(*sources: Any) -> bool:
    """本次分析是否真的收到了消息面证据。任一来源为真即为真。

    每个来源要么是真实条数（int），要么是**已排除占位文本**的内容字符串。
    实时检索、社交情绪、本地资讯池各算一路，pipeline 两条路径都用本函数，
    不要在别处另写判断。

    **不要把 pipeline 拼好的整段 news_context 传进来。**
    `src/search_service.py` 的 `format_intel_report()` 在零命中时仍会输出
    `【XX 情报搜索结果】` 标题和每个维度的「未找到相关信息」占位文本，整段永远
    非空；用它判定会把「搜了但一条没拿到」翻成「有证据」，恰好吞掉本模块要补的
    披露（review OR-COR-8f4c2d1b）。判定必须按来源逐个登记，不能闻字符串。
    """
    for source in sources:
        if source is None or isinstance(source, bool):
            if source:
                return True
            continue
        if isinstance(source, (int, float)):
            if source > 0:
                return True
            continue
        if str(source).strip():
            return True
    return False


def _disclosure_for_state(
    news_result_count: Optional[int],
    *,
    known: bool,
    evidence_present: bool,
    language: str,
) -> Optional[str]:
    try:
        not_configured, zero_results = _DISCLOSURES[language]
    except KeyError as exc:
        raise ValueError(f"Unsupported report language for empty-news disclosure: {language}") from exc

    if not known:
        return None
    # 证据存在就不提示，无论它来自哪一路来源；计数只解释「没有证据」的原因。
    if evidence_present:
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
        evidence_present = persisted_news_evidence_present(result, news_result_count)
    else:
        news_result_count = getattr(result, "news_result_count", None)
        known = getattr(result, "news_result_count_known", True)
        evidence_present = bool(getattr(result, "news_evidence_present", False))
    return _disclosure_for_state(
        news_result_count,
        known=known,
        evidence_present=evidence_present,
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
        evidence_present=persisted_news_evidence_present(raw_result, news_result_count),
        language=language,
    )


def persisted_news_evidence_present(raw_result: Any, news_result_count: Optional[int]) -> bool:
    """从持久化载荷恢复「本次分析是否用到新闻面证据」。

    本 PR 之前写入的记录没有该字段，此时退回按计数推断：>0 说明确有证据，
    其余按无证据处理，与该记录当时的报告表现一致，不会追溯改变旧报告。
    """
    if isinstance(raw_result, Mapping) and "news_evidence_present" in raw_result:
        return bool(raw_result.get("news_evidence_present"))
    return bool(news_result_count)
