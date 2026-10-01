"""Public macroeconomic tools consumed by the stock analysis agent."""

from copy import deepcopy
import logging
import os

from fxmacrodata_public import FXMacroDataClient, list_operations
from src.agent.tools.registry import ToolDefinition, ToolParameter, ToolPolicy

logger = logging.getLogger(__name__)


class FXMacroDataTool(ToolDefinition):
    """Keep nested public JSON Schemas intact in every DSA tool descriptor."""

    input_schema: dict

    def _params_json_schema(self) -> dict:
        return deepcopy(self.input_schema)

    def _descriptor_json_schema(self) -> dict:
        return self._params_json_schema()


def _available_operations() -> list:
    """Return the pinned client's operation catalogue, or none if it cannot load.

    The catalogue is read from package data at import time. A packaging fault
    (for example a frozen build without that data) leaves the FXMacroData tools
    unavailable instead of breaking the whole agent tool registry.
    """
    try:
        return list(list_operations())
    except Exception:
        logger.warning("[fxmacrodata_tools] operation catalogue unavailable; FXMacroData tools disabled")
        return []


def fxmacrodata_tool_names(*operations: str) -> list[str]:
    """Name tools for native specialist allowlists; no arguments selects all."""
    catalogue = _available_operations()
    if not catalogue:
        return []
    available = {operation.name for operation in catalogue}
    selected = list(operations) if operations else [operation.name for operation in catalogue]
    if any(operation not in available for operation in selected):
        raise ValueError("Unknown FXMacroData operation in specialist tool selection.")
    return [f"fxmacrodata_{operation}" for operation in selected]


def build_fxmacrodata_tools(client: FXMacroDataClient | None = None) -> list[FXMacroDataTool]:
    """Build read-only tools; the USD baseline works without configuration.

    An optional FXMACRODATA_API_KEY is read from the host environment at call
    time, never put into a tool schema, invocation argument or response.
    """
    def make_handler(operation_name):
        def handler(**arguments):
            provider = client
            try:
                if provider is None:
                    provider = FXMacroDataClient(api_key=os.environ.get("FXMACRODATA_API_KEY") or "", timeout=30)
                response = provider.execute(operation_name, arguments).as_dict()
                response["provider_url"] = (
                    "https://fxmacrodata.com/?utm_source=daily_stock_analysis"
                    "&utm_medium=integration&utm_campaign=open_source_integrations&utm_content=app"
                )
                return response
            except Exception:
                # DSA logs propagated exceptions; never propagate a client
                # construction or transport exception, or a request which
                # could contain a credential.
                return {"operation": operation_name, "status": "unavailable", "records": [],
                        "error": "FXMacroData could not complete this request."}
            finally:
                if client is None and provider is not None:
                    try:
                        provider.close()
                    except Exception:
                        # A close failure must not replace the handler result;
                        # the exception text is not logged for the same reason
                        # as above.
                        logger.debug("[fxmacrodata_tools] %s: client close failed", operation_name)

        return handler

    result = []
    for operation in _available_operations():
        required = operation.input_schema.get("required", [])
        parameters = [
            ToolParameter(
                name=name,
                type=schema.get("type", "object"),
                description=schema.get("description", name),
                required=name in required,
            )
            for name, schema in operation.input_schema.get("properties", {}).items()
        ]
        definition = FXMacroDataTool(
            name=f"fxmacrodata_{operation.name}",
            description=f"FXMacroData: {operation.description}",
            parameters=parameters,
            handler=make_handler(operation.name),
            category="market",
            policy=ToolPolicy.declared(
                read_only=True, permissions=["network"], timeout_seconds=35,
            ),
            timeout_seconds=35,
        )
        definition.input_schema = deepcopy(operation.input_schema)
        result.append(definition)
    return result


# Like the host's other tool modules, publish stable definitions for registry
# rebuilds. These handlers obtain a client and optional authorization only when
# invoked; importing this module makes no network requests and reads no key.
ALL_FXMACRODATA_TOOLS = build_fxmacrodata_tools()
