# -*- coding: utf-8 -*-
"""Stock-scope helpers for ask-stock follow-up chat turns."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


SWITCH_CLEANUP_KEYS = {
    "stock_name",
    "previous_analysis_summary",
    "previous_strategy",
    "previous_price",
    "previous_change_pct",
    "realtime_quote",
    "daily_history",
    "chip_distribution",
    "trend_result",
    "news_context",
    "fundamental_context",
    "market_structure_context",
    "analysis_context_pack_summary",
    "market_phase_context",
}

_STRONG_COMPARE_PATTERN = re.compile(r"比较|对比|vs\b|和[^，。,.!?！？]{0,40}比", re.IGNORECASE)
_WEAK_COMPARE_HINT_PATTERN = re.compile(r"差异(?!化)|区别|不同|相比|对照|比一比")
_CHOICE_COMPARE_PATTERN = re.compile(r"哪个|哪只|哪一个|谁更|更值得|更适合|怎么选|选哪|二选一")
_LINKED_COMPARE_PATTERN = re.compile(
    r"(?:和|与|跟|同)(?P<body>[^，。,.!?！？]{0,40})(?:差异(?!化)|区别|不同|相比|对照|比一比)"
)
_SWITCH_PATTERN = re.compile(r"换成|改看|分析|看看|研究|诊断")
_LOWERCASE_TICKER_PATTERN = re.compile(r"(?<![a-zA-Z.])([a-z]{2,5}(?:\.[a-z]{1,2})?)(?![a-zA-Z0-9])")
_EXCHANGE_TOKEN_CANDIDATES = {"SH", "SZ", "BJ", "HK", "SS"}
_CONTEXTUAL_INDICATOR_TOKENS = {"MA"}
_INDICATOR_CONTEXT_PATTERN = re.compile(
    r"指标|均线|移动平均|排列|多头|空头|金叉|死叉|支撑|压力|MA\d|SMA|EMA",
    re.IGNORECASE,
)

def _has_ascii_token_boundaries(text: str, start: int, end: int) -> bool:
    def _is_word_char(char: str) -> bool:
        return bool(char) and char.isascii() and (char.isalnum() or char == "_")

    return (
        not _is_word_char(text[start - 1:start])
        and not _is_word_char(text[end:end + 1])
    )


@dataclass(frozen=True)
class StockIdentity:
    """The minimal Chat adapter over the existing analysis-target parser."""

    stock_code: str
    canonical_id: str
    asset_type: str
    stock_name: Optional[str] = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if (not isinstance(self.stock_code, str) or not self.stock_code.strip()
                or not isinstance(self.canonical_id, str) or not self.canonical_id.strip()
                or self.asset_type not in {"stock", "index"}
                or (self.stock_name is not None and not isinstance(self.stock_name, str))):
            raise ValueError("Chat stock identity requires code, canonical_id and asset_type")

    @classmethod
    def from_code(cls, token: str, registry: Any) -> "StockIdentity":
        from src.services.stock_list_parser import ParseStatus, parse_analysis_target

        if registry is None:
            raise ValueError("Chat stock identity registry is unavailable")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Chat stock token must be a nonempty string")
        try:
            target = parse_analysis_target(token, registry)
        except Exception as exc:
            raise ValueError("Chat stock identity registry could not validate the token") from exc
        return cls.from_target(target, registry)

    @classmethod
    def from_target(cls, target: Any, registry: Any) -> "StockIdentity":
        """Adapt a target already parsed against this call's registry snapshot."""
        from src.services.stock_list_parser import ParseStatus, parse_analysis_target

        if target.asset_type not in {ParseStatus.STOCK, ParseStatus.INDEX} or not target.canonical_id:
            raise ValueError(target.unsupported_reason or "Unsupported Chat stock code")
        if target.asset_type == ParseStatus.INDEX:
            code = target.canonical_id
        elif target.exchange == "HK":
            code = f"HK{target.normalized_code}"
        elif target.exchange in {"SH", "SZ", "BJ"}:
            code = target.normalized_code
            bare = parse_analysis_target(code, registry)
            if bare.canonical_id != target.canonical_id:
                code = target.canonical_id
        else:
            code = target.canonical_id
        return cls(stock_code=code, canonical_id=target.canonical_id, asset_type=target.asset_type,
                   stock_name=target.matched_index.display_name if target.asset_type == ParseStatus.INDEX else None)

    def as_payload(self) -> Dict[str, str]:
        return {"stock_code": self.stock_code, "canonical_id": self.canonical_id,
                "asset_type": self.asset_type}


