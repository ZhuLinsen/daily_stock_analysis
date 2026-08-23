# -*- coding: utf-8 -*-
"""
Shared factory for building fully-configured AgentExecutor instances.

Centralises construction to eliminate boilerplate duplicated across
api/v1/endpoints/agent.py, bot/commands/chat.py, bot/commands/ask.py,
and src/core/pipeline.py.

Performance notes
-----------------
* ``ToolRegistry`` is built once and cached at module level — tool
  registrations are immutable after setup so the object is safe to share
  across every request.
* ``SkillManager`` is expensive to create (loads YAML files from disk).
  A prototype is built on first use and cheap ``deepcopy`` clones are
  returned for each request, preserving thread-safety (``activate()``
  mutates internal state).

Usage::

    from src.agent.factory import build_agent_executor

    executor = build_agent_executor(config, skills=["bull_trend", "shrink_pullback"])
    result   = executor.chat(message="...", session_id="...")
"""

import copy
import logging
import math
import threading
from dataclasses import dataclass
from typing import List, Optional

from src.config import AGENT_MAX_STEPS_DEFAULT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level caches
# ---------------------------------------------------------------------------
_TOOL_REGISTRY = None
# Track the per-category timeout mapping ``_TOOL_REGISTRY`` was built from, so
# callers passing a freshly-reloaded ``Config`` always observe the right
# ceilings instead of inheriting the first build's values.
#
# Deliberately keyed by *value* rather than ``id(config)``: CPython reuses the
# address of a freed object, so a ``Config.reset_instance()`` + ``get_config()``
# round-trip can hand back a new instance with the *same* id() as the collected
# one, which would silently mark a changed config as "unchanged".  This mirrors
# the ``_SKILL_MANAGER_CUSTOM_DIR`` value-comparison used by ``get_skill_manager``
# below.  Pair with :func:`reset_tool_registry` for runtime config reload paths.
_CACHED_TIMEOUT_MAP: Optional[dict] = None
_SKILL_MANAGER_PROTOTYPE = None
# Sentinel used as initial value so None (i.e. no custom dir) compares as "changed"
# on the very first call, forcing a build rather than accidentally skipping it.
_SENTINEL = object()
# Track which custom_dir the prototype was built with so we can invalidate
# the cache if AGENT_SKILL_DIR changes at runtime (e.g. via config reload).
_SKILL_MANAGER_CUSTOM_DIR: object = _SENTINEL

# Guards the module-level ToolRegistry cache against concurrent rebuild/reset.
# ``get_tool_registry`` builds the registry *outside* this lock (see below) and
# only takes it to atomically assign the shared ``_TOOL_REGISTRY`` /
# ``_CACHED_TIMEOUT_MAP`` pair, so two requests with different ``Config``
# objects can never observe a registry built for the other's timeouts.
_tool_registry_lock = threading.Lock()

# Safety ceiling for any single per-category timeout value sourced from
# ``AGENT_*_TOOL_TIMEOUT_S``.  ``inf``/``nan``/negative already degrade to
# "no limit"; this clips absurd-but-finite values so they can never reach
# ``future.result(timeout=...)`` and stall a request.  The global
# ``tool_call_timeout_seconds`` budget is *not* subject to this clip.
_MAX_TOOL_TIMEOUT_S = 3600.0


@dataclass
class SkillPromptState:
    """Resolved skill activation + prompt fragments for analysis entrypoints."""

    skill_manager: object
    skills_to_activate: List[str]
    explicit_skill_selection: bool
    use_legacy_default_prompt: bool
    skill_instructions: str
    default_skill_policy: str
    technical_skill_policy: str


