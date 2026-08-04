# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""L2 LLM ranker — relative ranking of shortlisted candidates."""

import copy
import json
import logging
import os
from dataclasses import dataclass

from src.llm.errors import call_litellm_with_param_recovery
from src.llm.generation_params import apply_litellm_generation_params
from src.services.screening.models import Pick
from src.services.screening.normalize import (
    bounded_float as _bounded_float,
    normalize_code,
    safe_string_list as _safe_string_list,
    safe_text,
)


def _normalize_code(value: object) -> str:
    # Candidate codes and LLM ranking JSON code fields are structured, so
    # US tickers may pass through (see normalize_code docstring).
    return normalize_code(value, allow_ticker=True)

logger = logging.getLogger(__name__)
_DEFAULT_RANKING_PROMPT_MAX_CHARS = 24_000
_PROMPT_TRIM_MARKER = "[prompt_trimmed]"


@dataclass
class RankingParseResult:
    picks: list[Pick]
    coverage: float
    errors: list[str]
    market_view: str = ""
    selection_logic: str = ""
    portfolio_risk: str = ""


@dataclass
class LLMRankingResult:
    picks: list[Pick]
    ranked: bool = False
    market_view: str = ""
    selection_logic: str = ""
    portfolio_risk: str = ""
    coverage: float = 0.0
    errors: list[str] | None = None
    model_used: str = ""
    attempted_models: list[str] | None = None
    failure_reason: str = ""

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []
        if self.attempted_models is None:
            self.attempted_models = []


def rank_candidates(
    candidates: list[Pick],
    ranking_hints: str,
    llm_api_key: str,
    llm_model: str,
    llm_base_url: str = "",
    *,
    context: str = "",
    rank_weight: float = 0.40,
    max_retries: int = 1,
    min_coverage: float = 0.60,
    fallback_models: list[str] | None = None,
    temperature: float = 0.2,
    json_mode: bool = True,
    silent: bool = True,
    channels: list[dict[str, object]] | None = None,
    config_path: str = "",
    timeout_sec: float = 60.0,
    max_prompt_chars: int | None = _DEFAULT_RANKING_PROMPT_MAX_CHARS,
    max_tokens: int | None = 2048,
) -> list[Pick]:
    """Use LLM to re-rank candidates and add ranking_reason / risk_summary.

    Falls back to screen_score order if LLM call fails.
    """
    return rank_candidates_with_metadata(
        candidates,
        ranking_hints,
        llm_api_key,
        llm_model,
        llm_base_url,
        context=context,
        rank_weight=rank_weight,
        max_retries=max_retries,
        min_coverage=min_coverage,
        fallback_models=fallback_models,
        temperature=temperature,
        json_mode=json_mode,
        silent=silent,
        channels=channels,
        config_path=config_path,
        timeout_sec=timeout_sec,
        max_prompt_chars=max_prompt_chars,
        max_tokens=max_tokens,
    ).picks


