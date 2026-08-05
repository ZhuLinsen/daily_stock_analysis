# -*- coding: utf-8 -*-
# Derived from AlphaSift revision 9f522747caafd3c0b1ddb7e14d5cf44c8580b6cf.
# Licensed under Apache-2.0 and modified for daily_stock_analysis.
"""Configuration."""

import os
from dataclasses import dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_POST_ANALYZERS = ["scorecard"]
DEFAULT_LLM_MODEL = "gemini/gemini-2.5-flash"
DEFAULT_SNAPSHOT_SOURCE_PRIORITY = ["sina", "efinance", "akshare_em", "em_datacenter"]
TUSHARE_FIRST_SOURCE_PRIORITY = ["tushare", "sina", "efinance", "akshare_em", "em_datacenter"]
_ENV_FILE_CACHE: dict[Path, tuple[tuple[int, int], dict[str, str]]] = {}
_APPLIED_ENV_FILE_VALUES: dict[str, str] = {}


def _load_env_file() -> None:
    """Load .env from cwd or project root if present."""
    candidates = [
        *_env_file_candidates_from_env(),
        Path.cwd() / ".env",
        _PROJECT_ROOT / ".env",
    ]
    seen: set[Path] = set()
    file_values: dict[str, str] = {}
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        for key, value in _read_env_file_values(path).items():
            file_values.setdefault(key, value)
    _apply_env_file_values(file_values)


def _read_env_file_values(path: Path) -> dict[str, str]:
    resolved = path.resolve()
    stat = path.stat()
    signature = (stat.st_mtime_ns, stat.st_size)
    cached = _ENV_FILE_CACHE.get(resolved)
    if cached is not None and cached[0] == signature:
        return dict(cached[1])

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cleaned = value.strip().strip("'\"")
        if cleaned == "":
            continue
        values.setdefault(key.strip(), cleaned)
    _ENV_FILE_CACHE[resolved] = (signature, dict(values))
    return values


def _apply_env_file_values(file_values: dict[str, str]) -> None:
    for key, old_value in list(_APPLIED_ENV_FILE_VALUES.items()):
        if os.environ.get(key) == old_value and file_values.get(key) != old_value:
            os.environ.pop(key, None)
        if os.environ.get(key) != old_value:
            _APPLIED_ENV_FILE_VALUES.pop(key, None)

    for key, value in file_values.items():
        if key not in os.environ:
            os.environ[key] = value
            _APPLIED_ENV_FILE_VALUES[key] = value


def _env_file_candidates_from_env() -> list[Path]:
    raw_values = [
        os.getenv("SCREENING_ENV_FILE", ""),
        os.getenv("SCREENING_ENV_FILES", ""),
    ]
    paths: list[Path] = []
    for raw in raw_values:
        for item in raw.replace(os.pathsep, ",").split(","):
            value = item.strip()
            if value:
                paths.append(Path(value))
    return paths


def _parse_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv_env(name: str, default: list[str] | None = None) -> list[str]:
    value = os.getenv(name)
    if value is None:
        return list(default or [])
    if value.strip().lower() in {"", "0", "false", "none", "off"}:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_optional_path_env(name: str) -> Path | None:
    value = os.getenv(name, "").strip()
    return Path(value) if value else None


def _has_tushare_token() -> bool:
    return bool(
        os.getenv("TUSHARE_TOKEN", "").strip()
        or os.getenv("TUSHARE_API_TOKEN", "").strip()
    )


def _resolve_snapshot_source_priority() -> list[str]:
    explicit = os.getenv("SNAPSHOT_SOURCE_PRIORITY")
    if explicit is not None:
        return [s.strip() for s in explicit.split(",") if s.strip()]
    if _has_tushare_token():
        return list(TUSHARE_FIRST_SOURCE_PRIORITY)
    return list(DEFAULT_SNAPSHOT_SOURCE_PRIORITY)


def _resolve_fallback_snapshot_path(data_dir: Path) -> Path | None:
    for name in ("SCREENING_FALLBACK_SNAPSHOT_PATH", "FALLBACK_SNAPSHOT_PATH"):
        raw = os.getenv(name)
        if raw is None:
            continue
        value = raw.strip()
        if value.lower() in {"", "0", "false", "none", "off"}:
            return None
        return Path(value)
    return data_dir / "snapshot.last_good.json"