def _coerce_config_int(raw_value: object, default: int, *, field_name: str | None = None) -> int:
    """Coerce optional numeric config values to int with a fallback default.

    This protects test doubles and incomplete config objects from propagating
    mock-like values (e.g., MagicMock attributes) into strict numeric paths.

    This function is side-effect free: it only returns a parsed int fallback value
    and intentionally never mutates source config attributes.
    """

    try:
        return int(raw_value)
    except (TypeError, ValueError, OverflowError):
        if field_name:
            logger.warning(
                "[AgentFactory] Invalid value for %s: %r, fallback to default %s",
                field_name,
                raw_value,
                default,
            )
        return default


def _normalize_skill_ids(
    skill_ids: Optional[List[str]],
    *,
    available_skill_ids: set[str],
) -> tuple[List[str], List[str]]:
    """Return validated skill ids plus unknown ids, preserving input order."""
    normalized: List[str] = []
    unknown: List[str] = []

    for skill_id in skill_ids or []:
        if not isinstance(skill_id, str):
            continue
        cleaned = skill_id.strip()
        if not cleaned:
            continue
        if cleaned == "all":
            if "all" not in normalized:
                normalized.append("all")
            continue
        if cleaned in available_skill_ids:
            if cleaned not in normalized:
                normalized.append(cleaned)
            continue
        if cleaned not in unknown:
            unknown.append(cleaned)

    return normalized, unknown


def normalize_requested_skill_ids(config, skill_ids: List[str]) -> List[str]:
    """Normalize API-requested Skill ids with the AgentFactory catalog rules."""
    skill_manager = get_skill_manager(config)
    available_skill_ids = {
        str(getattr(skill, "name", "")).strip()
        for skill in skill_manager.list_skills()
        if str(getattr(skill, "name", "")).strip()
    }
    normalized, unknown = _normalize_skill_ids(
        skill_ids,
        available_skill_ids=available_skill_ids,
    )
    if unknown:
        logger.warning("[AgentFactory] Ignoring unknown request skill ids: %s", unknown)
    return normalized


def _resolve_selected_skill_ids(
    *,
    requested_skills: Optional[List[str]],
    configured_skills: Optional[List[str]],
    default_skills: List[str],
    available_skill_ids: set[str],
) -> tuple[List[str], bool]:
    """Resolve active skill ids and whether they came from a valid explicit selection."""
    selection_source = None
    raw_skill_ids = None
    if requested_skills is not None:
        selection_source = "request"
        raw_skill_ids = requested_skills
    elif configured_skills is not None:
        selection_source = "config"
        raw_skill_ids = configured_skills
    else:
        return list(default_skills), False

    selected_skill_ids, unknown_skill_ids = _normalize_skill_ids(
        raw_skill_ids,
        available_skill_ids=available_skill_ids,
    )
    if unknown_skill_ids:
        logger.warning(
            "[AgentFactory] Ignoring unknown %s skill ids: %s",
            selection_source,
            unknown_skill_ids,
        )
    if selected_skill_ids:
        return selected_skill_ids, True

    if raw_skill_ids:
        logger.warning(
            "[AgentFactory] No valid %s skills remain after validation; falling back to default skills: %s",
            selection_source,
            default_skills,
        )
    return list(default_skills), False


def _should_use_legacy_default_prompt(
    *,
    skills_to_activate: List[str],
    explicit_skill_selection: bool,
    skill_catalog: List[object],
) -> bool:
    """Keep the legacy prompt only for the implicit built-in bull_trend fallback."""
    if explicit_skill_selection or skills_to_activate != ["bull_trend"]:
        return False

    bull_trend_skill = next(
        (
            skill
            for skill in skill_catalog
            if str(getattr(skill, "name", "")).strip() == "bull_trend"
        ),
        None,
    )
    return getattr(bull_trend_skill, "source", None) == "builtin"