@dataclass(frozen=True)
class StockScope:
    """Runtime stock-scope contract for one chat turn."""

    expected_stock_code: str = ""
    allowed_stock_codes: Set[str] = field(default_factory=set)
    mode: str = "maintain"
    strict: bool = False
    identities: Tuple[StockIdentity, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.strict, bool):
            raise ValueError("Stock scope strict marker must be boolean")
        object.__setattr__(self, "allowed_stock_codes", frozenset(self.allowed_stock_codes))
        object.__setattr__(self, "identities", tuple(self.identities))
        if self.identities and not self.strict:
            raise ValueError("Typed Chat identities cannot use the legacy scope path")
        if self.strict:
            identity_codes = {identity.stock_code for identity in self.identities}
            if (identity_codes != self.allowed_stock_codes
                    or len(identity_codes) != len(self.identities)
                    or (self.expected_stock_code and self.expected_stock_code not in identity_codes)):
                raise ValueError("Strict Chat scope must carry every allowed identity")

    def as_log_payload(self) -> Dict[str, Any]:
        return {
            "expected_stock_code": self.expected_stock_code,
            "allowed_stock_codes": sorted(self.allowed_stock_codes),
            "mode": self.mode,
            "strict": self.strict,
            "identities": [identity.as_payload() for identity in self.identities],
        }


@dataclass(frozen=True)
class StockScopeResolution:
    """Result produced before a chat turn enters the agent loop."""

    effective_context: Dict[str, Any]
    stock_scope: Optional[StockScope]


def _normalize_stock_code(value: Any, registry: Optional[Any] = None) -> str:
    """Normalize a code, preserving exact registered index canonicals."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    try:
        from src.agent.tools.execution import _normalize_tool_stock_code

        normalized = _normalize_tool_stock_code(text, registry)
    except Exception:
        normalized = text.strip().upper()
    return normalized if isinstance(normalized, str) else str(normalized)


def _is_denied_candidate(candidate: str, text: str = "") -> bool:
    token = candidate.strip().upper()
    if token in _EXCHANGE_TOKEN_CANDIDATES:
        return True
    if token in _CONTEXTUAL_INDICATOR_TOKENS and _INDICATOR_CONTEXT_PATTERN.search(text or ""):
        return True
    try:
        from src.agent.orchestrator import _COMMON_WORDS

        return token in _COMMON_WORDS
    except Exception:
        return False


def _append_candidate(
    candidates: List[str],
    candidate: str,
    text: str = "",
    registry: Optional[Any] = None,
) -> None:
    normalized = _normalize_stock_code(candidate, registry)
    if not normalized or _is_denied_candidate(normalized, text):
        return
    if normalized not in candidates:
        candidates.append(normalized)


def extract_stock_codes(text: str, registry: Optional[Any] = None) -> List[str]:
    """Extract candidates; no registry preserves the legacy stock-only path."""
    if not text:
        return []

    if registry is not None:
        # Preserve complete tokens BEFORE parsing, including ETFs and foreign
        # market suffixes. Never turn 005930.KS into an A-share candidate.
        candidates = []
        for token in extract_stock_code_tokens(text):
            try:
                identity = StockIdentity.from_code(token, registry)
            except ValueError:
                continue
            if identity.stock_code not in candidates:
                candidates.append(identity.stock_code)
        return candidates

    candidates: List[str] = []

    for pattern, flags in (
        (r"(?<![a-zA-Z])(?:SH|SZ|BJ)\d{6}(?!\d)", re.IGNORECASE),
        (r"(?<![a-zA-Z])hk\d{4,5}(?!\d)", re.IGNORECASE),
        (r"(?<![a-zA-Z])\d{1,5}\.HK(?![a-zA-Z])", re.IGNORECASE),
        (r"(?<!\d)(?:[03648]\d{5}|92\d{4})(?!\d)", 0),
        (r"(?<!\d)\d{5}(?!\d)", 0),
        (r"(?<![a-zA-Z.])([A-Z]{2,5}(?:\.[A-Z]{1,2})?)(?![a-zA-Z0-9])", 0),
    ):
        for match in re.finditer(pattern, text, flags):
            raw = match.group(1) if match.lastindex else match.group(0)
            _append_candidate(candidates, raw, text, registry)

    if (
        _SWITCH_PATTERN.search(text)
        or _STRONG_COMPARE_PATTERN.search(text)
        or _WEAK_COMPARE_HINT_PATTERN.search(text)
        or _CHOICE_COMPARE_PATTERN.search(text)
    ):
        for match in _LOWERCASE_TICKER_PATTERN.finditer(text):
            _append_candidate(candidates, match.group(1), text, registry)

    return candidates


def extract_stock_code_spans(text: str) -> List[tuple[int, int, str]]:
    """Actual whole-token occurrences in the supplied text's coordinates."""
    numeric = re.compile(
        r"(?<![a-zA-Z0-9_.])(?:"
        r"(?:sh|sz|bj|csi)\d{6}|hk\d{4,5}|"
        r"\d{1,6}\.(?:SH|SZ|SS|BJ|HK|KS|KQ|TW|T|CSI)|\d{5,6}"
        r")(?![a-zA-Z0-9_.])", re.IGNORECASE,
    )
    ticker = re.compile(r"(?<![a-zA-Z0-9_.])(?:us)?[A-Z]{1,5}(?:\.[A-Z]{1,2})?(?![a-zA-Z0-9_.])")
    matches = [(match.start(), match.end(), match.group()) for match in numeric.finditer(text or "")]
    for match in ticker.finditer(text or ""):
        if not any(start <= match.start() and match.end() <= end for start, end, _token in matches):
            matches.append((match.start(), match.end(), match.group()))
    if (_SWITCH_PATTERN.search(text or "") or _STRONG_COMPARE_PATTERN.search(text or "")
            or _WEAK_COMPARE_HINT_PATTERN.search(text or "") or _CHOICE_COMPARE_PATTERN.search(text or "")):
        for match in _LOWERCASE_TICKER_PATTERN.finditer(text or ""):
            if (_has_ascii_token_boundaries(text, *match.span(1))
                    and not any(start <= match.start(1) and match.end(1) <= end for start, end, _token in matches)):
                matches.append((match.start(1), match.end(1), match.group(1)))
    return [(start, end, token) for start, end, token in sorted(matches)
            if not _is_denied_candidate(token, text)]


