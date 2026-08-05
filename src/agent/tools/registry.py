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

SUPPORTED_TOOL_SURFACE_SCOPE_DIMENSIONS = frozenset({"stock"})


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


@dataclass(frozen=True)
class ToolPolicy:
    """Internal policy metadata for DSA Tool Surface descriptors."""

    read_only: Optional[bool] = None
    side_effects: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    policy_status: str = "unknown"
    scope_dimensions: List[str] = field(default_factory=list)
    cancellation_safe: bool = False

    @classmethod
    def unknown(cls) -> "ToolPolicy":
        return cls()

    @classmethod
    def declared(
        cls,
        *,
        read_only: bool,
        side_effects: Optional[List[str]] = None,
        permissions: Optional[List[str]] = None,
        scope_dimensions: Optional[List[str]] = None,
        cancellation_safe: bool = False,
    ) -> "ToolPolicy":
        return cls(
            read_only=read_only,
            side_effects=list(side_effects or []),
            permissions=list(permissions or []),
            policy_status="declared",
            scope_dimensions=list(scope_dimensions or []),
            cancellation_safe=bool(cancellation_safe),
        )

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "read_only": self.read_only,
            "side_effects": list(self.side_effects),
            "permissions": list(self.permissions),
            "policy_status": self.policy_status,
            "cancellation_safe": self.cancellation_safe,
        }


@dataclass
class ToolDefinition:
    """Complete definition of an agent-callable tool."""
    name: str
    description: str
    parameters: List[ToolParameter]
    handler: Callable
    category: str = "data"  # data | analysis | search | action
    policy: ToolPolicy = field(default_factory=ToolPolicy.unknown)

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

    def _descriptor_json_schema(self) -> dict:
        """Return a descriptor schema with explicit empty required list."""
        schema = self._params_json_schema()
        schema.setdefault("required", [])
        schema["additionalProperties"] = self.accepts_extra_arguments()
        return schema

    def accepts_extra_arguments(self) -> bool:
        """Return whether the handler explicitly accepts undeclared kwargs."""
        try:
            sig = inspect.signature(self.handler)
        except (TypeError, ValueError):
            return False
        return any(param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values())

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

    def to_public_descriptor(self) -> dict:
        """Return Tool Surface descriptor without exposing the Python handler."""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "parameters": self._descriptor_json_schema(),
            "policy": self.policy.to_public_dict(),
            "scope": {
                "scope_dimensions": list(self.policy.scope_dimensions),
                "requires_stock_scope": "stock" in self.policy.scope_dimensions,
            },
        }

    def to_mcp_descriptor(self) -> dict:
        """Return an MCP-compatible descriptor only; no server/transport implied."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self._descriptor_json_schema(),
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

    def resolve(self, name: str) -> Optional[ToolDefinition]:
        """Return a tool definition by exact registered name."""
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

    def validate_tool_policies(self, *, strict: bool = False) -> List[Dict[str, Any]]:
        """Return policy validation issues for registered tools.

        Ordinary registration intentionally stays permissive.  Strict mode is
        used by Tool Surface checks for production/default registries.
        """
        issues: List[Dict[str, Any]] = []
        for tool_def in self._tools.values():
            policy = tool_def.policy
            if policy.policy_status != "declared":
                if strict:
                    issues.append({
                        "tool": tool_def.name,
                        "code": "policy_unknown",
                        "message": "Tool policy is not declared.",
                    })
                continue
            if strict and policy.read_only is None:
                issues.append({
                    "tool": tool_def.name,
                    "code": "read_only_missing",
                    "message": "Tool policy read_only is not declared.",
                })
            if not strict:
                continue
            unsupported_scopes = [
                dimension
                for dimension in policy.scope_dimensions
                if dimension not in SUPPORTED_TOOL_SURFACE_SCOPE_DIMENSIONS
            ]
            for dimension in unsupported_scopes:
                issues.append({
                    "tool": tool_def.name,
                    "code": "unsupported_scope_dimension",
                    "message": f"Tool declares unsupported scope dimension: {dimension}.",
                    "dimension": dimension,
                })
            has_stock_param = any(param.name == "stock_code" for param in tool_def.parameters)
            declares_stock_scope = "stock" in policy.scope_dimensions
            if has_stock_param and not declares_stock_scope:
                issues.append({
                    "tool": tool_def.name,
                    "code": "stock_scope_missing",
                    "message": "Tool has stock_code parameter but does not declare stock scope.",
                })
            if declares_stock_scope and not has_stock_param:
                issues.append({
                    "tool": tool_def.name,
                    "code": "stock_scope_parameter_missing",
                    "message": "Tool declares stock scope but has no stock_code parameter.",
                })
        return issues

    # ----- Execution -----

    def execute(self, name: str, **kwargs) -> Any:
        """Execute a registered tool by name.

        Returns the result as a JSON-serializable value.
        Raises ``KeyError`` if tool not found.
        Raises the handler's exception on execution failure.

        Tool names must match the registry exactly.
        """
        tool_def = self.resolve(name)
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
    policy: Optional[ToolPolicy] = None,
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
            policy=policy or ToolPolicy.unknown(),
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