def _coerce_config_timeout(config, field_name: str) -> float:
    """Read a timeout field off ``config`` as a float, defaulting to ``0.0``.

    ``get_tool_registry`` builds its category map from the *caller-supplied*
    config, so it must tolerate partial config objects and test doubles: a
    missing attribute raises ``AttributeError`` and ``MagicMock() > 0`` raises
    ``TypeError``.  A plain ``float()`` conversion is not enough either --
    ``float(MagicMock())`` silently yields ``1.0``, which would quietly impose
    a bogus 1-second ceiling on every tool.  Only genuine numbers (or numeric
    strings, since ``.env`` values arrive as text) are accepted; anything else
    degrades to "no category limit" and defers to the global
    ``tool_call_timeout_seconds`` budget.
    """
    raw_value = getattr(config, field_name, None)

    if isinstance(raw_value, bool) or raw_value is None:
        # ``True`` would coerce to a nonsensical 1-second ceiling.
        return 0.0
    if isinstance(raw_value, (int, float)):
        value = float(raw_value)
        if not math.isfinite(value):
            # ``inf``/``nan`` are not valid ceilings; an ``inf`` would later
            # raise ``OverflowError`` at ``future.result(timeout=inf)``.
            logger.warning(
                "[AgentFactory] Non-finite value for %s: %r, treating as no category limit",
                field_name,
                raw_value,
            )
            return 0.0
        if value < 0:
            logger.warning(
                "[AgentFactory] Negative value for %s: %r, treating as no category limit",
                field_name,
                raw_value,
            )
            return 0.0
        if value == 0.0:
            # Explicitly disabled (the default) — silent, not a warning.
            return 0.0
        if value > _MAX_TOOL_TIMEOUT_S:
            logger.warning(
                "[AgentFactory] Clamping %s=%r to safety ceiling %ss",
                field_name, value, _MAX_TOOL_TIMEOUT_S,
            )
            return float(_MAX_TOOL_TIMEOUT_S)
        return value
    if isinstance(raw_value, str):
        try:
            value = float(raw_value.strip())
        except ValueError:
            logger.warning(
                "[AgentFactory] Invalid value for %s: %r, treating as no category limit",
                field_name,
                raw_value,
            )
            return 0.0
        if not math.isfinite(value):
            logger.warning(
                "[AgentFactory] Non-finite value for %s: %r, treating as no category limit",
                field_name,
                raw_value,
            )
            return 0.0
        if value < 0:
            logger.warning(
                "[AgentFactory] Negative value for %s: %r, treating as no category limit",
                field_name,
                raw_value,
            )
            return 0.0
        if value == 0.0:
            return 0.0
        if value > _MAX_TOOL_TIMEOUT_S:
            return float(_MAX_TOOL_TIMEOUT_S)
        return value

    # Mocks / arbitrary objects: never let them shape real timeout behaviour.
    logger.debug(
        "[AgentFactory] Non-numeric value for %s: %r, treating as no category limit",
        field_name,
        type(raw_value).__name__,
    )
    return 0.0


def _build_category_timeout_map(config) -> dict:
    """Map tool categories to their default timeout (seconds) from config.

    Only explicit overrides (value > 0) are carried; 0.0 means "no category
    limit, fall back to the global tool_call_timeout_seconds budget".

    ``market`` tools (get_market_indices / get_sector_rankings) are
    network-backed data calls, so they share the ``data`` ceiling.
    """
    data_timeout = _coerce_config_timeout(config, "agent_data_tool_timeout_s")
    return {
        k: v
        for k, v in {
            "data": data_timeout,
            "search": _coerce_config_timeout(config, "agent_search_tool_timeout_s"),
            "analysis": _coerce_config_timeout(config, "agent_analysis_tool_timeout_s"),
            "action": _coerce_config_timeout(config, "agent_action_tool_timeout_s"),
            "market": data_timeout,
        }.items()
        if v > 0
    }


