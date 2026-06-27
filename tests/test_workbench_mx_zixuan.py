# -*- coding: utf-8 -*-
"""Tests for miaoxiang_zixuan_query read-only guard."""

from typing import Any, Dict


def _mock_handler(command: str, stock: str = None, **kw) -> Dict[str, Any]:
    """Simulate _handle_mx_zixuan_query return."""
    return {
        "source": "miaoxiang_zixuan",
        "stale": False,
        "error": None,
        "data": {"command": command, "stock": stock},
        "disclaimer": "",
    }


def _endpoint_handler(request: Dict[str, Any]) -> Dict[str, Any]:
    """Replica of the endpoint logic for offline testing."""
    # Simulated imports
    _DISCLAIMER = "注意：自选股写操作(add/delete)将修改东方财富第三方账户的自选股列表。"

    command = request.get("command", "query")
    stock = request.get("stock")
    readonly = request.get("readonly", True)
    _write_commands = {"add", "delete"}

    if command.lower() in _write_commands:
        if readonly:
            return {
                "source": "miaoxiang_zixuan",
                "stale": False,
                "error": "只读模式拒绝写操作",
                "data": None,
                "disclaimer": _DISCLAIMER,
            }

    result = _mock_handler(command, stock=stock)
    if isinstance(result, dict) and "disclaimer" not in result:
        result["disclaimer"] = _DISCLAIMER
    return result


def test_query_command_passes_default():
    """Default command 'query' should pass through."""
    result = _endpoint_handler({"command": "query"})
    assert result.get("error") is None
    assert result.get("data") is not None
    assert result["data"]["command"] == "query"


def test_add_command_blocked_by_readonly():
    """add command with readonly=True should be blocked."""
    result = _endpoint_handler({"command": "add", "stock": "茅台"})
    assert result.get("error") is not None
    assert "只读模式拒绝写操作" in str(result.get("error"))
    assert result.get("data") is None


def test_delete_command_blocked_by_readonly():
    """delete command with readonly=True should be blocked."""
    result = _endpoint_handler({"command": "delete", "stock": "茅台", "readonly": True})
    assert result.get("error") is not None
    assert "只读模式" in str(result.get("error"))


def test_add_command_allowed_when_readonly_false():
    """add command with readonly=False should pass through."""
    result = _endpoint_handler({"command": "add", "stock": "茅台", "readonly": False})
    assert result.get("error") is None
    assert result.get("data") is not None
    assert result["data"]["command"] == "add"


def test_delete_command_allowed_when_readonly_false():
    """delete command with readonly=False should pass through."""
    result = _endpoint_handler({"command": "delete", "stock": "茅台", "readonly": False})
    assert result.get("error") is None
    assert result.get("data") is not None


def test_disclaimer_added_to_all_responses():
    """All responses should include disclaimer."""
    result = _endpoint_handler({"command": "query"})
    assert "disclaimer" in result

    result = _endpoint_handler({"command": "add", "readonly": False})
    assert "disclaimer" in result

    result = _endpoint_handler({"command": "add"})
    assert "disclaimer" in result


def test_command_case_insensitive():
    """Commands should be case-insensitive."""
    result = _endpoint_handler({"command": "ADD", "stock": "茅台", "readonly": True})
    assert result.get("error") is not None

    result = _endpoint_handler({"command": "ADD", "stock": "茅台", "readonly": False})
    assert result.get("error") is None
