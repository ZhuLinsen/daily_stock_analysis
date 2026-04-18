# -*- coding: utf-8 -*-
"""
Agent skills package.

Provides pluggable trading skills for the agent.
Skills are defined in natural language (YAML files) — no Python code needed.
"""

from src.agent.skills.base import (
    Skill,
    SkillManager,
    load_skill_from_markdown,
    load_skill_from_yaml,
    load_skills_from_directory,
)
from src.agent.skills.defaults import (
    DEFAULT_ACTIVE_SKILL_IDS,
    DEFAULT_ROUTER_SKILL_IDS,
    PRIMARY_DEFAULT_SKILL_ID,
    CORE_TRADING_SKILL_POLICY_ZH,
    TECHNICAL_SKILL_RULES_EN,
    get_default_active_skill_ids,
    get_default_router_skill_ids,
    get_primary_default_skill_id,
    get_regime_skill_ids,
)

__all__ = [
    "Skill",
    "SkillManager",
    "SkillAgent",
    "SkillRouter",
    "SkillAggregator",
    "DEFAULT_ACTIVE_SKILL_IDS",
    "DEFAULT_ROUTER_SKILL_IDS",
    "PRIMARY_DEFAULT_SKILL_ID",
    "CORE_TRADING_SKILL_POLICY_ZH",
    "TECHNICAL_SKILL_RULES_EN",
    "get_default_active_skill_ids",
    "get_default_router_skill_ids",
    "get_primary_default_skill_id",
    "get_regime_skill_ids",
    "load_skill_from_markdown",
    "load_skill_from_yaml",
    "load_skills_from_directory",
]


def __getattr__(name):
    if name == "SkillAgent":
        from src.agent.skills.skill_agent import SkillAgent

        return SkillAgent
    if name == "SkillRouter":
        from src.agent.skills.router import SkillRouter

        return SkillRouter
    if name == "SkillAggregator":
        from src.agent.skills.aggregator import SkillAggregator

        return SkillAggregator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