def _default_strategies_dir() -> Path:
    """Use the strategies versioned with the built-in screening engine."""
    return _PACKAGE_DIR / "strategies"


def _resolve_strategies_dir() -> Path:
    return _parse_optional_path_env("STRATEGIES_DIR") or _default_strategies_dir()


@dataclass
class Config:
    """Runtime configuration, loaded from env vars."""

    # LLM
    llm_api_key: str = ""
    llm_model: str = DEFAULT_LLM_MODEL
    llm_base_url: str = ""
    llm_config_path: Path | None = None
    llm_fallback_models: list[str] = field(default_factory=list)
    llm_channels: list[dict[str, object]] = field(default_factory=list)
    llm_context: str = ""
    llm_candidate_context_enabled: bool = False
    llm_candidate_context_max_candidates: int = 8
    llm_candidate_context_providers: list[str] = field(default_factory=lambda: ["news", "fund_flow", "announcement", "quote"])
    llm_candidate_context_news_limit: int = 3
    llm_candidate_context_announcement_limit: int = 3
    llm_candidate_context_cache_enabled: bool = True
    llm_candidate_context_cache_ttl_hours: int = 24
    llm_temperature: float = 0.2
    llm_json_mode: bool = True
    llm_silent: bool = True
    llm_rank_weight: float = 0.40
    llm_candidate_multiplier: int = 6
    llm_max_candidates: int = 30
    llm_max_retries: int = 1
    llm_min_coverage: float = 0.60
    llm_context_max_chars: int = 4000
    llm_timeout_sec: float = 60.0
    llm_max_tokens: int = 2048

    # Snapshot data source priority
    snapshot_source_priority: list[str] = field(
        default_factory=lambda: list(DEFAULT_SNAPSHOT_SOURCE_PRIORITY)
    )
    fallback_snapshot_path: Path | None = (
        _PROJECT_ROOT / "data" / "snapshot.last_good.json"
    )
    snapshot_cache_ttl_seconds: float = 300.0

    # Strategy directory
    strategies_dir: Path = field(default_factory=_default_strategies_dir)

    # Optional deterministic industry/concept enrichment.
    industry_map_files: list[Path] = field(default_factory=list)
    industry_provider: str = "none"
    industry_provider_max_boards: int = 80
    industry_provider_cache_dir: Path | None = (
        _PROJECT_ROOT / "data" / "industry_provider_cache"
    )
    industry_provider_cache_ttl_hours: int = 24

    # Optional: DSA API for L3 deep analysis
    dsa_api_url: str = ""
    dsa_report_type: str = "detailed"
    dsa_max_picks: int = 3
    dsa_timeout_sec: float = 120.0
    dsa_force_refresh: bool = False
    dsa_notify: bool = False

    # L3/post-ranking analyzers. scorecard is the default local scorer; DSA is
    # one optional backend, not the pipeline's default or only final stage.
    post_analyzers: list[str] = field(default_factory=lambda: list(DEFAULT_POST_ANALYZERS))
    post_analysis_max_picks: int = 3
    post_analyzer_url: str = ""
    post_analyzer_timeout_sec: float = 120.0

    # Optional daily K-line enrichment after snapshot hard filters.
    daily_enrich_enabled: bool = False
    daily_enrich_max_candidates: int = 100
    daily_lookback_days: int = 120
    daily_source: str = "auto"
    daily_fetch_retries: int = 2
    daily_fetch_max_workers: int = 1
    daily_history_cache_dir: Path | None = None
    daily_history_cache_ttl_hours: int = 24

    # Independent risk layer.
    risk_enabled: bool = True
    risk_max_penalty: float = 12.0
    risk_veto_high: bool = False

    # Portfolio diversity layer driven by LLM sector/theme risk buckets.
    portfolio_diversity_enabled: bool = True
    portfolio_max_same_llm_sector: int = 1
    portfolio_concentration_penalty: float = 4.0

    # Evaluation overlay.
    evaluation_cost_bps: float = 0.0
    evaluation_follow_through_pct: float = 3.0
    evaluation_failed_breakout_pct: float = -3.0
    evaluation_price_path_enabled: bool = False
    evaluation_price_path_lookback_days: int = 90

    # Data directory
    data_dir: Path = _PROJECT_ROOT / "data"

    # Optional guardrail for last-good snapshot fallback freshness.
    snapshot_fallback_max_age_hours: float | None = None

    def has_llm_config(self) -> bool:
        """Return whether any supported LiteLLM configuration is present."""
        return any([
            bool(self.llm_api_key),
            bool(self.llm_base_url and self.llm_model.startswith("ollama/")),
            bool(self.llm_config_path),
            bool(self.llm_channels),
            self.llm_model.startswith("ollama/"),
        ])

    @classmethod
    def from_env(cls) -> "Config":
        _load_env_file()
        channels = _parse_llm_channels_env()
        llm_model = _resolve_llm_model(channels)
        data_dir = Path(os.getenv("SCREENING_DATA_DIR", str(_PROJECT_ROOT / "data")))
        fallback_snapshot_path = _resolve_fallback_snapshot_path(data_dir)
        daily_history_cache_dir = (
            _parse_optional_path_env("SCREENING_DAILY_HISTORY_CACHE_DIR")
            or _parse_optional_path_env("DAILY_HISTORY_CACHE_DIR")
            or data_dir / "daily_history"
        )
        industry_provider_cache_dir = (
            _parse_optional_path_env("SCREENING_INDUSTRY_PROVIDER_CACHE_DIR")
            or _parse_optional_path_env("INDUSTRY_PROVIDER_CACHE_DIR")
            or data_dir / "industry_provider_cache"
        )
        return cls(
            llm_api_key=_resolve_llm_api_key(llm_model),
            llm_model=llm_model,
            llm_base_url=_resolve_llm_base_url(llm_model),
            llm_config_path=_parse_optional_path_env("LITELLM_CONFIG"),
            llm_fallback_models=_parse_csv_env("LITELLM_FALLBACK_MODELS", []),
            llm_channels=channels,
            llm_context=os.getenv("LLM_CONTEXT", ""),
            llm_candidate_context_enabled=_parse_bool_env("LLM_CANDIDATE_CONTEXT_ENABLED", False),
            llm_candidate_context_max_candidates=max(
                1,
                int(os.getenv("LLM_CANDIDATE_CONTEXT_MAX_CANDIDATES", "8")),
            ),
            llm_candidate_context_providers=_parse_csv_env(
                "LLM_CANDIDATE_CONTEXT_PROVIDERS",
                ["news", "fund_flow", "announcement", "quote"],
            ),
            llm_candidate_context_news_limit=max(1, int(os.getenv("LLM_CANDIDATE_CONTEXT_NEWS_LIMIT", "3"))),
            llm_candidate_context_announcement_limit=max(
                1,
                int(os.getenv("LLM_CANDIDATE_CONTEXT_ANNOUNCEMENT_LIMIT", "3")),
            ),
            llm_candidate_context_cache_enabled=_parse_bool_env("LLM_CANDIDATE_CONTEXT_CACHE_ENABLED", True),
            llm_candidate_context_cache_ttl_hours=max(
                0,
                int(os.getenv("LLM_CANDIDATE_CONTEXT_CACHE_TTL_HOURS", "24")),
            ),
            llm_temperature=_parse_float_env("LLM_TEMPERATURE", 0.2),
            llm_json_mode=_parse_bool_env("LLM_JSON_MODE", True),
            llm_silent=_parse_bool_env("LLM_SILENT", True),
            llm_rank_weight=_parse_float_env("LLM_RANK_WEIGHT", 0.40),
            llm_candidate_multiplier=max(1, int(os.getenv("LLM_CANDIDATE_MULTIPLIER", "6"))),
            llm_max_candidates=max(1, int(os.getenv("LLM_MAX_CANDIDATES", "30"))),
            llm_max_retries=max(0, int(os.getenv("LLM_MAX_RETRIES", "1"))),
            llm_min_coverage=_parse_float_env("LLM_MIN_COVERAGE", 0.60),
            llm_context_max_chars=max(500, int(os.getenv("LLM_CONTEXT_MAX_CHARS", "4000"))),
            llm_timeout_sec=max(1.0, _parse_float_env("LLM_TIMEOUT_SEC", 60.0)),
            llm_max_tokens=max(1, int(os.getenv("LLM_MAX_TOKENS", "2048"))),
            snapshot_source_priority=_resolve_snapshot_source_priority(),
            fallback_snapshot_path=fallback_snapshot_path,
            snapshot_cache_ttl_seconds=max(
                0.0,
                _parse_float_env("SCREENING_SNAPSHOT_CACHE_TTL_SEC", 300.0),
            ),
            snapshot_fallback_max_age_hours=_parse_optional_float_env(
                "SNAPSHOT_FALLBACK_MAX_AGE_HOURS"
            ),
            strategies_dir=_resolve_strategies_dir(),
            industry_map_files=[
                Path(item)
                for item in _parse_csv_env("INDUSTRY_MAP_FILES", [])
            ],
            industry_provider=os.getenv("INDUSTRY_PROVIDER", "none"),
            industry_provider_max_boards=max(1, int(os.getenv("INDUSTRY_PROVIDER_MAX_BOARDS", "80"))),
            industry_provider_cache_dir=industry_provider_cache_dir,
            industry_provider_cache_ttl_hours=max(
                0,
                int(
                    os.getenv(
                        "SCREENING_INDUSTRY_PROVIDER_CACHE_TTL_HOURS",
                        os.getenv("INDUSTRY_PROVIDER_CACHE_TTL_HOURS", "24"),
                    )
                ),
            ),
            dsa_api_url=os.getenv("DSA_API_URL", ""),
            dsa_report_type=os.getenv("DSA_REPORT_TYPE", "detailed"),
            dsa_max_picks=max(1, int(os.getenv("DSA_MAX_PICKS", "3"))),
            dsa_timeout_sec=float(os.getenv("DSA_TIMEOUT_SEC", "120")),
            dsa_force_refresh=_parse_bool_env("DSA_FORCE_REFRESH", False),
            dsa_notify=_parse_bool_env("DSA_NOTIFY", False),
            post_analyzers=_parse_csv_env("POST_ANALYZERS", DEFAULT_POST_ANALYZERS),
            post_analysis_max_picks=max(
                1,
                int(os.getenv("POST_ANALYSIS_MAX_PICKS", os.getenv("DSA_MAX_PICKS", "3"))),
            ),
            post_analyzer_url=os.getenv("POST_ANALYZER_URL", ""),
            post_analyzer_timeout_sec=float(os.getenv("POST_ANALYZER_TIMEOUT_SEC", "120")),
            daily_enrich_enabled=_parse_bool_env("DAILY_ENRICH_ENABLED", False),
            daily_enrich_max_candidates=max(1, int(os.getenv("DAILY_ENRICH_MAX_CANDIDATES", "100"))),
            daily_lookback_days=max(30, int(os.getenv("DAILY_LOOKBACK_DAYS", "120"))),
            daily_source=os.getenv("DAILY_SOURCE", "auto"),
            daily_fetch_retries=max(0, int(os.getenv("DAILY_FETCH_RETRIES", "2"))),
            daily_fetch_max_workers=max(1, int(os.getenv("DAILY_FETCH_MAX_WORKERS", "1"))),
            daily_history_cache_dir=daily_history_cache_dir,
            daily_history_cache_ttl_hours=max(
                0,
                int(
                    os.getenv(
                        "SCREENING_DAILY_HISTORY_CACHE_TTL_HOURS",
                        os.getenv("DAILY_HISTORY_CACHE_TTL_HOURS", "24"),
                    )
                ),
            ),
            risk_enabled=_parse_bool_env("RISK_ENABLED", True),
            risk_max_penalty=_parse_float_env("RISK_MAX_PENALTY", 12.0),
            risk_veto_high=_parse_bool_env("RISK_VETO_HIGH", False),
            portfolio_diversity_enabled=_parse_bool_env("PORTFOLIO_DIVERSITY_ENABLED", True),
            portfolio_max_same_llm_sector=max(
                1,
                int(os.getenv("PORTFOLIO_MAX_SAME_LLM_SECTOR", "1")),
            ),
            portfolio_concentration_penalty=_parse_float_env("PORTFOLIO_CONCENTRATION_PENALTY", 4.0),
            evaluation_cost_bps=_parse_float_env("EVALUATION_COST_BPS", 0.0),
            evaluation_follow_through_pct=_parse_float_env("EVALUATION_FOLLOW_THROUGH_PCT", 3.0),
            evaluation_failed_breakout_pct=_parse_float_env("EVALUATION_FAILED_BREAKOUT_PCT", -3.0),
            evaluation_price_path_enabled=_parse_bool_env("EVALUATION_PRICE_PATH_ENABLED", False),
            evaluation_price_path_lookback_days=max(
                30,
                int(os.getenv("EVALUATION_PRICE_PATH_LOOKBACK_DAYS", "90")),
            ),
            data_dir=data_dir,
        )


