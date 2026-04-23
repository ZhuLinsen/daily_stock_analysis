# -*- coding: utf-8 -*-
"""
Trading skill base classes and SkillManager.

Skills are pluggable trading analysis modules defined in **natural language**
(YAML files). Each skill describes a common or custom trading pattern
(e.g., 龙头策略, 缩量回踩, 均线金叉) used for analysis and push notifications.

Users can write custom skills by creating a YAML file — no Python code needed.
The built-in YAML files still live under ``strategies/`` for compatibility.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# Built-in skill YAML directory (project_root/strategies/ kept for compatibility)
_BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "strategies"


@dataclass
class Skill:
    """A trading skill that can be injected into the agent prompt.

    Each skill represents a common or custom trading pattern used
    for stock analysis and push notifications. Strategies are typically
    loaded from YAML files written in natural language.

    Attributes:
        name: Unique strategy identifier (e.g., "dragon_head").
        display_name: Human-readable name (e.g., "龙头策略").
        description: Brief description of when to apply this strategy.
        instructions: Detailed natural language instructions injected into the system prompt.
        category: Skill category — "trend" (趋势), "pattern" (形态), "reversal" (反转), "framework" (框架).
        core_rules: List of core trading rule numbers this strategy relates to (1-7).
        required_tools: List of tool names this skill depends on.
        allowed_tools: Optional allowlist metadata from SKILL.md frontmatter.
        aliases: Optional alias phrases used by NL selectors / bot commands.
        enabled: Whether this skill is currently active.
        source: Origin of this skill — "builtin" or file path of a custom definition.
        entrypoint: Definition file path (YAML or SKILL.md).
        bundle_dir: Skill bundle directory when loaded from SKILL.md.
        disable_model_invocation: Whether the model should avoid auto-invoking this skill.
        user_invocable: Whether the skill should be exposed in user-facing selectors.
        default_active: Whether this skill participates in the default activation set.
        default_router: Whether this skill participates in router fallback selection.
        default_priority: Ordering hint for defaults / selectors (lower comes first).
        market_regimes: Optional market regime tags used by the skill router.
        execution_context: Inline/fork execution hint from frontmatter.
        subagent_type: Optional subagent type hint from frontmatter.
        preferred_model: Optional model hint from frontmatter.
    """
    name: str
    display_name: str
    description: str
    instructions: str
    category: str = "trend"
    core_rules: List[int] = field(default_factory=list)
    required_tools: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    enabled: bool = False
    source: str = "builtin"
    entrypoint: str = ""
    bundle_dir: str = ""
    disable_model_invocation: bool = False
    user_invocable: bool = True
    default_active: bool = False
    default_router: bool = False
    default_priority: int = 100
    market_regimes: List[str] = field(default_factory=list)
    execution_context: str = "inline"
    subagent_type: str = ""
    preferred_model: str = ""


_FRONTMATTER_RE = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?(.*)$", re.DOTALL)


def _coerce_string_list(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _coerce_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _coerce_int(value: object, default: int = 100) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_skill_frontmatter(raw_text: str) -> tuple[Dict[str, object], str]:
    import yaml

    match = _FRONTMATTER_RE.match(raw_text)
    if not match:
        return {}, raw_text.strip()

    metadata_raw, body = match.groups()
    metadata = yaml.safe_load(metadata_raw) or {}
    if not isinstance(metadata, dict):
        raise ValueError("Skill frontmatter must be a YAML mapping")
    return metadata, body.strip()


def _infer_skill_description(instructions: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", instructions or "") if part.strip()]
    if not paragraphs:
        return ""
    first = re.sub(r"\s+", " ", paragraphs[0]).strip()
    return first[:280]


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
    import yaml  # lazy import — only needed when loading skill YAML

    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Skill file not found: {filepath}")

    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid skill file (expected YAML mapping): {filepath}")

    # Validate required fields
    required_fields = ["name", "display_name", "description", "instructions"]
    missing = [fld for fld in required_fields if not data.get(fld)]
    if missing:
        raise ValueError(
            f"Skill file {filepath.name} missing required fields: {missing}"
        )

    return Skill(
        name=str(data["name"]).strip(),
        display_name=str(data["display_name"]).strip(),
        description=str(data["description"]).strip(),
        instructions=str(data["instructions"]).strip(),
        category=str(data.get("category", "trend")).strip(),
        core_rules=data.get("core_rules", []) or [],
        required_tools=data.get("required_tools", []) or [],
        allowed_tools=_coerce_string_list(data.get("allowed_tools")),
        aliases=_coerce_string_list(data.get("aliases")),
        enabled=False,
        source=str(filepath),
        entrypoint=str(filepath),
        bundle_dir=str(filepath.parent),
        disable_model_invocation=bool(data.get("disable_model_invocation", False)),
        user_invocable=bool(data.get("user_invocable", True)),
        default_active=_coerce_bool(data.get("default_active"), False),
        default_router=_coerce_bool(data.get("default_router"), False),
        default_priority=_coerce_int(data.get("default_priority"), 100),
        market_regimes=(
            _coerce_string_list(data.get("market_regimes"))
            or _coerce_string_list(data.get("market-regimes"))
        ),
        execution_context=str(data.get("context", "inline")).strip() or "inline",
        subagent_type=str(data.get("agent", "")).strip(),
        preferred_model=str(data.get("model", "")).strip(),
    )


def load_skill_from_markdown(filepath: Union[str, Path]) -> Skill:
    """Load a single skill from a `SKILL.md` bundle entrypoint."""
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Skill file not found: {filepath}")

    raw_text = filepath.read_text(encoding="utf-8")
    metadata, instructions = _parse_skill_frontmatter(raw_text)
    if not instructions:
        raise ValueError(f"Skill file {filepath.name} missing markdown instructions")

    skill_name = str(metadata.get("name") or filepath.parent.name).strip()
    display_name = str(
        metadata.get("display_name")
        or metadata.get("title")
        or skill_name
    ).strip()
    description = str(
        metadata.get("description")
        or _infer_skill_description(instructions)
    ).strip()
    if not skill_name or not description:
        raise ValueError(f"Skill file {filepath.name} missing required name/description")

    allowed_tools = _coerce_string_list(metadata.get("allowed-tools"))
    if not allowed_tools:
        allowed_tools = _coerce_string_list(metadata.get("allowed_tools"))
    required_tools = _coerce_string_list(metadata.get("required-tools"))
    if not required_tools:
        required_tools = _coerce_string_list(metadata.get("required_tools"))

    return Skill(
        name=skill_name,
        display_name=display_name,
        description=description,
        instructions=instructions,
        category=str(metadata.get("category", "general")).strip() or "general",
        core_rules=metadata.get("core_rules", []) or [],
        required_tools=required_tools,
        allowed_tools=allowed_tools,
        aliases=_coerce_string_list(metadata.get("aliases")),
        enabled=False,
        source=str(filepath),
        entrypoint=str(filepath),
        bundle_dir=str(filepath.parent),
        disable_model_invocation=_coerce_bool(metadata.get("disable-model-invocation"), False),
        user_invocable=_coerce_bool(metadata.get("user-invocable"), True),
        default_active=_coerce_bool(
            metadata.get("default-active", metadata.get("default_active")),
            False,
        ),
        default_router=_coerce_bool(
            metadata.get("default-router", metadata.get("default_router")),
            False,
        ),
        default_priority=_coerce_int(
            metadata.get("default-priority", metadata.get("default_priority")),
            100,
        ),
        market_regimes=(
            _coerce_string_list(metadata.get("market-regimes"))
            or _coerce_string_list(metadata.get("market_regimes"))
        ),
        execution_context=str(metadata.get("context", "inline")).strip() or "inline",
        subagent_type=str(metadata.get("agent", "")).strip(),
        preferred_model=str(metadata.get("model", "")).strip(),
    )


def load_skills_from_directory(directory: Union[str, Path]) -> List[Skill]:
    """Load all skills from YAML files in a directory.

    Scans for top-level ``*.yaml`` / ``*.yml`` compatibility files and
    nested ``SKILL.md`` bundles, sorted alphabetically.
    Skips files that fail to parse (logs a warning).

    Args:
        directory: Path to the directory containing skill definitions.

    Returns:
        List of ``Skill`` instances (all disabled by default).
    """
    directory = Path(directory)
    if not directory.is_dir():
        logger.warning(f"Skill directory does not exist: {directory}")
        return []

    skills: List[Skill] = []
    yaml_files = sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))
    markdown_files = sorted(directory.rglob("SKILL.md"))

    for filepath in yaml_files:
        try:
            skill = load_skill_from_yaml(filepath)
            skills.append(skill)
            logger.debug(f"Loaded skill from YAML: {skill.name} ({filepath.name})")
        except Exception as e:
            logger.warning(f"Failed to load skill from {filepath.name}: {e}")

    for filepath in markdown_files:
        try:
            skill = load_skill_from_markdown(filepath)
            skills.append(skill)
            logger.debug(f"Loaded skill bundle: {skill.name} ({filepath})")
        except Exception as e:
            logger.warning(f"Failed to load skill bundle from {filepath}: {e}")

    return skills


class SkillManager:
    """Manages trading skills and generates combined prompt instructions.

    Supports loading skills from:
    1. YAML files in the built-in ``strategies/`` directory
    2. YAML files in a user-specified custom directory
    3. Programmatic ``Skill`` instances (backward compatible)

    Usage::

        manager = SkillManager()
        # Load built-in + custom skills from YAML
        manager.load_builtin_skills()
        manager.load_custom_skills("./my_skills")
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
        logger.debug(f"Registered skill: {skill.name} ({skill.display_name})")

    def load_builtin_skills(self) -> int:
        """Load all built-in skills from the compatibility `strategies/` directory.

        Returns:
            Number of skills loaded.
        """
        skills_dir = _BUILTIN_SKILLS_DIR
        if not skills_dir.is_dir():
            logger.warning(f"Built-in skill directory not found: {skills_dir}")
            return 0

        skills = load_skills_from_directory(skills_dir)
        for skill in skills:
            skill.source = "builtin"
            self.register(skill)

        logger.info(f"Loaded {len(skills)} built-in skills from {skills_dir}")
        return len(skills)

    def load_custom_skills(self, directory: Union[str, Path, None]) -> int:
        """Load custom skills from a user-specified directory.

        Custom skills override built-in ones if names conflict.

        Args:
            directory: Path to the custom skill directory.
                       If None or empty, does nothing.

        Returns:
            Number of skills loaded.
        """
        if not directory:
            return 0

        directory = Path(directory)
        if not directory.is_dir():
            logger.warning(f"Custom skill directory does not exist: {directory}")
            return 0

        skills = load_skills_from_directory(directory)
        for skill in skills:
            if skill.name in self._skills:
                logger.info(
                    f"Custom skill '{skill.name}' overrides built-in"
                )
            self.register(skill)

        logger.info(f"Loaded {len(skills)} custom skills from {directory}")
        return len(skills)

    def load_builtin_strategies(self) -> int:
        """Compatibility wrapper for older call sites."""
        return self.load_builtin_skills()

    def load_custom_strategies(self, directory: Union[str, Path, None]) -> int:
        """Compatibility wrapper for older call sites."""
        return self.load_custom_skills(directory)

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
            logger.info(f"Activated all {len(self._skills)} skills")
            return

        for s in self._skills.values():
            s.enabled = s.name in skill_names

        activated = [s.name for s in self._skills.values() if s.enabled]
        logger.info(f"Activated skills: {activated}")

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
            parts.append(f"#### {cat_label}类技能\n")
            for skill in skills_in_cat:
                rules_ref = ""
                if skill.core_rules:
                    rules_ref = f"（关联核心理念：第{'、'.join(str(r) for r in skill.core_rules)}条）"
                support_ref = ""
                if skill.bundle_dir and skill.entrypoint.endswith("SKILL.md"):
                    support_ref = "（bundle）"
                parts.append(
                    f"### 技能 {idx}: {skill.display_name} {rules_ref}{support_ref}\n\n"
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
