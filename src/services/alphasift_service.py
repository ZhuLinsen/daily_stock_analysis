# -*- coding: utf-8 -*-
"""AlphaSift service facade and DSA runtime bridge."""

from __future__ import annotations

import importlib
import hashlib
import inspect
import json
import logging
import math
import os
import re
import subprocess
import sys
import threading
import time
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from src.auth import COOKIE_NAME, is_auth_enabled, refresh_auth_state, verify_session
from src.config import Config, DEFAULT_ALPHASIFT_INSTALL_SPEC, get_configured_llm_models

logger = logging.getLogger(__name__)

ALPHASIFT_DSA_ADAPTER_MODULE = "alphasift.dsa_adapter"
ALPHASIFT_EXPECTED_MISSING_MODULES = frozenset({"alphasift", ALPHASIFT_DSA_ADAPTER_MODULE})
ALLOWED_ALPHASIFT_INSTALL_SPECS = frozenset({DEFAULT_ALPHASIFT_INSTALL_SPEC})
_ALPHASIFT_INSTALL_LOCK = threading.RLock()
ALPHASIFT_MANAGED_LITELLM_PROVIDERS = frozenset({"gemini", "vertex_ai", "anthropic", "openai", "deepseek"})
_ALPHASIFT_RUNTIME_ENV_LOCK = threading.RLock()
DSA_ENRICHMENT_MAX_CANDIDATES = 3
DSA_PRE_RANK_CONTEXT_MAX_CANDIDATES = 3
DSA_ALPHASIFT_LLM_CANDIDATE_MULTIPLIER = 2
DSA_ALPHASIFT_LLM_MAX_CANDIDATES = 12
DSA_ALPHASIFT_SNAPSHOT_SOURCE_PRIORITY = "sina,efinance,akshare_em,em_datacenter"
DSA_ALPHASIFT_SNAPSHOT_SOURCE_PRIORITY_WITH_TUSHARE = "tushare,sina,efinance,akshare_em,em_datacenter"
DSA_ALPHASIFT_CANDIDATE_CONTEXT_PROVIDERS = "news,fund_flow,announcement,quote"
DSA_ALPHASIFT_DATA_DIR = Path("data") / "alphasift"
DSA_ALPHASIFT_HOTSPOT_CACHE_PATH = DSA_ALPHASIFT_DATA_DIR / "hotspots.json"
DSA_ALPHASIFT_HOTSPOT_HISTORY_PATH = DSA_ALPHASIFT_DATA_DIR / "hotspot.history.jsonl"
DSA_ALPHASIFT_MIN_HOTSPOT_CACHE_COUNT = 3
DSA_ALPHASIFT_HOTSPOT_DETAIL_CACHE_TTL_SECONDS = 30 * 60
DSA_ALPHASIFT_HOTSPOT_EVENT_SUMMARY_MAX_CHARS = 90
DSA_ALPHASIFT_HOTSPOT_PREFETCH_DETAIL_COUNT = 8
DSA_ALPHASIFT_HOTSPOT_UNAVAILABLE_CODE = "eastmoney_hotspot_unavailable"
DSA_ALPHASIFT_HOTSPOT_UNAVAILABLE_MESSAGE = "热点源连接中断，暂无可用缓存。"
DSA_ALPHASIFT_HOTSPOT_CONNECTIVITY_ERROR_MARKERS = (
    "remote disconnected",
    "remote end closed connection",
    "connection aborted",
    "connection reset",
    "connection refused",
    "connection timed out",
    "read timed out",
    "connecttimeout",
    "readtimeout",
    "max retries exceeded",
    "chunkedencodingerror",
    "protocolerror",
    "incompleteread",
)
_DSA_FETCHER_MANAGER_LOCK = threading.RLock()
_DSA_FETCHER_MANAGER: Any = None
_FUNDAMENTAL_BLOCKS = ("valuation", "growth", "earnings", "institution", "capital_flow", "boards")
_ALPHASIFT_LITELLM_COMPLETION_ROUTES: ContextVar[Optional[Tuple[Dict[str, Any], ...]]] = ContextVar(
    "alphasift_litellm_completion_routes",
    default=None,
)
_ALPHASIFT_LITELLM_COMPLETION_ATTR = "_alphasift_litellm_completion_bridge"
_ALPHASIFT_LITELLM_COMPLETION_LOCK = threading.Lock()


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _resolve_alphasift_data_dir() -> Path:
    configured = _env_text(os.getenv("ALPHASIFT_DATA_DIR"))
    if configured:
        return Path(configured)
    return DSA_ALPHASIFT_DATA_DIR


def _alphasift_hotspot_cache_path() -> Path:
    if _env_text(os.getenv("ALPHASIFT_DATA_DIR")):
        return _resolve_alphasift_data_dir() / "hotspots.json"
    return DSA_ALPHASIFT_HOTSPOT_CACHE_PATH


def _alphasift_hotspot_history_path() -> Path:
    if _env_text(os.getenv("ALPHASIFT_DATA_DIR")):
        return _resolve_alphasift_data_dir() / "hotspot.history.jsonl"
    return DSA_ALPHASIFT_HOTSPOT_HISTORY_PATH


def _alphasift_hotspot_detail_cache_dir() -> Path:
    return _resolve_alphasift_data_dir() / "hotspot_details"


def _alphasift_hotspot_detail_cache_path(*, provider: str, topic: str) -> Path:
    provider_text = re.sub(r"[^A-Za-z0-9_.-]+", "_", _env_text(provider) or "akshare")
    digest = hashlib.sha1(f"{provider_text}\0{_env_text(topic)}".encode("utf-8")).hexdigest()
    return _alphasift_hotspot_detail_cache_dir() / f"{provider_text}.{digest}.json"


def _parse_cache_datetime(value: Any) -> Optional[datetime]:
    text = _env_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_alphasift_hotspot_detail_cache(
    *,
    provider: str,
    topic: str,
    allow_stale: bool = False,
) -> Optional[Dict[str, Any]]:
    cache_path = _alphasift_hotspot_detail_cache_path(provider=provider, topic=topic)
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("Failed to read AlphaSift hotspot detail cache from %s: %s", cache_path, exc)
        return None

    payload = raw.get("payload") if isinstance(raw, dict) else None
    if not isinstance(payload, dict):
        return None
    cached_at = raw.get("cached_at") or payload.get("cached_at")
    cached_dt = _parse_cache_datetime(cached_at)
    if cached_dt is None:
        return None
    age_seconds = max(0.0, (datetime.now(timezone.utc) - cached_dt).total_seconds())
    stale = age_seconds > DSA_ALPHASIFT_HOTSPOT_DETAIL_CACHE_TTL_SECONDS
    if stale and not allow_stale:
        return None

    cached = _ensure_hotspot_detail_compat_fields(dict(payload))
    cached.update({
        "enabled": True,
        "provider": provider or cached.get("provider") or "akshare",
        "cache_used": True,
        "cached_at": cached_at,
        "stale": bool(cached.get("stale") or stale),
    })
    if stale:
        cached["fallback_used"] = True
        cached["stale_age_seconds"] = round(age_seconds, 1)
    return _remove_non_finite_json_values(cached)


def _write_alphasift_hotspot_detail_cache(*, provider: str, topic: str, payload: Dict[str, Any]) -> None:
    cache_path = _alphasift_hotspot_detail_cache_path(provider=provider, topic=topic)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cleaned = _remove_non_finite_json_values(_ensure_hotspot_detail_compat_fields(dict(payload)))
        cached_at = _utc_now_iso()
        cache_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "provider": provider or cleaned.get("provider") or "akshare",
                    "topic": topic,
                    "cached_at": cached_at,
                    "payload": cleaned,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Failed to write AlphaSift hotspot detail cache for %s: %s", topic, exc)


