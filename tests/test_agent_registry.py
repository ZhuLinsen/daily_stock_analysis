# -*- coding: utf-8 -*-
"""
Tests for ToolRegistry, ToolDefinition, ToolParameter, and SkillManager.

Covers:
- Tool registration, lookup, listing, and removal
- Multi-provider schema generation (Gemini / OpenAI / Anthropic)
- Tool execution and error handling
- @tool decorator with type-hint inference
- SkillManager registration, activation, and prompt generation
"""

import unittest
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.agent.tools.registry import (
    ToolRegistry,
    ToolDefinition,
    ToolParameter,
    _infer_parameters,
)
from src.agent.skills.base import Skill, SkillManager


def _builtin_strategy_names() -> set[str]:
    strategies_dir = Path(__file__).resolve().parent.parent / "strategies"
    return {path.stem for path in strategies_dir.glob("*.yaml")}


# ============================================================
# Helpers
# ============================================================

def _make_tool(name: str = "test_tool", category: str = "data") -> ToolDefinition:
    """Create a simple ToolDefinition for testing."""
    return ToolDefinition(
        name=name,
        description=f"Test tool: {name}",
        parameters=[
            ToolParameter(name="stock_code", type="string", description="Stock code", required=True),
            ToolParameter(name="days", type="integer", description="Number of days", required=False, default=30),
        ],
        handler=lambda stock_code, days=30: {"code": stock_code, "days": days},
        category=category,
    )


def _make_skill(name: str = "test_skill", enabled: bool = True) -> Skill:
    """Create a simple Skill for testing."""
    return Skill(
        name=name,
        display_name=f"Test Skill ({name})",
        description=f"Test description for {name}",
        instructions=f"Instructions for {name}",
        required_tools=["get_realtime_quote"],
        enabled=enabled,
    )


# ============================================================
# ToolRegistry Tests
# ============================================================

class TestToolRegistry(unittest.TestCase):
    """Test ToolRegistry core operations."""

    def setUp(self):
        self.registry = ToolRegistry()

    def test_register_and_get(self):
        tool = _make_tool("alpha")
        self.registry.register(tool)
        self.assertIn("alpha", self.registry)
        self.assertEqual(self.registry.get("alpha"), tool)

    def test_register_overwrite(self):
        tool1 = _make_tool("dup")
        tool2 = _make_tool("dup")
        tool2.description = "overwritten"
        self.registry.register(tool1)
        self.registry.register(tool2)
        self.assertEqual(self.registry.get("dup").description, "overwritten")

    def test_unregister(self):
        tool = _make_tool("removable")
        self.registry.register(tool)
        self.assertIn("removable", self.registry)
        self.registry.unregister("removable")
        self.assertNotIn("removable", self.registry)

    def test_unregister_nonexistent(self):
        # Should not raise
        self.registry.unregister("ghost")

    def test_get_nonexistent(self):
        self.assertIsNone(self.registry.get("nonexistent"))

    def test_list_tools(self):
        self.registry.register(_make_tool("a", category="data"))
        self.registry.register(_make_tool("b", category="search"))
        self.registry.register(_make_tool("c", category="data"))
        self.assertEqual(len(self.registry.list_tools()), 3)
        self.assertEqual(len(self.registry.list_tools(category="data")), 2)
        self.assertEqual(len(self.registry.list_tools(category="search")), 1)

    def test_list_names(self):
        self.registry.register(_make_tool("x"))
        self.registry.register(_make_tool("y"))
        names = self.registry.list_names()
        self.assertIn("x", names)
        self.assertIn("y", names)

    def test_len_and_contains(self):
        self.assertEqual(len(self.registry), 0)
        self.registry.register(_make_tool("t"))
        self.assertEqual(len(self.registry), 1)
        self.assertTrue("t" in self.registry)
        self.assertFalse("z" in self.registry)

    def test_execute_success(self):
        tool = _make_tool("exec_test")
        self.registry.register(tool)
        result = self.registry.execute("exec_test", stock_code="600519", days=10)
        self.assertEqual(result, {"code": "600519", "days": 10})

    def test_execute_default_param(self):
        tool = _make_tool("default_test")
        self.registry.register(tool)
        result = self.registry.execute("default_test", stock_code="600519")
        self.assertEqual(result["days"], 30)

    def test_execute_not_found(self):
        with self.assertRaises(KeyError):
            self.registry.execute("not_exist", stock_code="600519")

    def test_execute_handler_error(self):
        def bad_handler(**kwargs):
            raise ValueError("boom")

        tool = ToolDefinition(
            name="bad_tool",
            description="Fails",
            parameters=[],
            handler=bad_handler,
        )
        self.registry.register(tool)
        with self.assertRaises(ValueError):
            self.registry.execute("bad_tool")