def reset_tool_registry() -> None:
    """Drop the cached :class:`ToolRegistry` so the next access rebuilds it.

    Intended for runtime config reload paths
    (``main._reload_runtime_config`` /
    ``SystemConfigService._reload_runtime_singletons``) so that newly-loaded
    ``AGENT_*_TOOL_TIMEOUT_S`` overrides actually take effect on subsequent
    :func:`build_agent_executor` / :func:`build_agent_chat_executor` calls,
    instead of being silently shadowed by the registry built at first import.

    Guarded by ``_tool_registry_lock`` so a concurrent :func:`get_tool_registry`
    cannot read a half-reset cache (``None`` registry with a stale map, or vice
    versa).
    """
    global _TOOL_REGISTRY, _CACHED_TIMEOUT_MAP
    with _tool_registry_lock:
        if _TOOL_REGISTRY is not None:
            logger.info("[AgentFactory] ToolRegistry cache cleared; will rebuild on next access")
        _TOOL_REGISTRY = None
        _CACHED_TIMEOUT_MAP = None


def _build_tool_registry(category_timeout_map):
    """Construct and populate a :class:`ToolRegistry` from the tool modules.

    Extracted from :func:`get_tool_registry` so the (potentially heavy) tool
    module imports and registrations happen *outside* the cache lock — holding
    the lock during imports would serialise startup and risk a deadlock if any
    imported module ever imported this module back.
    """
    from src.agent.tools.registry import ToolRegistry
    from src.agent.tools.data_tools import ALL_DATA_TOOLS
    from src.agent.tools.analysis_tools import ALL_ANALYSIS_TOOLS
    from src.agent.tools.search_tools import ALL_SEARCH_TOOLS
    from src.agent.tools.market_tools import ALL_MARKET_TOOLS
    from src.agent.tools.backtest_tools import ALL_BACKTEST_TOOLS

    registry = ToolRegistry(category_timeout_map=category_timeout_map or None)
    for tool_fn in (
        ALL_DATA_TOOLS
        + ALL_ANALYSIS_TOOLS
        + ALL_SEARCH_TOOLS
        + ALL_MARKET_TOOLS
        + ALL_BACKTEST_TOOLS
    ):
        registry.register(tool_fn)
    return registry


def get_tool_registry(config=None):
    """Return a :class:`ToolRegistry` bound to the lifetime of ``config``.

    The first call (or the first call after :func:`reset_tool_registry`)
    builds and caches a registry from ``config``.  The cache is keyed by the
    resolved per-category timeout *values*, so a config carrying different
    ``AGENT_*_TOOL_TIMEOUT_S`` settings (e.g. a freshly-reloaded ``Config``
    singleton) rebuilds the registry, while an equivalent config reuses the
    cached instance and avoids re-registering the whole tool surface.

    Value comparison is intentional: ``id(config)`` is not a safe key because
    CPython reuses the address of a collected object, so the instance returned
    after ``Config.reset_instance()`` can share the previous instance's id and
    would be misread as "unchanged".

    When ``config`` is ``None`` the function falls back to ``get_config()``,
    preserving the legacy contract for callers that do not yet know about
    config reload.

    Thread-safety: the fast-path cache hit reads both globals under the lock
    (so the check and the return observe one consistent pair — see
    ``reset_tool_registry``), and the registry build runs outside the lock with
    only the final assignment of the shared ``_TOOL_REGISTRY`` /
    ``_CACHED_TIMEOUT_MAP`` pair serialised (double-checked locking), so two
    requests with different ``Config`` objects can never observe a registry built
    for the other's timeouts.  On a (re)build the function returns the registry it
    just constructed for the caller's timeout map, so a concurrent rebuild cannot
    leak a mismatched registry into this call's result.
    """
    global _TOOL_REGISTRY, _CACHED_TIMEOUT_MAP

    if config is None:
        from src.config import get_config

        config = get_config()

    category_timeout_map = _build_category_timeout_map(config)
    # Fast path: take the lock so the cache-hit check and the return observe one
    # consistent (registry, timeout-map) pair — an unlocked check-then-use can
    # race with ``reset_tool_registry()`` and return ``None`` or a registry built
    # for the wrong timeout map (review OR-COM-a1e8b0c2).
    with _tool_registry_lock:
        if _TOOL_REGISTRY is not None and _CACHED_TIMEOUT_MAP == category_timeout_map:
            return _TOOL_REGISTRY

    # Build *outside* the lock (see ``_build_tool_registry`` rationale above).
    registry = _build_tool_registry(category_timeout_map)
    with _tool_registry_lock:
        # Re-check under the lock: another thread may have installed an
        # equivalent registry while we were importing the tool modules.
        if _TOOL_REGISTRY is not None and _CACHED_TIMEOUT_MAP == category_timeout_map:
            return _TOOL_REGISTRY
        invalidated = _TOOL_REGISTRY is not None
        _TOOL_REGISTRY = registry
        _CACHED_TIMEOUT_MAP = category_timeout_map
    if invalidated:
        logger.info(
            "[AgentFactory] ToolRegistry rebuilt for new category timeouts: %s",
            category_timeout_map or "none (global budget only)",
        )
    else:
        logger.info(
            "[AgentFactory] ToolRegistry cached (%d tools, category timeouts: %s)",
            len(registry._tools) if hasattr(registry, "_tools") else -1,
            category_timeout_map or "none (global budget only)",
        )
    # Return the registry built for *this* call's timeout map (not the shared
    # ``_TOOL_REGISTRY`` global).  Under a concurrent rebuild for a different
    # ``Config``/timeout map, this guarantees the caller gets the registry that
    # matches the timeouts it requested, instead of a registry built for another
    # request.  The global is still assigned above so equivalent subsequent calls
    # hit the cache fast path.
    return registry