def _ensure_hotspot_detail_compat_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Keep old and new AlphaSift hotspot detail consumers on the same shape."""
    stocks = payload.get("stocks")
    leader_stocks = payload.get("leader_stocks")
    if not isinstance(stocks, list):
        stocks = []
    if not isinstance(leader_stocks, list) or not leader_stocks:
        nested_leader_stocks = _extract_nested_hotspot_leader_stocks(payload)
        leader_stocks = nested_leader_stocks or (leader_stocks if isinstance(leader_stocks, list) else [])
    if not stocks and leader_stocks:
        stocks = leader_stocks
    if not leader_stocks and stocks:
        leader_stocks = stocks
    payload["stocks"] = stocks
    payload["leader_stocks"] = leader_stocks
    payload["stock_count"] = len(stocks)
    return payload


def _extract_nested_hotspot_leader_stocks(payload: Dict[str, Any]) -> List[Any]:
    for key in ("summary_detail", "summary"):
        summary = payload.get(key)
        if not isinstance(summary, dict):
            continue
        leader_stocks = summary.get("leader_stocks")
        if isinstance(leader_stocks, list) and leader_stocks:
            return leader_stocks
    return []


def _load_alphasift_hotspot_cache(*, provider: str, top: int) -> Optional[Dict[str, Any]]:
    cache_path = _alphasift_hotspot_cache_path()
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("Failed to read AlphaSift hotspot cache from %s: %s", cache_path, exc)
        return None

    payload = _normalize_alphasift_hotspot_cache_payload(raw)
    if not isinstance(payload, dict):
        return None
    hotspots = payload.get("hotspots")
    if not isinstance(hotspots, list) or not hotspots:
        return None

    top_count = max(1, min(int(top or 12), 50))
    if len(hotspots) < min(DSA_ALPHASIFT_MIN_HOTSPOT_CACHE_COUNT, top_count):
        logger.info(
            "Ignoring AlphaSift hotspot cache with too few rows: %s < %s",
            len(hotspots),
            min(DSA_ALPHASIFT_MIN_HOTSPOT_CACHE_COUNT, top_count),
        )
        return None

    selected = hotspots[:top_count]
    cached = dict(payload)
    cached.update({
        "enabled": True,
        "provider": provider or payload.get("provider") or "akshare",
        "hotspots": selected,
        "hotspot_count": len(selected),
        "cache_used": True,
        "cached_at": raw.get("cached_at") or payload.get("cached_at"),
    })
    cached["source_errors"] = list(cached.get("source_errors") or [])
    return _remove_non_finite_json_values(cached)


def _normalize_alphasift_hotspot_cache_payload(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    payload = raw.get("payload")
    if isinstance(payload, dict):
        return payload
    hotspots = raw.get("hotspots")
    if not isinstance(hotspots, list):
        return None
    metadata_raw = raw.get("metadata")
    metadata: Dict[str, Any] = metadata_raw if isinstance(metadata_raw, dict) else {}
    cached_at = raw.get("cached_at") or raw.get("generated_at") or metadata.get("generated_at")
    return {
        "enabled": True,
        "provider": _env_text(metadata.get("provider")) or "akshare",
        "provider_used": _env_text(metadata.get("provider_used")),
        "fallback_used": False,
        "cache_used": False,
        "cached_at": cached_at,
        "schema_version": raw.get("schema_version") or metadata.get("schema_version"),
        "source_errors": _list_text_values(raw.get("source_errors") or metadata.get("source_errors")),
        "stale": bool(raw.get("stale") or metadata.get("stale") or False),
        "stale_age_hours": raw.get("stale_age_hours") or metadata.get("stale_age_hours"),
        "hotspots": hotspots,
        "hotspot_count": len(hotspots),
    }


def _hotspot_route_has_external_event(route: Any) -> bool:
    if not isinstance(route, list):
        return False
    generated_sources = {"", "eastmoney_board_change", "fallback", "dsa_topic_catalyst", "ths_info"}
    for item in route:
        if not isinstance(item, dict):
            continue
        source = _env_text(item.get("source"))
        if source and source not in generated_sources:
            return True
    return False


def _has_configured_hotspot_news_source(config: Config) -> bool:
    fields = (
        "bocha_api_keys",
        "tavily_api_keys",
        "anspire_api_keys",
        "brave_api_keys",
        "serpapi_api_keys",
        "minimax_api_keys",
        "searxng_base_urls",
    )
    return any(bool(getattr(config, field, None)) for field in fields)


def _build_hotspot_event_routes_from_search(topic: str, config: Config) -> List[Dict[str, Any]]:
    topic_text = _env_text(topic)
    if not topic_text or not _has_configured_hotspot_news_source(config):
        return []
    try:
        from src.search_service import SearchService

        service = SearchService(
            bocha_keys=getattr(config, "bocha_api_keys", None),
            tavily_keys=getattr(config, "tavily_api_keys", None),
            anspire_keys=getattr(config, "anspire_api_keys", None),
            brave_keys=getattr(config, "brave_api_keys", None),
            serpapi_keys=getattr(config, "serpapi_api_keys", None),
            minimax_keys=getattr(config, "minimax_api_keys", None),
            searxng_base_urls=getattr(config, "searxng_base_urls", None),
            searxng_public_instances_enabled=False,
            news_max_age_days=int(getattr(config, "news_max_age_days", 3) or 3),
            news_strategy_profile=getattr(config, "news_strategy_profile", "short"),
        )
        response = service.search_stock_news(
            topic_text,
            topic_text,
            max_results=3,
            focus_keywords=[topic_text, "A股", "题材", "催化", "涨价"],
        )
    except Exception as exc:
        logger.info("AlphaSift hotspot event search skipped for %s: %s", topic_text, exc)
        return []

    if not bool(getattr(response, "success", False)):
        return []
    today = datetime.now().date().isoformat()
    event_parts: List[str] = []
    sources: List[str] = []
    first_url = ""
    first_date = ""
    first_published = ""
    for result in list(getattr(response, "results", []) or [])[:2]:
        title = _env_text(getattr(result, "title", ""))
        snippet = _env_text(getattr(result, "snippet", ""))
        if not title and not snippet:
            continue
        event_text = _compact_hotspot_news_text(title=title, snippet=snippet)
        if event_text:
            event_parts.append(event_text)
        published = _env_text(getattr(result, "published_date", ""))
        source = _env_text(getattr(result, "source", "")) or _env_text(getattr(response, "provider", "")) or "news_search"
        if source and source not in sources:
            sources.append(source)
        if not first_url:
            first_url = _env_text(getattr(result, "url", ""))
        if not first_date:
            first_date = _extract_date_text(published) or _extract_date_text(event_text)
        if not first_published:
            first_published = published
    if not event_parts:
        return []
    description = _summarize_hotspot_news_event(
        topic=topic_text,
        title="",
        snippet="；".join(event_parts),
        config=config,
    )
    date = first_date or _extract_date_text(description) or today
    return [{
        "title": "消息催化",
        "description": description,
        "source": ",".join(sources) if sources else "news_search",
        "date": date,
        "published_at": first_published or date,
        "url": first_url,
    }]


def _summarize_hotspot_news_event(*, topic: str, title: str, snippet: str, config: Config) -> str:
    compact_text = _compact_hotspot_news_text(title=title, snippet=snippet)
    llm_summary = _summarize_hotspot_news_event_with_llm(topic=topic, text=compact_text, config=config)
    if llm_summary:
        return _truncate_text(llm_summary, DSA_ALPHASIFT_HOTSPOT_EVENT_SUMMARY_MAX_CHARS)
    return _summarize_hotspot_news_event_locally(topic=topic, text=compact_text)


def _summarize_hotspot_news_event_locally(*, topic: str, text: str) -> str:
    cleaned = _strip_hotspot_news_noise(text)
    if not cleaned:
        return ""
    catalyst = _extract_hotspot_catalyst_phrase(cleaned)
    impacts = _extract_hotspot_impact_phrases(cleaned)
    if catalyst and impacts:
        summary = f"{catalyst}，带动{impacts}发酵。"
    elif catalyst:
        summary = f"{catalyst}，市场关注{topic}相关产业链机会。"
    else:
        summary = _first_meaningful_hotspot_sentence(cleaned)
    summary = _truncate_text(summary, DSA_ALPHASIFT_HOTSPOT_EVENT_SUMMARY_MAX_CHARS).rstrip(".。…")
    return _truncate_text(f"{summary}。", DSA_ALPHASIFT_HOTSPOT_EVENT_SUMMARY_MAX_CHARS)


def _strip_hotspot_news_noise(text: str) -> str:
    cleaned = _normalize_inline_text(text)
    cleaned = re.sub(r"【[^】]{1,24}】", " ", cleaned)
    cleaned = re.sub(r"\[[^\]]{1,24}\]", " ", cleaned)
    cleaned = re.sub(r"\b20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}[日号]?\b", " ", cleaned)
    cleaned = re.sub(r"\b\d{1,2}:\d{2}\b", " ", cleaned)
    cleaned = re.sub(r"\([^)]{0,18}\d+\.\d+[^)]{0,18}\)", " ", cleaned)
    cleaned = re.sub(r"（[^）]{0,18}\d+\.\d+[^）]{0,18}）", " ", cleaned)
    cleaned = re.sub(r"截至[^。；;]*", " ", cleaned)
    cleaned = re.sub(r"(建议关注|后续建议|风险提示|投资建议)[^。；;]*", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" ，,；;。.")


def _extract_hotspot_catalyst_phrase(text: str) -> str:
    patterns = (
        r"以[^，。；;]{1,12}代[^，。；;]{1,12}",
        r"[^，。；;]{1,18}(涨价|价格上行|供需偏紧|供应紧张|资源增储|订单增长|政策催化|出口管制|减产|并购重组|技术突破)[^，。；;]{0,24}",
        r"[^，。；;]{1,18}(替代|国产替代|需求增长|景气上行)[^，。；;]{0,24}",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _normalize_inline_text(match.group(0)).strip(" ，,；;。.")
    return ""


def _extract_hotspot_impact_phrases(text: str) -> str:
    impacts: List[str] = []
    keyword_groups = (
        ("小金属", ("小金属", "钼", "钨", "锑", "锗", "铟")),
        ("有色金属", ("有色", "铜", "铝", "锌", "铅")),
        ("相关个股", ("涨停", "异动", "走强", "大涨", "拉升")),
        ("产业链", ("产业链", "上游", "下游", "材料", "资源")),
    )
    for label, keywords in keyword_groups:
        if any(keyword in text for keyword in keywords) and label not in impacts:
            impacts.append(label)
    return "、".join(impacts[:3])


def _first_meaningful_hotspot_sentence(text: str) -> str:
    sentences = [
        _normalize_inline_text(item).strip(" ，,；;。.")
        for item in re.split(r"[。！？!?；;]", text)
        if _normalize_inline_text(item)
    ]
    for sentence in sentences:
        if len(sentence) >= 8 and not re.search(r"(现价|成交额|涨跌幅|换手率|建议关注|截至)", sentence):
            return sentence
    return sentences[0] if sentences else text


def _compact_hotspot_news_text(*, title: str, snippet: str) -> str:
    title_text = _normalize_inline_text(title)
    snippet_text = _normalize_inline_text(snippet)
    if title_text and snippet_text.startswith(title_text):
        snippet_text = snippet_text[len(title_text):].lstrip(" ：:，,。;；")
    if title_text and snippet_text == title_text:
        snippet_text = ""
    text = "。".join(part for part in (title_text, snippet_text) if part)
    text = re.sub(r"(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}[日号]?)\s+\d{1,2}:\d{2}", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_inline_text(value: Any) -> str:
    text = _env_text(value)
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _truncate_text(text: str, max_chars: int) -> str:
    text = _normalize_inline_text(text)
    if len(text) <= max_chars:
        return text
    sentence_parts = re.split(r"(?<=[。！？!?；;])", text)
    summary = ""
    for part in sentence_parts:
        if not part:
            continue
        if len(summary) + len(part) > max_chars:
            break
        summary += part
    if summary:
        return summary.rstrip("，,；;：: ")[:max_chars].rstrip("，,；;：: ") + "..."
    return text[: max(0, max_chars - 3)].rstrip("，,；;：: ") + "..."


def _summarize_hotspot_news_event_with_llm(*, topic: str, text: str, config: Config) -> str:
    model, _fallback_models = _resolve_alphasift_llm_models(config)
    if not _env_text(model) or not text:
        return ""
    try:
        import litellm

        prompt = (
            "请把下面新闻压缩成一句 A 股热点题材催化摘要。"
            "要求：不超过 70 个中文字符，只保留事件、影响方向和相关链条；"
            "不要输出完整报道、股票价格流水、免责声明或投资建议。\n\n"
            f"题材：{topic}\n新闻：{text}"
        )
        with _alphasift_litellm_headers(config):
            response = litellm.completion(
                model=model,
                messages=[
                    {"role": "system", "content": "你是A股题材事件摘要助手，只输出一句短摘要。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=120,
                timeout=8,
            )
        return _clean_hotspot_llm_summary(_extract_litellm_message_content(response))
    except Exception as exc:
        logger.info("AlphaSift hotspot LLM event summary skipped for %s: %s", topic, exc)
        return ""


def _extract_litellm_message_content(response: Any) -> str:
    try:
        choices = response.get("choices") if isinstance(response, dict) else getattr(response, "choices", None)
        if choices:
            choice = choices[0]
            message = choice.get("message") if isinstance(choice, dict) else getattr(choice, "message", None)
            if isinstance(message, dict):
                return _env_text(message.get("content"))
            return _env_text(getattr(message, "content", ""))
    except Exception:
        return ""
    return ""


def _clean_hotspot_llm_summary(text: str) -> str:
    summary = _normalize_inline_text(text).strip(" 　\"'“”‘’")
    summary = re.sub(r"^(摘要|总结|消息催化|事件催化)\s*[:：]\s*", "", summary)
    return summary


def _extract_date_text(text: str) -> str:
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text or "")
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _hotspot_rows_are_thin(rows: List[Any], *, top: int) -> bool:
    if len(rows) < min(DSA_ALPHASIFT_MIN_HOTSPOT_CACHE_COUNT, max(1, top)):
        return True
    rich_count = 0
    metric_count = 0
    for item in rows:
        if not isinstance(item, dict):
            continue
        if item.get("change_pct") is not None or item.get("changePct") is not None:
            rich_count += 1
        if (
            item.get("trend_score") is not None
            or item.get("trendScore") is not None
            or item.get("persistence_score") is not None
            or item.get("persistenceScore") is not None
        ):
            metric_count += 1
    return rich_count == 0 or metric_count == 0


def _snake_to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _enrich_hotspot_rows_from_provider(rows: List[Any], provider: Any, *, top: int) -> List[Dict[str, Any]]:
    try:
        provider_rows = provider.hotspot_rows(top=max(top, len(rows), 30))
    except Exception as exc:
        logger.warning("AlphaSift hotspot metric enrichment failed: %s", exc)
        return [dict(item) if isinstance(item, dict) else item for item in rows]
    by_topic: Dict[str, Dict[str, Any]] = {}
    for item in provider_rows or []:
        if not isinstance(item, dict):
            continue
        topic = _env_text(item.get("topic") or item.get("name"))
        if topic:
            by_topic[topic] = item
        name = _env_text(item.get("name"))
        if name and "·" in name:
            by_topic[name.split("·")[-1].strip()] = item
    enriched: List[Dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict):
            enriched.append(raw)
            continue
        item = dict(raw)
        topic = _env_text(item.get("topic") or item.get("name"))
        provider_item = by_topic.get(topic)
        if not provider_item:
            enriched.append(item)
            continue
        for key in (
            "change_pct",
            "heat_score",
            "trend_score",
            "persistence_score",
            "observations",
            "stage",
            "state",
            "sample_stock_count",
            "leaders",
            "theme_group",
        ):
            camel_key = _snake_to_camel(key)
            if item.get(key) in (None, "", [], {}) and item.get(camel_key) in (None, "", [], {}):
                value = provider_item.get(key)
                if value not in (None, "", [], {}):
                    item[key] = value
        if item.get("name") in (None, "", topic):
            item["name"] = provider_item.get("name") or topic
        enriched.append(item)
    return enriched


def _write_alphasift_hotspot_cache(payload: Dict[str, Any]) -> None:
    cache_path = _alphasift_hotspot_cache_path()
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cached_at = _utc_now_iso()
        cache_payload = dict(payload)
        cache_payload["cache_used"] = False
        cache_payload["cached_at"] = cached_at
        cache_path.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "generated_at": cached_at,
                    "cached_at": cached_at,
                    "metadata": {
                        "schema_version": 2,
                        "asset_type": "hotspot_cache",
                        "provider": cache_payload.get("provider"),
                        "provider_used": cache_payload.get("provider_used"),
                        "row_count": len(cache_payload.get("hotspots") or []),
                        "source_errors": _list_text_values(cache_payload.get("source_errors")),
                    },
                    "hotspots": cache_payload.get("hotspots") or [],
                    "payload": cache_payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Failed to write AlphaSift hotspot cache to %s: %s", cache_path, exc)


def _hotspot_topic_from_row(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return _env_text(row.get("topic") or row.get("name") or row.get("canonical_topic"))


def _attach_cached_hotspot_details(
    payload: Dict[str, Any],
    *,
    provider: str,
    top: int,
) -> Dict[str, Any]:
    rows = payload.get("hotspots")
    if not isinstance(rows, list) or not rows:
        return payload
    details = dict(payload.get("details") if isinstance(payload.get("details"), dict) else {})
    for row in rows[:max(0, min(int(top or 0), DSA_ALPHASIFT_HOTSPOT_PREFETCH_DETAIL_COUNT))]:
        topic = _hotspot_topic_from_row(row)
        if not topic or topic in details:
            continue
        cached = _load_alphasift_hotspot_detail_cache(provider=provider, topic=topic)
        if cached is not None:
            details[topic] = cached
    if details:
        attached = dict(payload)
        attached["details"] = _remove_non_finite_json_values(details)
        return attached
    return payload


def _empty_alphasift_hotspot_payload(
    *,
    provider: str,
    provider_used: str = "",
    source_errors: Optional[List[str]] = None,
    message: str = "",
) -> Dict[str, Any]:
    return {
        "enabled": True,
        "provider": provider,
        "provider_used": provider_used,
        "fallback_used": False,
        "cache_used": False,
        "cached_at": None,
        "source_errors": list(source_errors or []),
        "stale": False,
        "stale_age_hours": None,
        "hotspots": [],
        "hotspot_count": 0,
        "message": message,
    }


def _is_known_eastmoney_hotspot_connectivity_error(exc: BaseException) -> bool:
    retryable_types: List[Any] = [ConnectionError, TimeoutError]
    try:
        import requests

        retryable_types.extend(
            [
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ]
        )
    except Exception:
        pass
    try:
        import http.client

        retryable_types.extend([http.client.RemoteDisconnected, http.client.IncompleteRead])
    except Exception:
        pass
    try:
        import urllib3.exceptions

        retryable_types.extend(
            [
                urllib3.exceptions.ProtocolError,
                urllib3.exceptions.MaxRetryError,
                urllib3.exceptions.ReadTimeoutError,
                urllib3.exceptions.ConnectTimeoutError,
            ]
        )
    except Exception:
        pass

    retryable_tuple = tuple(retryable_types)
    pending: List[BaseException] = [exc]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        current_id = id(current)
        if current_id in seen:
            continue
        seen.add(current_id)
        if isinstance(current, retryable_tuple):
            return True
        message = f"{current.__class__.__name__}: {current}".lower()
        if any(marker in message for marker in DSA_ALPHASIFT_HOTSPOT_CONNECTIVITY_ERROR_MARKERS):
            return True
        cause = getattr(current, "__cause__", None)
        context = getattr(current, "__context__", None)
        if isinstance(cause, BaseException):
            pending.append(cause)
        if isinstance(context, BaseException):
            pending.append(context)
    return False


def _should_return_eastmoney_hotspot_unavailable(provider_arg: Any, exc: BaseException) -> bool:
    return isinstance(provider_arg, DsaEastMoneyHotspotProvider) and _is_known_eastmoney_hotspot_connectivity_error(exc)


class AlphaSiftStrategyResponse(BaseModel):
    id: str
    name: str = ""
    title: str = ""
    description: str = ""
    category: str = ""
    tag: str = ""
    tags: List[str] = Field(default_factory=list)
    market_scope: List[str] = Field(default_factory=list)
    market: str = ""


class AlphaSiftService:
    """Coordinate AlphaSift calls with DSA-owned runtime capabilities."""

    def __init__(self, config: Config):
        self.config = config

    def status(self) -> Dict[str, Any]:
        adapter_status, available, diagnostics = _get_alphasift_status_snapshot()
        payload = {
            "enabled": bool(self.config.alphasift_enabled),
            "available": available,
            "install_spec_is_default": _is_default_alphasift_install_spec(self.config.alphasift_install_spec),
            "contract_version": adapter_status.get("contract_version"),
            "version": adapter_status.get("version"),
            "strategy_count": adapter_status.get("strategy_count"),
        }
        if diagnostics:
            payload["diagnostics"] = diagnostics
        return payload

    def strategies(self) -> Dict[str, Any]:
        _ensure_alphasift_enabled(self.config)
        _ensure_alphasift_available_for_use()
        strategies = _list_strategies()
        return {
            "enabled": True,
            "strategies": strategies,
            "strategy_count": len(strategies),
        }

    def install(self, *, request: Request) -> Dict[str, Any]:
        _ensure_alphasift_install_access(request)
        _ensure_alphasift_enabled(self.config)
        return _install_alphasift(self.config)

    def hotspots(
        self,
        *,
        provider: str = "",
        top: int = 12,
        refresh: bool = False,
        include_details: bool = False,
    ) -> Dict[str, Any]:
        _ensure_alphasift_enabled(self.config)
        _ensure_alphasift_available_for_use()
        provider_name, provider_arg = _resolve_hotspot_provider(provider)
        top_count = max(1, min(int(top or 12), 50))
        if not refresh:
            cached = _load_alphasift_hotspot_cache(provider=provider_name, top=top_count)
            if cached is not None:
                return _attach_cached_hotspot_details(cached, provider=provider_name, top=top_count) if include_details else cached
            return _empty_alphasift_hotspot_payload(
                provider=provider_name,
                message="No cached AlphaSift hotspot snapshot. Click refresh to fetch live hotspots.",
            )

        hotspot_module = _import_alphasift_hotspot()
        discover_hotspots = _get_adapter_callable(
            hotspot_module,
            "discover_hotspots",
            "discover_hotspots() is not callable.",
        )

        try:
            with _alphasift_runtime_env(self.config):
                raw = discover_hotspots(
                    provider=provider_arg,
                    top=top_count,
                    history_path=_alphasift_hotspot_history_path(),
                    fallback_cache_path=_alphasift_hotspot_cache_path(),
                )
        except HTTPException:
            raise
        except Exception as exc:
            cached = _load_alphasift_hotspot_cache(provider=provider_name, top=top_count)
            if cached is not None:
                errors = list(cached.get("source_errors") or [])
                errors.append(f"live refresh failed: {exc}")
                cached["source_errors"] = errors
                cached["fallback_used"] = True
                cached["cache_used"] = True
                return _attach_cached_hotspot_details(cached, provider=provider_name, top=top_count) if include_details else cached
            if not _should_return_eastmoney_hotspot_unavailable(provider_arg, exc):
                diagnostics = _log_unexpected_alphasift_exception("hotspot_refresh", exc)
                raise HTTPException(
                    status_code=424,
                    detail={
                        "error": "alphasift_hotspot_refresh_failed",
                        "message": f"AlphaSift hotspot refresh failed: {exc}",
                        "diagnostics": diagnostics,
                    },
                ) from exc
            logger.warning("AlphaSift hotspot live refresh failed without cache: %s", exc)
            return _empty_alphasift_hotspot_payload(
                provider=provider_name,
                provider_used=type(provider_arg).__name__,
                source_errors=[DSA_ALPHASIFT_HOTSPOT_UNAVAILABLE_CODE],
                message=DSA_ALPHASIFT_HOTSPOT_UNAVAILABLE_MESSAGE,
            )

        items = _remove_non_finite_json_values(_to_plain(raw))
        if not isinstance(items, list):
            items = []
        selected = items[:top_count]
        source_errors = list(getattr(raw, "source_errors", []) or [])
        direct_hotspot_fallback_used = False
        if isinstance(provider_arg, DsaEastMoneyHotspotProvider) and _hotspot_rows_are_thin(selected, top=top_count):
            try:
                direct_hotspots = provider_arg.hotspot_rows(top=top_count)
            except Exception as exc:
                logger.warning("AlphaSift DSA direct hotspot fallback failed: %s", exc)
                direct_hotspots = []
                source_errors.append(f"dsa_direct_hotspots_failed: {exc}")
            if len(direct_hotspots) > len(selected):
                selected = direct_hotspots
                direct_hotspot_fallback_used = True
                source_errors.append("AlphaSift hotspot rows were thin; used DSA EastMoney board-change rows.")
        if isinstance(provider_arg, DsaEastMoneyHotspotProvider) and selected:
            selected = _enrich_hotspot_rows_from_provider(selected, provider_arg, top=top_count)
        if not selected and source_errors:
            cached = _load_alphasift_hotspot_cache(provider=provider_name, top=top_count)
            if cached is not None:
                errors = list(cached.get("source_errors") or [])
                errors.extend(source_errors)
                cached["source_errors"] = errors
                cached["fallback_used"] = True
                cached["cache_used"] = True
                return _attach_cached_hotspot_details(cached, provider=provider_name, top=top_count) if include_details else cached

        payload = {
            "enabled": True,
            "provider": provider_name,
            "provider_used": "dsa_eastmoney_board_change" if direct_hotspot_fallback_used else str(getattr(raw, "provider_used", "")),
            "fallback_used": direct_hotspot_fallback_used or bool(getattr(raw, "fallback_used", False)),
            "cache_used": False,
            "cached_at": None,
            "source_errors": source_errors,
            "stale": bool(getattr(raw, "stale", False)),
            "stale_age_hours": getattr(raw, "stale_age_hours", None),
            "hotspots": selected,
            "hotspot_count": len(selected),
        }
        if selected and include_details:
            payload = self._prefetch_hotspot_details(payload, provider=provider_name, refresh=False)
        if selected:
            _write_alphasift_hotspot_cache(payload)
        return payload

    def _prefetch_hotspot_details(self, payload: Dict[str, Any], *, provider: str, refresh: bool) -> Dict[str, Any]:
        rows = payload.get("hotspots")
        if not isinstance(rows, list) or not rows:
            return payload
        details = dict(payload.get("details") if isinstance(payload.get("details"), dict) else {})
        source_errors = _list_text_values(payload.get("source_errors"))
        for row in rows[:DSA_ALPHASIFT_HOTSPOT_PREFETCH_DETAIL_COUNT]:
            topic = _hotspot_topic_from_row(row)
            if not topic or (topic in details and not refresh):
                continue
            try:
                details[topic] = self.hotspot_detail(topic=topic, provider=provider, refresh=refresh)
            except HTTPException as exc:
                source_errors.append(f"hotspot_detail_prefetch_failed:{topic}:{exc.detail}")
            except Exception as exc:
                source_errors.append(f"hotspot_detail_prefetch_failed:{topic}:{exc}")
        attached = dict(payload)
        if details:
            attached["details"] = _remove_non_finite_json_values(details)
        if source_errors:
            attached["source_errors"] = source_errors
        return attached

    def hotspot_detail(self, *, topic: str, provider: str = "", refresh: bool = False) -> Dict[str, Any]:
        _ensure_alphasift_enabled(self.config)
        _ensure_alphasift_available_for_use()
        topic_text = _env_text(topic)
        if not topic_text:
            raise HTTPException(
                status_code=400,
                detail={"error": "alphasift_hotspot_topic_required", "message": "热点题材名称不能为空。"},
            )
        provider_name, provider_arg = _resolve_hotspot_provider(provider)
        if not isinstance(provider_arg, DsaEastMoneyHotspotProvider):
            provider_arg = DsaEastMoneyHotspotProvider()
        cached = None if refresh else _load_alphasift_hotspot_detail_cache(provider=provider_name, topic=topic_text)
        if cached is not None:
            return cached
        normalized: Dict[str, Any] = {}
        hotspot_helper_error: str = ""
        try:
            try:
                hotspot_module = _import_alphasift_hotspot()
                get_hotspot_detail = getattr(hotspot_module, "get_hotspot_detail", None)
            except Exception:
                get_hotspot_detail = None
            with _alphasift_runtime_env(self.config):
                if callable(get_hotspot_detail) and type(provider_arg) is DsaEastMoneyHotspotProvider:
                    try:
                        detail = get_hotspot_detail(
                            topic_text,
                            provider=provider_arg,
                            top_stocks=30,
                            history_path=_alphasift_hotspot_history_path(),
                            fallback_cache_path=_alphasift_hotspot_cache_path(),
                        )
                        normalized = _normalize_alphasift_hotspot_detail(
                            detail,
                            provider=provider_name,
                            requested_topic=topic_text,
                        )
                        normalized = _merge_provider_hotspot_route_fallback(
                            normalized,
                            provider=provider_arg,
                            topic=topic_text,
                        )
                    except Exception as exc:
                        hotspot_helper_error = f"{exc}"
                        logger.warning(
                            "AlphaSift contract hotspot detail fallback to provider for topic=%s: %s",
                            topic_text,
                            hotspot_helper_error,
                        )
                else:
                    normalized = provider_arg.hotspot_detail(topic_text)
                if not normalized:
                    normalized = provider_arg.hotspot_detail(topic_text)
        except Exception as exc:
            stale_cached = _load_alphasift_hotspot_detail_cache(
                provider=provider_name,
                topic=topic_text,
                allow_stale=True,
            )
            if stale_cached is not None:
                source_errors = _list_text_values(stale_cached.get("source_errors"))
                source_errors.append(f"alphasift_hotspot_detail_stale_cache: {exc}")
                stale_cached["source_errors"] = source_errors
                stale_cached["fallback_used"] = True
                return stale_cached
            raise HTTPException(
                status_code=424,
                detail={"error": "alphasift_hotspot_detail_failed", "message": f"AlphaSift hotspot detail failed: {exc}"},
            ) from exc
        if hotspot_helper_error:
            source_errors = _list_text_values(normalized.get("source_errors"))
            source_errors.append(f"alphasift_hotspot_detail_fallback: {hotspot_helper_error}")
            normalized["source_errors"] = source_errors
            normalized["fallback_used"] = True
            normalized["provider"] = provider_name
        if not _hotspot_route_has_external_event(normalized.get("route")):
            search_routes = _build_hotspot_event_routes_from_search(topic_text, self.config)
            if search_routes:
                route = normalized.get("route")
                normalized["route"] = search_routes + (route if isinstance(route, list) else [])
        normalized = _ensure_hotspot_detail_compat_fields(normalized)
        normalized["enabled"] = True
        normalized["provider"] = provider_name
        cleaned = _remove_non_finite_json_values(normalized)
        _write_alphasift_hotspot_detail_cache(provider=provider_name, topic=topic_text, payload=cleaned)
        return cleaned

    def screen(self, *, strategy: str, market: str, max_results: int) -> Dict[str, Any]:
        _ensure_alphasift_enabled(self.config)
        _ensure_alphasift_available_for_use()
        _ensure_supported_market(market)
        _ensure_supported_strategy(strategy)

        adapter = _get_dsa_adapter()
        screen = _get_adapter_callable(adapter, "screen", "screen() 不可调用。")
        try:
            raw = _call_alphasift_screen(screen, strategy, market, max_results, self.config)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error": "alphasift_screen_rejected", "message": str(exc)},
            ) from exc
        except (TypeError, KeyError) as exc:
            raise HTTPException(
                status_code=422,
                detail={"error": "alphasift_invalid_input", "message": f"AlphaSift 参数非法：{exc}"},
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=424,
                detail={"error": "alphasift_screen_failed", "message": f"AlphaSift 选股运行失败：{exc}"},
            ) from exc

        raw_data = _to_plain(raw)
        if not isinstance(raw_data, dict):
            raw_data = {"candidates": raw_data}
        raw_data = _remove_non_finite_json_values(raw_data)

        candidates = _normalize_candidates(raw_data)
        selected = candidates[:max_results]
        selected, dsa_enrichment = _enrich_candidates_with_dsa(selected)
        return {
            "enabled": True,
            "candidates": selected,
            "candidate_count": len(selected),
            "run_id": raw_data.get("run_id"),
            "strategy": raw_data.get("strategy") or strategy,
            "market": raw_data.get("market") or market,
            "snapshot_count": raw_data.get("snapshot_count"),
            "snapshot_source": raw_data.get("snapshot_source") or "",
            "after_filter_count": raw_data.get("after_filter_count"),
            "llm_ranked": raw_data.get("llm_ranked"),
            "llm_market_view": raw_data.get("llm_market_view") or "",
            "llm_selection_logic": raw_data.get("llm_selection_logic") or "",
            "llm_portfolio_risk": raw_data.get("llm_portfolio_risk") or "",
            "llm_coverage": raw_data.get("llm_coverage"),
            "llm_parse_errors": raw_data.get("llm_parse_errors") or [],
            "warnings": raw_data.get("warnings") or [],
            "source_errors": raw_data.get("source_errors") or [],
            "dsa_enrichment": dsa_enrichment,
            "deep_analysis_requested": raw_data.get("deep_analysis_requested"),
            "post_analyzers": raw_data.get("post_analyzers") or [],
            "daily_enriched": raw_data.get("daily_enriched"),
            "daily_enrich_count": raw_data.get("daily_enrich_count"),
            "risk_enabled": raw_data.get("risk_enabled"),
            "portfolio_diversity_enabled": raw_data.get("portfolio_diversity_enabled"),
            "portfolio_concentration_notes": raw_data.get("portfolio_concentration_notes") or [],
        }


def _normalize_alphasift_hotspot_detail(detail: Any, *, provider: str, requested_topic: str) -> Dict[str, Any]:
    raw_value = _remove_non_finite_json_values(_to_plain(detail))
    raw: Dict[str, Any] = raw_value if isinstance(raw_value, dict) else {}
    summary_value = raw.get("summary")
    summary: Dict[str, Any] = summary_value if isinstance(summary_value, dict) else {}
    stocks_value = raw.get("stocks")
    leader_stocks_value = raw.get("leader_stocks")
    stocks: List[Any] = stocks_value if isinstance(stocks_value, list) else []
    leader_stocks: List[Any] = leader_stocks_value if isinstance(leader_stocks_value, list) else []
    timeline_value = raw.get("timeline")
    timeline: List[Any] = timeline_value if isinstance(timeline_value, list) else []
    route_value = raw.get("route")
    route: List[Any] = route_value if isinstance(route_value, list) and route_value else _hotspot_timeline_to_route(timeline)
    source_errors = _list_text_values(raw.get("source_errors") or summary.get("source_errors"))
    topic = _env_text(summary.get("topic") or raw.get("topic") or requested_topic)
    canonical_topic = _env_text(summary.get("canonical_topic") or raw.get("canonical_topic"))
    name = _env_text(summary.get("name") or raw.get("name") or canonical_topic or topic)
    quality_status = _env_text(summary.get("quality_status") or raw.get("quality_status"))
    missing_fields = _list_text_values(summary.get("missing_fields") or raw.get("missing_fields"))
    summary_text_value = raw.get("summary")
    summary_text = (
        summary_text_value
        if isinstance(summary_text_value, str)
        else _build_alphasift_hotspot_summary_text(summary, topic=topic, canonical_topic=canonical_topic)
    )
    return _ensure_hotspot_detail_compat_fields({
        "enabled": True,
        "provider": provider,
        "topic": topic,
        "name": name,
        "canonical_topic": canonical_topic,
        "aliases": _list_text_values(summary.get("aliases") or raw.get("aliases")),
        "summary": summary_text,
        "summary_detail": summary,
        "route": route,
        "timeline": timeline,
        "stocks": stocks,
        "leader_stocks": leader_stocks,
        "source_errors": source_errors,
        "quality_status": quality_status,
        "missing_fields": missing_fields,
        "fallback_used": bool(summary.get("fallback_used") or raw.get("fallback_used") or False),
        "stale": bool(summary.get("stale") or raw.get("stale") or False),
        "stale_age_hours": summary.get("stale_age_hours") or raw.get("stale_age_hours"),
        "resolver_candidates": _list_dict_values(summary.get("resolver_candidates") or raw.get("resolver_candidates")),
    })


def _list_text_values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = _env_text(value)
        return [text] if text else []
    if not isinstance(value, list):
        text = _env_text(value)
        return [text] if text else []
    return [text for item in value if (text := _env_text(item))]


def _list_dict_values(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _hotspot_timeline_to_route(timeline: List[Any]) -> List[Dict[str, Any]]:
    route: List[Dict[str, Any]] = []
    for item in timeline:
        if not isinstance(item, dict):
            continue
        title = _env_text(item.get("title"))
        if not title:
            continue
        date = _env_text(item.get("date") or item.get("published_at"))
        source = _env_text(item.get("source")) or "alphasift_timeline"
        route.append({
            "title": title,
            "description": f"{date}：{title}" if date else title,
            "source": source,
            "url": _env_text(item.get("url")),
            "published_at": date,
        })
    if route:
        return route
    return [{
        "title": "等待发酵",
        "description": "暂未获取到明确催化事件，可继续观察涨跌幅、成交额和核心个股联动。",
        "source": "fallback",
    }]


def _merge_provider_hotspot_route_fallback(
    normalized: Dict[str, Any],
    *,
    provider: "DsaEastMoneyHotspotProvider",
    topic: str,
) -> Dict[str, Any]:
    if _has_meaningful_hotspot_route(normalized.get("route")):
        return normalized
    try:
        provider_detail = provider.hotspot_detail(topic)
    except Exception as exc:
        logger.warning(
            "AlphaSift provider route fallback failed for %s; keeping contract detail route: %s",
            topic,
            exc,
        )
        return normalized

    raw_value = _remove_non_finite_json_values(_to_plain(provider_detail))
    raw: Dict[str, Any] = raw_value if isinstance(raw_value, dict) else {}
    provider_route = raw.get("route")
    if _has_meaningful_hotspot_route(provider_route):
        normalized["route"] = provider_route
        provider_timeline = raw.get("timeline")
        if not normalized.get("timeline") and isinstance(provider_timeline, list):
            normalized["timeline"] = provider_timeline
        return normalized

    provider_timeline = raw.get("timeline")
    if isinstance(provider_timeline, list) and provider_timeline:
        provider_timeline_route = _hotspot_timeline_to_route(provider_timeline)
        if _has_meaningful_hotspot_route(provider_timeline_route):
            normalized["route"] = provider_timeline_route
            normalized["timeline"] = provider_timeline
    return normalized


def _has_meaningful_hotspot_route(route: Any) -> bool:
    if not isinstance(route, list):
        return False
    for item in route:
        if not isinstance(item, dict):
            continue
        title = _env_text(item.get("title"))
        description = _env_text(item.get("description"))
        source = _env_text(item.get("source"))
        if not title and not description:
            continue
        if source == "fallback" and title == "等待发酵":
            continue
        return True
    return False


def _build_alphasift_hotspot_summary_text(summary: Dict[str, Any], *, topic: str, canonical_topic: str) -> str:
    display_topic = canonical_topic or topic
    quality = _env_text(summary.get("quality_status"))
    heat = _safe_float(summary.get("heat_score"))
    stage = _env_text(summary.get("stage"))
    leaders = summary.get("leaders") if isinstance(summary.get("leaders"), list) else []
    parts = [f"{display_topic} 当前热点详情"]
    if heat is not None:
        parts.append(f"热度 {heat:.1f}")
    if stage:
        parts.append(f"阶段 {stage}")
    if leaders:
        parts.append("核心股 " + "、".join(_env_text(item) for item in leaders[:3] if _env_text(item)))
    if quality:
        parts.append(f"质量状态 {quality}")
    return "，".join(part for part in parts if part) + "。"


def _install_alphasift(config: Config) -> Dict[str, Any]:
    with _ALPHASIFT_INSTALL_LOCK:
        install_spec_is_default = _is_default_alphasift_install_spec(config.alphasift_install_spec)
        if _is_alphasift_available():
            _get_dsa_adapter()
            return _build_install_response(
                already_installed=True,
                install_spec_is_default=install_spec_is_default,
            )

        install_spec = _validate_install_spec(config.alphasift_install_spec)

        try:
            _purge_alphasift_modules()
            importlib.invalidate_caches()
            completed = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "--force-reinstall", install_spec],
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=424,
                detail={"error": "alphasift_install_failed", "message": f"修复安装 AlphaSift 失败：{exc}"},
            ) from exc

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout = (completed.stdout or "").strip()
            detail = stderr or stdout or f"pip exited with code {completed.returncode}"
            raise HTTPException(
                status_code=424,
                detail={
                    "error": "alphasift_install_failed",
                    "message": f"修复安装 AlphaSift 失败：{detail}",
                },
            )

        importlib.invalidate_caches()
        _purge_alphasift_modules()
        adapter_status = _call_alphasift_status()
        if not _is_adapter_available(adapter_status):
            raise HTTPException(
                status_code=424,
                detail={"error": "alphasift_unavailable", "message": "AlphaSift 安装完成，但适配层当前不可用（available=false）。请检查当前 Python 环境和安装状态后重试。"},
            )
        _get_dsa_adapter()

        return _build_install_response(
            already_installed=False,
            install_spec_is_default=_is_default_alphasift_install_spec(install_spec),
        )


def _validate_install_spec(raw_install_spec: str) -> str:
    install_spec = (raw_install_spec or "").strip()
    if not install_spec or install_spec.lower() == "alphasift":
        raise HTTPException(
            status_code=424,
            detail={
                "error": "alphasift_install_spec_missing",
                "message": f"请先将 ALPHASIFT_INSTALL_SPEC 配置为受信任来源：{DEFAULT_ALPHASIFT_INSTALL_SPEC}。",
            },
        )

    if install_spec not in ALLOWED_ALPHASIFT_INSTALL_SPECS:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "alphasift_install_spec_not_allowed",
                "message": (
                    "出于安全考虑，修复安装 AlphaSift 仅允许使用受信任来源："
                    f"{DEFAULT_ALPHASIFT_INSTALL_SPEC}。如需使用本地路径或 wheel，请先手动安装到当前 Python 环境。"
                ),
            },
        )

    return install_spec


def _ensure_alphasift_enabled(config: Config) -> None:
    if not config.alphasift_enabled:
        raise HTTPException(
            status_code=403,
            detail={"error": "alphasift_disabled", "message": "ALPHASIFT_ENABLED is false."},
        )


def _ensure_alphasift_ready(config: Config, *, request: Request) -> None:
    # Backward-compatible helper for tests/extensions. Normal strategies/screen
    # calls no longer mutate the Python environment; AlphaSift is installed with
    # project dependencies and `/install` remains an explicit repair action.
    _ensure_alphasift_available_for_use()


def _ensure_alphasift_available_for_use() -> None:
    _, available, diagnostics = _get_alphasift_status_snapshot()
    if available:
        return
    normalized_diagnostics = _include_alphasift_diagnostic_suffix(diagnostics)
    if _is_missing_alphasift_module(diagnostics):
        raise _alphasift_unavailable_exception(
            "AlphaSift 是 DSA 的项目依赖，但当前运行环境未安装适配层。请先执行 `pip install -r requirements.txt`，或重建 Docker/桌面后端产物。",
            diagnostics=normalized_diagnostics,
        )
    raise _alphasift_unavailable_exception(
        "AlphaSift 已开启但当前运行时状态异常。已保留异常诊断，避免自动重装掩盖真实问题。",
        diagnostics=normalized_diagnostics,
    )


def _is_missing_alphasift_module(diagnostics: Optional[Dict[str, str]]) -> bool:
    return bool(diagnostics and diagnostics.get("reason") == "missing_module")


def _include_alphasift_diagnostic_suffix(
    diagnostics: Optional[Dict[str, str]],
) -> Optional[Dict[str, str]]:
    if diagnostics is None:
        return None
    if diagnostics.get("reason") == "missing_module":
        return diagnostics
    normalized = dict(diagnostics)
    normalized.setdefault("resolution", "no_auto_install")
    normalized.setdefault(
        "message",
        "请先检查后端日志并修复运行时异常，当前未触发修复安装。",
    )
    return normalized


def _get_alphasift_status_snapshot() -> Tuple[Dict[str, Any], bool, Optional[Dict[str, str]]]:
    try:
        adapter_status = _call_alphasift_status()
    except HTTPException as exc:
        return {}, False, _extract_alphasift_diagnostics(exc)
    except Exception as exc:
        diagnostics = _log_unexpected_alphasift_exception("status_probe", exc)
        return {}, False, diagnostics

    return adapter_status, _is_adapter_available(adapter_status), None


def _ensure_alphasift_install_access(request: Request) -> None:
    if os.getenv("DSA_DESKTOP_MODE") == "true":
        return
    refresh_auth_state()
    if not is_auth_enabled():
        raise HTTPException(
            status_code=403,
            detail={
                "error": "alphasift_install_access_denied",
                "message": "AlphaSift 修复安装仅允许桌面模式或已启用管理员认证的会话。请先启用管理员认证后重试。",
            },
        )

    cookie_val = request.cookies.get(COOKIE_NAME)
    if cookie_val and verify_session(cookie_val):
        return

    raise HTTPException(
        status_code=401,
        detail={
            "error": "alphasift_install_access_denied",
            "message": "AlphaSift 修复安装需要有效管理员会话。",
        },
    )


def _is_alphasift_available() -> bool:
    _, available, _ = _get_alphasift_status_snapshot()
    return available


def _is_adapter_available(adapter_status: Any) -> bool:
    if isinstance(adapter_status, dict):
        return bool(adapter_status.get("available", True))
    return True


def _import_alphasift() -> Any:
    try:
        _prepare_alphasift_runtime_env()
        return importlib.import_module(ALPHASIFT_DSA_ADAPTER_MODULE)
    except ModuleNotFoundError as exc:
        if _is_expected_alphasift_missing(exc):
            diagnostics = {
                "reason": "missing_module",
                "stage": "import_adapter",
                "error_type": exc.__class__.__name__,
                "module": str(getattr(exc, "name", ALPHASIFT_DSA_ADAPTER_MODULE)),
            }
            raise _alphasift_unavailable_exception(
                f"AlphaSift 未安装或未挂载到当前 Python 环境，无法导入 {ALPHASIFT_DSA_ADAPTER_MODULE}：{exc}",
                diagnostics=diagnostics,
            ) from exc
        diagnostics = _log_unexpected_alphasift_exception("import_adapter", exc)
        raise _alphasift_unavailable_exception(
            f"AlphaSift 适配层导入失败，请检查依赖完整性和当前 Python 环境：{exc}",
            diagnostics=diagnostics,
        ) from exc
    except Exception as exc:
        diagnostics = _log_unexpected_alphasift_exception("import_adapter", exc)
        raise _alphasift_unavailable_exception(
            f"AlphaSift 适配层导入失败，请检查依赖完整性和当前 Python 环境：{exc}",
            diagnostics=diagnostics,
        ) from exc


def _import_alphasift_hotspot() -> Any:
    try:
        _prepare_alphasift_runtime_env()
        return importlib.import_module("alphasift.hotspot")
    except ModuleNotFoundError as exc:
        if getattr(exc, "name", None) in {"alphasift", "alphasift.hotspot"}:
            diagnostics = {
                "reason": "missing_module",
                "stage": "import_hotspot",
                "error_type": exc.__class__.__name__,
                "module": str(getattr(exc, "name", "alphasift.hotspot")),
            }
            raise _alphasift_unavailable_exception(
                f"AlphaSift hotspot module is unavailable: {exc}",
                diagnostics=diagnostics,
            ) from exc
        diagnostics = _log_unexpected_alphasift_exception("import_hotspot", exc)
        raise _alphasift_unavailable_exception(
            f"AlphaSift hotspot module import failed: {exc}",
            diagnostics=diagnostics,
        ) from exc
    except Exception as exc:
        diagnostics = _log_unexpected_alphasift_exception("import_hotspot", exc)
        raise _alphasift_unavailable_exception(
            f"AlphaSift hotspot module import failed: {exc}",
            diagnostics=diagnostics,
        ) from exc


def _prepare_alphasift_runtime_env() -> None:
    if os.getenv("STRATEGIES_DIR"):
        return

    spec = importlib.util.find_spec("alphasift")
    if not spec or not spec.origin:
        return

    package_strategies_dir = Path(spec.origin).resolve().parent / "strategies"
    if package_strategies_dir.is_dir():
        os.environ["STRATEGIES_DIR"] = str(package_strategies_dir)


def _get_dsa_adapter() -> Any:
    adapter = _import_alphasift()
    for attr in ("get_status", "list_strategies", "screen"):
        _get_adapter_callable(adapter, attr, f"{attr}() 不可调用。")
    return adapter


def _get_adapter_callable(adapter: Any, name: str, missing_error: str) -> Any:
    callable_obj = getattr(adapter, name, None)
    if not callable(callable_obj):
        raise HTTPException(
            status_code=424,
            detail={"error": "alphasift_unavailable", "message": f"已导入 alphasift 适配层，但 {missing_error}"},
        )
    return callable_obj


def _call_alphasift_status() -> Dict[str, Any]:
    try:
        adapter = _import_alphasift()
    except ModuleNotFoundError as exc:
        if _is_expected_alphasift_missing(exc):
            logger.warning("AlphaSift import missing expected module during status probe: %s", exc)
            diagnostics = {
                "reason": "missing_module",
                "stage": "import_adapter",
                "error_type": exc.__class__.__name__,
                "module": str(getattr(exc, "name", ALPHASIFT_DSA_ADAPTER_MODULE)),
            }
            raise _alphasift_unavailable_exception(
                f"AlphaSift 未安装或未挂载到当前 Python 环境，无法导入 {ALPHASIFT_DSA_ADAPTER_MODULE}：{exc}",
                diagnostics=diagnostics,
            ) from exc

        diagnostics = _log_unexpected_alphasift_exception("import_adapter", exc)
        raise _alphasift_unavailable_exception(
            f"AlphaSift 适配层导入失败，请检查依赖完整性和当前 Python 环境：{exc}",
            diagnostics=diagnostics,
        ) from exc
    try:
        get_status = _get_adapter_callable(adapter, "get_status", "get_status() 不可调用。")
    except HTTPException as exc:
        diagnostics = _log_unexpected_alphasift_exception("get_status_callable", exc)
        raise _alphasift_unavailable_exception(
            "AlphaSift 适配层 get_status 不可调用，请检查适配层版本。",
            diagnostics=diagnostics,
        ) from exc
    try:
        result = _to_plain(get_status())
    except Exception as exc:
        diagnostics = _log_unexpected_alphasift_exception("get_status", exc)
        raise _alphasift_unavailable_exception(
            f"AlphaSift 适配层 get_status 调用失败：{exc}",
            diagnostics=diagnostics,
        ) from exc
    if not isinstance(result, dict):
        exc = TypeError(f"get_status returned {type(result).__name__}, expected dict")
        diagnostics = _log_unexpected_alphasift_exception("get_status_result", exc)
        raise _alphasift_unavailable_exception(
            "AlphaSift 适配层 get_status 返回结构非法，请检查适配层版本。",
            diagnostics=diagnostics,
        ) from exc
    return result


def _is_expected_alphasift_missing(exc: ModuleNotFoundError) -> bool:
    return getattr(exc, "name", None) in ALPHASIFT_EXPECTED_MISSING_MODULES


def _purge_alphasift_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "alphasift" or module_name.startswith("alphasift."):
            sys.modules.pop(module_name, None)


def _alphasift_unavailable_exception(
    message: str,
    *,
    diagnostics: Optional[Dict[str, str]] = None,
) -> HTTPException:
    detail: Dict[str, Any] = {"error": "alphasift_unavailable", "message": message}
    if diagnostics:
        detail["diagnostics"] = diagnostics
    return HTTPException(status_code=424, detail=detail)


def _log_unexpected_alphasift_exception(stage: str, exc: BaseException) -> Dict[str, str]:
    logger.warning("Unexpected AlphaSift %s failure: %s", stage, exc, exc_info=exc.__traceback__ is not None)
    return {
        "reason": "unexpected_exception",
        "stage": stage,
        "error_type": exc.__class__.__name__,
    }


def _extract_alphasift_diagnostics(exc: HTTPException) -> Optional[Dict[str, str]]:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    diagnostics = detail.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    return {str(key): str(value) for key, value in diagnostics.items()}


def _list_strategies() -> List[Dict[str, Any]]:
    adapter = _get_dsa_adapter()
    list_strategies = _get_adapter_callable(adapter, "list_strategies", "list_strategies() 不可调用。")
    raw = _to_plain(list_strategies())
    if not isinstance(raw, list):
        raise HTTPException(
            status_code=424,
            detail={"error": "alphasift_invalid_result", "message": "AlphaSift list_strategies 返回非列表。"},
        )

    normalized: List[Dict[str, Any]] = []
    for item in raw:
        strategy = _normalize_strategy(item)
        if not strategy.get("id"):
            continue
        normalized.append(strategy)
    return normalized


def _normalize_strategy(raw: Any) -> Dict[str, Any]:
    item = _to_plain(raw)
    if isinstance(item, str):
        return _strategy_model(id=item, name=item, title=item)
    if not isinstance(item, dict):
        value = str(item)
        return _strategy_model(id=value, name=value, title=value)

    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    market_scope = item.get("market_scope") or item.get("marketScope") or []
    if not isinstance(market_scope, list):
        market_scope = [str(market_scope)] if market_scope else []

    strategy_id = str(
        item.get("id")
        or item.get("strategy")
        or item.get("strategy_id")
        or item.get("name")
        or "",
    )
    name = str(item.get("name") or item.get("title") or strategy_id)
    category = str(item.get("category") or item.get("tag") or "")
    return _strategy_model(
        id=strategy_id,
        name=name,
        title=str(item.get("title") or name),
        description=str(item.get("description") or ""),
        category=category,
        tag=str(item.get("tag") or category),
        tags=[str(tag) for tag in tags],
        market_scope=[str(market) for market in market_scope],
        market=str(item.get("market") or item.get("market_id") or ""),
    )


def _strategy_model(**kwargs: Any) -> Dict[str, Any]:
    normalized = AlphaSiftStrategyResponse(**kwargs)
    try:
        return normalized.model_dump()
    except AttributeError:
        return normalized.dict()


def _ensure_supported_strategy(strategy: str) -> None:
    strategies = _list_strategies()
    if not strategies:
        return

    ids = {item.get("id") for item in strategies if item.get("id")}
    if strategy in ids:
        return

    # 兼容“策略列表为空时手动输入”以及“用户手动覆盖策略参数”场景，
    # 策略由适配层进行最终校验，因此在列表外仍保持透传。


def _call_alphasift_screen(screen: Any, strategy: str, market: str, max_results: int, config: Config) -> Any:
    signature = inspect.signature(screen)
    params = signature.parameters
    supports_var_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in params.values())
    positional_params = [
        parameter
        for parameter in params.values()
        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    supports_var_positional = any(parameter.kind == inspect.Parameter.VAR_POSITIONAL for parameter in params.values())

    supports_max_results = "max_results" in params or supports_var_kwargs
    supports_max_output = "max_output" in params or supports_var_kwargs
    supports_use_llm = "use_llm" in params or supports_var_kwargs
    supports_context = "context" in params or supports_var_kwargs

    kwargs: Dict[str, Any] = {"market": market}
    if supports_max_results:
        kwargs["max_results"] = max_results
    elif supports_max_output:
        kwargs["max_output"] = max_results
    else:
        kwargs["max_results"] = max_results

    if supports_use_llm:
        kwargs["use_llm"] = True
    if supports_context:
        kwargs["context"] = _build_alphasift_context(config, max_results=max_results)

    with (
        _alphasift_runtime_env(config, max_results=max_results),
        _alphasift_dsa_daily_history_provider(),
        _alphasift_litellm_headers(config),
    ):
        try:
            return screen(strategy, **kwargs)
        except TypeError as exc:
            message = str(exc)
            signature_mismatch = ("keyword" in message and "argument" in message) or (
                "positional" in message and "given" in message
            )
            if not signature_mismatch:
                raise
            if "context" in kwargs:
                retry_kwargs = dict(kwargs)
                retry_kwargs.pop("context", None)
                try:
                    return screen(strategy, **retry_kwargs)
                except TypeError as retry_exc:
                    exc = retry_exc
            if not (supports_var_kwargs or supports_var_positional or len(positional_params) >= 3):
                raise exc
            return screen(strategy, market, max_results)


@contextmanager
def _alphasift_runtime_env(config: Config, *, max_results: Optional[int] = None) -> Iterator[None]:
    updates = _build_alphasift_runtime_env(config, max_results=max_results)
    if not updates:
        yield
        return

    sentinel = object()
    with _ALPHASIFT_RUNTIME_ENV_LOCK:
        previous = {key: os.environ.get(key, sentinel) for key in updates}
        os.environ.update(updates)
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is sentinel:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value  # type: ignore[assignment]


@contextmanager
def _alphasift_dsa_daily_history_provider() -> Iterator[None]:
    try:
        daily_module = importlib.import_module("alphasift.daily")
    except Exception:
        yield
        return

    original_fetch = getattr(daily_module, "fetch_daily_history", None)
    if not callable(original_fetch):
        yield
        return

    def fetch_daily_history_with_dsa(
        code: str,
        *,
        lookback_days: int = 120,
        source: str = "akshare",
        retries: int = 2,
    ) -> Any:
        try:
            dsa_df, dsa_source = get_dsa_daily_history(code, lookback_days=lookback_days)
            normalized = _normalize_dsa_daily_history(dsa_df)
            if normalized is not None and not normalized.empty:
                normalized.attrs["source"] = f"dsa:{dsa_source}"
                return normalized
        except Exception as exc:
            logger.warning(
                "AlphaSift DSA daily history fetch failed for %s; falling back to AlphaSift source %s: %s",
                code,
                source,
                exc,
            )
        return original_fetch(code, lookback_days=lookback_days, source=source, retries=retries)

    with _ALPHASIFT_RUNTIME_ENV_LOCK:
        setattr(daily_module, "fetch_daily_history", fetch_daily_history_with_dsa)
        try:
            yield
        finally:
            setattr(daily_module, "fetch_daily_history", original_fetch)


def _resolve_alphasift_snapshot_source_priority(config: Config) -> str:
    token = _env_text(getattr(config, "tushare_token", None) or os.getenv("TUSHARE_TOKEN"))
    if token:
        return DSA_ALPHASIFT_SNAPSHOT_SOURCE_PRIORITY_WITH_TUSHARE
    return DSA_ALPHASIFT_SNAPSHOT_SOURCE_PRIORITY


def _build_alphasift_runtime_env(config: Config, *, max_results: Optional[int] = None) -> Dict[str, str]:
    # Bridge runtime only: only inject resolved DSA values for this request/process scope.
    # User .env/config is never rewritten here; unset channels/models are not silently migrated.
    # 与 LiteLLM provider/model、openai-compatible `api_base` 与 headers 注入语义保持一致，
    # 参见 https://docs.litellm.ai/docs/providers 与
    # https://docs.litellm.ai/docs/proxy/configs#the-model_list-key
    env: Dict[str, str] = {}

    def put(key: str, value: Any) -> None:
        text = _env_text(value)
        if text:
            env[key] = text

    def put_default(key: str, value: Any) -> None:
        if os.getenv(key) not in (None, ""):
            return
        put(key, value)

    litellm_model, fallback_models = _resolve_alphasift_llm_models(config)
    put("LITELLM_MODEL", litellm_model)
    if fallback_models:
        put("LITELLM_FALLBACK_MODELS", ",".join(fallback_models))
    put("LITELLM_CONFIG", config.litellm_config_path)
    if os.getenv("LLM_TEMPERATURE") not in (None, ""):
        put("LLM_TEMPERATURE", config.llm_temperature)

    channels = _normalize_dsa_llm_channels(config)
    if channels:
        put("LLM_CHANNELS", ",".join(channel["name"] for channel in channels))
        for channel in channels:
            prefix = channel["name"].upper()
            put(f"LLM_{prefix}_ENABLED", "true")
            put(f"LLM_{prefix}_PROTOCOL", channel.get("protocol"))
            put(f"LLM_{prefix}_BASE_URL", channel.get("base_url"))
            put(f"LLM_{prefix}_API_KEYS", ",".join(channel.get("api_keys") or []))
            put(f"LLM_{prefix}_MODELS", ",".join(channel.get("models") or []))
            if channel.get("extra_headers"):
                put(
                    f"LLM_{prefix}_EXTRA_HEADERS",
                    json.dumps(channel.get("extra_headers"), ensure_ascii=False),
                )

    gemini_keys = _dedupe_strings([
        *(config.gemini_api_keys or []),
        *_channel_keys_for_provider(channels, {"gemini", "vertex_ai"}),
    ])
    anthropic_keys = _dedupe_strings([
        *(config.anthropic_api_keys or []),
        *_channel_keys_for_provider(channels, {"anthropic"}),
    ])
    openai_keys = _dedupe_strings([
        *(config.openai_api_keys or []),
        *_channel_keys_for_provider(channels, {"openai"}),
    ])
    deepseek_keys = _dedupe_strings([
        *(config.deepseek_api_keys or []),
        *_channel_keys_for_provider(channels, {"deepseek"}),
    ])

    _put_provider_keys(env, "GEMINI", gemini_keys)
    _put_provider_keys(env, "ANTHROPIC", anthropic_keys)
    _put_provider_keys(env, "OPENAI", openai_keys)
    _put_provider_keys(env, "DEEPSEEK", deepseek_keys)

    put("OPENAI_BASE_URL", config.openai_base_url or _first_channel_base_url(channels, {"openai"}))
    put_default("DAILY_SOURCE", "auto")
    put("LLM_CANDIDATE_CONTEXT_ENABLED", "false")
    put_default("LLM_CANDIDATE_CONTEXT_PROVIDERS", DSA_ALPHASIFT_CANDIDATE_CONTEXT_PROVIDERS)
    put_default("LLM_CANDIDATE_MULTIPLIER", str(DSA_ALPHASIFT_LLM_CANDIDATE_MULTIPLIER))
    put_default("LLM_MAX_CANDIDATES", str(_resolve_dsa_llm_max_candidates(max_results)))
    put_default("SNAPSHOT_SOURCE_PRIORITY", _resolve_alphasift_snapshot_source_priority(config))
    alphasift_data_dir = _resolve_alphasift_data_dir()
    put_default("ALPHASIFT_DATA_DIR", str(alphasift_data_dir))
    put_default("ALPHASIFT_FALLBACK_SNAPSHOT_PATH", str(alphasift_data_dir / "snapshot.last_good.json"))
    put_default("ALPHASIFT_DAILY_HISTORY_CACHE_DIR", str(alphasift_data_dir / "daily_history"))
    put_default("ALPHASIFT_INDUSTRY_PROVIDER_CACHE_DIR", str(alphasift_data_dir / "industry_provider_cache"))
    return env


def _resolve_hotspot_provider(provider: str) -> Tuple[str, Any]:
    requested = (provider or "").strip()
    if requested.lower() == "akshare":
        return requested, DsaEastMoneyHotspotProvider()
    if requested:
        return requested, requested
    configured = (os.getenv("INDUSTRY_PROVIDER") or "").strip()
    if configured.lower() == "akshare":
        return configured, DsaEastMoneyHotspotProvider()
    return configured or "none", configured or "none"


class DsaEastMoneyHotspotProvider:
    """Minimal EastMoney board provider for AlphaSift hotspot scoring."""

    _BASE_URL = "https://push2.eastmoney.com/api/qt/clist/get"
    _HTTP_TIMEOUT_SECONDS = 8
    _COMMON_PARAMS = {
        "pn": "1",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f12",
        "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
    }
    _BROAD_BOARD_KEYWORDS = (
        "融资融券",
        "深股通",
        "沪股通",
        "创业板",
        "昨日",
        "机构重仓",
        "富时罗素",
        "MSCI",
        "标普",
        "上证",
        "深证",
        "中证",
        "HS300",
        "证金",
        "QFII",
        "基金",
        "转融券",
        "预增",
        "预盈",
        "亏损",
        "低价",
        "小盘股",
        "中盘股",
        "百元股",
        "破发",
        "破增发",
        "趋势股",
        "广东板块",
        "江苏板块",
        "浙江板块",
        "上海板块",
        "深圳特区",
        "央国企",
        "国企改革",
        "专精特新",
        "其他",
        "Ⅱ",
        "Ⅲ",
    )
    _CHANGE_EVENT_LABELS = {
        4: "快速拉升",
        8: "快速回落",
        16: "大幅上涨",
        32: "大幅下跌",
        64: "有大笔买入",
        128: "有大笔卖出",
        8193: "火箭发射",
        8194: "高台跳水",
        8201: "大笔买入",
        8202: "大笔卖出",
        8203: "封涨停板",
        8204: "打开涨停板",
        8207: "有打开跌停板",
        8208: "封跌停板",
        8209: "向上缺口",
        8210: "向下缺口",
        8211: "60日新高",
        8212: "60日新低",
        8213: "60日大幅上涨",
        8214: "60日大幅下跌",
        8215: "竞价上涨",
        8216: "竞价下跌",
        8217: "高开",
        8218: "低开",
        8219: "放量",
        8220: "缩量",
        8221: "向上突破",
        8222: "向下破位",
    }
    _METAL_TOPIC_GROUPS = {
        "钼": "小金属",
        "钨": "小金属",
        "钴": "小金属",
        "镍": "小金属",
        "锑": "小金属",
        "铟": "小金属",
        "锗": "小金属",
        "铅锌": "工业金属",
        "铜": "工业金属",
        "铝": "工业金属",
        "锡": "工业金属",
        "黄金": "贵金属",
        "白银": "贵金属",
        "贵金属": "贵金属",
    }
    def __init__(self) -> None:
        import requests

        self._board_changes_raw_cache: Any = None
        self._board_changes_frame_cache: Any = None
        self._constituent_cache: Dict[Tuple[str, str], Any] = {}
        self._session = requests.Session()
        self._request_lock = threading.RLock()
        self._last_request_ts = 0.0
        self._min_request_interval = 0.25

    def _eastmoney_get_once(self, url: str, **kwargs: Any) -> Any:
        with self._request_lock:
            elapsed = time.monotonic() - self._last_request_ts
            if elapsed < self._min_request_interval:
                time.sleep(self._min_request_interval - elapsed)
            try:
                return self._session.get(url, **kwargs)
            finally:
                self._last_request_ts = time.monotonic()

    def _eastmoney_get(self, url: str, **kwargs: Any) -> Any:
        import requests

        retryable_errors = (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        )
        delays = (0.3, 0.8)
        last_error: Optional[BaseException] = None
        for attempt in range(len(delays) + 1):
            try:
                return self._eastmoney_get_once(url, **kwargs)
            except retryable_errors as exc:
                last_error = exc
                if attempt >= len(delays):
                    break
                logger.warning(
                    "AlphaSift EastMoney hotspot request failed; retrying attempt=%s: %s",
                    attempt + 1,
                    exc,
                )
                time.sleep(delays[attempt])
        assert last_error is not None
        raise last_error

    def stock_board_concept_name_em(self) -> Any:
        frame = self._fetch_board_changes_with_fallback()
        if frame is not None and not frame.empty:
            return frame
        frame = self._fetch_rankings_with_fallback("concept")
        if frame is not None and not frame.empty:
            return frame
        return self._fetch_board_names(source_fs="m:90 t:3 f:!50")

    def stock_board_industry_name_em(self) -> Any:
        concept_frame = self._fetch_board_changes_with_fallback()
        if concept_frame is not None and not concept_frame.empty:
            import pandas as pd

            return pd.DataFrame()
        frame = self._fetch_rankings_with_fallback("industry")
        if frame is not None and not frame.empty:
            return frame
        return self._fetch_board_names(source_fs="m:90 t:2 f:!50")

    def hotspot_rows(self, *, top: int = 12) -> List[Dict[str, Any]]:
        import pandas as pd

        frame = self.stock_board_concept_name_em()
        df = pd.DataFrame(frame)
        if df.empty:
            return []
        rows: List[Dict[str, Any]] = []
        for index, row in df.head(max(1, min(top, 50))).iterrows():
            name = _env_text(row.get("name") or row.get("板块名称") or row.get("行业名称") or row.get("名称"))
            if not name:
                continue
            change_pct = _safe_float(row.get("change_pct") or row.get("涨跌幅"))
            event_count = int(_safe_float(row.get("event_count") or row.get("observations")) or 0)
            leader = _env_text(row.get("leader"))
            leaders_raw = row.get("leaders")
            leaders = _list_text_values(leaders_raw) or ([leader] if leader else [])
            heat_score = _safe_float(row.get("heat_score"))
            if heat_score is None:
                heat_score = min(99.0, max(1.0, max(change_pct or 0.0, 0.0) * 9.0 + event_count / 120.0))
            trend_score = _safe_float(row.get("trend_score"))
            if trend_score is None:
                trend_score = self._derive_trend_score(change_pct=change_pct, event_count=event_count)
            persistence_score = _safe_float(row.get("persistence_score"))
            if persistence_score is None:
                persistence_score = self._derive_persistence_score(event_count=event_count)
            stage = _env_text(row.get("stage") or row.get("state")) or self._derive_hotspot_stage(
                change_pct=change_pct,
                event_count=event_count,
            )
            display_name = self._display_hotspot_name(name)
            rows.append({
                "topic": name,
                "name": display_name,
                "theme_group": self._hotspot_group(name),
                "source": "dsa_eastmoney_board_change",
                "rank": len(rows) + 1,
                "change_pct": change_pct,
                "heat_score": round(float(heat_score), 2),
                "trend_score": trend_score,
                "persistence_score": persistence_score,
                "observations": event_count,
                "state": stage,
                "stage": stage,
                "sample_stock_count": int(_safe_float(row.get("sample_stock_count")) or len(leaders)),
                "leaders": leaders,
            })
        return rows

    def stock_board_concept_cons_em(self, symbol: str = "") -> Any:
        cached = self._get_constituent_cache("concept", symbol)
        if cached is not None:
            return cached
        frames = [self._fetch_eastmoney_constituents(symbol, source="concept")]
        try:
            frames.append(self._fetch_ths_constituents(symbol))
        except Exception as exc:
            logger.warning(
                "AlphaSift THS constituent fetch failed for %s; falling back to alternative sources: %s",
                symbol,
                exc,
            )
        frames.append(self._fallback_constituents(symbol))
        frames.append(self._related_hotspot_constituents(symbol))
        frame = self._merge_constituent_frames(frames)
        self._set_constituent_cache("concept", symbol, frame)
        return frame

    def stock_board_industry_cons_em(self, symbol: str = "") -> Any:
        cached = self._get_constituent_cache("industry", symbol)
        if cached is not None:
            return cached
        frame = self._merge_constituent_frames([
            self._fetch_eastmoney_constituents(symbol, source="industry"),
            self._fallback_constituents(symbol),
        ])
        self._set_constituent_cache("industry", symbol, frame)
        return frame

    def hotspot_detail(self, topic: str) -> Dict[str, Any]:
        try:
            summary = self._find_board_change(topic)
        except Exception as exc:
            logger.warning(
                "AlphaSift board-change summary fetch failed for %s; continuing without summary: %s",
                topic,
                exc,
            )
            summary = {}
        if self._is_industry_hotspot(topic):
            stocks = self._normalize_constituent_records(self.stock_board_industry_cons_em(topic))
        else:
            stocks = self._normalize_constituent_records(self.stock_board_concept_cons_em(topic))
        stocks = self._enrich_constituent_quotes(stocks)
        route = self._build_hotspot_route(topic, summary)
        info = self._fetch_ths_info(topic)
        if info:
            route.append({
                "title": "同花顺板块概况",
                "description": "；".join(f"{key} {value}" for key, value in list(info.items())[:4]),
                "source": "ths_info",
            })
        if not stocks and summary:
            stock_code = _env_text(summary.get("板块异动最频繁个股及所属类型-股票代码"))
            stock_name = _env_text(summary.get("板块异动最频繁个股及所属类型-股票名称"))
            if stock_code or stock_name:
                stocks.append({
                    "code": stock_code,
                    "name": stock_name,
                    "role": "异动核心",
                    "change_pct": None,
                    "hot_stock_score": 60.0,
                })
        return _ensure_hotspot_detail_compat_fields({
            "topic": topic,
            "name": self._display_hotspot_name(topic),
            "canonical_topic": topic,
            "summary": self._build_hotspot_summary(topic, summary),
            "route": route,
            "stocks": stocks[:30],
            "leader_stocks": stocks[:30],
            "stock_count": len(stocks),
            "source_errors": [],
        })

    def _fetch_board_changes(self) -> Any:
        import pandas as pd

        if self._board_changes_frame_cache is not None:
            return self._board_changes_frame_cache.copy()

        df = self._fetch_board_changes_raw()
        if df is None or df.empty:
            return pd.DataFrame()
        rows = []
        for index, row in df.iterrows():
            topic = _env_text(row.get("板块名称"))
            if not topic or self._is_broad_board(topic):
                continue
            change_pct = _safe_float(row.get("涨跌幅"))
            event_count = int(_safe_float(row.get("板块异动总次数")) or 0)
            leader = _env_text(row.get("板块异动最频繁个股及所属类型-股票名称"))
            heat_score = min(99.0, max(1.0, event_count / 120.0 + max(change_pct or 0.0, 0.0) * 9.0))
            trend_score = self._derive_trend_score(change_pct=change_pct, event_count=event_count)
            persistence_score = self._derive_persistence_score(event_count=event_count)
            leaders = [leader] if leader else []
            stage = self._derive_hotspot_stage(change_pct=change_pct, event_count=event_count)
            rows.append({
                "name": topic,
                "change_pct": change_pct,
                "rank": index + 1,
                "heat_score": heat_score,
                "trend_score": trend_score,
                "persistence_score": persistence_score,
                "observations": event_count,
                "state": stage,
                "stage": stage,
                "sample_stock_count": len(leaders),
                "leaders": leaders,
                "leader": leader,
                "event_count": event_count,
            })
        rows.sort(key=lambda item: (item.get("heat_score") or 0, item.get("event_count") or 0), reverse=True)
        frame = pd.DataFrame(rows)
        self._board_changes_frame_cache = frame
        return frame.copy()

    def _fetch_board_changes_raw(self) -> Any:
        import akshare as ak

        if self._board_changes_raw_cache is not None:
            return self._board_changes_raw_cache.copy()
        df = ak.stock_board_change_em()
        self._board_changes_raw_cache = df
        return df.copy() if df is not None else df

    def _fetch_board_changes_with_fallback(self) -> Any:
        import pandas as pd

        try:
            return self._fetch_board_changes()
        except Exception as exc:
            logger.warning("AlphaSift hotspot board-change fetch failed; falling back to ranking/board names: %s", exc)
            return pd.DataFrame()

    def _is_broad_board(self, name: str) -> bool:
        return any(keyword in name for keyword in self._BROAD_BOARD_KEYWORDS)

    def _fetch_rankings(self, source: str) -> Any:
        import pandas as pd

        manager = _get_dsa_fetcher_manager()
        fetch = manager.get_concept_rankings if source == "concept" else manager.get_sector_rankings
        top, _bottom = fetch(100)
        rows = []
        for index, item in enumerate(top or []):
            name = _env_text((item or {}).get("name"))
            if not name:
                continue
            rows.append({
                "name": name,
                "change_pct": (item or {}).get("change_pct"),
                "rank": index + 1,
            })
        return pd.DataFrame(rows)

    def _fetch_rankings_with_fallback(self, source: str) -> Any:
        import pandas as pd

        try:
            return self._fetch_rankings(source)
        except Exception as exc:
            logger.warning("AlphaSift hotspot %s ranking fetch failed; falling back to board names: %s", source, exc)
            return pd.DataFrame()

    def _fetch_board_names(self, *, source_fs: str) -> Any:
        import pandas as pd

        params = dict(self._COMMON_PARAMS)
        params.update({"pz": "100", "fs": source_fs})
        response = self._eastmoney_get(
            self._BASE_URL,
            params=params,
            timeout=self._HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"},
        )
        response.raise_for_status()
        payload = response.json()
        rows = ((payload.get("data") or {}).get("diff") or []) if isinstance(payload, dict) else []
        normalized = [
            {
                "板块名称": str(row.get("f14") or "").strip(),
                "涨跌幅": row.get("f3"),
                "序号": index + 1,
                "name": str(row.get("f14") or "").strip(),
                "change_pct": row.get("f3"),
                "rank": index + 1,
                "leader": str(row.get("f140") or row.get("f128") or "").strip(),
                "up_count": row.get("f104"),
                "down_count": row.get("f105"),
                "source": "eastmoney_push2_board_spot",
            }
            for index, row in enumerate(rows)
            if str(row.get("f14") or "").strip()
        ]
        return pd.DataFrame(normalized)

    def _find_board_change(self, topic: str) -> Dict[str, Any]:
        df = self._fetch_board_changes_raw()
        if df is None or df.empty:
            return {}
        rows = df[df["板块名称"].astype(str) == topic]
        if rows.empty:
            rows = df[df["板块名称"].astype(str).str.contains(re.escape(topic), case=False, na=False)]
        if rows.empty:
            return {}
        return rows.iloc[0].to_dict()

    def _is_industry_hotspot(self, topic: str) -> bool:
        # EastMoney board-change rows are concept-like hot boards; if the topic is
        # already in that live change set, avoid an extra industry request.
        try:
            concept_frame = self._fetch_board_changes_with_fallback()
            if self._board_frame_contains_topic(concept_frame, topic):
                return False
        except Exception:
            pass
        try:
            frame = self.stock_board_industry_name_em()
        except Exception as exc:
            logger.warning(
                "AlphaSift industry hotspot source check failed for %s; using concept constituents: %s",
                topic,
                exc,
            )
            return False
        return self._board_frame_contains_topic(frame, topic)

    def _derive_trend_score(self, *, change_pct: Optional[float], event_count: int) -> float:
        change_component = max(change_pct or 0.0, 0.0) * 12.0
        event_component = min(event_count / 8.0, 45.0)
        return round(min(99.0, max(1.0, change_component + event_component)), 1)

    def _derive_persistence_score(self, *, event_count: int) -> float:
        return round(min(99.0, max(1.0, event_count / 3.0)), 1)

    def _derive_hotspot_stage(self, *, change_pct: Optional[float], event_count: int) -> str:
        positive_change = max(change_pct or 0.0, 0.0)
        if event_count >= 180 and positive_change >= 3.0:
            return "加速发酵"
        if event_count >= 90:
            return "持续发酵"
        if positive_change >= 5.0:
            return "快速拉升"
        return "初次异动"

    def _hotspot_group(self, topic: str) -> str:
        topic_text = _env_text(topic)
        for keyword, group in self._METAL_TOPIC_GROUPS.items():
            if keyword and keyword in topic_text:
                return group
        return ""

    def _display_hotspot_name(self, topic: str) -> str:
        topic_text = _env_text(topic)
        group = self._hotspot_group(topic_text)
        if group and topic_text != group:
            return f"{group} · {topic_text}"
        return topic_text

    def _board_frame_contains_topic(self, frame: Any, topic: str) -> bool:
        import pandas as pd

        topic_text = _env_text(topic)
        if not topic_text:
            return False
        df = pd.DataFrame(frame)
        if df.empty:
            return False
        for column in ("name", "板块名称", "行业名称", "名称"):
            if column not in df.columns:
                continue
            values = df[column].map(_env_text)
            if bool((values == topic_text).any()):
                return True
        return False

    def _build_hotspot_summary(self, topic: str, summary: Dict[str, Any]) -> str:
        if not summary:
            return f"{topic} 当前暂无可用的板块异动摘要。"
        change_pct = _safe_float(summary.get("涨跌幅"))
        event_count = int(_safe_float(summary.get("板块异动总次数")) or 0)
        leader = _env_text(summary.get("板块异动最频繁个股及所属类型-股票名称"))
        action = _env_text(summary.get("板块异动最频繁个股及所属类型-买卖方向"))
        parts = [f"{topic} 当前涨跌幅 {change_pct:.2f}%" if change_pct is not None else f"{topic} 当前有异动记录"]
        if event_count:
            parts.append(f"盘中异动 {event_count} 次")
        if leader:
            parts.append(f"高频异动个股为 {leader}{f'（{action}）' if action else ''}")
        return "，".join(parts) + "。"

    def _build_hotspot_route(self, topic: str, summary: Dict[str, Any]) -> List[Dict[str, Any]]:
        route_by_date: Dict[str, Dict[str, Any]] = {}
        today = datetime.now().date().isoformat()

        def put_daily_item(*, date: str, title: str, description: str, source: str) -> None:
            day = date or today
            existing = route_by_date.get(day)
            if existing:
                existing["description"] = f"{existing['description']}；{description}"
                if source and source not in str(existing.get("source") or ""):
                    existing["source"] = f"{existing.get('source')},{source}"
                return
            route_by_date[day] = {
                "title": title,
                "description": description,
                "source": source,
                "date": day,
                "published_at": day,
            }

        ths_event = self._fetch_ths_summary_event(topic)
        if ths_event:
            event_date = self._extract_route_date(ths_event) or today
            put_daily_item(
                date=event_date,
                title="题材驱动",
                description=ths_event,
                source="ths_summary",
            )
        if summary:
            change_events = self._parse_change_events(summary.get("板块具体异动类型列表及出现次数"))[:5]
            event_text = "；".join(f"{item['label']}出现 {item['count']} 次" for item in change_events)
            description = self._build_hotspot_summary(topic, summary)
            if event_text:
                description = f"{description} 当日结构：{event_text}。"
            put_daily_item(
                date=today,
                title="当日发酵",
                description=description,
                source="eastmoney_board_change",
            )
        route = [
            route_by_date[date]
            for date in sorted(route_by_date.keys(), reverse=True)
        ]
        if not route:
            route.append({
                "title": "等待发酵",
                "description": "暂未获取到明确催化事件，可继续观察涨跌幅、成交额和核心个股联动。",
                "source": "fallback",
                "date": today,
                "published_at": today,
            })
        return route

    def _extract_route_date(self, text: str) -> str:
        match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text or "")
        if not match:
            return ""
        year, month, day = match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    def _parse_change_events(self, raw: Any) -> List[Dict[str, Any]]:
        if isinstance(raw, str):
            try:
                import ast

                raw = ast.literal_eval(raw)
            except Exception:
                raw = []
        events = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            event_type = int(_safe_float(item.get("t")) or 0)
            count = int(_safe_float(item.get("ct")) or 0)
            if not count:
                continue
            events.append({
                "type": event_type,
                "label": self._CHANGE_EVENT_LABELS.get(event_type, f"异动类型 {event_type}"),
                "count": count,
            })
        return sorted(events, key=lambda item: item["count"], reverse=True)

    def _fetch_ths_summary_event(self, topic: str) -> str:
        import akshare as ak

        try:
            df = ak.stock_board_concept_summary_ths()
        except Exception:
            return ""
        if df is None or df.empty:
            return ""
        if "概念名称" not in df.columns:
            logger.warning(
                "AlphaSift THS summary missing required column '概念名称'; skip enrichment.",
            )
            return ""
        rows = df[df["概念名称"].astype(str) == topic]
        if rows.empty:
            rows = df[df["概念名称"].astype(str).str.contains(re.escape(topic), case=False, na=False)]
        if rows.empty:
            return ""
        row = rows.iloc[0]
        date = _env_text(row.get("日期"))
        event = _env_text(row.get("驱动事件"))
        return f"{date}：{event}" if date and event else event

    def _fetch_ths_info(self, topic: str) -> Dict[str, str]:
        import akshare as ak

        try:
            df = ak.stock_board_concept_info_ths(symbol=topic)
        except Exception:
            return {}
        if df is None or df.empty or "项目" not in df.columns or "值" not in df.columns:
            return {}
        return {
            _env_text(row.get("项目")): _env_text(row.get("值"))
            for _, row in df.iterrows()
            if _env_text(row.get("项目"))
        }

    def _fetch_eastmoney_constituents(self, topic: str, *, source: str) -> Any:
        import akshare as ak

        try:
            if source == "industry":
                return ak.stock_board_industry_cons_em(symbol=topic)
            return ak.stock_board_concept_cons_em(symbol=topic)
        except Exception:
            return None

    def _fetch_ths_constituents(self, topic: str) -> Any:
        import pandas as pd
        import requests

        code = self._resolve_ths_concept_code(topic)
        if not code:
            return pd.DataFrame()
        url = f"http://q.10jqka.com.cn/gn/detail/code/{code}/"
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "http://q.10jqka.com.cn/gn/"},
            timeout=self._HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        html = response.content.decode("gbk", "ignore")
        rows = []
        seen = set()
        for match in re.finditer(r">(\d{6})<.*?>([^<>\n]{2,12})<", html, re.S):
            code_text = match.group(1)
            name_text = re.sub(r"\s+", "", match.group(2))
            if code_text in seen or not name_text or re.search(r"\d", name_text):
                continue
            seen.add(code_text)
            rows.append({"code": code_text, "name": name_text})
            if len(rows) >= 80:
                break
        return pd.DataFrame(rows)

    def _resolve_ths_concept_code(self, topic: str) -> str:
        import akshare as ak

        try:
            df = ak.stock_board_concept_name_ths()
        except Exception:
            return ""
        if df is None or df.empty:
            return ""
        rows = df[df["name"].astype(str) == topic]
        if rows.empty:
            rows = df[df["name"].astype(str).str.contains(re.escape(topic), case=False, na=False)]
        if rows.empty and topic.endswith("概念"):
            base = topic[:-2]
            rows = df[df["name"].astype(str).str.contains(re.escape(base), case=False, na=False)]
        if rows.empty:
            return ""
        return _env_text(rows.iloc[0].get("code"))

    def _fallback_constituents(self, topic: str) -> Any:
        import pandas as pd

        try:
            summary = self._find_board_change(topic)
        except Exception as exc:
            logger.warning(
                "AlphaSift board-change constituent fallback failed for %s; trying other sources: %s",
                topic,
                exc,
            )
            return pd.DataFrame()
        code = _env_text(summary.get("板块异动最频繁个股及所属类型-股票代码"))
        name = _env_text(summary.get("板块异动最频繁个股及所属类型-股票名称"))
        if not code and not name:
            return pd.DataFrame()
        return pd.DataFrame([{
            "code": code,
            "name": name,
            "change_pct": None,
            "hot_stock_score": 60.0,
        }])

    def _related_hotspot_constituents(self, topic: str) -> Any:
        import pandas as pd

        group = self._hotspot_group(topic)
        if not group:
            return pd.DataFrame()
        try:
            raw = self._fetch_board_changes_raw()
        except Exception:
            return pd.DataFrame()
        df = pd.DataFrame(raw)
        if df.empty:
            return pd.DataFrame()
        rows: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for _, row in df.iterrows():
            board_name = _env_text(row.get("板块名称"))
            if not board_name or self._hotspot_group(board_name) != group:
                continue
            code = _env_text(row.get("板块异动最频繁个股及所属类型-股票代码"))
            name = _env_text(row.get("板块异动最频繁个股及所属类型-股票名称"))
            if not code and not name:
                continue
            key = code or name
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "code": code,
                "name": name,
                "change_pct": _safe_float(row.get("涨跌幅")),
                "role": f"{group}活跃股",
                "hot_stock_score": 35.0,
                "source": "eastmoney_board_change.related_group",
            })
            if len(rows) >= 12:
                break
        return pd.DataFrame(rows)

    def _get_constituent_cache(self, source: str, topic: str) -> Any:
        import pandas as pd

        if not hasattr(self, "_constituent_cache"):
            self._constituent_cache = {}
        frame = self._constituent_cache.get((source, _env_text(topic)))
        if frame is None:
            return None
        return pd.DataFrame(frame).copy()

    def _set_constituent_cache(self, source: str, topic: str, frame: Any) -> None:
        import pandas as pd

        if not hasattr(self, "_constituent_cache"):
            self._constituent_cache = {}
        self._constituent_cache[(source, _env_text(topic))] = pd.DataFrame(frame).copy()

    def _merge_constituent_frames(self, frames: List[Any]) -> Any:
        import pandas as pd

        merged: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for frame in frames:
            df = pd.DataFrame(frame)
            if df.empty:
                continue
            for _, row in df.iterrows():
                code = _env_text(row.get("code") or row.get("代码") or row.get("证券代码"))
                name = _env_text(row.get("name") or row.get("名称") or row.get("股票名称"))
                if not code and not name:
                    continue
                key = code or name
                if key in seen:
                    continue
                seen.add(key)
                record = row.to_dict()
                record.setdefault("code", code)
                record.setdefault("name", name)
                merged.append(record)
        return pd.DataFrame(merged)

    def _enrich_constituent_quotes(self, stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        codes = [str(item.get("code") or "").strip() for item in stocks if item.get("code")]
        codes = [code for code in codes if code][:12]
        if len(codes) < 4:
            return stocks
        try:
            manager = _get_dsa_fetcher_manager()
            manager.prefetch_realtime_quotes(codes)
        except Exception as exc:
            logger.debug("AlphaSift hotspot quote prefetch skipped: %s", exc)
            return stocks
        quote_by_code: Dict[str, Any] = {}
        for code in codes:
            try:
                quote = manager.get_realtime_quote(code, log_final_failure=False)
            except Exception:
                quote = None
            if quote is not None:
                quote_by_code[code] = quote
        if not quote_by_code:
            return stocks
        enriched: List[Dict[str, Any]] = []
        for item in stocks:
            next_item = dict(item)
            code = str(next_item.get("code") or "").strip()
            quote = quote_by_code.get(code)
            if quote is not None:
                if next_item.get("change_pct") is None:
                    next_item["change_pct"] = _safe_float(getattr(quote, "change_pct", None))
                if next_item.get("amount") is None:
                    next_item["amount"] = _safe_float(getattr(quote, "amount", None))
                if next_item.get("turnover_rate") is None:
                    next_item["turnover_rate"] = _safe_float(getattr(quote, "turnover_rate", None))
                if next_item.get("volume_ratio") is None:
                    next_item["volume_ratio"] = _safe_float(getattr(quote, "volume_ratio", None))
                if next_item.get("hot_stock_score") in (None, 0.0):
                    next_item["hot_stock_score"] = min(99.0, max(1.0, abs(next_item.get("change_pct") or 0.0) * 8.0))
            enriched.append(next_item)
        return enriched

    def _normalize_constituent_records(self, frame: Any) -> List[Dict[str, Any]]:
        import pandas as pd

        df = pd.DataFrame(frame)
        if df.empty:
            return []
        records = []
        for _, row in df.iterrows():
            code = _env_text(row.get("code") or row.get("代码") or row.get("证券代码"))
            name = _env_text(row.get("name") or row.get("名称") or row.get("股票名称"))
            if not code and not name:
                continue
            records.append({
                "code": code,
                "name": name,
                "change_pct": _safe_float(row.get("change_pct") or row.get("涨跌幅") or row.get("涨幅")),
                "amount": _safe_float(row.get("amount") or row.get("成交额") or row.get("成交金额")),
                "turnover_rate": _safe_float(row.get("turnover_rate") or row.get("换手率")),
                "volume_ratio": _safe_float(row.get("volume_ratio") or row.get("量比")),
                "role": _env_text(row.get("role")) or "概念股",
                "hot_stock_score": _safe_float(row.get("hot_stock_score")) or 0.0,
            })
        return records


def _build_alphasift_context(config: Config, *, max_results: Optional[int] = None) -> Dict[str, Any]:
    # context.llm.model/fallback/model_list 与 LiteLLM 路由语义保持一致，
    # 参见 https://docs.litellm.ai/docs/proxy/configs#the-model_list-key
    channels = _normalize_dsa_llm_channels(config)
    litellm_model, fallback_models = _resolve_alphasift_llm_models(config)
    return {
        "llm": {
            "model": litellm_model,
            "fallback_models": fallback_models,
            "temperature": config.llm_temperature,
            "channels": channels,
            "model_list": _build_alphasift_litellm_model_list(config, channels),
            "litellm_config_path": config.litellm_config_path or "",
            "candidate_context_enabled": False,
            "candidate_multiplier": DSA_ALPHASIFT_LLM_CANDIDATE_MULTIPLIER,
            "max_candidates": _resolve_dsa_llm_max_candidates(max_results),
        },
        "dsa": {
            "contract_version": "1",
            "mode": "pre_rank_light",
            "max_candidates": DSA_PRE_RANK_CONTEXT_MAX_CANDIDATES,
            "include_news": False,
            "news_max_results": 0,
            "capabilities": [
                "candidate_context",
                "daily_history",
                "realtime_quote",
                "fundamental_context",
            ],
            "get_candidate_context": get_dsa_candidate_context,
            "get_daily_history": get_dsa_daily_history,
            "get_realtime_quote": get_dsa_realtime_quote,
            "get_fundamental_context": get_dsa_fundamental_context,
        },
    }

@contextmanager
def _alphasift_litellm_headers(config: Config) -> Iterator[None]:
    header_routes = _build_alphasift_litellm_header_routes(config)
    if not header_routes:
        yield
        return

    try:
        litellm_module = importlib.import_module("litellm")
    except Exception:
        yield
        return

    completion = getattr(litellm_module, "completion", None)
    if not callable(completion):
        yield
        return

    bridge_completion = getattr(completion, _ALPHASIFT_LITELLM_COMPLETION_ATTR, None)
    if bridge_completion:
        token = _ALPHASIFT_LITELLM_COMPLETION_ROUTES.set(
            tuple(route.copy() for route in header_routes),
        )
        try:
            yield
        finally:
            _ALPHASIFT_LITELLM_COMPLETION_ROUTES.reset(token)
        return

    original_completion = completion

    def completion_with_dsa_headers(*args: Any, **kwargs: Any) -> Any:
        routes = _ALPHASIFT_LITELLM_COMPLETION_ROUTES.get()
        if routes:
            headers = _match_alphasift_litellm_headers(args, kwargs, routes)
            if headers:
                existing_headers = kwargs.get("extra_headers")
                if isinstance(existing_headers, dict):
                    merged_headers = dict(headers)
                    merged_headers.update(existing_headers)
                    kwargs = dict(kwargs)
                    kwargs["extra_headers"] = merged_headers
                elif existing_headers in (None, ""):
                    kwargs = dict(kwargs)
                    kwargs["extra_headers"] = dict(headers)
        return original_completion(*args, **kwargs)

    setattr(completion_with_dsa_headers, _ALPHASIFT_LITELLM_COMPLETION_ATTR, True)
    setattr(completion_with_dsa_headers, "_alphasift_litellm_completion_original", original_completion)
    completion_with_dsa_headers.__name__ = "completion_with_dsa_headers"

    if completion is not completion_with_dsa_headers:
        with _ALPHASIFT_LITELLM_COMPLETION_LOCK:
            if not getattr(getattr(litellm_module, "completion", None), _ALPHASIFT_LITELLM_COMPLETION_ATTR, False):
                setattr(litellm_module, "completion", completion_with_dsa_headers)

    token = _ALPHASIFT_LITELLM_COMPLETION_ROUTES.set(
        tuple(route.copy() for route in header_routes),
    )
    try:
        yield
    finally:
        _ALPHASIFT_LITELLM_COMPLETION_ROUTES.reset(token)


def _build_alphasift_litellm_model_list(config: Config, channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    explicit_model_list = _to_plain(config.llm_model_list or [])
    if isinstance(explicit_model_list, list) and explicit_model_list:
        return explicit_model_list
    return _channel_litellm_model_list(channels)


def _channel_litellm_model_list(channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    model_list_builder = getattr(Config, "_channels_to_model_list", None)
    if callable(model_list_builder):
        return _to_plain(model_list_builder(channels))

    model_list: List[Dict[str, Any]] = []
    for channel in channels:
        headers = dict(channel.get("extra_headers") or {})
        base_url = _env_text(channel.get("base_url"))
        for model_name in channel.get("models") or []:
            for api_key in channel.get("api_keys") or []:
                litellm_params: Dict[str, Any] = {"model": model_name}
                if api_key:
                    litellm_params["api_key"] = api_key
                if base_url:
                    litellm_params["api_base"] = base_url
                if headers:
                    litellm_params["extra_headers"] = dict(headers)
                model_list.append({"model_name": model_name, "litellm_params": litellm_params})
    return model_list


def _build_alphasift_litellm_header_routes(config: Config) -> List[Dict[str, Any]]:
    channels = _normalize_dsa_llm_channels(config)
    model_list = _build_alphasift_litellm_model_list(config, channels)
    routes: List[Dict[str, Any]] = []
    for entry in model_list:
        if not isinstance(entry, dict):
            continue
        params = entry.get("litellm_params") or {}
        if not isinstance(params, dict):
            continue
        headers = params.get("extra_headers")
        if not isinstance(headers, dict) or not headers:
            continue
        model_names = _dedupe_strings([
            entry.get("model_name"),
            params.get("model"),
        ])
        if not model_names:
            continue
        routes.append(
            {
                "models": model_names,
                "api_key": _env_text(params.get("api_key")),
                "api_base": _env_text(params.get("api_base") or params.get("base_url")),
                "extra_headers": dict(headers),
            }
        )
    return routes


def _match_alphasift_litellm_headers(
    args: Tuple[Any, ...],
    kwargs: Dict[str, Any],
    routes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    model = _env_text(kwargs.get("model"))
    if not model and args:
        model = _env_text(args[0])
    if not model:
        return {}

    api_key = _env_text(kwargs.get("api_key"))
    api_base = _env_text(kwargs.get("api_base") or kwargs.get("base_url"))
    for route in routes:
        if model not in set(route.get("models") or []):
            continue
        route_api_key = _env_text(route.get("api_key"))
        if route_api_key and api_key and route_api_key != api_key:
            continue
        route_api_base = _env_text(route.get("api_base"))
        if route_api_base and api_base and route_api_base != api_base:
            continue
        headers = route.get("extra_headers")
        return dict(headers) if isinstance(headers, dict) else {}
    return {}


def _resolve_dsa_llm_max_candidates(max_results: Optional[int]) -> int:
    requested = max_results if isinstance(max_results, int) and max_results > 0 else DSA_ENRICHMENT_MAX_CANDIDATES
    return min(
        DSA_ALPHASIFT_LLM_MAX_CANDIDATES,
        max(requested, requested * DSA_ALPHASIFT_LLM_CANDIDATE_MULTIPLIER),
    )


def _resolve_alphasift_llm_models(config: Config) -> Tuple[str, List[str]]:
    primary = _env_text(config.litellm_model)
    configured_models = get_configured_llm_models(config.llm_model_list or [])
    configured_model_set = set(configured_models)

    if configured_models and (
        not primary or (primary not in configured_model_set and _is_managed_litellm_model(primary))
    ):
        primary = configured_models[0]

    raw_fallbacks = _dedupe_strings(config.litellm_fallback_models or [])
    if not configured_models:
        return primary, [model for model in raw_fallbacks if model != primary]

    fallback_models: List[str] = []
    seen = {primary} if primary else set()

    for model in raw_fallbacks:
        if model in seen:
            continue
        if model in configured_model_set or not _is_managed_litellm_model(model):
            fallback_models.append(model)
            seen.add(model)

    for model in configured_models:
        if model and model not in seen:
            fallback_models.append(model)
            seen.add(model)

    return primary, fallback_models


def _is_managed_litellm_model(model: str) -> bool:
    text = _env_text(model)
    if not text:
        return False
    provider = text.split("/", 1)[0].lower() if "/" in text else "openai"
    return provider in ALPHASIFT_MANAGED_LITELLM_PROVIDERS


def _normalize_dsa_llm_channels(config: Config) -> List[Dict[str, Any]]:
    channels: List[Dict[str, Any]] = []
    for index, raw in enumerate(config.llm_channels or []):
        if not isinstance(raw, dict):
            continue
        name = _env_text(raw.get("name")) or f"channel{index + 1}"
        api_keys = _dedupe_strings(raw.get("api_keys") if isinstance(raw.get("api_keys"), list) else [])
        models = _dedupe_strings(raw.get("models") if isinstance(raw.get("models"), list) else [])
        channel = {
            "name": name,
            "protocol": _env_text(raw.get("protocol")),
            "base_url": _env_text(raw.get("base_url")),
            "api_keys": api_keys,
            "models": models,
            "extra_headers": raw.get("extra_headers") if isinstance(raw.get("extra_headers"), dict) else {},
            "enabled": bool(raw.get("enabled", True)),
        }
        if channel["enabled"] and (api_keys or models or channel["base_url"] or channel["extra_headers"]):
            channels.append(channel)
    return channels


def _channel_keys_for_provider(channels: List[Dict[str, Any]], providers: set[str]) -> List[str]:
    keys: List[str] = []
    for channel in channels:
        protocol = _env_text(channel.get("protocol")).lower()
        models = channel.get("models") or []
        model_providers = {
            str(model).split("/", 1)[0].lower()
            for model in models
            if isinstance(model, str) and "/" in model
        }
        if protocol in providers or model_providers.intersection(providers):
            keys.extend(channel.get("api_keys") or [])
    return keys


def _first_channel_base_url(channels: List[Dict[str, Any]], providers: set[str]) -> str:
    for channel in channels:
        protocol = _env_text(channel.get("protocol")).lower()
        base_url = _env_text(channel.get("base_url"))
        if base_url and protocol in providers:
            return base_url
    return ""


def _put_provider_keys(env: Dict[str, str], provider: str, keys: List[str]) -> None:
    if not keys:
        return
    env[f"{provider}_API_KEYS"] = ",".join(keys)
    env[f"{provider}_API_KEY"] = keys[0]


def _dedupe_strings(values: Any) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    if not isinstance(values, list):
        return result
    for value in values:
        text = _env_text(value)
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _env_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def _get_dsa_fetcher_manager() -> Any:
    global _DSA_FETCHER_MANAGER
    if _DSA_FETCHER_MANAGER is None:
        with _DSA_FETCHER_MANAGER_LOCK:
            if _DSA_FETCHER_MANAGER is None:
                from data_provider import DataFetcherManager

                _DSA_FETCHER_MANAGER = DataFetcherManager()
    return _DSA_FETCHER_MANAGER


def _get_dsa_search_service() -> Any:
    from src.search_service import get_search_service

    return get_search_service()


def get_dsa_daily_history(stock_code: str, *, lookback_days: int = 120) -> Tuple[Any, str]:
    from src.services.history_loader import load_history_df

    normalized_code = _env_text(stock_code).zfill(6)
    days = max(int(lookback_days or 0), 30)
    return load_history_df(normalized_code, days=days)


def _normalize_dsa_daily_history(raw_df: Any) -> Any:
    if raw_df is None:
        return None

    import pandas as pd

    df = pd.DataFrame(raw_df).copy()
    if df.empty:
        return df

    aliases = {
        "date": ("date", "trade_date", "datetime", "日期"),
        "open": ("open", "开盘"),
        "high": ("high", "最高"),
        "low": ("low", "最低"),
        "close": ("close", "收盘", "price"),
        "volume": ("volume", "vol", "成交量"),
        "amount": ("amount", "成交额"),
    }
    normalized = pd.DataFrame(index=df.index)
    for target, candidates in aliases.items():
        source_column = next((column for column in candidates if column in df.columns), None)
        if source_column is not None:
            normalized[target] = df[source_column]

    if "close" not in normalized.columns:
        return pd.DataFrame()
    for column in ("open", "high", "low"):
        if column not in normalized.columns:
            normalized[column] = normalized["close"]
    if "volume" not in normalized.columns:
        normalized["volume"] = 0

    if "date" in normalized.columns:
        normalized["date"] = normalized["date"].map(_normalize_daily_date_value)

    for column in ("open", "high", "low", "close", "volume", "amount"):
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized = normalized.dropna(subset=["close"])
    return normalized.reset_index(drop=True)


def _normalize_daily_date_value(value: Any) -> str:
    text = _env_text(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def get_dsa_realtime_quote(stock_code: str) -> Dict[str, Any]:
    manager = _get_dsa_fetcher_manager()
    quote = manager.get_realtime_quote(stock_code, log_final_failure=False)
    if quote is None:
        return {}
    if hasattr(quote, "to_dict") and callable(quote.to_dict):
        return _remove_non_finite_json_values(quote.to_dict())
    payload = _to_plain(quote)
    return _remove_non_finite_json_values(payload if isinstance(payload, dict) else {})


def get_dsa_fundamental_context(stock_code: str) -> Dict[str, Any]:
    manager = _get_dsa_fetcher_manager()
    context = manager.get_fundamental_context(stock_code, budget_seconds=4.0)
    return _compact_fundamental_context(_remove_non_finite_json_values(_to_plain(context)))


def search_dsa_stock_news(stock_code: str, stock_name: str = "", max_results: int = 3) -> Dict[str, Any]:
    service = _get_dsa_search_service()
    if not getattr(service, "is_available", False):
        return {
            "success": False,
            "error": "DSA search service unavailable",
            "results": [],
        }

    response = service.search_stock_news(stock_code, stock_name or stock_code, max_results=max_results)
    results = []
    for item in getattr(response, "results", []) or []:
        results.append(
            {
                "title": getattr(item, "title", ""),
                "snippet": getattr(item, "snippet", ""),
                "url": getattr(item, "url", ""),
                "source": getattr(item, "source", ""),
                "published_date": getattr(item, "published_date", None),
            }
        )
    return _remove_non_finite_json_values(
        {
            "query": getattr(response, "query", ""),
            "provider": getattr(response, "provider", ""),
            "success": bool(getattr(response, "success", False)),
            "error": getattr(response, "error_message", None),
            "results": results,
        }
    )


def get_dsa_candidate_context(
    stock_code: str,
    stock_name: str = "",
    *,
    include_news: bool = False,
    include_fundamentals: bool = True,
    mode: str = "pre_rank_light",
) -> Dict[str, Any]:
    candidate = {"code": stock_code, "name": stock_name, "raw": {}}
    context = _build_dsa_candidate_context(
        candidate,
        include_news=include_news,
        include_fundamentals=include_fundamentals,
        profile=mode or "pre_rank_light",
    )
    return context.get("dsa_context", {})


def _enrich_candidates_with_dsa(candidates: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    enriched_count = 0
    warnings: List[str] = []
    limit = min(len(candidates), DSA_ENRICHMENT_MAX_CANDIDATES)

    for index, candidate in enumerate(candidates):
        if index >= limit:
            continue
        existing_context = candidate.get("dsa_context")
        if (
            isinstance(existing_context, dict)
            and existing_context.get("enriched")
            and _candidate_has_dsa_news(candidate)
        ):
            enriched_count += 1
            existing_warnings = existing_context.get("warnings") or []
            if isinstance(existing_warnings, list):
                warnings.extend(str(item) for item in existing_warnings if item)
            elif existing_warnings:
                warnings.append(str(existing_warnings))
            continue
        try:
            enriched = _build_dsa_candidate_context(
                candidate,
                include_news=True,
                include_fundamentals=True,
                profile="post_rank_full",
            )
            candidate.update(enriched)
            if enriched.get("dsa_context", {}).get("enriched"):
                enriched_count += 1
            warnings.extend(enriched.get("dsa_context", {}).get("warnings") or [])
        except Exception as exc:  # noqa: BLE001 - DSA enrichment must not block screening.
            code = candidate.get("code") or f"rank-{candidate.get('rank', index + 1)}"
            message = f"{code}: {exc}"
            warnings.append(message)
            logger.warning("DSA enrichment failed for AlphaSift candidate %s: %s", code, exc)
            candidate["dsa_context"] = {
                "enriched": False,
                "warnings": [message],
            }

    return candidates, {
        "enabled": True,
        "max_candidates": DSA_ENRICHMENT_MAX_CANDIDATES,
        "requested_count": limit,
        "enriched_count": enriched_count,
        "warnings": _dedupe_strings(warnings),
    }


def _candidate_has_dsa_news(candidate: Dict[str, Any]) -> bool:
    news_items = candidate.get("dsa_news")
    if isinstance(news_items, list) and any(isinstance(item, dict) for item in news_items):
        return True
    context = candidate.get("dsa_context")
    if not isinstance(context, dict):
        return False
    return _news_has_results(context.get("news"))


def _news_has_results(news: Any) -> bool:
    if isinstance(news, dict):
        results = news.get("results")
        return isinstance(results, list) and any(isinstance(item, dict) for item in results)
    if isinstance(news, list):
        return any(isinstance(item, dict) for item in news)
    return False


def _build_dsa_candidate_context(
    candidate: Dict[str, Any],
    *,
    include_news: bool = True,
    include_fundamentals: bool = True,
    profile: str = "post_rank_full",
) -> Dict[str, Any]:
    code = _env_text(candidate.get("code"))
    name = _env_text(candidate.get("name"))
    warnings: List[str] = []
    if not code:
        return {
            "dsa_context": {
                "enriched": False,
                "warnings": ["missing candidate code"],
            }
        }

    existing_context = candidate.get("dsa_context")
    if not isinstance(existing_context, dict):
        existing_context = {}

    quote = existing_context.get("quote") if isinstance(existing_context.get("quote"), dict) else {}
    fundamentals = (
        existing_context.get("fundamentals")
        if isinstance(existing_context.get("fundamentals"), dict)
        else {}
    )
    existing_news = existing_context.get("news") if isinstance(existing_context.get("news"), dict) else {}
    news: Dict[str, Any] = dict(existing_news) if existing_news else {"success": False, "results": []}
    existing_warnings = existing_context.get("warnings") or []
    if isinstance(existing_warnings, list):
        warnings.extend(str(item) for item in existing_warnings if item)
    elif existing_warnings:
        warnings.append(str(existing_warnings))

    try:
        manager = _get_dsa_fetcher_manager()
        resolved_name = manager.get_stock_name(code, allow_realtime=False)
        if resolved_name and (not name or name == code):
            name = resolved_name
            candidate["name"] = resolved_name
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"stock_name_failed: {exc}")

    if not quote:
        try:
            quote = get_dsa_realtime_quote(code)
            if not quote:
                warnings.append("realtime_quote_missing")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"realtime_quote_failed: {exc}")
            quote = {}

    if quote:
        candidate["price"] = _first_non_empty(candidate.get("price"), quote.get("price"))
        candidate["change_pct"] = _first_non_empty(candidate.get("change_pct"), quote.get("change_pct"))
        candidate["amount"] = _first_non_empty(candidate.get("amount"), quote.get("amount"))
        if not candidate.get("name") and quote.get("name"):
            candidate["name"] = quote.get("name")

    if include_fundamentals and not fundamentals:
        try:
            fundamentals = get_dsa_fundamental_context(code)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"fundamental_context_failed: {exc}")
            fundamentals = {}

    if include_news:
        if not _news_has_results(news):
            try:
                news = search_dsa_stock_news(code, _env_text(candidate.get("name")) or name or code, max_results=3)
                if not news.get("success"):
                    warnings.append(news.get("error") or "stock_news_unavailable")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"stock_news_failed: {exc}")
                news = {"success": False, "error": str(exc), "results": []}
    elif not _news_has_results(news):
        news = {
            "success": False,
            "skipped": True,
            "reason": "pre_rank_light_context",
            "results": [],
        }

    summary = _build_dsa_analysis_summary(candidate, quote, fundamentals, news)
    context = {
        "enriched": bool(quote or fundamentals or news.get("results")),
        "profile": profile,
        "news_included": bool(include_news),
        "quote": quote,
        "fundamentals": fundamentals,
        "news": news,
        "warnings": _dedupe_strings(warnings),
    }
    return {
        "dsa_context": context,
        "dsa_news": news.get("results") or [],
        "dsa_analysis_summary": summary,
    }


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _compact_fundamental_context(context: Any) -> Dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    compact: Dict[str, Any] = {
        "market": context.get("market"),
        "status": context.get("status"),
        "coverage": context.get("coverage") if isinstance(context.get("coverage"), dict) else {},
    }
    for block in _FUNDAMENTAL_BLOCKS:
        payload = context.get(block)
        if isinstance(payload, dict):
            compact[block] = {
                "status": payload.get("status"),
                "data": payload.get("data") if isinstance(payload.get("data"), dict) else {},
            }
    errors = context.get("errors")
    if isinstance(errors, list) and errors:
        compact["errors"] = [str(item) for item in errors[:3]]
    return compact


def _build_dsa_analysis_summary(
    candidate: Dict[str, Any],
    quote: Dict[str, Any],
    fundamentals: Dict[str, Any],
    news: Dict[str, Any],
) -> str:
    parts: List[str] = []
    price = _first_non_empty(quote.get("price"), candidate.get("price"))
    change_pct = _first_non_empty(quote.get("change_pct"), candidate.get("change_pct"))
    if price is not None:
        text = f"DSA行情：现价 {price}"
        if change_pct is not None:
            text += f"，涨跌幅 {change_pct}%"
        parts.append(text)

    coverage = fundamentals.get("coverage") if isinstance(fundamentals, dict) else {}
    if isinstance(coverage, dict) and coverage:
        available_blocks = [key for key, value in coverage.items() if str(value).lower() in {"available", "partial"}]
        if available_blocks:
            parts.append(f"DSA基本面覆盖：{', '.join(available_blocks[:4])}")

    news_results = news.get("results") if isinstance(news, dict) else []
    if isinstance(news_results, list) and news_results:
        titles = [str(item.get("title") or "").strip() for item in news_results if isinstance(item, dict)]
        titles = [title for title in titles if title]
        if titles:
            parts.append(f"DSA新闻：{'；'.join(titles[:2])}")

    if not parts:
        return ""
    return "；".join(parts)


def _ensure_supported_market(market: str) -> None:
    status = _call_alphasift_status()
    supported_markets = status.get("supported_markets") or status.get("markets") or status.get("market")
    if not supported_markets:
        return

    normalized: List[Any]
    if isinstance(supported_markets, str):
        normalized = [supported_markets]
    elif isinstance(supported_markets, (list, tuple, set)):
        normalized = list(supported_markets)
    else:
        normalized = []

    if market not in normalized:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "alphasift_invalid_market",
                "message": (
                    f"市场 {market} 不在 AlphaSift 适配层支持范围内"
                    f"（支持市场：{', '.join(map(str, normalized)) or '未知'}）。"
                ),
            },
        )


def _normalize_candidates(raw: Any) -> List[Dict[str, Any]]:
    data = _to_plain(raw)
    items = data
    if isinstance(data, dict):
        for key in ("candidates", "picks", "items", "results", "stocks"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
    if not isinstance(items, list):
        return []
    return [_normalize_candidate(item, index + 1) for index, item in enumerate(items)]


def _normalize_candidate(raw: Any, rank: int) -> Dict[str, Any]:
    item = _remove_non_finite_json_values(_to_plain(raw))
    if not isinstance(item, dict):
        item = {"code": str(item)}
    source = item.get("raw") if isinstance(item.get("raw"), dict) else item
    dsa_context = item.get("dsa_context") or source.get("dsa_context") or {}
    dsa_news = item.get("dsa_news") or source.get("dsa_news") or _extract_dsa_news_from_context(dsa_context)
    dsa_analysis_summary = (
        item.get("dsa_analysis_summary")
        or source.get("dsa_analysis_summary")
        or _extract_dsa_analysis_summary_from_context(dsa_context)
    )
    return {
        "rank": item.get("rank") or source.get("rank") or rank,
        "code": item.get("code") or source.get("code") or item.get("symbol") or source.get("symbol") or item.get("stock_code") or source.get("stock_code") or "",
        "name": item.get("name") or source.get("name") or item.get("stock_name") or source.get("stock_name") or "",
        "score": _first_present(item, source, "score", "final_score"),
        "screen_score": _first_present(item, source, "screen_score"),
        "reason": item.get("reason") or source.get("reason") or source.get("ranking_reason") or source.get("risk_summary") or item.get("summary") or _build_candidate_reason(source),
        "risk_level": item.get("risk_level") or source.get("risk_level") or "",
        "risk_flags": item.get("risk_flags") or source.get("risk_flags") or [],
        "llm_score": _first_present(item, source, "llm_score"),
        "llm_confidence": _first_present(item, source, "llm_confidence"),
        "llm_sector": item.get("llm_sector") or source.get("llm_sector") or "",
        "llm_theme": item.get("llm_theme") or source.get("llm_theme") or "",
        "llm_tags": item.get("llm_tags") or source.get("llm_tags") or [],
        "llm_thesis": item.get("llm_thesis") or source.get("llm_thesis") or "",
        "llm_catalysts": item.get("llm_catalysts") or source.get("llm_catalysts") or [],
        "llm_risks": item.get("llm_risks") or source.get("llm_risks") or [],
        "llm_watch_items": item.get("llm_watch_items") or source.get("llm_watch_items") or [],
        "llm_invalidators": item.get("llm_invalidators") or source.get("llm_invalidators") or [],
        "llm_style_fit": item.get("llm_style_fit") or source.get("llm_style_fit") or "",
        "price": _first_present(item, source, "price"),
        "change_pct": _first_present(item, source, "change_pct"),
        "amount": _first_present(item, source, "amount"),
        "industry": item.get("industry") or source.get("industry") or "",
        "factor_scores": item.get("factor_scores") or source.get("factor_scores") or {},
        "dsa_context": dsa_context,
        "dsa_news": dsa_news,
        "dsa_analysis_summary": dsa_analysis_summary,
        "post_analysis_summaries": item.get("post_analysis_summaries") or source.get("post_analysis_summaries") or {},
        "post_analysis_tags": item.get("post_analysis_tags") or source.get("post_analysis_tags") or [],
        "raw": source,
    }


def _extract_dsa_news_from_context(context: Any) -> List[Dict[str, Any]]:
    if not isinstance(context, dict):
        return []
    news = context.get("news")
    if isinstance(news, dict):
        results = news.get("results")
    elif isinstance(news, list):
        results = news
    else:
        results = None
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


def _extract_dsa_analysis_summary_from_context(context: Any) -> str:
    if not isinstance(context, dict):
        return ""
    for key in ("dsa_analysis_summary", "analysis_summary", "summary"):
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            return value
    news = context.get("news")
    if isinstance(news, dict):
        for key in ("analysis_summary", "summary"):
            value = news.get(key)
            if isinstance(value, str) and value.strip():
                return value
    news_items = _extract_dsa_news_from_context(context)
    if not news_items:
        return ""
    quote = context.get("quote") if isinstance(context.get("quote"), dict) else {}
    fundamentals = context.get("fundamentals") if isinstance(context.get("fundamentals"), dict) else {}
    return _build_dsa_analysis_summary({}, quote, fundamentals, {"results": news_items})


def _first_present(primary: Dict[str, Any], source: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if primary.get(key) is not None:
            return primary.get(key)
        if source.get(key) is not None:
            return source.get(key)
    return None


def _build_candidate_reason(item: Dict[str, Any]) -> str:
    summaries = item.get("post_analysis_summaries")
    if isinstance(summaries, dict):
        summary = next((str(value) for value in summaries.values() if value), "")
        if summary:
            return summary

    factors = item.get("factor_scores")
    parts: List[str] = []
    if isinstance(factors, dict) and factors:
        top_factors = sorted(
            ((key, value) for key, value in factors.items() if isinstance(value, (int, float))),
            key=lambda pair: pair[1],
            reverse=True,
        )[:3]
        if top_factors:
            factor_text = "、".join(f"{key} {value:.1f}" for key, value in top_factors)
            parts.append(f"主要因子：{factor_text}")
    if item.get("industry"):
        parts.append(f"行业：{item['industry']}")
    if item.get("risk_level"):
        parts.append(f"风险等级：{item['risk_level']}")
    return "；".join(parts)


def _to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    if isinstance(value, list):
        return [_to_plain(item) for item in value]
    return value


def _remove_non_finite_json_values(value: Any) -> Any:
    if isinstance(value, list):
        return [_remove_non_finite_json_values(item) for item in value]
    if isinstance(value, tuple):
        return [_remove_non_finite_json_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _remove_non_finite_json_values(item) for key, item in value.items()}
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _build_install_response(already_installed: bool, install_spec_is_default: bool) -> Dict[str, Any]:
    return {
        "installed": True,
        "already_installed": already_installed,
        "install_spec_is_default": install_spec_is_default,
    }


def _is_default_alphasift_install_spec(install_spec: str) -> bool:
    return (install_spec or "").strip() == DEFAULT_ALPHASIFT_INSTALL_SPEC