# ============================================================
# Schema generation tests
# ============================================================

class TestToolDefinitionSchemas(unittest.TestCase):
    """Test schema generation (OpenAI format used by litellm for all providers)."""

    def setUp(self):
        self.tool = _make_tool("quote_tool")

    def test_openai_tool(self):
        oai = self.tool.to_openai_tool()
        self.assertEqual(oai["type"], "function")
        func = oai["function"]
        self.assertEqual(func["name"], "quote_tool")
        schema = func["parameters"]
        self.assertEqual(schema["type"], "object")
        self.assertIn("stock_code", schema["properties"])
        self.assertIn("stock_code", schema["required"])
        self.assertNotIn("days", schema["required"])

    def test_enum_parameter(self):
        tool = ToolDefinition(
            name="enum_tool",
            description="Test enum",
            parameters=[
                ToolParameter(
                    name="direction",
                    type="string",
                    description="Direction",
                    enum=["buy", "sell", "hold"],
                ),
            ],
            handler=lambda direction: direction,
        )
        oai = tool.to_openai_tool()
        self.assertEqual(oai["function"]["parameters"]["properties"]["direction"]["enum"], ["buy", "sell", "hold"])

    def test_registry_bulk_schemas(self):
        reg = ToolRegistry()
        reg.register(_make_tool("t1"))
        reg.register(_make_tool("t2"))
        self.assertEqual(len(reg.to_openai_tools()), 2)


# ============================================================
# @tool decorator / _infer_parameters tests
# ============================================================

class TestInferParameters(unittest.TestCase):
    """Test _infer_parameters from type hints."""

    def test_basic_types(self):
        def my_func(code: str, count: int, ratio: float, flag: bool):
            pass

        params = _infer_parameters(my_func)
        self.assertEqual(len(params), 4)
        type_map = {p.name: p.type for p in params}
        self.assertEqual(type_map["code"], "string")
        self.assertEqual(type_map["count"], "integer")
        self.assertEqual(type_map["ratio"], "number")
        self.assertEqual(type_map["flag"], "boolean")

    def test_default_values(self):
        def my_func(code: str, days: int = 30):
            pass

        params = _infer_parameters(my_func)
        code_p = next(p for p in params if p.name == "code")
        days_p = next(p for p in params if p.name == "days")
        self.assertTrue(code_p.required)
        self.assertFalse(days_p.required)
        self.assertEqual(days_p.default, 30)

    def test_list_type(self):
        from typing import List

        def my_func(items: List[str]):
            pass

        params = _infer_parameters(my_func)
        self.assertEqual(params[0].type, "array")

    def test_dict_type(self):
        from typing import Dict

        def my_func(data: Dict[str, int]):
            pass

        params = _infer_parameters(my_func)
        self.assertEqual(params[0].type, "object")

    def test_skip_self(self):
        def my_func(self, code: str):
            pass

        params = _infer_parameters(my_func)
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0].name, "code")


# ============================================================
# SkillManager Tests
# ============================================================

