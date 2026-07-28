"""Adapters that reuse the project's search, LiteLLM, WeCom, and Feishu providers."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, List, Optional

from src.llm.response_content import strip_leading_think_wrapper
from src.personal_news.repository import canonicalize_url
from src.personal_news.schemas import NewsAnalysis, NewsCandidate, NewsRadarSettings

logger = logging.getLogger(__name__)


class ExistingSearchNewsSource:
    """Thin adapter over the existing multi-provider SearchService."""

    name = "existing-search-service"

    def __init__(self, config: Any):
        self.config = config

    def fetch(self, settings: NewsRadarSettings) -> List[NewsCandidate]:
        from src.search_service import SearchService

        service = SearchService(
            bocha_keys=self.config.bocha_api_keys,
            tavily_keys=self.config.tavily_api_keys,
            anspire_keys=self.config.anspire_api_keys,
            brave_keys=self.config.brave_api_keys,
            serpapi_keys=self.config.serpapi_keys,
            minimax_keys=self.config.minimax_api_keys,
            searxng_base_urls=self.config.searxng_base_urls,
            searxng_public_instances_enabled=self.config.searxng_public_instances_enabled,
            news_max_age_days=self.config.news_max_age_days,
            news_strategy_profile="ultra_short",
        )
        candidates: List[NewsCandidate] = []
        for symbol in settings.watchlist:
            response = service.search_stock_news(symbol, symbol, max_results=8)
            if not response.success:
                logger.warning("personal-news source failed for %s: %s", symbol, response.error_message)
                continue
            price_change, volume_change = self._quote_snapshot(symbol)
            for item in response.results:
                published_at = self._parse_datetime(item.published_date)
                evidence_text = f"{item.title} {item.snippet or ''}".casefold()
                candidates.append(
                    NewsCandidate(
                        title=item.title,
                        url=item.url,
                        source=item.source or response.provider or self.name,
                        summary=item.snippet or "",
                        published_at=published_at,
                        symbols=[symbol],
                        is_announcement=any(term in evidence_text for term in ("公告", "filing", "announcement")),
                        is_regulatory=any(term in evidence_text for term in ("监管", "处罚", "调查", "sec ", "hkex")),
                        source_reliability=70,
                        price_change_percent=price_change,
                        volume_change_percent=volume_change,
                        raw_payload={"provider": response.provider, "query": response.query},
                    )
                )
        if settings.macro_keywords:
            response = service.search_stock_news(
                "MACRO",
                "全球宏观",
                max_results=10,
                focus_keywords=settings.macro_keywords,
            )
            if response.success:
                for item in response.results:
                    candidates.append(
                        NewsCandidate(
                            title=item.title,
                            url=item.url,
                            source=item.source or response.provider or self.name,
                            summary=item.snippet or "",
                            published_at=self._parse_datetime(item.published_date),
                            symbols=[],
                            source_reliability=65,
                            raw_payload={"provider": response.provider, "query": response.query, "macro": True},
                        )
                    )
        return candidates

    @staticmethod
    def _quote_snapshot(symbol: str) -> tuple[Optional[float], Optional[float]]:
        """Reuse cached daily bars; network quote fallback remains owned by existing providers."""
        try:
            from src.storage import DatabaseManager

            rows = DatabaseManager.get_instance().get_latest_data(symbol, days=2)
            if not rows:
                return None, None
            price_change = float(rows[0].pct_chg) if rows[0].pct_chg is not None else None
            volume_change = None
            if len(rows) >= 2 and rows[0].volume is not None and rows[1].volume not in (None, 0):
                volume_change = (float(rows[0].volume) / float(rows[1].volume) - 1) * 100
            return price_change, volume_change
        except Exception:
            logger.debug("personal-news cached quote unavailable for %s", symbol, exc_info=True)
            return None, None

    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None


class LiteLLMNewsAnalyzer:
    """Strict JSON analyzer using the repository's LiteLLM dependency."""

    provider_name = "openai-compatible"

    def __init__(
        self,
        config: Any,
        completion_fn: Optional[Callable[..., Any]] = None,
    ):
        self.config = config
        self.model = config.litellm_model or (
            f"openai/{config.openai_model}" if "/" not in config.openai_model else config.openai_model
        )
        self._completion_fn = completion_fn

    def analyze(self, candidate: NewsCandidate, *, data_time: datetime) -> NewsAnalysis:
        if not candidate.url:
            raise ValueError("source URL is required")
        prompt = self._build_prompt(candidate, data_time)
        last_error: Optional[Exception] = None
        for attempt in range(2):
            try:
                raw = self._complete(prompt, correction=attempt == 1)
                result = NewsAnalysis.model_validate_json(strip_leading_think_wrapper(raw))
                allowed_urls = {canonicalize_url(candidate.url)}
                if any(canonicalize_url(url) not in allowed_urls for url in result.source_urls):
                    raise ValueError("analysis returned a source URL that was not present in evidence")
                return result
            except Exception as exc:  # validation and provider failures share the one-retry contract
                last_error = exc
                logger.warning("personal-news LLM validation failed (attempt=%s): %s", attempt + 1, exc)
        raise ValueError(f"invalid structured analysis after retry: {last_error}")

    def _complete(self, prompt: str, *, correction: bool) -> str:
        completion_fn = self._completion_fn
        if completion_fn is None:
            import litellm

            completion_fn = litellm.completion
        messages = [
            {
                "role": "system",
                "content": (
                    "你是谨慎的股票新闻解释器。只能使用输入事实，不得补充未经来源支持的事实、行情或财务数字。"
                    "禁止使用必涨、必跌、稳赚、满仓或确定性目标价。必须输出符合给定 schema 的单个 JSON 对象。"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        if correction:
            messages.append({"role": "user", "content": "上次输出未通过 schema。只返回合法 JSON，不要代码围栏。"})
        response = completion_fn(
            model=self.model,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"},
            api_key=self.config.openai_api_key,
            api_base=self.config.openai_base_url,
            timeout=60,
        )
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty LLM response")
        return content

    @staticmethod
    def _build_prompt(candidate: NewsCandidate, data_time: datetime) -> str:
        payload = {
            "title": candidate.title,
            "summary": candidate.summary,
            "source": candidate.source,
            "published_at": candidate.published_at.isoformat() if candidate.published_at else None,
            "symbols": candidate.symbols,
            "price_change_percent": candidate.price_change_percent,
            "volume_change_percent": candidate.volume_change_percent,
            "source_urls": [candidate.url],
            "data_time": data_time.isoformat(),
        }
        schema = NewsAnalysis.model_json_schema()
        return (
            "根据 evidence 解释可能影响，同时列出正面与负面因素。证据不足时 action 必须为 "
            "INSUFFICIENT_EVIDENCE。source_urls 只能复制 evidence 中的 URL。\n"
            f"evidence={json.dumps(payload, ensure_ascii=False)}\n"
            f"json_schema={json.dumps(schema, ensure_ascii=False)}"
        )


class ExistingPushNotifier:
    """Sends through the existing WeCom and Feishu sender implementations."""

    def __init__(self, config: Any):
        self.config = config

    def channels(self) -> Iterable[str]:
        if self.config.wechat_webhook_url:
            yield "wechat"
        if self.config.feishu_webhook_url or (
            self.config.feishu_app_id and self.config.feishu_app_secret and self.config.feishu_chat_id
        ):
            yield "feishu"

    def send(self, channel: str, content: str) -> bool:
        if channel == "wechat":
            from src.notification_sender.wechat_sender import WechatSender

            return WechatSender(self.config).send_to_wechat(content)
        if channel == "feishu":
            from src.notification_sender.feishu_sender import FeishuSender

            return FeishuSender(self.config).send_to_feishu(content)
        raise ValueError(f"unsupported push channel: {channel}")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
