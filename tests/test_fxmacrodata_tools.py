"""Offline native registry tests; all values below are test fixtures."""
import json
from pathlib import Path

import pytest

from fxmacrodata_public import Result, list_operations
from src.agent.tools import fxmacrodata_tools
from src.agent.tools.fxmacrodata_tools import build_fxmacrodata_tools, fxmacrodata_tool_names
from src.agent.tools.registry import ToolRegistry


class FixtureClient:
    def execute(self, operation, arguments):
        return Result(operation, {"data": [{"val": 1.25, "announcement_datetime": 1000000000,
                                          "source_url": "https://example.org/release"}],
                                  "requested": arguments})


@pytest.mark.parametrize("operation", list_operations(), ids=lambda operation: operation.name)
def test_every_operation_is_a_native_tool(operation):
    registry = ToolRegistry()
    for definition in build_fxmacrodata_tools(FixtureClient()):
        registry.register(definition)
    tool = registry.get(f"fxmacrodata_{operation.name}")
    assert tool.to_openai_tool()["function"]["parameters"] == operation.input_schema
    assert tool.to_mcp_descriptor()["inputSchema"] == operation.input_schema
    assert registry.validate_tool_policies(strict=True) == []
    result = registry.execute(tool.name)
    assert result["records"][0]["val"] == 1.25
    assert result["data"]["data"][0]["announcement_datetime"] == 1000000000
    assert "utm_source=daily_stock_analysis" in result["provider_url"]


def test_transport_failures_do_not_enter_report_logs():
    class FailingClient:
        def execute(self, *args):
            raise RuntimeError("transport detail must not appear")

    response = build_fxmacrodata_tools(FailingClient())[0].handler()
    assert response["status"] == "unavailable"
    assert "transport detail" not in json.dumps(response)


def test_client_construction_failures_degrade_to_unavailable(monkeypatch):
    class UnconstructableClient:
        def __init__(self, **kwargs):
            raise RuntimeError("construction detail must not appear")

    monkeypatch.setattr(fxmacrodata_tools, "FXMacroDataClient", UnconstructableClient)
    response = build_fxmacrodata_tools()[0].handler()
    assert response["status"] == "unavailable"
    assert response["records"] == []
    assert "construction detail" not in json.dumps(response)


def test_owned_client_is_closed_after_execute_failure(monkeypatch):
    closed = []

    class OwnedFailingClient:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == ""

        def execute(self, *args):
            raise RuntimeError("transport detail must not appear")

        def close(self):
            closed.append(True)

    monkeypatch.delenv("FXMACRODATA_API_KEY", raising=False)
    monkeypatch.setattr(fxmacrodata_tools, "FXMacroDataClient", OwnedFailingClient)
    response = build_fxmacrodata_tools()[0].handler()
    assert response["status"] == "unavailable"
    assert "transport detail" not in json.dumps(response)
    assert closed == [True]


def test_close_failure_keeps_unavailable_result(monkeypatch):
    class CloseFailingClient:
        def __init__(self, **kwargs):
            pass

        def execute(self, *args):
            raise RuntimeError("transport detail must not appear")

        def close(self):
            raise RuntimeError("close detail must not appear")

    monkeypatch.setattr(fxmacrodata_tools, "FXMacroDataClient", CloseFailingClient)
    response = build_fxmacrodata_tools()[0].handler()
    assert response["status"] == "unavailable"
    assert response["records"] == []
    assert "detail must not appear" not in json.dumps(response)


def test_factory_registers_tools_for_report_and_chat():
    # Execute the exact factory registration function without importing unrelated
    # data providers, whose startup requires the application's full dependencies.
    import ast
    import sys
    import types
    from unittest.mock import patch

    source = Path(__file__).resolve().parents[1] / "src/agent/factory.py"
    node = next(node for node in ast.parse(source.read_text(encoding="utf-8")).body
                if isinstance(node, ast.FunctionDef) and node.name == "_build_tool_registry")
    modules = {}
    for name in ("data", "analysis", "search", "market", "backtest"):
        module = types.ModuleType(f"src.agent.tools.{name}_tools")
        setattr(module, f"ALL_{name.upper()}_TOOLS", [])
        modules[module.__name__] = module
    namespace = {}
    with patch.dict(sys.modules, modules):
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), namespace)
        registry = namespace["_build_tool_registry"]({"market": 35})
    assert set(registry.list_names()) == {f"fxmacrodata_{op.name}" for op in list_operations()}


@pytest.mark.parametrize("specialist", ["intel", "risk", "portfolio"])
def test_native_multi_agent_filter_keeps_specialist_macro_tools(specialist):
    import ast
    import logging
    from types import SimpleNamespace

    source_root = Path(__file__).resolve().parents[1] / "src/agent/agents"
    tree = ast.parse((source_root / f"{specialist}_agent.py").read_text(encoding="utf-8"))
    specialist_class = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    assignment = next(node for node in specialist_class.body
                      if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "tool_names"
                              for target in node.targets))
    namespace = {"fxmacrodata_tool_names": fxmacrodata_tool_names}
    exec(compile(ast.Module(body=[assignment], type_ignores=[]), str(source_root), "exec"), namespace)
    names = namespace["tool_names"]
    assert names and len(names) == len(set(names))

    # Exercise the upstream method that previously removed every FXMD tool.
    base = ast.parse((source_root / "base_agent.py").read_text(encoding="utf-8"))
    base_class = next(node for node in base.body if isinstance(node, ast.ClassDef)
                      and node.name == "BaseAgent")
    method = next(node for node in base_class.body if isinstance(node, ast.FunctionDef)
                  and node.name == "_filtered_registry")
    namespace.update(ToolRegistry=ToolRegistry, logger=logging.getLogger(__name__))
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source_root), "exec"), namespace)
    registry = ToolRegistry(category_timeout_map={"market": 35})
    for definition in build_fxmacrodata_tools(FixtureClient()):
        registry.register(definition)
    agent = SimpleNamespace(tool_names=names, tool_registry=registry, agent_name=specialist)
    filtered = namespace["_filtered_registry"](agent)
    assert set(filtered.list_names()) == {name for name in names if name.startswith("fxmacrodata_")}
    if specialist == "intel":
        assert set(filtered.list_names()) == set(fxmacrodata_tool_names())
    for name in filtered.list_names():
        assert filtered.execute(name)["records"][0]["val"] == 1.25


def test_specialist_selection_rejects_unknown_operation():
    with pytest.raises(ValueError, match="Unknown FXMacroData operation"):
        fxmacrodata_tool_names("not_an_operation")


def test_missing_operation_catalogue_disables_tools_without_breaking_import(monkeypatch):
    # A frozen build without the client's package data must not break the
    # registry: importing the module yields no FXMacroData tools.
    import importlib

    import fxmacrodata_public

    def missing_catalogue():
        raise FileNotFoundError("operations.json")

    monkeypatch.setattr(fxmacrodata_public, "list_operations", missing_catalogue)
    try:
        module = importlib.reload(fxmacrodata_tools)
        assert module.ALL_FXMACRODATA_TOOLS == []
        assert module.build_fxmacrodata_tools(FixtureClient()) == []
        assert module.fxmacrodata_tool_names() == []
        assert module.fxmacrodata_tool_names("data_catalogue", "release_calendar") == []
    finally:
        monkeypatch.undo()
        importlib.reload(fxmacrodata_tools)
    assert fxmacrodata_tools.ALL_FXMACRODATA_TOOLS