def get_skill_manager(config=None):
    """Return a deepcopy-clone of the cached SkillManager prototype.

    The prototype is initialised from disk on first call; subsequent calls
    return ``copy.deepcopy(prototype)`` which is ~10× faster than re-reading
    YAML files.  Each clone is independent so ``.activate()`` calls do not
    bleed between requests.

    Cache invalidation: if ``config.agent_skill_dir`` changes at runtime
    (e.g. via the web settings reload), the prototype is rebuilt automatically.
    """
    global _SKILL_MANAGER_PROTOTYPE, _SKILL_MANAGER_CUSTOM_DIR

    if config is None:
        from src.config import get_config
        config = get_config()

    current_custom_dir = getattr(config, "agent_skill_dir", None)
    if _SKILL_MANAGER_PROTOTYPE is not None and current_custom_dir == _SKILL_MANAGER_CUSTOM_DIR:
        return copy.deepcopy(_SKILL_MANAGER_PROTOTYPE)

    from src.agent.skills.base import SkillManager

    if _SKILL_MANAGER_PROTOTYPE is not None:
        logger.info("[AgentFactory] SkillManager prototype invalidated (agent_skill_dir changed: %r -> %r)",
                    _SKILL_MANAGER_CUSTOM_DIR, current_custom_dir)

    skill_manager = SkillManager()
    skill_manager.load_builtin_skills()

    if current_custom_dir:
        try:
            skill_manager.load_custom_skills(current_custom_dir)
        except Exception as exc:
            logger.warning("[AgentFactory] Failed to load custom skills from %s: %s", current_custom_dir, exc)

    _SKILL_MANAGER_PROTOTYPE = skill_manager
    _SKILL_MANAGER_CUSTOM_DIR = current_custom_dir
    logger.info("[AgentFactory] SkillManager prototype cached (%d skills)", len(skill_manager._skills))
    return copy.deepcopy(_SKILL_MANAGER_PROTOTYPE)


