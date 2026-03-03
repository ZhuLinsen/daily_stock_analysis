# -*- coding: utf-8 -*-
"""
Agent skills package.

Provides pluggable trading strategy skills for the agent.
Strategies are defined in natural language (YAML files) — no Python code needed.
"""

from src.agent.skills.base import Skill, SkillManager, load_skill_from_yaml, load_skills_from_directory

__all__ = ["Skill", "SkillManager", "load_skill_from_yaml", "load_skills_from_directory"]