def extract_stock_code_tokens(text: str) -> List[str]:
    """Compatibility list view; occurrence consumers use spans directly."""
    return list(dict.fromkeys(token for _start, _end, token in extract_stock_code_spans(text)))


def _is_compare_message(
    message: str,
    candidates: List[str],
    current_code: str,
    registry: Optional[Any] = None,
) -> bool:
    if _STRONG_COMPARE_PATTERN.search(message):
        return True
    new_candidates = {code for code in candidates if code != current_code}
    if len(new_candidates) >= 2:
        return True
    if _CHOICE_COMPARE_PATTERN.search(message) and len(candidates) >= 2:
        return True
    if not _WEAK_COMPARE_HINT_PATTERN.search(message):
        return False
    if len(candidates) >= 2:
        return True

    if not new_candidates:
        return False

    for match in _LINKED_COMPARE_PATTERN.finditer(message):
        body_candidates = set(extract_stock_codes(f"比较 {match.group('body')}", registry))
        if body_candidates & new_candidates:
            return True
    return False


def _with_skills(context: Dict[str, Any], skills: Optional[Iterable[str]]) -> Dict[str, Any]:
    if skills is None:
        return context
    next_context = dict(context)
    next_context["skills"] = list(skills)
    return next_context


def _switch_context(context: Dict[str, Any], stock_code: str) -> Dict[str, Any]:
    next_context = {
        key: value
        for key, value in context.items()
        if key not in SWITCH_CLEANUP_KEYS and key != "allowed_stock_codes"
    }
    next_context["stock_code"] = stock_code
    next_context["stock_name"] = ""
    return next_context


def resolve_stock_scope(
    message: str,
    context: Optional[Dict[str, Any]],
    *,
    skills: Optional[Iterable[str]] = None,
    strict_initial_scope: bool = False,
    registry: Optional[Any] = None,
) -> StockScopeResolution:
    """Resolve one turn with a shared registry, failing open to stock semantics."""
    if registry is None:
        try:
            from src.services.stock_list_parser import default_index_registry

            registry = default_index_registry()
        except Exception:
            registry = None
    if registry is not None and not getattr(registry, "_entries", ()):
        registry = None

    original_context = dict(context or {})
    message_text = message or ""
    current_code = _normalize_stock_code(original_context.get("stock_code"), registry)
    invalid_context_code = bool(current_code and _is_denied_candidate(current_code, message_text))
    original_context.pop("allowed_stock_codes", None)
    if invalid_context_code:
        original_context.pop("stock_code", None)
        original_context.pop("stock_name", None)
        current_code = ""

    if not current_code:
        if invalid_context_code or strict_initial_scope:
            candidates = extract_stock_codes(message_text, registry)
            if strict_initial_scope and not invalid_context_code and not candidates:
                return StockScopeResolution(
                    effective_context=_with_skills(original_context, skills),
                    stock_scope=None,
                )
            allowed = set(candidates)
            expected = candidates[0] if len(candidates) == 1 else ""
            effective_context = dict(original_context)
            mode = "switch" if expected else ("compare" if len(candidates) > 1 else "maintain")
            if expected:
                effective_context["stock_code"] = expected
                effective_context["stock_name"] = ""
            return StockScopeResolution(
                effective_context=_with_skills(effective_context, skills),
                stock_scope=StockScope(
                    expected_stock_code=expected,
                    allowed_stock_codes=allowed,
                    mode=mode,
                ),
            )
        return StockScopeResolution(
            effective_context=_with_skills(original_context, skills),
            stock_scope=None,
        )

    candidates = extract_stock_codes(message_text, registry)
    new_candidates = [code for code in candidates if code != current_code]
    mode = "maintain"
    effective_context = dict(original_context)
    expected = current_code
    allowed = {current_code}

    if _is_compare_message(message_text, candidates, current_code, registry):
        mode = "compare"
        allowed.update(candidates)
    elif _SWITCH_PATTERN.search(message_text) and len(new_candidates) == 1:
        mode = "switch"
        expected = new_candidates[0]
        allowed = {expected}
        effective_context = _switch_context(original_context, expected)

    effective_context["stock_code"] = expected if mode == "switch" else current_code
    effective_context = _with_skills(effective_context, skills)

    return StockScopeResolution(
        effective_context=effective_context,
        stock_scope=StockScope(
            expected_stock_code=expected,
            allowed_stock_codes=allowed,
            mode=mode,
        ),
    )
