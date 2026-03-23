# -*- coding: utf-8 -*-
"""
Tool Registry for the Agent framework.

Provides:
- ToolParameter / ToolDefinition dataclasses
- ToolRegistry: central tool registry with multi-provider schema generation
- @tool decorator for easy tool registration
"""

import json
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# Data classes
# ============================================================

@dataclass
class ToolParameter:
    """Schema for a single tool parameter."""
    name: str
    type: str  # "string" | "number" | "integer" | "boolean" | "array" | "object"
    description: str
    required: bool = True
    enum: Optional[List[str]] = None
    default: Any = None


@dataclass
class ToolDefinition:
    """Complete definition of an agent-callable tool."""
    name: str
    description: str
    parameters: List[ToolParameter]
    handler: Callable
    category: str = "data"  # data | analysis | search | action

    # ----- Multi-provider schema converters -----

    def _params_json_schema(self) -> dict:
        """Convert parameters to JSON Schema (shared by OpenAI/Anthropic)."""
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for p in self.parameters:
            prop: Dict[str, Any] = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)
        schema: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema

    def to_openai_tool(self) -> dict:
        """Convert to OpenAI ``tools`` list element format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._params_json_schema(),
            },
        }


# ============================================================
# Tool Registry
# ============================================================

class ToolRegistry:
    """Central registry for all agent-callable tools.

    Usage::

        registry = ToolRegistry()
        registry.register(tool_def)
        registry.execute("get_realtime_quote", stock_code="600519")
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    # ----- Registration -----

    def register(self, tool_def: ToolDefinition) -> None:
        """Register a tool definition."""
        if tool_def.name in self._tools:
            logger.warning(f"Tool '{tool_def.name}' already registered, overwriting")
        self._tools[tool_def.name] = tool_def
        logger.debug(f"Registered tool: {tool_def.name} (category={tool_def.category})")

    def unregister(self, name: str) -> None:
        """Remove a registered tool."""
        self._tools.pop(name, None)

    # ----- Query -----

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Return a tool definition by name."""
        return self._tools.get(name)

    def list_tools(self, category: Optional[str] = None) -> List[ToolDefinition]:
        """List all tools, optionally filtered by category."""
        tools = list(self._tools.values())
        if category:
            tools = [t for t in tools if t.category == category]
        return tools

    def list_names(self) -> List[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    # ----- Schema generation -----

    def to_openai_tools(self) -> List[dict]:
        """Generate OpenAI-format tools list (used by litellm for all providers)."""
        return [t.to_openai_tool() for t in self._tools.values()]

    # ----- Execution -----

    def execute(self, name: str, **kwargs) -> Any:
        """Execute a registered tool by name.

        Returns the result as a JSON-serializable value.
        Raises ``KeyError`` if tool not found.
        Raises the handler's exception on execution failure.

        Supports Gemini namespaced tool names (e.g. default_api:get_realtime_quote -> get_realtime_quote).
        """
        tool_def = self._tools.get(name)
        if tool_def is None and ":" in name:
            # Gemini may return namespaced names like default_api:get_realtime_quote
            tool_def = self._tools.get(name.split(":", 1)[-1])
        if tool_def is None:
            raise KeyError(f"Tool '{name}' not found in registry. Available: {self.list_names()}")

        return tool_def.handler(**kwargs)


# ============================================================
# @tool decorator
# ============================================================

# Global default registry (singleton pattern)
_default_registry: Optional[ToolRegistry] = None


def get_default_registry() -> ToolRegistry:
    """Get or create the global default ToolRegistry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = ToolRegistry()
    return _default_registry


def tool(
    name: str,
    description: str,
    category: str = "data",
    parameters: Optional[List[ToolParameter]] = None,
    registry: Optional[ToolRegistry] = None,
):
    """Decorator to register a function as an agent tool.

    Parameters can be specified explicitly or inferred from type hints.

    Example::

        @tool(name="get_realtime_quote", category="data",
              description="Get real-time stock quote")
        def get_realtime_quote(stock_code: str) -> dict:
            ...
    """
    def decorator(func: Callable) -> Callable:
        # Infer parameters from type hints if not provided
        params = parameters
        if params is None:
            params = _infer_parameters(func)

        tool_def = ToolDefinition(
            name=name,
            description=description,
            parameters=params,
            handler=func,
            category=category,
        )

        target_registry = registry or get_default_registry()
        target_registry.register(tool_def)

        # Attach metadata to function for introspection
        func._tool_definition = tool_def
        return func

    return decorator


def _infer_parameters(func: Callable) -> List[ToolParameter]:
    """Infer ToolParameter list from function signature and type hints."""
    sig = inspect.signature(func)
    hints = getattr(func, '__annotations__', {})
    params: List[ToolParameter] = []

    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        # Skip return annotation
        hint = hints.get(param_name, str)
        # Handle Optional and other typing constructs
        origin = getattr(hint, '__origin__', None)
        if origin is not None:
            # Optional[X] -> X, List[X] -> array, etc.
            args = getattr(hint, '__args__', ())
            if origin is list or (hasattr(origin, '__name__') and origin.__name__ == 'List'):
                param_type = "array"
            elif origin is dict:
                param_type = "object"
            else:
                # Union/Optional - use first non-None arg
                for a in args:
                    if a is not type(None):
                        param_type = type_map.get(a, "string")
                        break
                else:
                    param_type = "string"
        else:
            param_type = type_map.get(hint, "string")

        has_default = param.default is not inspect.Parameter.empty
        tp = ToolParameter(
            name=param_name,
            type=param_type,
            description=f"Parameter: {param_name}",
            required=not has_default,
            default=param.default if has_default else None,
        )
        params.append(tp)

    return params