class TestSkillManager(unittest.TestCase):
    """Test SkillManager operations."""

    def setUp(self):
        self.manager = SkillManager()

    def test_register_and_get(self):
        skill = _make_skill("s1")
        self.manager.register(skill)
        self.assertEqual(self.manager.get("s1"), skill)

    def test_get_nonexistent(self):
        self.assertIsNone(self.manager.get("ghost"))

    def test_list_skills(self):
        self.manager.register(_make_skill("a"))
        self.manager.register(_make_skill("b"))
        self.assertEqual(len(self.manager.list_skills()), 2)

    def test_list_active_skills(self):
        self.manager.register(_make_skill("a", enabled=True))
        self.manager.register(_make_skill("b", enabled=False))
        active = self.manager.list_active_skills()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].name, "a")

    def test_activate_specific(self):
        self.manager.register(_make_skill("x", enabled=True))
        self.manager.register(_make_skill("y", enabled=True))
        self.manager.register(_make_skill("z", enabled=True))
        self.manager.activate(["y"])
        active_names = [s.name for s in self.manager.list_active_skills()]
        self.assertIn("y", active_names)
        self.assertNotIn("x", active_names)
        self.assertNotIn("z", active_names)

    def test_activate_all(self):
        self.manager.register(_make_skill("a", enabled=False))
        self.manager.register(_make_skill("b", enabled=False))
        self.manager.activate(["all"])
        self.assertEqual(len(self.manager.list_active_skills()), 2)

    def test_get_skill_instructions_empty(self):
        self.assertEqual(self.manager.get_skill_instructions(), "")

    def test_get_skill_instructions_content(self):
        self.manager.register(_make_skill("demo"))
        instructions = self.manager.get_skill_instructions()
        self.assertIn("Test Skill (demo)", instructions)
        self.assertIn("Instructions for demo", instructions)
        self.assertIn("策略 1:", instructions)

    def test_get_required_tools(self):
        s1 = _make_skill("s1")
        s1.required_tools = ["tool_a", "tool_b"]
        s2 = _make_skill("s2")
        s2.required_tools = ["tool_b", "tool_c"]
        self.manager.register(s1)
        self.manager.register(s2)
        required = set(self.manager.get_required_tools())
        self.assertEqual(required, {"tool_a", "tool_b", "tool_c"})

    def test_get_required_tools_respects_enabled(self):
        s1 = _make_skill("s1", enabled=True)
        s1.required_tools = ["tool_a"]
        s2 = _make_skill("s2", enabled=False)
        s2.required_tools = ["tool_b"]
        self.manager.register(s1)
        self.manager.register(s2)
        required = self.manager.get_required_tools()
        self.assertIn("tool_a", required)
        self.assertNotIn("tool_b", required)


# ============================================================
# Built-in skills import test
# ============================================================

class TestBuiltinSkills(unittest.TestCase):
    """Verify all built-in strategies load from YAML and have correct structure."""

    def test_load_all_builtin_strategies(self):
        """Load strategies from YAML files in strategies/ directory."""
        from src.agent.skills.base import SkillManager

        manager = SkillManager()
        expected = _builtin_strategy_names()
        count = manager.load_builtin_strategies()
        self.assertEqual(count, len(expected), "Should load all built-in strategies from YAML")

        skills = manager.list_skills()
        names = set()
        for skill in skills:
            self.assertIsInstance(skill, Skill)
            self.assertTrue(len(skill.name) > 0)
            self.assertTrue(len(skill.display_name) > 0)
            self.assertTrue(len(skill.instructions) > 0)
            self.assertIsInstance(skill.required_tools, list)
            self.assertEqual(skill.source, "builtin")
            names.add(skill.name)

        # All names should be unique
        self.assertEqual(len(names), len(expected))

        # Verify all strategy names from YAML are loaded
        self.assertEqual(names, expected)


# ============================================================
# Built-in tools import test
# ============================================================