def _parse_float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


def _parse_optional_float_env(name: str) -> float | None:
    value = os.getenv(name)
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned.lower() in {"", "none", "off", "false"}:
        return None
    return float(cleaned)


def _parse_llm_channels_env() -> list[dict[str, object]]:
    channels = []
    for raw_name in _parse_csv_env("LLM_CHANNELS", []):
        name = raw_name.strip()
        if not name:
            continue
        key = name.upper()
        enabled = _parse_bool_env(f"LLM_{key}_ENABLED", True)
        api_keys = (
            _parse_csv_env(f"LLM_{key}_API_KEYS", [])
            or _parse_csv_env(f"LLM_{key}_API_KEY", [])
        )
        channels.append({
            "name": name.lower(),
            "protocol": os.getenv(f"LLM_{key}_PROTOCOL", "openai").strip().lower(),
            "base_url": os.getenv(f"LLM_{key}_BASE_URL", "").strip(),
            "api_keys": api_keys,
            "models": _parse_csv_env(f"LLM_{key}_MODELS", []),
            "enabled": enabled,
        })
    return [channel for channel in channels if channel["enabled"]]


def _resolve_llm_model(channels: list[dict[str, object]]) -> str:
    explicit = (
        os.getenv("LITELLM_MODEL")
        or os.getenv("LLM_MODEL")
        or os.getenv("AGENT_LITELLM_MODEL")
        or ""
    ).strip()
    if explicit:
        return _normalize_litellm_model(explicit)

    for channel in channels:
        models = channel.get("models", [])
        if isinstance(models, list) and models:
            return _normalize_litellm_model(str(models[0]), str(channel.get("protocol", "openai")))

    if os.getenv("OLLAMA_API_BASE"):
        ollama_model = os.getenv("OLLAMA_MODEL", "").strip()
        return f"ollama/{ollama_model}" if ollama_model else DEFAULT_LLM_MODEL
    if os.getenv("DEEPSEEK_API_KEY"):
        return "deepseek/deepseek-chat"
    if os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEYS"):
        return _normalize_litellm_model(os.getenv("GEMINI_MODEL", DEFAULT_LLM_MODEL), "gemini")
    if os.getenv("OPENAI_API_KEY"):
        return _normalize_litellm_model(os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "openai")
    if os.getenv("AIHUBMIX_KEY"):
        return _normalize_litellm_model(os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "openai")
    return DEFAULT_LLM_MODEL


