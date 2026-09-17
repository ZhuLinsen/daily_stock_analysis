import sys
import types

import pytest

from src import telemetry


class _Observation:
    def __init__(self, client, name):
        self.client = client
        self.name = name
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class _Manager:
    def __init__(self, client, observation):
        self.client = client
        self.observation = observation

    def __enter__(self):
        self.client.stack.append(self.observation.name)
        self.client.parents.append(tuple(self.client.stack))
        return self.observation

    def __exit__(self, *_args):
        self.client.stack.pop()


class _Client:
    def __init__(self):
        self.observations = []
        self.parents = []
        self.stack = []

    def start_as_current_observation(self, **kwargs):
        item = _Observation(self, kwargs["name"])
        item.start_kwargs = kwargs
        self.observations.append(item)
        return _Manager(self, item)


def _install_client(monkeypatch, client):
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setitem(sys.modules, "langfuse", types.SimpleNamespace(get_client=lambda: client))


def test_disabled_is_noop(monkeypatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.delitem(sys.modules, "langfuse", raising=False)
    with telemetry.observation("disabled") as current:
        assert current is None


def test_nested_observations_and_success_update(monkeypatch):
    client = _Client()
    _install_client(monkeypatch, client)
    with telemetry.observation("agent"):
        with telemetry.observation("tool") as child:
            telemetry.update_observation(child, metadata={"status": "success"})
    assert client.parents == [("agent",), ("agent", "tool")]
    assert client.observations[1].updates[-1]["metadata"] == {"status": "success"}


def test_sdk_unavailable_does_not_block(monkeypatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setitem(
        sys.modules, "langfuse", types.SimpleNamespace(get_client=lambda: (_ for _ in ()).throw(OSError()))
    )
    with telemetry.observation("unavailable") as current:
        assert current is None


def test_allowlist_drops_secrets_prompts_and_identifiers():
    result = telemetry.safe_metadata(
        {
            "provider": "openai",
            "status": "success",
            "api_key": "secret",
            "prompt": "sensitive prompt",
            "response": "sensitive response",
            "stock_code": "600519",
            "user_id": "user-1",
        }
    )
    assert result == {"provider": "openai", "status": "success"}
    assert "secret" not in repr(result)


def test_business_exception_is_preserved_and_marked(monkeypatch):
    client = _Client()
    _install_client(monkeypatch, client)

    @telemetry.observe("failure")
    def fail():
        raise ValueError("sensitive detail")

    with pytest.raises(ValueError, match="sensitive detail"):
        fail()
    update = client.observations[0].updates[-1]
    assert update["status_message"] == "ValueError"
    assert "sensitive detail" not in repr(update)


def test_usage_normalization_ignores_non_token_payloads():
    assert telemetry.safe_usage({"prompt_tokens": "4", "completion_tokens": 2, "total_tokens": 6, "raw": "secret"}) == {
        "prompt_tokens": 4,
        "completion_tokens": 2,
        "total_tokens": 6,
        "input_tokens": 4,
        "output_tokens": 2,
    }