class TestBuiltinToolDefinitions(unittest.TestCase):
    """Verify all tool definitions can be imported and are valid."""

    def test_import_data_tools(self):
        from src.agent.tools.data_tools import ALL_DATA_TOOLS
        self.assertGreater(len(ALL_DATA_TOOLS), 0, "ALL_DATA_TOOLS must not be empty")
        for td in ALL_DATA_TOOLS:
            self.assertIsInstance(td, ToolDefinition)
            self.assertTrue(len(td.name) > 0)
            self.assertEqual(td.category, "data")

    def test_import_analysis_tools(self):
        from src.agent.tools.analysis_tools import ALL_ANALYSIS_TOOLS
        self.assertGreater(len(ALL_ANALYSIS_TOOLS), 0, "ALL_ANALYSIS_TOOLS must not be empty")
        for td in ALL_ANALYSIS_TOOLS:
            self.assertIsInstance(td, ToolDefinition)
            self.assertEqual(td.category, "analysis")

    def test_import_search_tools(self):
        from src.agent.tools.search_tools import ALL_SEARCH_TOOLS
        self.assertGreater(len(ALL_SEARCH_TOOLS), 0, "ALL_SEARCH_TOOLS must not be empty")
        for td in ALL_SEARCH_TOOLS:
            self.assertIsInstance(td, ToolDefinition)
            self.assertEqual(td.category, "search")

    def test_import_market_tools(self):
        from src.agent.tools.market_tools import ALL_MARKET_TOOLS
        self.assertGreater(len(ALL_MARKET_TOOLS), 0, "ALL_MARKET_TOOLS must not be empty")
        for td in ALL_MARKET_TOOLS:
            self.assertIsInstance(td, ToolDefinition)
            self.assertEqual(td.category, "market")

    def test_all_tools_have_valid_schemas(self):
        """All tools should generate valid OpenAI-format schemas (used by litellm)."""
        from src.agent.tools.data_tools import ALL_DATA_TOOLS
        from src.agent.tools.analysis_tools import ALL_ANALYSIS_TOOLS
        from src.agent.tools.search_tools import ALL_SEARCH_TOOLS
        from src.agent.tools.market_tools import ALL_MARKET_TOOLS

        all_tools = ALL_DATA_TOOLS + ALL_ANALYSIS_TOOLS + ALL_SEARCH_TOOLS + ALL_MARKET_TOOLS
        for td in all_tools:
            oai = td.to_openai_tool()
            self.assertEqual(oai["type"], "function")
            self.assertIn("parameters", oai["function"])


if __name__ == '__main__':
    unittest.main()


# ============================================================
# YAML strategy loading tests
# ============================================================

class TestYAMLStrategyLoading(unittest.TestCase):
    """Test loading strategies from YAML files."""

    def test_load_single_yaml(self):
        """Load a single strategy from a YAML file."""
        import tempfile, os
        from src.agent.skills.base import load_skill_from_yaml, Skill

        yaml_content = """
name: test_yaml_strategy
display_name: 测试YAML策略
description: 一个用于测试的策略
category: trend
core_rules: [1, 3]
required_tools:
  - analyze_trend
  - get_daily_history
instructions: |
  **测试策略**

  这是一个用自然语言编写的测试策略。
  判断标准：当 MA5 > MA10 时买入。
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(yaml_content)
            tmp_path = f.name

        try:
            skill = load_skill_from_yaml(tmp_path)
            self.assertIsInstance(skill, Skill)
            self.assertEqual(skill.name, "test_yaml_strategy")
            self.assertEqual(skill.display_name, "测试YAML策略")
            self.assertEqual(skill.category, "trend")
            self.assertEqual(skill.core_rules, [1, 3])
            self.assertEqual(skill.required_tools, ["analyze_trend", "get_daily_history"])
            self.assertIn("自然语言", skill.instructions)
            self.assertFalse(skill.enabled)
        finally:
            os.unlink(tmp_path)

    def test_load_minimal_yaml(self):
        """Load a strategy with only required fields."""
        import tempfile, os
        from src.agent.skills.base import load_skill_from_yaml

        yaml_content = """