def _normalize_litellm_model(model: str, protocol: str = "openai") -> str:
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


def _resolve_llm_api_key(model: str) -> str:
    explicit = os.getenv("LLM_API_KEY", "").strip()
    if explicit:
        return explicit
    if model.startswith("gemini/"):
        keys = _parse_csv_env("GEMINI_API_KEYS", [])
        return keys[0] if keys else os.getenv("GEMINI_API_KEY", "")
    if model.startswith("deepseek/"):
        return os.getenv("DEEPSEEK_API_KEY", "")
    if model.startswith("anthropic/"):
        return os.getenv("ANTHROPIC_API_KEY", "")
    if os.getenv("AIHUBMIX_KEY"):
        return os.getenv("AIHUBMIX_KEY", "")
    if model.startswith("openai/"):
        return os.getenv("OPENAI_API_KEY", "")
    return os.getenv("OPENAI_API_KEY", "")


def _resolve_llm_base_url(model: str) -> str:
    explicit = os.getenv("LLM_BASE_URL", "").strip()
    if explicit:
        return explicit
    if model.startswith("ollama/"):
        return os.getenv("OLLAMA_API_BASE", "")
    if os.getenv("AIHUBMIX_KEY"):
        return os.getenv("AIHUBMIX_BASE_URL", "https://api.aihubmix.com/v1")
    if model.startswith("openai/"):
        return os.getenv("OPENAI_BASE_URL", "")
    return os.getenv("OPENAI_BASE_URL", "")