def rank_candidates_with_metadata(
    candidates: list[Pick],
    ranking_hints: str,
    llm_api_key: str,
    llm_model: str,
    llm_base_url: str = "",
    *,
    context: str = "",
    rank_weight: float = 0.40,
    max_retries: int = 1,
    min_coverage: float = 0.60,
    fallback_models: list[str] | None = None,
    temperature: float = 0.2,
    json_mode: bool = True,
    silent: bool = True,
    channels: list[dict[str, object]] | None = None,
    config_path: str = "",
    timeout_sec: float = 60.0,
    max_prompt_chars: int | None = _DEFAULT_RANKING_PROMPT_MAX_CHARS,
    degradation: list[str] | None = None,
    max_tokens: int | None = 2048,
) -> LLMRankingResult:
    """Use LLM to re-rank candidates and return global research metadata."""
    if not candidates:
        return LLMRankingResult(picks=candidates)

    prompt = _build_ranking_prompt(
        candidates,
        ranking_hints,
        context,
        max_chars=max_prompt_chars,
        degradation=degradation,
    )

    model_chain = _dedupe([llm_model, *(fallback_models or [])])
    attempted_models: list[str] = []
    all_errors: list[str] = []
    last_coverage = 0.0
    failure_reason = "no_model_configured"

    for candidate_model in model_chain:
        attempted_models.append(candidate_model)
        model_errors: list[str] = []
        for attempt in range(max_retries + 1):
            attempt_prompt = prompt
            if attempt:
                attempt_prompt += (
                    "\n\n上一次输出没有满足结构化覆盖率要求。"
                    "请重新返回严格 JSON，并覆盖尽可能多的候选代码。"
                )
            try:
                # Keep transport/provider retries scoped to one model here. A
                # syntactically successful but unusable response must also
                # advance to the configured fallback model chain.
                response = _call_llm(
                    attempt_prompt,
                    llm_api_key,
                    candidate_model,
                    llm_base_url,
                    fallback_models=[],
                    temperature=temperature,
                    json_mode=json_mode,
                    silent=silent,
                    channels=channels or [],
                    config_path=config_path,
                    timeout_sec=timeout_sec,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                failure_reason = "timeout" if _is_timeout_error(exc) else "call_failed"
                model_errors.append(f"{failure_reason}:{exc.__class__.__name__}")
                break

            parsed = _parse_ranking_response_detail(response, candidates)
            last_coverage = parsed.coverage
            model_errors.extend(parsed.errors)
            if parsed.coverage < min_coverage:
                failure_reason = "invalid_response"
                continue

            ranked = parsed.picks
            for i, pick in enumerate(ranked):
                pick.rank = i + 1
                if pick.llm_score is None:
                    pick.llm_score = 100.0 - i * (100.0 / max(len(ranked), 1))
                weight = min(max(rank_weight, 0.0), 1.0)
                pick.final_score = pick.screen_score * (1 - weight) + (pick.llm_score or 0) * weight
            ranked.sort(key=lambda item: item.final_score, reverse=True)
            for i, pick in enumerate(ranked, start=1):
                pick.rank = i
            return LLMRankingResult(
                picks=ranked,
                ranked=True,
                market_view=parsed.market_view,
                selection_logic=parsed.selection_logic,
                portfolio_risk=parsed.portfolio_risk,
                coverage=parsed.coverage,
                errors=parsed.errors,
                model_used=candidate_model,
                attempted_models=attempted_models,
            )

        all_errors.extend(f"{candidate_model}:{error}" for error in _dedupe(model_errors))
        logger.warning(
            "LLM ranking model=%s returned no usable ranking; trying next fallback; errors=%s",
            candidate_model,
            model_errors,
        )

    logger.warning(
        "LLM ranking failed after models=%s; reason=%s; coverage=%.2f; errors=%s",
        attempted_models,
        failure_reason,
        last_coverage,
        all_errors,
    )
    return LLMRankingResult(
        picks=candidates,
        coverage=last_coverage,
        errors=_dedupe(all_errors),
        attempted_models=attempted_models,
        failure_reason=failure_reason,
    )


def _build_ranking_prompt(
    candidates: list[Pick],
    hints: str,
    context: str = "",
    *,
    max_chars: int | None = _DEFAULT_RANKING_PROMPT_MAX_CHARS,
    degradation: list[str] | None = None,
) -> str:
    hints_text = hints.strip() or "无额外排序提示。"
    context_text = context.strip() or "无额外上下文。只能基于候选池结构化数据和策略偏好判断。"
    candidates_text = "\n".join(_format_candidate_for_prompt(p) for p in candidates)
    prompt = _render_ranking_prompt(hints_text, context_text, candidates_text)
    if max_chars is None or len(prompt) <= max_chars:
        return prompt
    return _build_bounded_ranking_prompt(
        candidates,
        hints_text,
        context_text,
        max_chars=max_chars,
        degradation=degradation,
    )


def _render_ranking_prompt(hints: str, context: str, candidates_text: str) -> str:
    return f"""你是一个专业的股票研究员，任务是在“已经由代码硬筛过”的候选池内做相对排序。
你不能推荐候选池外股票，不能修改硬筛条件，不能给目标价或承诺收益。你的价值在于：
1. 结合策略偏好，对候选之间做跨股票比较；
2. 识别结构化数据暴露不出的潜在催化、风格匹配和风险点；
3. 对行业/概念热度和 DSA 补充的行情、基本面、新闻做语义归因，但不能把单日热度当作唯一买入理由；
4. 给出简短、可审计、可复核的排序理由。

## 排序依据
{hints}

## 市场/情报上下文
{context}

## 候选列表
{candidates_text}

## 输出要求
只返回 JSON，不要 Markdown，不要解释 JSON 以外的文本。
格式：
{{
  "market_view": "一句话概括当前候选池和市场背景是否适合该策略",
  "selection_logic": "说明本次排序最主要的2-3个判断维度",
  "portfolio_risk": "说明最终名单可能存在的集中风险或共同风险",
  "ranked": [
    {{
      "code": "股票代码",
      "llm_score": 0-100,
      "confidence": 0-1,
      "sector": "行业/主题短标签，优先参考候选的 industry/concepts，并尽量统一，如 券商、银行、医药、AI算力",
      "theme": "主要交易逻辑或主题",
      "thesis": "该候选入选的核心投资假设",
      "reason": "一句话排序理由",
      "risk": "一句话主要风险",
      "catalysts": ["潜在催化1", "潜在催化2"],
      "risk_flags": ["风险标签1"],
      "tags": ["价值", "趋势", "防守", "事件", "流动性"],
      "style_fit": "与策略风格的匹配度说明",
      "watch_items": ["后续应跟踪的数据或事件"],
      "invalidators": ["会推翻该候选逻辑的观察点"]
    }}
  ]
}}
"""


def _build_bounded_ranking_prompt(
    candidates: list[Pick],
    hints: str,
    context: str,
    *,
    max_chars: int,
    degradation: list[str] | None,
) -> str:
    trimmed: list[str] = []
    identity_text = "\n".join(_format_candidate_for_prompt(p, detail="identity") for p in candidates)
    base_min = _render_ranking_prompt(
        _truncate_prompt_text(hints, 900, "hints", trimmed),
        "",
        identity_text,
    )
    context_budget = max(int(max_chars) - len(base_min) - 80, 0)
    context_text = _truncate_prompt_text(context, context_budget, "context", trimmed)

    prompt_without_candidates = _render_ranking_prompt(
        _truncate_prompt_text(hints, 900, "hints", trimmed),
        context_text,
        "",
    )
    candidate_budget = max(int(max_chars) - len(prompt_without_candidates), 0)
    candidates_text = _fit_candidate_prompt_lines(candidates, candidate_budget, trimmed)
    prompt = _render_ranking_prompt(
        _truncate_prompt_text(hints, 900, "hints", trimmed),
        context_text,
        candidates_text,
    )

    if len(prompt) > max_chars:
        overflow = len(prompt) - int(max_chars)
        context_text = _truncate_prompt_text(
            context_text,
            max(len(context_text) - overflow - 80, 0),
            "context",
            trimmed,
        )
        prompt_without_candidates = _render_ranking_prompt(
            _truncate_prompt_text(hints, 600, "hints", trimmed),
            context_text,
            "",
        )
        candidate_budget = max(int(max_chars) - len(prompt_without_candidates), 0)
        candidates_text = _fit_candidate_prompt_lines(candidates, candidate_budget, trimmed)
        prompt = _render_ranking_prompt(
            _truncate_prompt_text(hints, 600, "hints", trimmed),
            context_text,
            candidates_text,
        )

    if len(prompt) > max_chars:
        marker = f"\n...{_PROMPT_TRIM_MARKER}:hard_cap"
        prompt = prompt[: max(int(max_chars) - len(marker), 0)].rstrip() + marker
        trimmed.append("hard_cap")

    if trimmed and degradation is not None:
        labels = ",".join(dict.fromkeys(trimmed))
        degradation.append(f"LLM ranking prompt truncated: trimmed={labels}")
    return prompt[:max_chars]


def _format_candidate_for_prompt(p: Pick, *, detail: str = "full") -> str:
    if detail == "identity":
        return (
            f"- {p.code} {p.name}: rank={p.rank}, "
            f"screen_score={p.screen_score:.1f}, final_score={p.final_score:.1f}"
        )
    if detail == "compact":
        return (
            f"- {p.code} {p.name}: rank={p.rank}, price={p.price}, "
            f"change_pct={p.change_pct}%, amount={p.amount:.0f}, "
            f"screen_score={p.screen_score:.1f}, industry={p.industry or 'unknown'}, "
            f"concepts={p.concepts or 'unknown'}, board_heat_score={p.board_heat_score}, "
            f"signal_score={p.signal_score}, dsa_context={_format_dsa_context_for_prompt(p)}"
        )
    return (
        f"- {p.code} {p.name}: price={p.price}, change_pct={p.change_pct}%, "
        f"amount={p.amount:.0f}, turnover={p.turnover_rate}, volume_ratio={p.volume_ratio}, "
        f"total_mv={p.total_mv}, PE={p.pe_ratio}, PB={p.pb_ratio}, "
        f"industry={p.industry or 'unknown'}, concepts={p.concepts or 'unknown'}, "
        f"industry_rank={p.industry_rank}, industry_change_pct={p.industry_change_pct}, "
        f"board_heat_score={p.board_heat_score}, board_heat_summary={p.board_heat_summary or 'unknown'}, "
        f"board_heat_latest_score={p.board_heat_latest_score}, "
        f"board_heat_trend_score={p.board_heat_trend_score}, "
        f"board_heat_persistence_score={p.board_heat_persistence_score}, "
        f"board_heat_cooling_score={p.board_heat_cooling_score}, "
        f"board_heat_observations={p.board_heat_observations}, "
        f"board_heat_state={p.board_heat_state or 'unknown'}, "
        f"change_60d={p.change_60d}, signal_score={p.signal_score}, "
        f"macd={p.macd_status}, rsi={p.rsi_status}, "
        f"breakout_20d_pct={p.breakout_20d_pct}, range_20d_pct={p.range_20d_pct}, "
        f"volume_ratio_20d={p.volume_ratio_20d}, body_pct={p.body_pct}, "
        f"pullback_to_ma20_pct={p.pullback_to_ma20_pct}, "
        f"consolidation_days_20d={p.consolidation_days_20d}, "
        f"screen_score={p.screen_score:.1f}, factor_scores={p.factor_scores}, "
        f"dsa_context={_format_dsa_context_for_prompt(p)}"
    )


def _fit_candidate_prompt_lines(
    candidates: list[Pick],
    budget: int,
    trimmed: list[str],
) -> str:
    marker = f"...{_PROMPT_TRIM_MARKER}:candidate_details"
    full_text = "\n".join(_format_candidate_for_prompt(p) for p in candidates)
    if len(full_text) <= budget:
        return full_text

    available = max(int(budget) - len(marker) - 1, 0)
    if available <= 0:
        trimmed.append("candidate_details")
        return marker[:budget]

    identity_lines = [_format_candidate_for_prompt(p, detail="identity") for p in candidates]
    lines: list[str] = []
    used = 0
    omitted = 0
    for line in identity_lines:
        extra = len(line) + (1 if lines else 0)
        if used + extra > available:
            omitted += 1
            continue
        lines.append(line)
        used += extra

    if omitted == 0:
        for idx, pick in enumerate(candidates):
            for detail in ("full", "compact"):
                replacement = _format_candidate_for_prompt(pick, detail=detail)
                delta = len(replacement) - len(lines[idx])
                if used + delta <= available:
                    lines[idx] = replacement
                    used += delta
                    break

    if omitted:
        trimmed.append("candidate_omitted")
        lines.append(f"...{_PROMPT_TRIM_MARKER}:candidate_omitted={omitted}")
    else:
        trimmed.append("candidate_details")
        lines.append(marker)
    return "\n".join(lines)


def _truncate_prompt_text(text: str, limit: int, label: str, trimmed: list[str]) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    marker = f"\n...{_PROMPT_TRIM_MARKER}:{label}"
    trimmed.append(label)
    if limit <= len(marker) + 8:
        return marker[:limit]
    return text[: max(limit - len(marker), 0)].rstrip() + marker


def _format_dsa_context_for_prompt(p: Pick) -> str:
    parts: list[str] = []
    if p.dsa_analysis_summary:
        parts.append(f"summary={_truncate_text(p.dsa_analysis_summary, 240)}")

    context = p.dsa_context if isinstance(p.dsa_context, dict) else {}
    quote = context.get("quote") if isinstance(context.get("quote"), dict) else {}
    if quote:
        parts.append(
            "quote="
            f"price:{quote.get('price')},change_pct:{quote.get('change_pct')},"
            f"amount:{quote.get('amount')}"
        )

    fundamentals = context.get("fundamentals") if isinstance(context.get("fundamentals"), dict) else {}
    coverage = fundamentals.get("coverage") if isinstance(fundamentals.get("coverage"), dict) else {}
    if coverage:
        available = [
            str(key)
            for key, value in coverage.items()
            if str(value).lower() in {"available", "partial"}
        ]
        if available:
            parts.append(f"fundamental_coverage={','.join(available[:5])}")

    news_items = p.dsa_news
    if not news_items:
        news_payload = context.get("news") if isinstance(context.get("news"), dict) else {}
        raw_results = news_payload.get("results") if isinstance(news_payload, dict) else []
        if isinstance(raw_results, list):
            news_items = [item for item in raw_results if isinstance(item, dict)]
    titles = [
        _truncate_text(str(item.get("title") or "").strip(), 80)
        for item in news_items[:3]
        if isinstance(item, dict) and item.get("title")
    ]
    if titles:
        parts.append(f"news_titles={';'.join(titles)}")

    warnings = context.get("warnings") if isinstance(context.get("warnings"), list) else []
    warning_text = [str(item) for item in warnings[:3] if item]
    if warning_text:
        parts.append(f"warnings={';'.join(warning_text)}")

    return "; ".join(parts) if parts else "none"


def _truncate_text(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + "…"


def _call_llm(
    prompt: str,
    api_key: str,
    model: str,
    base_url: str,
    *,
    fallback_models: list[str] | None = None,
    temperature: float = 0.2,
    json_mode: bool = True,
    silent: bool = True,
    channels: list[dict[str, object]] | None = None,
    config_path: str = "",
    timeout_sec: float = 60.0,
    max_tokens: int | None = 2048,
) -> str:
    """Call LLM via litellm with fallback models and channel configs."""
    import litellm

    if silent:
        _silence_litellm_logs(litellm)

    messages = [{"role": "user", "content": prompt}]
    model_chain = _dedupe([model, *(fallback_models or [])])
    last_error: Exception | None = None

    if config_path:
        router_result = _call_litellm_router(
            litellm,
            config_path=config_path,
            model_chain=model_chain,
            messages=messages,
            temperature=temperature,
            json_mode=json_mode,
            timeout_sec=timeout_sec,
            max_tokens=max_tokens,
        )
        if router_result is not None:
            return router_result

    for candidate_model in model_chain:
        for kwargs in _build_litellm_attempts(
            candidate_model,
            api_key=api_key,
            base_url=base_url,
            channels=channels or [],
        ):
            kwargs["messages"] = messages
            kwargs["timeout"] = timeout_sec
            kwargs["num_retries"] = 0
            if max_tokens is not None and int(max_tokens) > 0:
                kwargs["max_tokens"] = int(max_tokens)
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            kwargs = _apply_screening_litellm_generation_params(
                kwargs,
                model=candidate_model,
                temperature=temperature,
            )
            try:
                response = _call_screening_litellm_completion(
                    lambda request_kwargs: litellm.completion(**request_kwargs),
                    model=candidate_model,
                    call_kwargs=kwargs,
                )
                return _extract_completion_text(response)
            except Exception as exc:
                last_error = exc
                if _is_timeout_error(exc):
                    raise
                continue

    if last_error is not None:
        raise last_error
    raise RuntimeError("No LLM model configured")


def _extract_completion_text(response: object) -> str:
    """Normalize text returned by OpenAI-compatible and reasoning gateways."""
    try:
        choices = response.get("choices") if isinstance(response, dict) else getattr(response, "choices")
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, dict) else getattr(choice, "message")
    except (AttributeError, IndexError, KeyError, TypeError):
        return ""

    def field(name: str) -> object:
        if isinstance(message, dict):
            return message.get(name)
        value = getattr(message, name, None)
        if value is not None:
            return value
        extra = getattr(message, "model_extra", None)
        return extra.get(name) if isinstance(extra, dict) else None

    content = _coerce_completion_content(field("content"))
    if content.strip():
        return content

    # If provider returns segmented blocks (LiteLLM, MiniMax, etc.), prefer
    # extracting text from content_blocks before treating the response as empty.
    content_blocks = None
    for owner in (choice, message):
        if isinstance(owner, dict):
            cb = owner.get("content_blocks")
        else:
            cb = getattr(owner, "content_blocks", None)
        if cb:
            content_blocks = cb
            break
    if content_blocks is not None:
        content = _coerce_completion_content(content_blocks)
        if content.strip():
            return content

    # Do NOT fall back to internal 'reasoning_content' (chain-of-thought) as the
    # model's final output. Treat absence of final content as empty to allow
    # higher-level fallback logic (try next model or use factor ranking).
    return ""


def _coerce_completion_content(value: object) -> str:
    """Coerce various completion content shapes into joined text.

    Filter out non-final provider blocks (thinking/draft) by honoring the
    block 'type' field. This prevents earlier thinking blocks from overriding
    the model's final output when both are present.
    """
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
            continue
        # Determine block type and preferred text field robustly for dicts and
        # provider objects.
        if isinstance(item, dict):
            block_type = str(item.get("type") or "").strip().lower()
            text = item.get("text") or item.get("content")
        else:
            block_type = str(getattr(item, "type", None) or "").strip().lower()
            text = getattr(item, "text", None) or getattr(item, "content", None)
        # Skip thinking/diagnostic blocks; only accept final textual blocks.
        if block_type and block_type not in {"text", "output_text"}:
            continue
        if isinstance(text, str):
            parts.append(text)
    # Join without adding characters to avoid inserting raw newlines inside
    # JSON strings when providers segment content across blocks.
    return "".join(parts)


def _is_json_mode_unsupported(exc: Exception) -> bool:
    """Return True only for provider errors that clearly reject JSON mode."""
    if _is_timeout_error(exc):
        return False
    text = str(exc).lower()
    return (
        "response_format" in text
        or "json mode" in text
        or "json_object" in text
        or ("not support" in text and "json" in text)
        or ("unsupported" in text and "json" in text)
    )


def _is_timeout_error(exc: Exception) -> bool:
    text = str(exc).lower()
    timeout_markers = ("timeout", "timed out", "readtimeout", "apitimeout")
    return any(marker in text for marker in timeout_markers)


def _parse_ranking_response(response: str, candidates: list[Pick]) -> list[Pick]:
    """Parse LLM response and reorder candidates."""
    return _parse_ranking_response_detail(response, candidates).picks


def _parse_ranking_response_detail(response: str, candidates: list[Pick]) -> RankingParseResult:
    """Parse LLM response and return diagnostics."""
    errors: list[str] = []
    if not response or not response.strip():
        errors.append("empty_response")
        logger.warning("Empty LLM ranking response")
        return RankingParseResult(candidates, 0.0, errors)

    parsed = _extract_ranking_json(response, errors)
    if parsed is None:
        errors.append("no_json_found")
        logger.warning("No JSON object or array found in LLM response")
        return RankingParseResult(candidates, 0.0, errors)
    if isinstance(parsed, dict):
        items = parsed.get("ranked", [])
        market_view = _safe_str(parsed.get("market_view"), max_len=260)
        selection_logic = _safe_str(parsed.get("selection_logic"), max_len=360)
        portfolio_risk = _safe_str(parsed.get("portfolio_risk"), max_len=360)
    else:
        items = parsed
        market_view = ""
        selection_logic = ""
        portfolio_risk = ""
    if not isinstance(items, list):
        errors.append("ranked_not_list")
        logger.warning("LLM ranking JSON has no ranked list")
        return RankingParseResult(candidates, 0.0, errors)

    # Parse into detached picks so partial/low-coverage results never mutate the
    # caller's candidate list before coverage validation passes.
    working_candidates = [copy.deepcopy(pick) for pick in candidates]
    code_to_pick = {
        _normalize_code(p.code): p for p in working_candidates if _normalize_code(p.code)
    }

    ranked = []
    matched = 0
    seen_codes = set()
    for item in items:
        if not isinstance(item, dict):
            errors.append("non_object_item")
            continue
        code = _normalize_code(item.get("code", ""))
        if code in seen_codes:
            errors.append(f"duplicate_code:{code}")
            continue
        seen_codes.add(code)
        if code in code_to_pick:
            pick = code_to_pick.pop(code)
            pick.ranking_reason = _safe_str(item.get("reason"), max_len=180)
            pick.risk_summary = _safe_str(item.get("risk"), max_len=180)
            pick.llm_score = _bounded_float(item.get("llm_score"), low=0, high=100)
            pick.llm_confidence = _bounded_float(item.get("confidence"), low=0, high=1)
            pick.llm_sector = _safe_str(
                item.get("sector") or item.get("industry") or item.get("sector_label"),
                max_len=40,
            )
            pick.llm_theme = _safe_str(item.get("theme"), max_len=100)
            pick.llm_thesis = _safe_str(item.get("thesis"), max_len=220)
            pick.llm_catalysts = _safe_string_list(item.get("catalysts"))
            pick.llm_invalidators = _safe_string_list(item.get("invalidators"))
            pick.llm_style_fit = _safe_str(item.get("style_fit"), max_len=120)
            pick.llm_watch_items = _safe_string_list(item.get("watch_items"))
            pick.llm_risks = _safe_string_list(item.get("risk_flags"))
            pick.llm_tags = _safe_string_list(item.get("tags"))
            if pick.llm_sector:
                pick.llm_tags = _dedupe([*pick.llm_tags, f"sector:{pick.llm_sector}"])
            if pick.llm_theme:
                pick.llm_tags = _dedupe([*pick.llm_tags, f"theme:{pick.llm_theme}"])
            if pick.llm_style_fit:
                pick.llm_tags = _dedupe([*pick.llm_tags, f"style_fit:{pick.llm_style_fit}"])
            ranked.append(pick)
            matched += 1
        elif code:
            errors.append(f"unknown_code:{code}")

    # Append any candidates not mentioned by LLM
    ranked.extend(code_to_pick.values())
    coverage = matched / max(len(candidates), 1)
    return RankingParseResult(
        ranked,
        coverage,
        errors,
        market_view=market_view,
        selection_logic=selection_logic,
        portfolio_risk=portfolio_risk,
    )


def _safe_str(value, *, max_len: int) -> str:
    return safe_text(value, max_len=max_len)


def _try_parse_json_lenient(raw: str, errors: list[str]):
    """Attempt to parse LLM JSON output, tolerating common formatting drift.

    Steps applied in order: strict parse → strip trailing commas → balance
    truncated brackets → return None if all fail. Any repair that succeeds is
    recorded in ``errors`` for diagnostics.
    """
    import re

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        first_error = exc

    # Repair 1: remove trailing commas before } or ].
    repaired = re.sub(r",(\s*[}\]])", r"\1", raw)
    if repaired != raw:
        try:
            result = json.loads(repaired)
            errors.append("json_repaired:trailing_comma")
            return result
        except json.JSONDecodeError:
            pass

    # Repair 2: close unbalanced brackets caused by truncated output.
    open_curly = repaired.count("{") - repaired.count("}")
    open_square = repaired.count("[") - repaired.count("]")
    if open_curly > 0 or open_square > 0:
        patched = repaired + ("]" * max(open_square, 0)) + ("}" * max(open_curly, 0))
        try:
            result = json.loads(patched)
            errors.append("json_repaired:closed_brackets")
            return result
        except json.JSONDecodeError:
            pass

    errors.append(f"json_decode_error:{first_error}")
    logger.warning("Failed to parse LLM ranking JSON: %s", first_error)
    return None


def _extract_ranking_json(response: str, errors: list[str]):
    """Extract ranking JSON from common LLM response shapes."""
    for raw in _iter_json_payloads(response):
        parsed = _try_parse_json_lenient(raw, errors)
        if _looks_like_ranking_payload(parsed):
            return parsed

    partial = _extract_partial_ranking_array(response, errors)
    if partial is not None:
        return partial
    return None


def _looks_like_ranking_payload(value: object) -> bool:
    if isinstance(value, dict):
        return isinstance(value.get("ranked"), list)
    if isinstance(value, list):
        return any(isinstance(item, dict) and "code" in item for item in value)
    return False


def _iter_json_payloads(response: str):
    """Yield likely JSON payload substrings in priority order."""
    import re

    yielded: set[str] = set()
    fence_pattern = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
    for match in fence_pattern.finditer(response):
        payload = match.group(1).strip()
        if payload and payload not in yielded:
            yielded.add(payload)
            yield payload

    cleaned = fence_pattern.sub(lambda match: match.group(1), response)
    for payload in _balanced_json_values(cleaned):
        if payload not in yielded:
            yielded.add(payload)
            yield payload


def _balanced_json_values(text: str) -> list[str]:
    """Return balanced top-level JSON object/array substrings."""
    values: list[str] = []
    stack: list[str] = []
    start: int | None = None
    in_string = False
    escaped = False
    pairs = {"{": "}", "[": "]"}

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char in pairs:
            if not stack:
                start = index
            stack.append(pairs[char])
            continue
        if char in ("}", "]") and stack:
            expected = stack.pop()
            if char != expected:
                stack.clear()
                start = None
                continue
            if not stack and start is not None:
                values.append(text[start : index + 1])
                start = None
    return values


def _extract_partial_ranking_array(response: str, errors: list[str]):
    """Recover a ranked list from multiple JSON objects in a noisy response."""
    items = []
    item_errors: list[str] = []
    for raw in _balanced_json_values(response):
        parsed = _try_parse_json_lenient(raw, item_errors)
        if isinstance(parsed, dict) and "code" in parsed:
            items.append(parsed)
    if not items:
        return None
    errors.append("json_repaired:partial_array")
    return {"ranked": items}


def _call_litellm_router(
    litellm,
    *,
    config_path: str,
    model_chain: list[str],
    messages: list[dict[str, str]],
    temperature: float,
    json_mode: bool,
    timeout_sec: float,
    max_tokens: int | None = 2048,
) -> str | None:
    try:
        import yaml

        with open(config_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        model_list = data.get("model_list")
        if not isinstance(model_list, list) or not model_list:
            return None
        router = litellm.Router(model_list=model_list)
        for model in model_chain:
            kwargs = {
                "model": model,
                "messages": messages,
                "timeout": timeout_sec,
                "num_retries": 0,
            }
            if max_tokens is not None and int(max_tokens) > 0:
                kwargs["max_tokens"] = int(max_tokens)
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            kwargs = _apply_screening_litellm_generation_params(
                kwargs,
                model=model,
                temperature=temperature,
                model_list=model_list,
            )
            try:
                response = _call_screening_litellm_completion(
                    lambda request_kwargs: router.completion(**request_kwargs),
                    model=model,
                    call_kwargs=kwargs,
                    model_list=model_list,
                )
                return _extract_completion_text(response)
            except Exception:
                raise
    except Exception as exc:
        if _is_timeout_error(exc):
            raise
        logger.warning("LiteLLM router config failed, falling back to direct calls: %s", exc)
    return None


def _apply_screening_litellm_generation_params(
    call_kwargs: dict[str, object],
    *,
    model: str,
    temperature: float | None,
    model_list: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return apply_litellm_generation_params(
        call_kwargs,
        model,
        temperature,
        model_list=model_list,
    )


def _call_screening_litellm_completion(
    call,
    *,
    model: str,
    call_kwargs: dict[str, object],
    model_list: list[dict[str, object]] | None = None,
):
    try:
        return call_litellm_with_param_recovery(
            call,
            model=model,
            call_kwargs=call_kwargs,
            model_list=model_list,
            logger=logger,
            log_label="[Screening LiteLLM]",
        )
    except Exception as exc:
        if "response_format" not in call_kwargs or not _is_json_mode_unsupported(exc):
            raise
        # Some providers do not support JSON mode. Retry the same request
        # without it before moving to fallback models. Do not do this for
        # timeout/connection failures: a local OpenAI-compatible server may
        # keep generating after the client timeout, so a blind retry can
        # duplicate expensive work while the first request is still running.
        retry_kwargs = dict(call_kwargs)
        retry_kwargs.pop("response_format", None)
        return call_litellm_with_param_recovery(
            call,
            model=model,
            call_kwargs=retry_kwargs,
            model_list=model_list,
            logger=logger,
            log_label="[Screening LiteLLM]",
        )


def _silence_litellm_logs(litellm) -> None:
    os.environ.setdefault("LITELLM_LOG", "ERROR")
    try:
        litellm.set_verbose = False
        litellm.suppress_debug_info = True
    except Exception:
        pass
    for logger_name in ("LiteLLM", "litellm"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def _build_litellm_attempts(
    model: str,
    *,
    api_key: str,
    base_url: str,
    channels: list[dict[str, object]],
) -> list[dict[str, object]]:
    attempts = []
    for channel in channels:
        if not _channel_matches_model(channel, model):
            continue
        api_keys = channel.get("api_keys", [])
        if not isinstance(api_keys, list) or not api_keys:
            api_keys = [api_key] if api_key else [""]
        for channel_key in api_keys:
            attempts.append(_completion_kwargs(
                model,
                api_key=str(channel_key or ""),
                base_url=str(channel.get("base_url", "") or base_url or ""),
            ))

    attempts.append(_completion_kwargs(model, api_key=api_key, base_url=base_url))
    return _unique_attempts(attempts)


def _completion_kwargs(model: str, *, api_key: str, base_url: str) -> dict[str, object]:
    kwargs: dict[str, object] = {"model": model}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["api_base"] = base_url
    return kwargs


def _channel_matches_model(channel: dict[str, object], model: str) -> bool:
    models = channel.get("models", [])
    if not isinstance(models, list) or not models:
        return False
    normalized = {_normalize_model_name(str(item), str(channel.get("protocol", "openai"))) for item in models}
    return model in normalized or model.split("/", 1)[-1] in {item.split("/", 1)[-1] for item in normalized}


def _normalize_model_name(model: str, protocol: str) -> str:
    model = model.strip()
    if "/" in model:
        return model
    if protocol == "ollama":
        return f"ollama/{model}"
    if protocol == "gemini":
        return f"gemini/{model}"
    if protocol == "deepseek":
        return f"deepseek/{model}"
    return f"openai/{model}"


def _unique_attempts(items: list[dict[str, object]]) -> list[dict[str, object]]:
    seen = set()
    result = []
    for item in items:
        key = (item.get("model"), item.get("api_key"), item.get("api_base"))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        key = str(item).strip()
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result