def resolve_skill_prompt_state(config=None, skills: Optional[List[str]] = None) -> SkillPromptState:
    """Resolve active skills and prompt fragments for analyzer / agent entrypoints."""
    if config is None:
        from src.config import get_config
        config = get_config()

    from src.agent.skills.defaults import (
        get_default_active_skill_ids,
        get_default_technical_skill_policy,
        get_default_trading_skill_policy,
    )

    skill_manager = get_skill_manager(config)
    skill_catalog = list(skill_manager.list_skills())
    available_skill_ids = {
        str(getattr(skill, "name", "")).strip()
        for skill in skill_catalog
        if str(getattr(skill, "name", "")).strip()
    }
    configured_skills = getattr(config, "agent_skills", None)
    if configured_skills == []:
        configured_skills = None
    default_skills = get_default_active_skill_ids(
        skill_catalog,
        available_skill_ids=available_skill_ids or None,
    )
    skills_to_activate, explicit_skill_selection = _resolve_selected_skill_ids(
        requested_skills=skills,
        configured_skills=configured_skills,
        default_skills=default_skills,
        available_skill_ids=available_skill_ids,
    )

    use_legacy_default_prompt = _should_use_legacy_default_prompt(
        skills_to_activate=skills_to_activate,
        explicit_skill_selection=explicit_skill_selection,
        skill_catalog=skill_catalog,
    )

    skill_manager.activate(skills_to_activate)
    logger.info("[AgentFactory] Activated skills: %s", skills_to_activate)

    return SkillPromptState(
        skill_manager=skill_manager,
        skills_to_activate=skills_to_activate,
        explicit_skill_selection=explicit_skill_selection,
        use_legacy_default_prompt=use_legacy_default_prompt,
        skill_instructions=skill_manager.get_skill_instructions(),
        default_skill_policy=get_default_trading_skill_policy(
            explicit_skill_selection=not use_legacy_default_prompt,
        ),
        technical_skill_policy=get_default_technical_skill_policy(
            explicit_skill_selection=not use_legacy_default_prompt,
        ),
    )


def build_agent_executor(config=None, skills: Optional[List[str]] = None):
    """Build and return a configured AgentExecutor (or future orchestrator).

    When ``AGENT_ARCH=multi``, this returns an orchestrator that manages
    multiple specialised agents. Otherwise it returns the legacy single-agent
    executor.

    Args:
        config: Application config object.  When *None*, ``get_config()`` is
                called automatically.
        skills: Skill ids to activate.  When *None* falls back to
                ``config.agent_skills``; if that is also empty falls back to
                the central default skill set.

    Returns:
        A ready-to-call :class:`src.agent.executor.AgentExecutor` instance.
    """
    if config is None:
        from src.config import get_config
        config = get_config()

    arch = getattr(config, "agent_arch", "single")

    from src.agent.llm_adapter import LLMToolAdapter

    # Pass ``config`` explicitly so a reloaded ``Config`` instance observes
    # the new per-category timeout map (Issue #1890 compatibility concern:
    # the module-level ToolRegistry would otherwise keep the first build's
    # timeouts even after ``_reload_runtime_config``).
    registry = get_tool_registry(config)
    prompt_state = resolve_skill_prompt_state(config, skills=skills)
    skill_manager = prompt_state.skill_manager
    logger.info(
        "[AgentFactory] Resolved skill prompt state: skills=%s (arch=%s, explicit=%s, legacy_default_prompt=%s)",
        prompt_state.skills_to_activate,
        arch,
        prompt_state.explicit_skill_selection,
        prompt_state.use_legacy_default_prompt,
    )

    llm_adapter = LLMToolAdapter(config)

    if arch == "multi":
        return _build_orchestrator(
            config,
            registry,
            llm_adapter,
            skill_manager,
            technical_skill_policy=prompt_state.technical_skill_policy,
        )

    from src.agent.executor import AgentExecutor
    # Intentionally do not mutate config routing fields here. We only coerce
    # execution params (max_steps/timeout_seconds) from config values; provider,
    # model, base URL and channel routes stay unchanged and are consumed by
    # downstream adapter logic as-is.
    return AgentExecutor(
        tool_registry=registry,
        llm_adapter=llm_adapter,
        skill_instructions=prompt_state.skill_instructions,
        default_skill_policy=prompt_state.default_skill_policy,
        use_legacy_default_prompt=prompt_state.use_legacy_default_prompt,
        max_steps=_coerce_config_int(
            getattr(config, "agent_max_steps", AGENT_MAX_STEPS_DEFAULT),
            AGENT_MAX_STEPS_DEFAULT,
            field_name="agent_max_steps",
        ),
        timeout_seconds=_coerce_config_int(
            getattr(config, "agent_orchestrator_timeout_s", 0),
            0,
            field_name="agent_orchestrator_timeout_s",
        ),
    )