name: minimal
display_name: 最简策略
description: 最简描述
instructions: 用自然语言描述的策略内容
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(yaml_content)
            tmp_path = f.name

        try:
            skill = load_skill_from_yaml(tmp_path)
            self.assertEqual(skill.name, "minimal")
            self.assertEqual(skill.category, "trend")  # default
            self.assertEqual(skill.core_rules, [])
            self.assertEqual(skill.required_tools, [])
        finally:
            os.unlink(tmp_path)

    def test_load_yaml_missing_required_fields(self):
        """YAML missing required fields should raise ValueError."""
        import tempfile, os
        from src.agent.skills.base import load_skill_from_yaml

        yaml_content = """
name: incomplete
display_name: 不完整
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
            f.write(yaml_content)
            tmp_path = f.name

        try:
            with self.assertRaises(ValueError):
                load_skill_from_yaml(tmp_path)
        finally:
            os.unlink(tmp_path)

    def test_load_nonexistent_file(self):
        """Loading a nonexistent file should raise FileNotFoundError."""
        from src.agent.skills.base import load_skill_from_yaml
        with self.assertRaises(FileNotFoundError):
            load_skill_from_yaml("/nonexistent/path.yaml")

    def test_load_directory(self):
        """Load all strategies from a directory."""
        import tempfile, os
        from src.agent.skills.base import load_skills_from_directory

        tmpdir = tempfile.mkdtemp()
        try:
            # Create two valid YAML files
            for i, name in enumerate(["strategy_a", "strategy_b"]):
                with open(os.path.join(tmpdir, f"{name}.yaml"), 'w', encoding='utf-8') as f:
                    f.write(f"""
name: {name}
display_name: 策略{chr(65 + i)}
description: 描述{chr(65 + i)}
instructions: 自然语言策略描述 {name}
""")

            # Create an invalid YAML file (should be skipped)
            with open(os.path.join(tmpdir, "bad.yaml"), 'w', encoding='utf-8') as f:
                f.write("name: bad\n")  # missing required fields

            # A non-YAML file should be ignored
            with open(os.path.join(tmpdir, "ignore.txt"), 'w') as f:
                f.write("not a strategy")

            skills = load_skills_from_directory(tmpdir)
            # Only 2 valid strategies (bad.yaml skipped, ignore.txt ignored)
            self.assertEqual(len(skills), 2)
            names = {s.name for s in skills}
            self.assertEqual(names, {"strategy_a", "strategy_b"})
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_custom_overrides_builtin(self):
        """Custom strategy with same name should override built-in."""
        import tempfile, os
        from src.agent.skills.base import SkillManager

        manager = SkillManager()
        manager.load_builtin_strategies()

        # Verify dragon_head exists as builtin
        original = manager.get("dragon_head")
        self.assertIsNotNone(original)
        self.assertEqual(original.source, "builtin")

        # Create a custom directory with an overriding strategy
        tmpdir = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmpdir, "dragon_head.yaml"), 'w', encoding='utf-8') as f:
                f.write("""
name: dragon_head
display_name: 自定义龙头策略
description: 我自己的龙头策略
instructions: 按照我的规则分析龙头股
""")
            manager.load_custom_strategies(tmpdir)

            overridden = manager.get("dragon_head")
            self.assertEqual(overridden.display_name, "自定义龙头策略")
            self.assertIn(tmpdir, overridden.source)
        finally:
            import shutil
            shutil.rmtree(tmpdir)

    def test_builtin_strategies_have_source_field(self):
        """All built-in strategies should have source='builtin'."""
        from src.agent.skills.base import SkillManager

        manager = SkillManager()
        manager.load_builtin_strategies()
        for skill in manager.list_skills():
            self.assertEqual(skill.source, "builtin",
                             f"Strategy {skill.name} should have source='builtin'")
