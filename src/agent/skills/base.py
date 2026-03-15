# -*- coding: utf-8 -*-
"""
Strategy (Skill) base classes and SkillManager.

Strategies are pluggable trading analysis modules defined in **natural language**
(YAML files). Each strategy describes a common or custom trading pattern
(e.g., 龙头策略, 缩量回踩, 均线金叉) used for analysis and push notifications.

Users can write custom strategies by creating a YAML file — no Python code needed.
See ``strategies/README.md`` for the format specification.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# Built-in strategies directory (project_root/strategies/)
_BUILTIN_STRATEGIES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "strategies"


@dataclass
class Skill:
    """A trading strategy that can be injected into the agent prompt.

    Each strategy represents a common or custom trading pattern used
    for stock analysis and push notifications. Strategies are typically
    loaded from YAML files written in natural language.

    Attributes:
        name: Unique strategy identifier (e.g., "dragon_head").
        display_name: Human-readable name (e.g., "龙头策略").
        description: Brief description of when to apply this strategy.
        instructions: Detailed natural language instructions injected into the system prompt.
        category: Strategy category — "trend" (趋势), "pattern" (形态), "reversal" (反转), "framework" (框架).
        core_rules: List of core trading rule numbers this strategy relates to (1-7).
        required_tools: List of tool names this strategy depends on.
        enabled: Whether this strategy is currently active.
        source: Origin of this strategy — "builtin" or file path of a custom YAML.
    """
    name: str
    display_name: str
    description: str
    instructions: str
    category: str = "trend"
    core_rules: List[int] = field(default_factory=list)
    required_tools: List[str] = field(default_factory=list)
    enabled: bool = False
    source: str = "builtin"


def load_skill_from_yaml(filepath: Union[str, Path]) -> Skill:
    """Load a single Skill from a YAML file.

    The YAML file must contain at minimum: ``name``, ``display_name``,
    ``description``, and ``instructions``. All values are natural language text.

    Args:
        filepath: Path to the ``.yaml`` file.

    Returns:
        A ``Skill`` instance with ``enabled=False``.

    Raises:
        ValueError: If required fields are missing or the file is invalid.
        FileNotFoundError: If the file does not exist.
    """
    import yaml  # lazy import — only needed when loading strategies

    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Strategy file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid strategy file (expected YAML mapping): {filepath}")

    # Validate required fields
    required_fields = ["name", "display_name", "description", "instructions"]
    missing = [fld for fld in required_fields if not data.get(fld)]
    if missing:
        raise ValueError(
            f"Strategy file {filepath.name} missing required fields: {missing}"
        )

    return Skill(
        name=str(data["name"]).strip(),
        display_name=str(data["display_name"]).strip(),
        description=str(data["description"]).strip(),
        instructions=str(data["instructions"]).strip(),
        category=str(data.get("category", "trend")).strip(),
        core_rules=data.get("core_rules", []) or [],
        required_tools=data.get("required_tools", []) or [],
        enabled=False,
        source=str(filepath),
    )


def load_skills_from_directory(directory: Union[str, Path]) -> List[Skill]:
    """Load all strategies from YAML files in a directory.

    Scans for ``*.yaml`` and ``*.yml`` files, sorted alphabetically.
    Skips files that fail to parse (logs a warning).

    Args:
        directory: Path to the directory containing YAML strategy files.

    Returns:
        List of ``Skill`` instances (all disabled by default).
    """
    directory = Path(directory)
    if not directory.is_dir():
        logger.warning(f"Strategy directory does not exist: {directory}")
        return []

    skills: List[Skill] = []
    yaml_files = sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))

    for filepath in yaml_files:
        try:
            skill = load_skill_from_yaml(filepath)
            skills.append(skill)
            logger.debug(f"Loaded strategy from YAML: {skill.name} ({filepath.name})")
        except Exception as e:
            logger.warning(f"Failed to load strategy from {filepath.name}: {e}")

    return skills


class SkillManager:
    """Manages strategy plugins and generates combined prompt instructions.

    Supports loading strategies from:
    1. YAML files in the built-in ``strategies/`` directory
    2. YAML files in a user-specified custom directory
    3. Programmatic ``Skill`` instances (backward compatible)

    Usage::

        manager = SkillManager()
        # Load built-in + custom strategies from YAML
        manager.load_builtin_strategies()
        manager.load_custom_strategies("./my_strategies")
        # Or register programmatically
        manager.register(some_skill)
        # Activate and generate prompt
        manager.activate(["dragon_head", "shrink_pullback"])
        instructions = manager.get_skill_instructions()
    """

    def __init__(self):
        self._skills: Dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """Register a skill (programmatic or YAML-loaded)."""
        self._skills[skill.name] = skill
        logger.debug(f"Registered strategy: {skill.name} ({skill.display_name})")

    def load_builtin_strategies(self) -> int:
        """Load all built-in strategies from the ``strategies/`` directory.

        Returns:
            Number of strategies loaded.
        """
        strategies_dir = _BUILTIN_STRATEGIES_DIR
        if not strategies_dir.is_dir():
            logger.warning(f"Built-in strategies directory not found: {strategies_dir}")
            return 0

        skills = load_skills_from_directory(strategies_dir)
        for skill in skills:
            skill.source = "builtin"
            self.register(skill)

        logger.info(f"Loaded {len(skills)} built-in strategies from {strategies_dir}")
        return len(skills)

    def load_custom_strategies(self, directory: Union[str, Path, None]) -> int:
        """Load custom strategies from a user-specified directory.

        Custom strategies override built-in ones if names conflict.

        Args:
            directory: Path to the custom strategies directory.
                       If None or empty, does nothing.

        Returns:
            Number of strategies loaded.
        """
        if not directory:
            return 0

        directory = Path(directory)
        if not directory.is_dir():
            logger.warning(f"Custom strategy directory does not exist: {directory}")
            return 0

        skills = load_skills_from_directory(directory)
        for skill in skills:
            skill.source = str(directory / f"{skill.name}.yaml")
            if skill.name in self._skills:
                logger.info(
                    f"Custom strategy '{skill.name}' overrides built-in"
                )
            self.register(skill)

        logger.info(f"Loaded {len(skills)} custom strategies from {directory}")
        return len(skills)

    def get(self, name: str) -> Optional[Skill]:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> List[Skill]:
        """List all registered skills."""
        return list(self._skills.values())

    def list_active_skills(self) -> List[Skill]:
        """List only active (enabled) skills."""
        return [s for s in self._skills.values() if s.enabled]

    def activate(self, skill_names: List[str]) -> None:
        """Activate specific skills by name. Deactivate all others.

        Args:
            skill_names: List of skill names to activate.
                         If ["all"], activate everything.
        """
        if skill_names == ["all"] or "all" in skill_names:
            for s in self._skills.values():
                s.enabled = True
            logger.info(f"Activated all {len(self._skills)} strategies")
            return

        for s in self._skills.values():
            s.enabled = s.name in skill_names

        activated = [s.name for s in self._skills.values() if s.enabled]
        logger.info(f"Activated strategies: {activated}")

    def get_skill_instructions(self) -> str:
        """Generate combined instruction text for all active skills.

        Returns a formatted string ready to be injected into the agent
        system prompt, organized by category.
        """
        active = self.list_active_skills()
        if not active:
            return ""

        # Group by category
        categories = {"trend": "趋势", "pattern": "形态", "reversal": "反转", "framework": "框架"}
        grouped: Dict[str, List[Skill]] = {}
        for skill in active:
            cat = skill.category or "trend"
            grouped.setdefault(cat, []).append(skill)

        parts = []
        idx = 1
        # Render known categories in fixed order, then any remaining custom categories
        ordered_keys = ["trend", "pattern", "reversal", "framework"]
        for cat_key in ordered_keys + [k for k in grouped if k not in ordered_keys]:
            skills_in_cat = grouped.get(cat_key, [])
            if not skills_in_cat:
                continue
            cat_label = categories.get(cat_key, cat_key)
            parts.append(f"#### {cat_label}类策略\n")
            for skill in skills_in_cat:
                rules_ref = ""
                if skill.core_rules:
                    rules_ref = f"（关联核心理念：第{'、'.join(str(r) for r in skill.core_rules)}条）"
                parts.append(
                    f"### 策略 {idx}: {skill.display_name} {rules_ref}\n\n"
                    f"**适用场景**: {skill.description}\n\n"
                    f"{skill.instructions}\n"
                )
                idx += 1

        return "\n".join(parts)

    def get_required_tools(self) -> List[str]:
        """Get all tool names required by active skills."""
        tools: set = set()
        for s in self.list_active_skills():
            tools.update(s.required_tools)
        return list(tools)