def build_agent_chat_executor(config=None, skills: Optional[List[str]] = None):
    """Build the backend-neutral executor used only by Agent Chat endpoints."""
    if config is None:
        from src.config import get_config

        config = get_config()

    from src.agent.agent_backend import (
        AgentBackendConfigError,
        LiteLLMAgentBackend,
        resolve_agent_backend_id,
    )
    from src.agent.chat_executor import AgentChatExecutor

    backend_id = resolve_agent_backend_id(config)
    arch = str(getattr(config, "agent_arch", "single") or "single").strip().lower()
    if backend_id == "codex_app_server" and arch != "single":
        raise AgentBackendConfigError(
            "unsupported_agent_arch",
            "Codex Agent currently supports single-agent Chat only",
        )
    if backend_id == "litellm" and arch == "multi":
        return build_agent_executor(config, skills=skills)

    # Pass ``config`` explicitly so a reloaded ``Config`` instance observes
    # the new per-category timeout map (see ``build_agent_executor`` for the
    # same rationale).
    registry = get_tool_registry(config)
    prompt_state = resolve_skill_prompt_state(config, skills=skills)
    if backend_id == "litellm":
        from src.agent.llm_adapter import LLMToolAdapter

        context_llm_adapter = LLMToolAdapter(config)
        backend = LiteLLMAgentBackend(registry, context_llm_adapter)
    else:
        from src.agent.codex_agent_backend import CodexAgentBackend
        from src.agent.tool_surface import ToolSurface

        context_llm_adapter = None
        backend = CodexAgentBackend(ToolSurface(registry), config)

    return AgentChatExecutor(
        backend=backend,
        config=config,
        context_llm_adapter=context_llm_adapter,
        skill_instructions=prompt_state.skill_instructions,
        default_skill_policy=prompt_state.default_skill_policy,
        use_legacy_default_prompt=prompt_state.use_legacy_default_prompt,
        max_steps=_coerce_config_int(
            getattr(config, "agent_max_steps", AGENT_MAX_STEPS_DEFAULT),
            AGENT_MAX_STEPS_DEFAULT,
            field_name="agent_max_steps",
        ),
        timeout_seconds=_coerce_config_int(
            getattr(config, "agent_orchestrator_timeout_s", 0),
            0,
            field_name="agent_orchestrator_timeout_s",
        ),
    )


def _build_orchestrator(config, registry, llm_adapter, skill_manager, *, technical_skill_policy: str = ""):
    """Build and return an :class:`AgentOrchestrator` (multi-agent mode).

    The orchestrator presents the same ``run()`` / ``chat()`` interface as
    :class:`AgentExecutor` so callers need no changes.
    """
    from src.agent.orchestrator import AgentOrchestrator

    mode = getattr(config, "agent_orchestrator_mode", "standard")
    logger.info("[AgentFactory] Building AgentOrchestrator (mode=%s)", mode)

    return AgentOrchestrator(
        tool_registry=registry,
        llm_adapter=llm_adapter,
        skill_instructions=skill_manager.get_skill_instructions(),
        technical_skill_policy=technical_skill_policy,
        max_steps=_coerce_config_int(
            getattr(config, "agent_max_steps", AGENT_MAX_STEPS_DEFAULT),
            AGENT_MAX_STEPS_DEFAULT,
            field_name="agent_max_steps",
        ),
        mode=mode,
        skill_manager=skill_manager,
        config=config,
    )


# Keep legacy alias so any external callers using the old name still work.
build_executor = build_agent_executor
